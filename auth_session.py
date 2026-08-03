from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, MutableMapping, Protocol

import streamlit as st

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


class SecureSessionBridge(Protocol):
    """Boundary for a future opaque HttpOnly-cookie backend session service.

    A conforming bridge owns provider tokens outside Streamlit and exposes only
    an opaque session identifier via a Secure, HttpOnly, SameSite cookie. This
    repository intentionally does not implement a browser token store.
    """

    def restore(self, opaque_session_id: str) -> SessionTokens | None: ...

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
    return StreamlitMemorySessionStore()
