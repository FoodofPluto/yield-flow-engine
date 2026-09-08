from __future__ import annotations

from unittest.mock import patch

import auth_session
import pytest
from auth_session import BrokerBackedSessionStore, SessionBridgeError, SessionTokens


class FakeBridge:
    def __init__(self):
        self.tokens: SessionTokens | None = None
        self.revoked = False

    def restore(self, opaque_session_id: str) -> SessionTokens | None:
        return None if self.revoked or opaque_session_id != "opaque-cookie" else self.tokens

    def persist(self, tokens: SessionTokens, user_id: str, opaque_session_id: str | None = None) -> str | None:
        self.tokens = tokens
        return None if opaque_session_id else "/auth/session/activate?ticket=single-use-ticket"

    def revoke(self, opaque_session_id: str) -> None:
        self.revoked = True


def test_browser_refresh_restores_valid_server_side_session() -> None:
    bridge = FakeBridge()
    first_state = {"auth_identity": {"provider_user_id": "user-1"}}
    first = BrokerBackedSessionStore(first_state, bridge)
    with patch("auth_session._browser_cookie", return_value=None):
        first.save(SessionTokens("access", "refresh"))
        with patch("auth_session.get_auth_session_store", return_value=first):
            with patch.object(auth_session.st, "session_state", first_state):
                auth_session.persist_current_session("user-1")
    assert "ticket=" in first_state["furuflow_session_activation"]

    refreshed = BrokerBackedSessionStore({}, bridge)
    with patch("auth_session._browser_cookie", return_value="opaque-cookie"):
        assert refreshed.load() == SessionTokens("access", "refresh")


def test_revoked_browser_session_fails_closed_on_refresh() -> None:
    bridge = FakeBridge()
    bridge.tokens = SessionTokens("access", "refresh")
    bridge.revoked = True
    refreshed = BrokerBackedSessionStore({}, bridge)
    with patch("auth_session._browser_cookie", return_value="opaque-cookie"):
        assert refreshed.load() is None


def test_broker_persistence_failure_does_not_silently_claim_refresh_support() -> None:
    class FailingBridge(FakeBridge):
        def persist(self, tokens: SessionTokens, user_id: str, opaque_session_id: str | None = None) -> str | None:
            raise SessionBridgeError("unavailable")

    state: dict[str, object] = {}
    store = BrokerBackedSessionStore(state, FailingBridge())
    store.save(SessionTokens("access", "refresh"))
    with patch("auth_session._browser_cookie", return_value=None):
        with patch("auth_session.get_auth_session_store", return_value=store):
            with pytest.raises(SessionBridgeError):
                auth_session.persist_current_session("user-1")


def test_pending_activation_is_rendered_once_then_removed_from_session_state() -> None:
    synthetic_ticket = "synthetic-single-use-ticket"
    state = {"furuflow_session_activation": f"/auth/session/activate?ticket={synthetic_ticket}"}
    with patch.dict(
        auth_session.os.environ,
        {"FURUFLOW_SESSION_BROKER_PUBLIC_ORIGIN": "https://app.invalid"},
        clear=False,
    ):
        with patch.object(auth_session.st, "session_state", state):
            with patch("auth_session.component_html") as render:
                auth_session.render_pending_session_activation()
                auth_session.render_pending_session_activation()

    assert "furuflow_session_activation" not in state
    render.assert_called_once()
    markup = render.call_args.args[0]
    assert f"https://app.invalid/auth/session/activate?ticket={synthetic_ticket}" in markup
    assert 'referrerpolicy="no-referrer"' in markup
    assert 'onload="this.remove()"' in markup


def test_pending_activation_rejects_unexpected_ticket_paths_without_rendering() -> None:
    state = {"furuflow_session_activation": "/auth/session/activate?ticket=synthetic&next=https://evil.invalid"}
    with patch.dict(
        auth_session.os.environ,
        {"FURUFLOW_SESSION_BROKER_PUBLIC_ORIGIN": "https://app.invalid"},
        clear=False,
    ):
        with patch.object(auth_session.st, "session_state", state):
            with patch("auth_session.component_html") as render:
                auth_session.render_pending_session_activation()

    assert "furuflow_session_activation" not in state
    render.assert_not_called()
