from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Callable, Mapping


BROKER_ONLY_KEYS = (
    "SUPABASE_SERVICE_ROLE_KEY",
    "FURUFLOW_SESSION_ENCRYPTION_KEY",
)
BROKER_REQUIRED_KEYS = (
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "FURUFLOW_SESSION_ENCRYPTION_KEY",
    "FURUFLOW_SESSION_BRIDGE_KEY",
)
STREAMLIT_REQUIRED_KEYS = (
    "ENVIRONMENT",
    "DEV_MODE",
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",
    "SUPABASE_REDIRECT_URL_PREVIEW",
    "SUPABASE_REDIRECT_URL_PRODUCTION",
    "FURUFLOW_SESSION_BROKER_PUBLIC_ORIGIN",
    "FURUFLOW_SESSION_BRIDGE_KEY",
)
EXECUTION_ENV_KEYS = (
    "LANG",
    "LC_ALL",
    "PATH",
    "PYTHONHOME",
    "PYTHONPATH",
    "PYTHONUNBUFFERED",
    "PYTHONDONTWRITEBYTECODE",
    "TZ",
)
INTERNAL_BROKER_URL = "http://127.0.0.1:8510"
NGINX_TEMPLATE = Path("deploy/render/nginx.conf.template")
NGINX_CONFIG = Path("/etc/nginx/conf.d/furuflow.conf")


@dataclass(frozen=True)
class ChildSpec:
    name: str
    argv: tuple[str, ...]
    environment: dict[str, str]
    user: str | None


@dataclass(frozen=True)
class ManagedChild:
    name: str
    process: subprocess.Popen[bytes]


def _required(source: Mapping[str, str], keys: tuple[str, ...]) -> None:
    missing = [key for key in keys if not source.get(key, "").strip()]
    if missing:
        raise RuntimeError("Missing required deployment environment: " + ", ".join(missing))


def _execution_environment(source: Mapping[str, str], *, home: str) -> dict[str, str]:
    environment = {key: source[key] for key in EXECUTION_ENV_KEYS if source.get(key)}
    environment["HOME"] = home
    return environment


def build_child_environments(source: Mapping[str, str]) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Return Streamlit, broker, and Nginx environments with explicit boundaries."""

    _required(source, STREAMLIT_REQUIRED_KEYS)
    _required(source, BROKER_REQUIRED_KEYS)

    streamlit = dict(source)
    for key in BROKER_ONLY_KEYS:
        streamlit.pop(key, None)
    streamlit["FURUFLOW_SESSION_BROKER_INTERNAL_URL"] = INTERNAL_BROKER_URL
    streamlit["HOME"] = "/home/furuflow-streamlit"

    broker = _execution_environment(source, home="/home/furuflow-broker")
    for key in BROKER_REQUIRED_KEYS:
        broker[key] = source[key]

    nginx = _execution_environment(source, home="/tmp")
    return streamlit, broker, nginx


def render_nginx_config(template: Path, destination: Path, port_value: str) -> None:
    try:
        port = int(port_value)
    except ValueError as exc:
        raise RuntimeError("PORT must be an integer.") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError("PORT must be between 1 and 65535.")
    rendered = template.read_text(encoding="utf-8").replace("${PORT}", str(port))
    if "${PORT}" in rendered:
        raise RuntimeError("Nginx listener configuration was not rendered.")
    destination.write_text(rendered, encoding="utf-8")


def _privilege_dropper(username: str) -> Callable[[], None]:
    def drop() -> None:
        import pwd

        account = pwd.getpwnam(username)
        os.initgroups(username, account.pw_gid)
        os.setgid(account.pw_gid)
        os.setuid(account.pw_uid)

    return drop


def _specs(
    streamlit_environment: dict[str, str],
    broker_environment: dict[str, str],
    nginx_environment: dict[str, str],
) -> tuple[ChildSpec, ...]:
    python = sys.executable
    return (
        ChildSpec(
            "session-broker",
            (
                python,
                "-m",
                "gunicorn",
                "--bind",
                "127.0.0.1:8510",
                "--timeout",
                "30",
                "--error-logfile",
                "-",
                "session_broker:create_app()",
            ),
            broker_environment,
            "furuflow-broker",
        ),
        ChildSpec(
            "streamlit",
            (
                python,
                "-m",
                "streamlit",
                "run",
                "app.py",
                "--server.address",
                "127.0.0.1",
                "--server.port",
                "8501",
                "--server.headless",
                "true",
                "--browser.gatherUsageStats",
                "false",
            ),
            streamlit_environment,
            "furuflow-streamlit",
        ),
        ChildSpec("nginx", ("nginx", "-g", "daemon off;"), nginx_environment, None),
    )


def _stop(children: list[ManagedChild]) -> None:
    for child in children:
        if child.process.poll() is None:
            child.process.terminate()

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline and any(child.process.poll() is None for child in children):
        time.sleep(0.1)

    for child in children:
        if child.process.poll() is None:
            child.process.kill()
    for child in children:
        try:
            child.process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            pass


def main() -> int:
    source = dict(os.environ)
    port = source.get("PORT", "10000")
    try:
        streamlit_environment, broker_environment, nginx_environment = build_child_environments(source)
        render_nginx_config(NGINX_TEMPLATE, NGINX_CONFIG, port)
    except (OSError, RuntimeError) as exc:
        print(f"supervisor configuration error: {exc}", file=sys.stderr, flush=True)
        return 1

    # Remove broker-only values from the supervisor before Streamlit is spawned.
    for key in BROKER_ONLY_KEYS:
        os.environ.pop(key, None)
        source.pop(key, None)

    children: list[ManagedChild] = []
    stopping_signal: int | None = None

    def request_stop(signum: int, _frame: object) -> None:
        nonlocal stopping_signal
        stopping_signal = signum

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    try:
        for spec in _specs(streamlit_environment, broker_environment, nginx_environment):
            process = subprocess.Popen(
                spec.argv,
                cwd="/app",
                env=spec.environment,
                preexec_fn=_privilege_dropper(spec.user) if spec.user else None,
            )
            children.append(ManagedChild(spec.name, process))
            print(f"supervisor started {spec.name} pid={process.pid}", flush=True)
            if spec.name == "session-broker":
                for key in BROKER_ONLY_KEYS:
                    broker_environment.pop(key, None)

        while True:
            if stopping_signal is not None:
                print(f"supervisor received signal {stopping_signal}", flush=True)
                _stop(children)
                return 128 + stopping_signal
            for child in children:
                return_code = child.process.poll()
                if return_code is not None:
                    print(
                        f"supervisor detected {child.name} exit code={return_code}; stopping container",
                        file=sys.stderr,
                        flush=True,
                    )
                    _stop(children)
                    return return_code if return_code != 0 else 1
            time.sleep(0.25)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"supervisor startup error: {type(exc).__name__}", file=sys.stderr, flush=True)
        _stop(children)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
