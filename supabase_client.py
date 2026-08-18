from __future__ import annotations

import base64
import json
import logging
import os
import re
import socket
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

REQUIRED_PRODUCTION_AUTH_ENV = ("SUPABASE_URL", "SUPABASE_ANON_KEY")
REQUIRED_PRODUCTION_BILLING_ENV = (
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "STRIPE_PRICE_ID",
    "STRIPE_PRODUCT_ID",
)
PRODUCTION_LIKE_ENVIRONMENTS = {"preview", "staging", "production"}
SENSITIVE_KEY_PREFIXES = ("sb_secret_", "service_role")
REDIRECT_ENV_BY_ENVIRONMENT = {
    "development": "SUPABASE_REDIRECT_URL_DEVELOPMENT",
    "preview": "SUPABASE_REDIRECT_URL_PREVIEW",
    "staging": "SUPABASE_REDIRECT_URL_PREVIEW",
    "production": "SUPABASE_REDIRECT_URL_PRODUCTION",
    "test": "SUPABASE_REDIRECT_URL_TEST",
}
_PLACEHOLDER_RE = re.compile(
    r"(?i)(placeholder|change[-_ ]?me|replace[-_ ]?me|your[-_ ]|example|dummy|sample|todo|^anon$|^key$)"
)
_PUBLISHABLE_KEY_RE = re.compile(r"^sb_publishable_[A-Za-z0-9_-]{20,}$")
_LEGACY_JWT_RE = re.compile(r"^[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{20,}$")


class AuthConfigurationError(RuntimeError):
    """Raised when Supabase auth configuration is unsafe or incomplete."""

    def __init__(self, errors: list[str]):
        self.errors = tuple(errors)
        super().__init__("Invalid Supabase authentication configuration: " + "; ".join(errors))


@dataclass(frozen=True)
class AuthConfig:
    environment: str
    project_url: str
    anon_key: str
    redirect_base_url: str
    redirect_env_name: str
    jwks_url: str
    project_ref: str | None


def _normalise_environment(value: str | None = None) -> str:
    environment = (value if value is not None else os.getenv("ENVIRONMENT", "")).strip().lower()
    aliases = {"": "development", "dev": "development", "local": "development"}
    return aliases.get(environment, environment)


def _environment() -> str:
    return _normalise_environment()


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _truthy_env(name: str) -> bool:
    return _truthy(os.getenv(name))


def _is_loopback(hostname: str | None) -> bool:
    host = (hostname or "").strip("[]").lower()
    return host == "localhost" or host == "::1" or host.startswith("127.")


def _decode_jwt_payload(value: str) -> dict[str, Any] | None:
    parts = value.split(".")
    if len(parts) != 3:
        return None
    try:
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return decoded if isinstance(decoded, dict) else None


def _validate_root_url(value: str, *, environment: str, label: str) -> tuple[list[str], Any | None]:
    errors: list[str] = []
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError:
        return [f"{label} is malformed"], None

    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        errors.append(f"{label} must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        errors.append(f"{label} must not contain credentials")
    if parsed.path not in {"", "/"}:
        errors.append(f"{label} must be the project root and must not contain an API subpath")
    if parsed.params or parsed.query or parsed.fragment:
        errors.append(f"{label} must not contain params, a query string, or a fragment")
    if environment in PRODUCTION_LIKE_ENVIRONMENTS and parsed.scheme != "https":
        errors.append(f"{label} must use HTTPS in {environment}")
    if environment in PRODUCTION_LIKE_ENVIRONMENTS and _is_loopback(parsed.hostname):
        errors.append(f"{label} must not use a loopback host in {environment}")
    if port is not None and environment in PRODUCTION_LIKE_ENVIRONMENTS:
        errors.append(f"{label} must not use a custom port in {environment}")
    return errors, parsed


def _validate_redirect_url(value: str, *, environment: str, label: str) -> list[str]:
    errors: list[str] = []
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError:
        return [f"{label} is malformed"]

    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        errors.append(f"{label} must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        errors.append(f"{label} must not contain credentials")
    if parsed.query or parsed.fragment:
        errors.append(f"{label} must not contain a query string or fragment")
    if environment in PRODUCTION_LIKE_ENVIRONMENTS and parsed.scheme != "https":
        errors.append(f"{label} must use HTTPS in {environment}")
    if environment in PRODUCTION_LIKE_ENVIRONMENTS and _is_loopback(parsed.hostname):
        errors.append(f"{label} must not use a loopback host in {environment}")
    if port is not None and environment in PRODUCTION_LIKE_ENVIRONMENTS:
        errors.append(f"{label} must not use a custom port in {environment}")
    return errors


def _validate_public_key(value: str, project_host: str | None) -> tuple[list[str], str | None]:
    errors: list[str] = []
    project_ref: str | None = None
    lower_value = value.lower()

    if _PLACEHOLDER_RE.search(value):
        errors.append("SUPABASE_ANON_KEY has a placeholder-shaped value")
        return errors, None
    if lower_value.startswith(SENSITIVE_KEY_PREFIXES):
        errors.append("SUPABASE_ANON_KEY must be a publishable/anon key, never a secret or service-role key")
        return errors, None
    if _PUBLISHABLE_KEY_RE.fullmatch(value):
        return errors, None

    payload = _decode_jwt_payload(value) if _LEGACY_JWT_RE.fullmatch(value) else None
    if not payload:
        errors.append("SUPABASE_ANON_KEY is not a valid publishable key or legacy anon JWT")
        return errors, None
    if payload.get("role") != "anon":
        errors.append("SUPABASE_ANON_KEY JWT role must be anon")
    ref_claim = payload.get("ref")
    if isinstance(ref_claim, str) and ref_claim:
        project_ref = ref_claim
        cloud_ref = (project_host or "").removesuffix(".supabase.co")
        if project_host and project_host.endswith(".supabase.co") and cloud_ref != project_ref:
            errors.append("SUPABASE_URL project reference does not match SUPABASE_ANON_KEY")
    return errors, project_ref


def auth_configuration_errors(environ: Mapping[str, str] | None = None) -> list[str]:
    env = os.environ if environ is None else environ
    environment = _normalise_environment(env.get("ENVIRONMENT"))
    errors: list[str] = []

    if environment not in REDIRECT_ENV_BY_ENVIRONMENT:
        errors.append("ENVIRONMENT must be development, preview, staging, production, or test")
        return errors

    if environment in PRODUCTION_LIKE_ENVIRONMENTS and _truthy(env.get("DEV_MODE")):
        errors.append(f"DEV_MODE=true is forbidden in {environment}")

    redirect_env_name = REDIRECT_ENV_BY_ENVIRONMENT[environment]
    required = ("SUPABASE_URL", "SUPABASE_ANON_KEY", redirect_env_name)
    missing = [name for name in required if not (env.get(name) or "").strip()]
    if missing:
        errors.append("missing required values: " + ", ".join(missing))

    project_url = (env.get("SUPABASE_URL") or "").strip()
    parsed = None
    if project_url:
        url_errors, parsed = _validate_root_url(project_url, environment=environment, label="SUPABASE_URL")
        errors.extend(url_errors)

    key = (env.get("SUPABASE_ANON_KEY") or "").strip()
    if key:
        key_errors, _ = _validate_public_key(key, parsed.hostname if parsed else None)
        errors.extend(key_errors)

    redirect_url = (env.get(redirect_env_name) or "").strip()
    if redirect_url:
        errors.extend(_validate_redirect_url(redirect_url, environment=environment, label=redirect_env_name))

    configured_jwks = (env.get("SUPABASE_JWKS_URL") or "").strip()
    if configured_jwks and project_url and parsed and not _validate_root_url(
        project_url, environment=environment, label="SUPABASE_URL"
    )[0]:
        expected = f"{project_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
        if configured_jwks != expected:
            errors.append("SUPABASE_JWKS_URL must match the configured project root")

    return errors


def load_auth_config(environ: Mapping[str, str] | None = None) -> AuthConfig:
    env = os.environ if environ is None else environ
    errors = auth_configuration_errors(env)
    if errors:
        raise AuthConfigurationError(errors)

    environment = _normalise_environment(env.get("ENVIRONMENT"))
    project_url = (env.get("SUPABASE_URL") or "").strip().rstrip("/")
    anon_key = (env.get("SUPABASE_ANON_KEY") or "").strip()
    redirect_env_name = REDIRECT_ENV_BY_ENVIRONMENT[environment]
    redirect_base_url = (env.get(redirect_env_name) or "").strip().rstrip("/")
    jwks_url = (env.get("SUPABASE_JWKS_URL") or "").strip() or (
        f"{project_url}/auth/v1/.well-known/jwks.json"
    )
    payload = _decode_jwt_payload(anon_key) or {}
    project_ref = payload.get("ref") if isinstance(payload.get("ref"), str) else None
    return AuthConfig(
        environment=environment,
        project_url=project_url,
        anon_key=anon_key,
        redirect_base_url=redirect_base_url,
        redirect_env_name=redirect_env_name,
        jwks_url=jwks_url,
        project_ref=project_ref,
    )


def get_supabase_jwks_url() -> str | None:
    project_url = os.getenv("SUPABASE_URL", "").strip()
    if not project_url:
        return None
    environment = _environment()
    errors, _ = _validate_root_url(project_url, environment=environment, label="SUPABASE_URL")
    if errors:
        return None
    return os.getenv("SUPABASE_JWKS_URL", "").strip() or (
        f"{project_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    )


def require_production_auth_config() -> None:
    if _environment() not in PRODUCTION_LIKE_ENVIRONMENTS:
        return
    errors = auth_configuration_errors()
    if errors:
        logger.critical("Refusing startup because Supabase auth configuration validation failed.")
        raise AuthConfigurationError(errors)


def require_production_billing_config() -> None:
    if _environment() != "production":
        return
    missing = [name for name in REQUIRED_PRODUCTION_BILLING_ENV if not os.getenv(name)]
    if missing:
        logger.critical("Refusing production startup: missing Stripe vars: %s", ",".join(missing))
        raise RuntimeError(f"Missing production Stripe configuration: {', '.join(missing)}")


def healthcheck_auth(*, check_connectivity: bool = False, timeout: float = 5.0) -> dict[str, Any]:
    errors = auth_configuration_errors()
    result: dict[str, Any] = {
        "ok": not errors,
        "provider": "supabase",
        "environment": _environment(),
        "configuration_errors": errors,
    }
    if check_connectivity and not errors:
        connectivity = diagnose_auth_connectivity(timeout=timeout)
        result["connectivity"] = connectivity["checks"]
        result["ok"] = connectivity["ok"]
    return result


def healthcheck_billing() -> dict[str, Any]:
    missing = [name for name in REQUIRED_PRODUCTION_BILLING_ENV if not os.getenv(name)]
    return {
        "ok": not missing,
        "provider": "stripe",
        "missing": missing,
        "environment": _environment(),
    }


def _http_check(url: str, key: str, *, timeout: float, expect_jwks: bool = False) -> tuple[bool, str]:
    try:
        response = requests.get(
            url,
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
            timeout=timeout,
            allow_redirects=False,
        )
    except requests.RequestException:
        return False, "request failed"
    if response.status_code != 200:
        return False, f"unexpected HTTP status {response.status_code}"
    if expect_jwks:
        try:
            payload = response.json()
        except ValueError:
            return False, "response was not JSON"
        if not isinstance(payload, dict) or not isinstance(payload.get("keys"), list) or not payload["keys"]:
            return False, "JWKS did not contain signing keys"
    return True, "available"


def diagnose_auth_connectivity(*, timeout: float = 5.0) -> dict[str, Any]:
    """Run redacted DNS/Auth/JWKS/key-coherence diagnostics.

    Results contain only check names, status, and bounded diagnostic text. URLs,
    keys, tokens, response bodies, and provider exception text are never returned.
    """

    config = load_auth_config()
    parsed = urlparse(config.project_url)
    checks: list[dict[str, Any]] = []
    try:
        socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
        dns_ok = True
        checks.append({"name": "dns_resolution", "ok": True, "detail": "resolved"})
    except OSError:
        dns_ok = False
        checks.append({"name": "dns_resolution", "ok": False, "detail": "resolution failed"})

    endpoints = (
        ("auth_health", f"{config.project_url}/auth/v1/health", False),
        ("jwks_availability", config.jwks_url, True),
        ("project_url_key_coherence", f"{config.project_url}/auth/v1/settings", False),
    )
    for name, endpoint, expect_jwks in endpoints:
        if not dns_ok:
            checks.append({"name": name, "ok": False, "detail": "not attempted because DNS failed"})
            continue
        ok, detail = _http_check(endpoint, config.anon_key, timeout=timeout, expect_jwks=expect_jwks)
        checks.append({"name": name, "ok": ok, "detail": detail})

    return {"ok": all(check["ok"] for check in checks), "checks": checks, "environment": config.environment}


def get_supabase_client():
    errors = auth_configuration_errors()
    any_auth_value = bool(os.getenv("SUPABASE_URL") or os.getenv("SUPABASE_ANON_KEY"))
    if errors:
        if _environment() in PRODUCTION_LIKE_ENVIRONMENTS or any_auth_value:
            raise AuthConfigurationError(errors)
        logger.info("Supabase auth is not configured for this development/test process.")
        return None

    config = load_auth_config()
    try:
        from supabase import create_client
        from supabase.lib.client_options import SyncClientOptions
    except ImportError as exc:
        logger.error("Supabase client dependency is unavailable.")
        raise RuntimeError("Supabase authentication dependency is unavailable.") from exc

    try:
        # A fresh client prevents its in-memory Auth storage from being shared
        # across Streamlit browser sessions. Provider persistence is kept only
        # for the lifetime of this isolated operation.
        options = SyncClientOptions(auto_refresh_token=False, persist_session=True, flow_type="pkce")
        return create_client(config.project_url, config.anon_key, options=options)
    except Exception as exc:
        logger.error("Supabase client initialization failed.")
        raise RuntimeError("Supabase authentication client could not be initialized.") from exc
