from __future__ import annotations

from dataclasses import dataclass, field
import html
import os
from urllib.parse import urlparse
from typing import Any, MutableMapping, Protocol

import httpx
import streamlit as st
from streamlit.components.v1 import html as component_html

ACCESS_TOKEN_KEY = "supabase_access_token"
REFRESH_TOKEN_KEY = "supabase_refresh_token"


@dataclass(frozen=True)
class SessionTokens:
    """Provider tokens held only in server-side session memory."""

    access_token: str = field(repr=False)
    refresh_token: str | None = field(default=None, repr=False)


class AuthSessionStore(Protocol):
    def load(self) -> SessionTokens | None: ...

    def save(self, tokens: SessionTokens) -> None: ...

    def clear(self) -> None: ...


class SessionBridgeError(RuntimeError):
    """The trusted persistence bridge could not safely retain the session."""


class SecureSessionBridge(Protocol):
    """Boundary for the opaque HttpOnly-cookie backend session service.

    A conforming bridge owns provider tokens outside Streamlit and exposes only
    an opaque session identifier via a Secure, HttpOnly, SameSite cookie. This
    browser never receives provider tokens.
    """

    def restore(self, opaque_session_id: str) -> SessionTokens | None: ...

    def persist(self, tokens: SessionTokens, user_id: str, opaque_session_id: str | None = None) -> str | None: ...

    def revoke(self, opaque_session_id: str) -> None: ...


class StreamlitMemorySessionStore:
    """Per-WebSocket server memory; survives reruns but not browser refreshes."""

    def __init__(self, state: MutableMapping[str, Any] | None = None):
        self._state = state if state is not None else st.session_state

    def load(self) -> SessionTokens | None:
        access_token = self._state.get(ACCESS_TOKEN_KEY)
        if not isinstance(access_token, str) or not access_token:
            return None
        refresh_token = self._state.get(REFRESH_TOKEN_KEY)
        return SessionTokens(
            access_token=access_token,
            refresh_token=refresh_token if isinstance(refresh_token, str) and refresh_token else None,
        )

    def save(self, tokens: SessionTokens) -> None:
        self._state[ACCESS_TOKEN_KEY] = tokens.access_token
        if tokens.refresh_token:
            self._state[REFRESH_TOKEN_KEY] = tokens.refresh_token
        else:
            self._state.pop(REFRESH_TOKEN_KEY, None)

    def clear(self) -> None:
        self._state.pop(ACCESS_TOKEN_KEY, None)
        self._state.pop(REFRESH_TOKEN_KEY, None)


def get_auth_session_store() -> AuthSessionStore:
    if os.getenv("FURUFLOW_SESSION_BROKER_INTERNAL_URL", "").strip():
        return BrokerBackedSessionStore()
    return StreamlitMemorySessionStore()


def require_production_session_config() -> None:
    if os.getenv("ENVIRONMENT", "").strip().lower() != "production":
        return
    internal = os.getenv("FURUFLOW_SESSION_BROKER_INTERNAL_URL", "").strip()
    public = os.getenv("FURUFLOW_SESSION_BROKER_PUBLIC_ORIGIN", "").strip()
    redirect = os.getenv("SUPABASE_REDIRECT_URL_PRODUCTION", "").strip()
    bridge_key = os.getenv("FURUFLOW_SESSION_BRIDGE_KEY", "")
    public_url = urlparse(public)
    redirect_url = urlparse(redirect)
    if (
        not internal
        or public_url.scheme != "https"
        or public_url.path not in {"", "/"}
        or (public_url.scheme, public_url.netloc) != (redirect_url.scheme, redirect_url.netloc)
        or len(bridge_key) < 32
    ):
        raise RuntimeError("Production requires the secure opaque-cookie session broker.")
    if os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("FURUFLOW_SESSION_ENCRYPTION_KEY"):
        raise RuntimeError("Service-role and session-encryption credentials must not be exposed to Streamlit.")


def _browser_cookie() -> str | None:
    try:
        value = st.context.cookies.get("__Host-furuflow_session")
        return value if isinstance(value, str) and value else None
    except Exception:
        return None


class HttpSessionBridge:
    def __init__(self):
        self._url = os.environ["FURUFLOW_SESSION_BROKER_INTERNAL_URL"].rstrip("/")
        self._key = os.environ["FURUFLOW_SESSION_BRIDGE_KEY"]

    def _headers(self, opaque_session_id: str | None = None) -> dict[str, str]:
        headers = {"X-FuruFlow-Bridge-Key": self._key}
        if opaque_session_id:
            headers["X-FuruFlow-Session"] = opaque_session_id
        return headers

    def restore(self, opaque_session_id: str) -> SessionTokens | None:
        try:
            response = httpx.get(
                f"{self._url}/v1/session/restore", headers=self._headers(opaque_session_id), timeout=5.0
            )
            if response.status_code != 200:
                return None
            body = response.json()
            return SessionTokens(body["access_token"], body.get("refresh_token"))
        except (httpx.HTTPError, KeyError, ValueError):
            return None

    def persist(self, tokens: SessionTokens, user_id: str, opaque_session_id: str | None = None) -> str | None:
        body = {"user_id": user_id, "access_token": tokens.access_token, "refresh_token": tokens.refresh_token}
        try:
            if opaque_session_id:
                response = httpx.put(
                    f"{self._url}/v1/session", headers=self._headers(opaque_session_id), json=body, timeout=5.0
                )
                if response.status_code == 204:
                    return None
            response = httpx.post(
                f"{self._url}/v1/session/tickets", headers=self._headers(), json=body, timeout=5.0
            )
            response.raise_for_status()
            path = response.json()["activation_path"]
            if isinstance(path, str) and path.startswith("/auth/session/activate?ticket="):
                return path
            raise SessionBridgeError("Secure session activation was rejected.")
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise SessionBridgeError("Secure session persistence is unavailable.") from exc

    def revoke(self, opaque_session_id: str) -> None:
        try:
            httpx.delete(f"{self._url}/v1/session", headers=self._headers(opaque_session_id), timeout=5.0)
        except httpx.HTTPError:
            pass


class BrokerBackedSessionStore(StreamlitMemorySessionStore):
    """Memory-fast store restored from an opaque HttpOnly browser session."""

    def __init__(self, state: MutableMapping[str, Any] | None = None, bridge: SecureSessionBridge | None = None):
        super().__init__(state)
        self._bridge = bridge or HttpSessionBridge()

    def load(self) -> SessionTokens | None:
        cached = super().load()
        if cached:
            return cached
        opaque = _browser_cookie()
        if not opaque:
            return None
        restored = self._bridge.restore(opaque)
        if restored:
            super().save(restored)
        return restored

    def save(self, tokens: SessionTokens) -> None:
        super().save(tokens)

    def clear(self) -> None:
        opaque = _browser_cookie()
        if opaque:
            self._bridge.revoke(opaque)
        self._state.pop("furuflow_session_activation", None)
        super().clear()


def persist_current_session(user_id: str) -> None:
    store = get_auth_session_store()
    tokens = store.load()
    if isinstance(store, BrokerBackedSessionStore) and tokens:
        activation = store._bridge.persist(tokens, user_id, _browser_cookie())
        if activation:
            st.session_state["furuflow_session_activation"] = activation


def render_pending_session_activation() -> None:
    path = st.session_state.get("furuflow_session_activation")
    origin = os.getenv("FURUFLOW_SESSION_BROKER_PUBLIC_ORIGIN", "").rstrip("/")
    if not isinstance(path, str) or not path.startswith("/auth/session/activate?ticket=") or not origin:
        return
    url = html.escape(origin + path, quote=True)
    component_html(f'<iframe src="{url}" referrerpolicy="no-referrer" style="display:none"></iframe>', height=0)
