from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import streamlit as st

from db import claim_session as db_claim_session
from db import clear_session, get_user_by_email, get_user_by_provider_user_id, touch_session, upsert_user
from furuflow_auth import (
    AuthSessionError,
    clear_cached_session,
    get_supabase_identity,
    provider_sign_out,
    set_auth_notice,
)
from supabase_client import require_production_auth_config, require_production_billing_config

logger = logging.getLogger(__name__)

LEGACY_AUTH_PROVIDER = "legacy_email"
SUPABASE_AUTH_PROVIDER = "supabase"


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _environment() -> str:
    return os.getenv("ENVIRONMENT", "").strip().lower()


def _enforce_production_safety() -> None:
    require_production_auth_config()
    require_production_billing_config()
    if _environment() == "production" and _truthy_env("DEV_MODE"):
        logger.critical("Refusing startup: DEV_MODE=true is not allowed when ENVIRONMENT=production.")
        raise RuntimeError("Unsafe auth configuration: DEV_MODE=true is forbidden in production.")


_enforce_production_safety()


def _is_verified_identity(identity: dict[str, Any] | None) -> bool:
    if not identity:
        return False
    return bool(identity.get("authenticated") and identity.get("email_verified") and identity.get("provider_user_id"))


def _legacy_identity_from_session() -> dict[str, Any] | None:
    email = (st.session_state.get("auth_email") or "").strip().lower()
    if not email:
        return None

    # TODO(supabase-auth): remove legacy email identity once Supabase Auth is enforced.
    return {
        "email": email,
        "provider_user_id": None,
        "auth_provider": LEGACY_AUTH_PROVIDER,
        "email_verified": False,
        "authenticated": False,
        "legacy": True,
    }


def get_current_identity() -> dict[str, Any] | None:
    try:
        identity = get_supabase_identity()
        if identity:
            st.session_state["auth_identity"] = identity
            return identity
    except AuthSessionError as exc:
        logger.warning("auth_event=session_restore outcome=failed reason=%s", exc.code)
        clear_cached_session()
        st.session_state.pop("auth_identity", None)
        set_auth_notice(str(exc), exc.code)
        return None

    identity = _legacy_identity_from_session()
    if identity:
        st.session_state["auth_identity"] = identity
        logger.info("auth_event=legacy_session outcome=active reason=unverified")
        return identity

    st.session_state.pop("auth_identity", None)
    return None


def get_current_user() -> dict[str, Any] | None:
    identity = get_current_identity()
    if not identity:
        return None

    email = identity["email"].lower()
    provider_user_id = identity.get("provider_user_id")
    user = get_user_by_provider_user_id(provider_user_id) if provider_user_id else get_user_by_email(email)
    if not user:
        user = upsert_user(
            email=email,
            provider_user_id=identity.get("provider_user_id"),
            auth_provider=identity.get("auth_provider"),
            email_verified=bool(identity.get("email_verified")),
            last_login_at=datetime.now(timezone.utc).isoformat(),
        )
    else:
        user = upsert_user(
            email=email,
            provider_user_id=identity.get("provider_user_id"),
            auth_provider=identity.get("auth_provider") or user.get("auth_provider"),
            email_verified=bool(identity.get("email_verified")),
            last_login_at=datetime.now(timezone.utc).isoformat(),
        )

    user["_identity"] = identity
    user["_identity_verified"] = _is_verified_identity(identity)
    return user


def is_authenticated() -> bool:
    return _is_verified_identity(get_current_identity())


def is_admin(user: dict[str, Any] | None) -> bool:
    if not user:
        return False
    if not user.get("is_admin"):
        return False
    verified = bool(user.get("_identity_verified") or (user.get("email_verified") and user.get("provider_user_id")))
    if not verified:
        logger.warning("auth_event=admin_access outcome=blocked reason=unverified_identity")
        return False
    return True


def can_access_pro(user: dict[str, Any] | None) -> bool:
    if not user:
        return False

    if _environment() == "production" and _truthy_env("DEV_MODE"):
        raise RuntimeError("Unsafe auth configuration: DEV_MODE=true is forbidden in production.")

    verified = bool(user.get("_identity_verified") or (user.get("email_verified") and user.get("provider_user_id")))
    if not verified:
        if user.get("is_admin") or user.get("lifetime_access") or user.get("pro_active"):
            logger.warning("auth_event=pro_access outcome=blocked reason=unverified_identity")
        return False

    if _truthy_env("DEV_MODE") and _environment() != "production":
        return True

    return is_admin(user) or bool(user.get("lifetime_access")) or bool(user.get("pro_active"))


def logout() -> None:
    identity = st.session_state.get("auth_identity") or _legacy_identity_from_session()
    if identity and identity.get("email"):
        clear_session(identity["email"], st.session_state.get("auth_session_id"))

    provider_sign_out()
    for key in ("auth_email", "auth_session_id", "auth_session_claimed", "access_granted", "auth_identity"):
        st.session_state.pop(key, None)


def claim_session() -> str | None:
    identity = get_current_identity()
    if not identity or not identity.get("email"):
        return None

    session_id = st.session_state.get("auth_session_id")
    if not session_id:
        session_id = uuid.uuid4().hex
        st.session_state["auth_session_id"] = session_id
        st.session_state["auth_session_claimed"] = False

    if not st.session_state.get("auth_session_claimed", False):
        db_claim_session(identity["email"], session_id)
        st.session_state["auth_session_claimed"] = True

    return session_id


def validate_session() -> bool:
    identity = get_current_identity()
    session_id = st.session_state.get("auth_session_id")
    if not identity or not identity.get("email") or not session_id:
        return False

    user = get_user_by_email(identity["email"])
    active_session_id = user.get("current_session_id") if user else None
    if active_session_id and active_session_id != session_id:
        logger.warning("auth_event=local_session outcome=displaced reason=single_session_lock")
        logout()
        return False

    touch_session(identity["email"], session_id)
    return True
