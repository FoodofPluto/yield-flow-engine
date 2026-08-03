from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, MutableMapping
from urllib.parse import urlencode

import httpx
import streamlit as st

from auth_session import (
    ACCESS_TOKEN_KEY,
    REFRESH_TOKEN_KEY,
    SessionTokens,
    get_auth_session_store,
)
from db import get_user_by_email, get_user_by_provider_user_id, upsert_user
from supabase_client import AuthConfigurationError, get_supabase_client, load_auth_config

logger = logging.getLogger(__name__)

AUTH_PROVIDER = "supabase"
IDENTITY_KEY = "auth_identity"
IDENTITY_VALIDATED_AT_KEY = "auth_identity_validated_at"
AUTH_NOTICE_KEY = "auth_notice"
PASSWORD_RECOVERY_KEY = "supabase_password_recovery"
IDENTITY_REVALIDATE_SECONDS = 60
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_CALLBACK_ACTIONS = {"signin", "verify", "recovery"}
_SENSITIVE_CALLBACK_PARAMETERS = {
    "code",
    "token",
    "token_hash",
    "access_token",
    "refresh_token",
    "expires_in",
    "expires_at",
    "type",
    "error",
    "error_code",
    "error_description",
    "auth_action",
    "auth_state",
}
_PKCE_FLOW_TTL_SECONDS = 10 * 60
_PKCE_FLOW_LIMIT = 1024
_PKCE_FLOWS: dict[str, "_PKCEFlow"] = {}
_PKCE_FLOW_LOCK = threading.Lock()


class AuthSessionError(RuntimeError):
    def __init__(self, message: str, code: str = "auth_error"):
        self.code = code
        super().__init__(message)


class _ProviderFlowError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class _PKCEFlow:
    verifier: str
    action: str
    created_at: float


def _prune_pkce_flows(now: float) -> None:
    expired = [state for state, flow in _PKCE_FLOWS.items() if now - flow.created_at > _PKCE_FLOW_TTL_SECONDS]
    for state in expired:
        _PKCE_FLOWS.pop(state, None)
    while len(_PKCE_FLOWS) >= _PKCE_FLOW_LIMIT:
        oldest = min(_PKCE_FLOWS, key=lambda state: _PKCE_FLOWS[state].created_at)
        _PKCE_FLOWS.pop(oldest, None)


def _create_pkce_flow(action: str) -> tuple[str, str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
    state = secrets.token_urlsafe(32)
    now = time.time()
    with _PKCE_FLOW_LOCK:
        _prune_pkce_flows(now)
        _PKCE_FLOWS[state] = _PKCEFlow(verifier=verifier, action=action, created_at=now)
    return state, verifier, challenge


def _consume_pkce_flow(state: str | None, action: str) -> str:
    if not state or len(state) > 256 or not re.fullmatch(r"[A-Za-z0-9_-]+", state):
        raise AuthSessionError("This authentication link is invalid or expired. Request a new one.", "missing_callback_state")
    now = time.time()
    with _PKCE_FLOW_LOCK:
        _prune_pkce_flows(now)
        flow = _PKCE_FLOWS.pop(state, None)
    if not flow or flow.action != action:
        raise AuthSessionError("This authentication link is invalid or expired. Request a new one.", "invalid_callback_state")
    return flow.verifier


def _discard_pkce_flow(state: str) -> None:
    with _PKCE_FLOW_LOCK:
        _PKCE_FLOWS.pop(state, None)


def _auth_event(event: str, outcome: str, reason: str) -> None:
    """Emit bounded operational state without tokens, URLs, or user PII."""

    safe = re.compile(r"^[a-z0-9_]{1,48}$")
    if not all(safe.fullmatch(value) for value in (event, outcome, reason)):
        return
    logger.info("auth_event=%s outcome=%s reason=%s", event, outcome, reason)


def _normalise_email(email: str) -> str:
    value = (email or "").strip().lower()
    if not _EMAIL_RE.fullmatch(value):
        raise AuthSessionError("Enter a valid email address.", "invalid_email")
    return value


def _validate_password(password: str) -> None:
    if len(password or "") < 12:
        raise AuthSessionError("Use a password with at least 12 characters.", "weak_password")


def _provider_code(exc: Exception) -> str:
    for attribute in ("code", "error_code"):
        value = getattr(exc, attribute, None)
        if isinstance(value, str) and value:
            return value.strip().lower()
    message = str(exc).lower()
    patterns = {
        "invalid_credentials": ("invalid login credentials", "invalid credentials"),
        "email_not_confirmed": ("email not confirmed",),
        "user_banned": ("user is banned", "banned"),
        "user_not_found": ("user not found", "account not found"),
        "rate_limit": ("rate limit", "too many requests", "over_email_send_rate_limit"),
        "otp_expired": ("otp expired", "token has expired", "expired"),
        "email_exists": ("already registered", "already exists", "user_already_exists", "email_exists"),
        "same_password": ("same password",),
        "bad_jwt": ("bad jwt", "invalid jwt", "jwt expired"),
    }
    for code, needles in patterns.items():
        if any(needle in message for needle in needles):
            return code
    return "provider_error"


def _user_facing_provider_error(exc: Exception, operation: str) -> AuthSessionError:
    code = _provider_code(exc)
    if code in {"invalid_credentials", "invalid_grant"}:
        return AuthSessionError("Email or password is incorrect.", "invalid_credentials")
    if code == "email_not_confirmed":
        return AuthSessionError("Verify your email address before signing in.", "email_not_confirmed")
    if code in {"user_banned", "user_not_found"}:
        return AuthSessionError("This account is unavailable. Contact support if this is unexpected.", "account_unavailable")
    if code in {"rate_limit", "over_request_rate_limit", "over_email_send_rate_limit"}:
        return AuthSessionError("Too many authentication attempts. Wait a few minutes and try again.", "rate_limited")
    if code in {"otp_expired", "bad_jwt", "session_not_found", "refresh_token_not_found"}:
        return AuthSessionError("This authentication session or link has expired. Request a new one.", "expired")
    if code == "same_password":
        return AuthSessionError("Choose a password you have not used for this account.", "same_password")
    if operation == "signup" and code in {"email_exists", "user_already_exists"}:
        return AuthSessionError("Check your inbox to continue. If the account exists, use sign in or password reset.", "duplicate_email")
    return AuthSessionError("Authentication could not be completed. Try again shortly.", "provider_error")


def _client():
    try:
        client = get_supabase_client()
    except AuthConfigurationError as exc:
        _auth_event("configuration", "failed", "invalid")
        raise AuthSessionError("Authentication is not configured for this deployment.", "configuration") from exc
    except Exception as exc:
        _auth_event("client", "failed", "unavailable")
        raise AuthSessionError("Authentication is temporarily unavailable.", "provider_unavailable") from exc
    if client is None:
        raise AuthSessionError("Authentication is not configured for this deployment.", "configuration")
    return client


def get_auth_redirect_url(action: str, state: str | None = None) -> str:
    if action not in _CALLBACK_ACTIONS:
        raise ValueError("Unsupported authentication callback action.")
    try:
        config = load_auth_config()
    except AuthConfigurationError as exc:
        raise AuthSessionError("Authentication redirect configuration is incomplete.", "configuration") from exc
    parameters = {"auth_action": action}
    if state:
        parameters["auth_state"] = state
    return f"{config.redirect_base_url}?{urlencode(parameters)}"


def _auth_http_post(endpoint: str, body: dict[str, Any], redirect_to: str) -> dict[str, Any]:
    try:
        config = load_auth_config()
        response = httpx.post(
            f"{config.project_url}/auth/v1/{endpoint}",
            params={"redirect_to": redirect_to},
            headers={
                "apikey": config.anon_key,
                "Authorization": f"Bearer {config.anon_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=10.0,
            follow_redirects=False,
        )
    except AuthConfigurationError as exc:
        raise AuthSessionError("Authentication is not configured for this deployment.", "configuration") from exc
    except httpx.HTTPError as exc:
        raise _ProviderFlowError("provider_unavailable") from exc

    try:
        payload = response.json() if response.content else {}
    except ValueError:
        payload = {}
    if response.status_code < 200 or response.status_code >= 300:
        code = (payload.get("code") or payload.get("error_code")) if isinstance(payload, dict) else None
        raise _ProviderFlowError(code if isinstance(code, str) and code else f"http_{response.status_code}")
    return payload if isinstance(payload, dict) else {}


def _begin_pkce_email_flow(endpoint: str, action: str, body: dict[str, Any]) -> dict[str, Any]:
    state, _verifier, challenge = _create_pkce_flow(action)
    redirect_to = get_auth_redirect_url(action, state)
    request_body = {
        **body,
        "code_challenge": challenge,
        "code_challenge_method": "s256",
    }
    try:
        payload = _auth_http_post(endpoint, request_body, redirect_to)
        if endpoint == "signup" and payload.get("access_token"):
            _discard_pkce_flow(state)
        return payload
    except Exception:
        _discard_pkce_flow(state)
        raise


def _signup_response(payload: dict[str, Any]) -> Any:
    user_payload = payload.get("user") if isinstance(payload.get("user"), dict) else payload
    identities = user_payload.get("identities") if isinstance(user_payload, dict) else None
    user = SimpleNamespace(identities=identities) if isinstance(user_payload, dict) else None
    access_token = payload.get("access_token")
    session = None
    if isinstance(access_token, str) and access_token:
        refresh_token = payload.get("refresh_token")
        session = SimpleNamespace(
            access_token=access_token,
            refresh_token=refresh_token if isinstance(refresh_token, str) else None,
        )
    return SimpleNamespace(user=user, session=session)


def _store_session(session: Any) -> None:
    access_token = getattr(session, "access_token", None)
    refresh_token = getattr(session, "refresh_token", None)
    if not isinstance(access_token, str) or not access_token:
        raise AuthSessionError("Authentication did not return a usable session.", "missing_session")
    get_auth_session_store().save(
        SessionTokens(
            access_token=access_token,
            refresh_token=refresh_token if isinstance(refresh_token, str) and refresh_token else None,
        )
    )


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _token_is_expired(token: str) -> bool:
    """Use unverified expiry only to decide whether to attempt provider refresh."""

    try:
        parts = token.split(".")
        if len(parts) != 3:
            return False
        payload = json.loads(_b64url_decode(parts[1]))
        exp = payload.get("exp")
        return isinstance(exp, int) and exp <= int(time.time())
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return False


def validate_supabase_session(token: str | None = None) -> dict[str, Any] | None:
    """Resolve identity through Supabase Auth, never mutable JWT metadata."""

    if not token:
        return None
    try:
        response = _client().auth.get_user(token)
    except AuthSessionError:
        raise
    except Exception as exc:
        error = _user_facing_provider_error(exc, "validate")
        _auth_event("session_validate", "failed", error.code)
        raise error from exc

    user = getattr(response, "user", None)
    provider_user_id = getattr(user, "id", None) if user else None
    email = (getattr(user, "email", "") or "").strip().lower() if user else ""
    email_confirmed_at = getattr(user, "email_confirmed_at", None) if user else None
    if not user or not provider_user_id or not email:
        _auth_event("session_validate", "failed", "revoked_or_missing")
        raise AuthSessionError("This account session is no longer valid. Sign in again.", "account_unavailable")
    if getattr(user, "deleted_at", None) or getattr(user, "banned_until", None):
        _auth_event("session_validate", "failed", "account_unavailable")
        raise AuthSessionError("This account is unavailable. Contact support if this is unexpected.", "account_unavailable")
    if not email_confirmed_at:
        _auth_event("session_validate", "failed", "email_unverified")
        raise AuthSessionError("Verify your email address before signing in.", "email_not_confirmed")

    _auth_event("session_validate", "succeeded", "verified")
    return {
        "provider_user_id": str(provider_user_id),
        "email": email,
        "email_verified": True,
        "email_confirmed_at": email_confirmed_at,
    }


def signup(email: str, password: str) -> dict[str, Any]:
    address = _normalise_email(email)
    _validate_password(password)
    try:
        response = _signup_response(
            _begin_pkce_email_flow(
                "signup",
                "verify",
                {
                    "email": address,
                    "password": password,
                    "data": {},
                    "gotrue_meta_security": {"captcha_token": None},
                },
            )
        )
    except AuthSessionError:
        raise
    except Exception as exc:
        error = _user_facing_provider_error(exc, "signup")
        if error.code == "duplicate_email":
            _auth_event("signup", "accepted", "duplicate_obscured")
            return {"status": "verification_required"}
        _auth_event("signup", "failed", error.code)
        raise error from exc

    session = getattr(response, "session", None)
    user = getattr(response, "user", None)
    identities = getattr(user, "identities", None) if user else None
    if session:
        _store_session(session)
        identity = resolve_verified_identity(validate_supabase_session(session.access_token))
        _auth_event("signup", "succeeded", "session_created")
        return {"status": "signed_in", "identity": identity}
    if identities == []:
        _auth_event("signup", "accepted", "duplicate_obscured")
    else:
        _auth_event("signup", "accepted", "verification_pending")
    return {"status": "verification_required"}


def resend_verification(email: str) -> None:
    address = _normalise_email(email)
    try:
        _begin_pkce_email_flow(
            "resend",
            "verify",
            {
                "type": "signup",
                "email": address,
                "gotrue_meta_security": {"captcha_token": None},
            },
        )
    except AuthSessionError:
        raise
    except Exception as exc:
        error = _user_facing_provider_error(exc, "resend")
        if error.code in {"account_unavailable", "invalid_credentials"}:
            _auth_event("verification_resend", "accepted", "account_obscured")
            return
        _auth_event("verification_resend", "failed", error.code)
        raise error from exc
    _auth_event("verification_resend", "accepted", "provider_accepted")


def sign_in_with_password(email: str, password: str) -> dict[str, Any]:
    address = _normalise_email(email)
    if not password:
        raise AuthSessionError("Enter your password.", "missing_password")
    try:
        response = _client().auth.sign_in_with_password({"email": address, "password": password})
    except AuthSessionError:
        raise
    except Exception as exc:
        error = _user_facing_provider_error(exc, "password_login")
        _auth_event("password_login", "failed", error.code)
        raise error from exc
    session = getattr(response, "session", None)
    if not session:
        raise AuthSessionError("Password sign-in did not return a session.", "missing_session")
    _store_session(session)
    try:
        identity = resolve_verified_identity(validate_supabase_session(session.access_token))
    except AuthSessionError:
        clear_cached_session()
        raise
    if identity is None:
        clear_cached_session()
        raise AuthSessionError("Password sign-in did not resolve an identity.", "missing_identity")
    _auth_event("password_login", "succeeded", "verified")
    return identity


def request_magic_link(email: str) -> None:
    address = _normalise_email(email)
    try:
        _begin_pkce_email_flow(
            "otp",
            "signin",
            {
                "email": address,
                "data": {},
                "create_user": False,
                "gotrue_meta_security": {"captcha_token": None},
            },
        )
    except AuthSessionError:
        raise
    except Exception as exc:
        error = _user_facing_provider_error(exc, "magic_link")
        if error.code in {"account_unavailable", "invalid_credentials"}:
            _auth_event("magic_link_request", "accepted", "account_obscured")
            return
        _auth_event("magic_link_request", "failed", error.code)
        raise error from exc
    _auth_event("magic_link_request", "accepted", "provider_accepted")


def request_password_reset(email: str) -> None:
    address = _normalise_email(email)
    try:
        _begin_pkce_email_flow(
            "recover",
            "recovery",
            {
                "email": address,
                "gotrue_meta_security": {"captcha_token": None},
            },
        )
    except AuthSessionError:
        raise
    except Exception as exc:
        error = _user_facing_provider_error(exc, "password_reset_request")
        if error.code in {"account_unavailable", "invalid_credentials"}:
            _auth_event("password_reset_request", "accepted", "account_obscured")
            return
        _auth_event("password_reset_request", "failed", error.code)
        raise error from exc
    _auth_event("password_reset_request", "accepted", "provider_accepted")


def _query_value(query_params: MutableMapping[str, Any], name: str) -> str | None:
    value = query_params.get(name)
    if isinstance(value, list):
        value = value[0] if value else None
    return value if isinstance(value, str) and value else None


def remove_sensitive_callback_parameters(query_params: MutableMapping[str, Any] | None = None) -> None:
    params = st.query_params if query_params is None else query_params
    for name in _SENSITIVE_CALLBACK_PARAMETERS:
        if name in params:
            del params[name]


def handle_auth_callback(query_params: MutableMapping[str, Any] | None = None) -> dict[str, Any] | None:
    params = st.query_params if query_params is None else query_params
    code = _query_value(params, "code")
    callback_state = _query_value(params, "auth_state")
    provider_error = _query_value(params, "error") or _query_value(params, "error_code")
    has_query_token = any(_query_value(params, name) for name in ("access_token", "refresh_token", "token"))
    if not code and not provider_error and not has_query_token:
        return None

    action = (_query_value(params, "auth_action") or "signin").lower()
    if action not in _CALLBACK_ACTIONS:
        action = "signin"
    try:
        if provider_error:
            if callback_state:
                _discard_pkce_flow(callback_state)
            raise AuthSessionError("This authentication link is invalid or expired. Request a new one.", "callback_rejected")
        if has_query_token:
            if callback_state:
                _discard_pkce_flow(callback_state)
            raise AuthSessionError("This deployment only accepts secure authorization-code callbacks.", "unsafe_callback")
        if not code or len(code) > 2048 or any(character.isspace() for character in code):
            raise AuthSessionError("This authentication link is invalid or expired. Request a new one.", "invalid_callback")
        code_verifier = _consume_pkce_flow(callback_state, action)
        try:
            response = _client().auth.exchange_code_for_session(
                {
                    "auth_code": code,
                    "code_verifier": code_verifier,
                    "redirect_to": get_auth_redirect_url(action, callback_state),
                }
            )
        except AuthSessionError:
            raise
        except Exception as exc:
            raise _user_facing_provider_error(exc, "callback") from exc
        session = getattr(response, "session", None)
        if not session:
            raise AuthSessionError("This authentication link did not create a session. Request a new one.", "missing_session")
        _store_session(session)
        try:
            identity = resolve_verified_identity(validate_supabase_session(session.access_token))
        except AuthSessionError:
            clear_cached_session()
            raise
        st.session_state[PASSWORD_RECOVERY_KEY] = action == "recovery"
        _auth_event("callback_exchange", "succeeded", action)
        return {"status": "password_recovery" if action == "recovery" else "signed_in", "identity": identity}
    except AuthSessionError as exc:
        _auth_event("callback_exchange", "failed", exc.code)
        raise
    finally:
        # Authorization codes and provider errors are single-use callback state;
        # never leave them in the visible browser URL after processing.
        remove_sensitive_callback_parameters(params)


def complete_password_reset(new_password: str) -> dict[str, Any]:
    _validate_password(new_password)
    if not st.session_state.get(PASSWORD_RECOVERY_KEY):
        raise AuthSessionError("Open a fresh password-reset link before choosing a new password.", "recovery_required")
    tokens = get_auth_session_store().load()
    if not tokens:
        raise AuthSessionError("The password-reset session expired. Request a new reset link.", "expired")
    client = _client()
    try:
        session_response = client.auth.set_session(tokens.access_token, tokens.refresh_token or "")
        refreshed_session = getattr(session_response, "session", None)
        if refreshed_session:
            _store_session(refreshed_session)
        client.auth.update_user({"password": new_password})
    except Exception as exc:
        error = _user_facing_provider_error(exc, "password_reset_complete")
        _auth_event("password_reset_complete", "failed", error.code)
        raise error from exc
    st.session_state[PASSWORD_RECOVERY_KEY] = False
    identity = validate_authenticated_session()
    _auth_event("password_reset_complete", "succeeded", "updated")
    return identity or {}


def refresh_session() -> dict[str, Any] | None:
    tokens = get_auth_session_store().load()
    if not tokens or not tokens.refresh_token:
        return None
    try:
        response = _client().auth.refresh_session(tokens.refresh_token)
    except AuthSessionError:
        clear_cached_session()
        raise
    except Exception as exc:
        clear_cached_session()
        error = _user_facing_provider_error(exc, "refresh")
        _auth_event("token_refresh", "failed", error.code)
        raise error from exc
    session = getattr(response, "session", None)
    if not session:
        clear_cached_session()
        raise AuthSessionError("The session could not be refreshed. Sign in again.", "expired")
    _store_session(session)
    identity = resolve_verified_identity(validate_supabase_session(session.access_token))
    _auth_event("token_refresh", "succeeded", "rotated")
    return identity


def resolve_verified_identity(auth_user: dict[str, Any] | None) -> dict[str, Any] | None:
    if not auth_user:
        return None

    provider_user_id = auth_user.get("provider_user_id")
    email = (auth_user.get("email") or "").strip().lower()
    if not provider_user_id or not email or not auth_user.get("email_verified"):
        raise AuthSessionError("Supabase identity is not verified.", "email_not_confirmed")

    existing_by_provider = get_user_by_provider_user_id(provider_user_id)
    now = datetime.now(timezone.utc).isoformat()
    migration_notes = None
    migrated_from_legacy = False

    if existing_by_provider:
        user = upsert_user(
            email=existing_by_provider["email"],
            provider_user_id=provider_user_id,
            auth_provider=AUTH_PROVIDER,
            email_verified=True,
            last_login_at=now,
        )
    else:
        legacy_user = get_user_by_email(email)
        if legacy_user:
            migrated_from_legacy = legacy_user.get("auth_provider") == "legacy_email"
            migration_notes = "Matched authoritative Supabase identity to the existing local account."
        user = upsert_user(
            email=email,
            provider_user_id=provider_user_id,
            auth_provider=AUTH_PROVIDER,
            email_verified=True,
            last_login_at=now,
            migrated_at=now if migrated_from_legacy else None,
            migrated_from_legacy=migrated_from_legacy if migrated_from_legacy else None,
            migration_notes=migration_notes,
        )

    identity = {
        "email": user["email"],
        "provider_user_id": provider_user_id,
        "auth_provider": AUTH_PROVIDER,
        "email_verified": True,
        "authenticated": True,
        "legacy": False,
        "user_id": user["user_id"],
    }
    st.session_state[IDENTITY_KEY] = identity
    st.session_state[IDENTITY_VALIDATED_AT_KEY] = time.time()
    return identity


def validate_authenticated_session() -> dict[str, Any] | None:
    tokens = get_auth_session_store().load()
    if not tokens:
        return None
    if _token_is_expired(tokens.access_token):
        refreshed = refresh_session()
        if refreshed:
            return refreshed
        clear_cached_session()
        raise AuthSessionError("The session expired. Sign in again.", "expired")

    try:
        return resolve_verified_identity(validate_supabase_session(tokens.access_token))
    except AuthSessionError as exc:
        if exc.code == "expired" and tokens.refresh_token:
            return refresh_session()
        clear_cached_session()
        raise


def provider_sign_out() -> bool:
    tokens = get_auth_session_store().load()
    provider_revoked = False
    try:
        if tokens:
            _client().auth.admin.sign_out(tokens.access_token, "global")
            provider_revoked = True
            _auth_event("logout", "succeeded", "provider_revoked")
        else:
            _auth_event("logout", "succeeded", "local_only")
    except Exception:
        # Local credentials are always cleared even if the provider is down.
        _auth_event("logout", "partial", "provider_unavailable")
    finally:
        clear_cached_session()
    return provider_revoked


def clear_cached_session() -> None:
    get_auth_session_store().clear()
    for key in (IDENTITY_KEY, IDENTITY_VALIDATED_AT_KEY, PASSWORD_RECOVERY_KEY):
        st.session_state.pop(key, None)


def set_auth_notice(message: str, code: str, level: str = "error") -> None:
    if level not in {"error", "info", "success", "warning"}:
        level = "error"
    st.session_state[AUTH_NOTICE_KEY] = {"message": message, "code": code, "level": level}


def pop_auth_notice() -> dict[str, str] | None:
    notice = st.session_state.pop(AUTH_NOTICE_KEY, None)
    return notice if isinstance(notice, dict) else None


def get_supabase_identity() -> dict[str, Any] | None:
    cached = st.session_state.get(IDENTITY_KEY)
    validated_at = st.session_state.get(IDENTITY_VALIDATED_AT_KEY)
    tokens = get_auth_session_store().load()
    if (
        isinstance(cached, dict)
        and isinstance(validated_at, (int, float))
        and tokens
        and not _token_is_expired(tokens.access_token)
        and time.time() - validated_at < IDENTITY_REVALIDATE_SECONDS
    ):
        return cached
    return validate_authenticated_session()
