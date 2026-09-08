"""Start Streamlit headlessly and verify its local health endpoint."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


SENSITIVE_ENV = (
    "DISCORD_WEBHOOK",
    "DISCORD_WEBHOOK_URL",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "SUPABASE_ANON_KEY",
    "SUPABASE_JWKS_URL",
    "SUPABASE_JWT_SECRET",
    "SUPABASE_REDIRECT_URL_DEVELOPMENT",
    "SUPABASE_REDIRECT_URL_PREVIEW",
    "SUPABASE_REDIRECT_URL_PRODUCTION",
    "SUPABASE_REDIRECT_URL_TEST",
    "SUPABASE_URL",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "TWITTER_ACCESS_TOKEN",
    "TWITTER_ACCESS_TOKEN_SECRET",
    "TWITTER_API_KEY",
    "TWITTER_API_SECRET",
    "X_ACCESS_TOKEN",
    "X_ACCESS_TOKEN_SECRET",
    "X_API_KEY",
    "X_API_SECRET",
)


def _available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    port = _available_port()
    env = os.environ.copy()
    for name in SENSITIVE_ENV:
        env.pop(name, None)
    env.update(
        {
            "ENVIRONMENT": "test",
            "DEV_MODE": "false",
            "FURUFLOW_DISABLE_EXTERNAL_SIDE_EFFECTS": "true",
            "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
        }
    )

    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(root / "app.py"),
        "--server.headless=true",
        f"--server.port={port}",
        "--server.address=127.0.0.1",
    ]
    process = subprocess.Popen(
        command,
        cwd=root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    deadline = time.monotonic() + 30
    health_url = f"http://127.0.0.1:{port}/_stcore/health"

    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                output = process.stdout.read() if process.stdout else ""
                print("Streamlit exited before becoming healthy.")
                print("\n".join(output.splitlines()[-20:]))
                return 1
            try:
                with urllib.request.urlopen(health_url, timeout=1) as response:
                    if response.status == 200 and response.read().strip() == b"ok":
                        print("Streamlit boot smoke passed with external side effects disabled.")
                        return 0
            except OSError:
                time.sleep(0.25)
        print("Timed out waiting for Streamlit health endpoint.")
        return 1
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
