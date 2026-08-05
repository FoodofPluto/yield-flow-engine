from __future__ import annotations

import logging
import os
import uuid
from typing import Any

import streamlit as st

from account_control import AccountStateUnavailable, SupabaseAccountClient
from auth_session import get_auth_session_store, require_production_session_config
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
    require_production_session_config()
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

    provider_user_id = identity.get("provider_user_id")
    if not provider_user_id or not _is_verified_identity(identity):
        return {
            **identity,
            "is_admin": False,
            "lifetime_access": False,
            "pro_active": False,
            "demo_active": False,
            "_identity": identity,
            "_identity_verified": False,
            "_account_available": False,
        }
    tokens = get_auth_session_store().load()
    if not tokens:
        return None
    try:
        user = SupabaseAccountClient().get_account(provider_user_id, tokens.access_token, environment=_environment())
    except AccountStateUnavailable:
        logger.warning("auth_event=account_state outcome=failed reason=unavailable")
        user = {
            "user_id": provider_user_id,
            "provider_user_id": provider_user_id,
            "is_admin": False,
            "lifetime_access": False,
            "pro_active": False,
            "demo_active": False,
            "_account_available": False,
        }
    user["email"] = identity["email"].lower()
    user["email_verified"] = True
    user["_identity"] = identity
    user["_identity_verified"] = _is_verified_identity(identity)
    user.setdefault("_account_available", user.get("_account_authority") == "supabase")
    return user


def is_authenticated() -> bool:
    return _is_verified_identity(get_current_identity())


def is_admin(user: dict[str, Any] | None) -> bool:
    if not user:
        return False
    if user.get("_account_authority") != "supabase" or not user.get("is_admin"):
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

    if user.get("_account_authority") != "supabase":
        logger.warning("auth_event=pro_access outcome=blocked reason=account_state_unavailable")
        return False

    return is_admin(user) or bool(user.get("lifetime_access")) or bool(user.get("pro_active")) or bool(
        user.get("demo_active")
    )


def logout() -> None:
    tokens = get_auth_session_store().load()
    session_id = st.session_state.get("auth_session_id")
    if tokens and isinstance(session_id, str):
        try:
            SupabaseAccountClient().revoke_session(tokens.access_token, session_id)
        except AccountStateUnavailable:
            logger.warning("auth_event=account_session outcome=partial reason=control_plane_unavailable")

    provider_sign_out()
    for key in ("auth_email", "auth_session_id", "auth_session_claimed", "access_granted", "auth_identity"):
        st.session_state.pop(key, None)


def claim_session() -> str | None:
    identity = get_current_identity()
    if not _is_verified_identity(identity):
        return None

    session_id = st.session_state.get("auth_session_id")
    if not session_id:
        session_id = uuid.uuid4().hex
        st.session_state["auth_session_id"] = session_id
        st.session_state["auth_session_claimed"] = False

    if not st.session_state.get("auth_session_claimed", False):
        tokens = get_auth_session_store().load()
        if not tokens:
            return None
        try:
            SupabaseAccountClient().claim_session(tokens.access_token, session_id)
            st.session_state["auth_session_claimed"] = True
        except AccountStateUnavailable:
            logger.warning("auth_event=account_session outcome=failed reason=control_plane_unavailable")
            return None

    return session_id


def validate_session() -> bool:
    identity = get_current_identity()
    session_id = st.session_state.get("auth_session_id")
    if not _is_verified_identity(identity) or not isinstance(session_id, str):
        return False
    tokens = get_auth_session_store().load()
    if not tokens:
        return False
    try:
        active = SupabaseAccountClient().touch_session(tokens.access_token, session_id)
    except AccountStateUnavailable:
        logger.warning("auth_event=account_session outcome=failed reason=control_plane_unavailable")
        return False
    if not active:
        logger.warning("auth_event=account_session outcome=displaced reason=single_session_lock")
        logout()
    return active
