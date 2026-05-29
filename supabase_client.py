from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

REQUIRED_PRODUCTION_AUTH_ENV = ("SUPABASE_URL", "SUPABASE_ANON_KEY")
REQUIRED_PRODUCTION_BILLING_ENV = ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET")


def _environment() -> str:
    return os.getenv("ENVIRONMENT", "").strip().lower()


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def get_supabase_jwks_url() -> str | None:
    configured = os.getenv("SUPABASE_JWKS_URL", "").strip()
    if configured:
        return configured

    supabase_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    if not supabase_url:
        return None
    return f"{supabase_url}/auth/v1/.well-known/jwks.json"


def require_production_auth_config() -> None:
    if _environment() != "production":
        return
    if _truthy_env("DEV_MODE"):
        logger.critical("Refusing production startup: DEV_MODE=true.")
        raise RuntimeError("Unsafe auth configuration: DEV_MODE=true is forbidden in production.")

    missing = [name for name in REQUIRED_PRODUCTION_AUTH_ENV if not os.getenv(name)]
    has_jwt_signing_config = bool(os.getenv("SUPABASE_JWT_SECRET") or get_supabase_jwks_url())
    if not has_jwt_signing_config:
        missing.append("SUPABASE_JWT_SECRET or SUPABASE_JWKS_URL")
    if missing:
        logger.critical("Refusing production startup: missing Supabase auth vars: %s", ",".join(missing))
        raise RuntimeError(f"Missing production Supabase auth configuration: {', '.join(missing)}")


def require_production_billing_config() -> None:
    if _environment() != "production":
        return
    missing = [name for name in REQUIRED_PRODUCTION_BILLING_ENV if not os.getenv(name)]
    if missing:
        logger.critical("Refusing production startup: missing Stripe vars: %s", ",".join(missing))
        raise RuntimeError(f"Missing production Stripe configuration: {', '.join(missing)}")


def healthcheck_auth() -> dict[str, Any]:
    missing = [name for name in REQUIRED_PRODUCTION_AUTH_ENV if not os.getenv(name)]
    has_jwt_signing_config = bool(os.getenv("SUPABASE_JWT_SECRET") or get_supabase_jwks_url())
    if not has_jwt_signing_config:
        missing.append("SUPABASE_JWT_SECRET or SUPABASE_JWKS_URL")
    configured = not missing
    return {
        "ok": configured,
        "provider": "supabase",
        "missing": missing,
        "environment": _environment() or "development",
    }


def healthcheck_billing() -> dict[str, Any]:
    missing = [name for name in REQUIRED_PRODUCTION_BILLING_ENV if not os.getenv(name)]
    return {
        "ok": not missing,
        "provider": "stripe",
        "missing": missing,
        "environment": _environment() or "development",
    }


@lru_cache(maxsize=1)
def get_supabase_client():
    require_production_auth_config()
    url = os.getenv("SUPABASE_URL")
    anon_key = os.getenv("SUPABASE_ANON_KEY")
    if not url or not anon_key:
        logger.info("Supabase client not initialized; SUPABASE_URL or SUPABASE_ANON_KEY is missing.")
        return None

    try:
        from supabase import create_client
    except ImportError as exc:
        logger.exception("supabase-py is not installed.")
        if _environment() == "production":
            raise RuntimeError("supabase-py is required in production.") from exc
        return None

    try:
        return create_client(url, anon_key)
    except Exception as exc:
        logger.exception("Failed to initialize Supabase client.")
        if _environment() == "production":
            raise RuntimeError("Supabase client initialization failed.") from exc
        return None


require_production_auth_config()
require_production_billing_config()
