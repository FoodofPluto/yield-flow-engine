from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from datetime import UTC, datetime
from typing import Any

import streamlit as st

from db import get_user_by_email, get_user_by_provider_user_id, upsert_user
from supabase_client import get_supabase_client, get_supabase_jwks_url

logger = logging.getLogger(__name__)

AUTH_PROVIDER = "supabase"
ACCESS_TOKEN_KEY = "supabase_access_token"
REFRESH_TOKEN_KEY = "supabase_refresh_token"
IDENTITY_KEY = "auth_identity"


class AuthSessionError(RuntimeError):
    pass


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _decode_jwt_unverified(token: str) -> dict[str, Any]:
    return _decode_jwt_part(token, 1, "payload")


def _decode_jwt_header_unverified(token: str) -> dict[str, Any]:
    return _decode_jwt_part(token, 0, "header")


def _decode_jwt_part(token: str, index: int, label: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise AuthSessionError("Invalid Supabase access token format.")
    try:
        return json.loads(_b64url_decode(parts[index]))
    except Exception as exc:
        raise AuthSessionError(f"Invalid Supabase access token {label}.") from exc


def _validate_hs256_jwt(token: str, secret: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise AuthSessionError("Invalid Supabase access token format.")

    signing_input = f"{parts[0]}.{parts[1]}".encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    supplied = _b64url_decode(parts[2])
    if not hmac.compare_digest(expected, supplied):
        raise AuthSessionError("Invalid Supabase access token signature.")

    claims = _decode_jwt_unverified(token)
    exp = claims.get("exp")
    if not isinstance(exp, int) or exp <= int(time.time()):
        raise AuthSessionError("Supabase access token is expired.")

    if claims.get("aud") not in {"authenticated", "supabase"}:
        raise AuthSessionError("Supabase access token has an unexpected audience.")

    return claims


def _validate_jwks_jwt(token: str, jwks_url: str) -> dict[str, Any]:
    try:
        import jwt

        signing_key = jwt.PyJWKClient(jwks_url).get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256"],
            audience=["authenticated", "supabase"],
            options={"require": ["exp", "sub"]},
        )
    except Exception as exc:
        logger.warning("Supabase JWKS token validation failed: %s", exc)
        raise AuthSessionError("Supabase JWKS token validation failed.") from exc


def _verified_identity_from_claims(token: str, claims: dict[str, Any]) -> dict[str, Any]:
    provider_user_id = claims.get("sub")
    email = (claims.get("email") or "").strip().lower()
    if not provider_user_id or not email:
        raise AuthSessionError("Supabase token is missing required identity claims.")
    if not _email_verified_from_claims(claims):
        raise AuthSessionError("Supabase identity email is not verified.")
    return {
        "provider_user_id": provider_user_id,
        "email": email,
        "email_verified": True,
        "access_token": token,
        "claims": claims,
    }


def _email_verified_from_claims(claims: dict[str, Any]) -> bool:
    user_metadata = claims.get("user_metadata") or {}
    app_metadata = claims.get("app_metadata") or {}
    return bool(
        claims.get("email_confirmed_at")
        or claims.get("confirmed_at")
        or user_metadata.get("email_verified")
        or app_metadata.get("email_verified")
    )


def validate_supabase_session(token: str | None = None) -> dict[str, Any] | None:
    if not token:
        return None

    header = _decode_jwt_header_unverified(token)
    alg = header.get("alg")
    jwt_secret = os.getenv("SUPABASE_JWT_SECRET")
    if alg == "HS256" and jwt_secret:
        return _verified_identity_from_claims(token, _validate_hs256_jwt(token, jwt_secret))

    jwks_url = get_supabase_jwks_url()
    if alg == "ES256" and jwks_url:
        return _verified_identity_from_claims(token, _validate_jwks_jwt(token, jwks_url))

    if jwt_secret or jwks_url:
        raise AuthSessionError("Supabase token uses an unsupported signing algorithm or signing configuration.")

    client = get_supabase_client()
    if not client:
        return None

    try:
        response = client.auth.get_user(token)
    except Exception as exc:
        logger.warning("Supabase token validation failed: %s", exc)
        raise AuthSessionError("Supabase token validation failed.") from exc

    user = getattr(response, "user", None)
    if not user:
        raise AuthSessionError("Supabase token did not resolve to a user.")

    provider_user_id = getattr(user, "id", None)
    email = (getattr(user, "email", "") or "").strip().lower()
    email_confirmed_at = getattr(user, "email_confirmed_at", None)
    if not provider_user_id or not email:
        raise AuthSessionError("Supabase user response is missing identity fields.")
    if not email_confirmed_at:
        raise AuthSessionError("Supabase email is not verified.")

    return {
        "provider_user_id": provider_user_id,
        "email": email,
        "email_verified": True,
        "access_token": token,
        "claims": {},
    }


def _store_session(session: Any) -> None:
    access_token = getattr(session, "access_token", None)
    refresh_token = getattr(session, "refresh_token", None)
    if not access_token:
        raise AuthSessionError("Supabase login did not return an access token.")
    st.session_state[ACCESS_TOKEN_KEY] = access_token
    if refresh_token:
        st.session_state[REFRESH_TOKEN_KEY] = refresh_token


def sign_in_with_password(email: str, password: str) -> dict[str, Any]:
    client = get_supabase_client()
    if not client:
        raise AuthSessionError("Supabase client is not configured.")

    response = client.auth.sign_in_with_password({"email": email.strip().lower(), "password": password})
    session = getattr(response, "session", None)
    if not session:
        raise AuthSessionError("Supabase password login did not return a session.")
    _store_session(session)
    return resolve_verified_identity(validate_supabase_session(session.access_token))


def request_magic_link(email: str) -> None:
    client = get_supabase_client()
    if not client:
        raise AuthSessionError("Supabase client is not configured.")
    client.auth.sign_in_with_otp({"email": email.strip().lower()})


def refresh_session() -> dict[str, Any] | None:
    refresh_token = st.session_state.get(REFRESH_TOKEN_KEY)
    if not refresh_token:
        return None
    client = get_supabase_client()
    if not client:
        return None

    try:
        response = client.auth.refresh_session(refresh_token)
    except Exception as exc:
        logger.warning("Supabase session refresh failed: %s", exc)
        raise AuthSessionError("Supabase session refresh failed.") from exc

    session = getattr(response, "session", None)
    if not session:
        raise AuthSessionError("Supabase refresh did not return a session.")
    _store_session(session)
    return resolve_verified_identity(validate_supabase_session(session.access_token))


def resolve_verified_identity(auth_user: dict[str, Any] | None) -> dict[str, Any] | None:
    if not auth_user:
        return None

    provider_user_id = auth_user.get("provider_user_id")
    email = (auth_user.get("email") or "").strip().lower()
    if not provider_user_id or not email or not auth_user.get("email_verified"):
        raise AuthSessionError("Supabase identity is not verified.")

    existing_by_provider = get_user_by_provider_user_id(provider_user_id)
    now = datetime.now(UTC).isoformat()
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
            migration_notes = "Matched verified Supabase email to legacy account; admin role preserved only if previously assigned manually."
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
    return identity


def validate_authenticated_session() -> dict[str, Any] | None:
    token = st.session_state.get(ACCESS_TOKEN_KEY)
    if not token:
        return None

    try:
        return resolve_verified_identity(validate_supabase_session(token))
    except AuthSessionError as exc:
        if "expired" in str(exc).lower():
            logger.info("Supabase access token expired; attempting refresh.")
            refreshed = refresh_session()
            if refreshed:
                return refreshed
            clear_cached_session()
            raise AuthSessionError("Supabase session expired and could not be refreshed.") from exc
        logger.warning("Invalid Supabase session rejected: %s", exc)
        raise


def clear_cached_session() -> None:
    for key in (ACCESS_TOKEN_KEY, REFRESH_TOKEN_KEY, IDENTITY_KEY):
        st.session_state.pop(key, None)


def get_supabase_identity() -> dict[str, Any] | None:
    return validate_authenticated_session()
