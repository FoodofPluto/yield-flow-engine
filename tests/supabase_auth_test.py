from __future__ import annotations

import base64
import importlib
import json
import os
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

import pytest
import streamlit as st

PROJECT_URL = "https://abcdefghijklmnopqrst.supabase.co"
PUBLISHABLE_KEY = "sb_publishable_" + "A" * 32


def _session(access: str = "access-token", refresh: str = "refresh-token") -> SimpleNamespace:
    return SimpleNamespace(access_token=access, refresh_token=refresh)


def _expired_token() -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"ES256"}').decode().rstrip("=")
    payload = base64.urlsafe_b64encode(json.dumps({"exp": int(time.time()) - 30}).encode()).decode().rstrip("=")
    return f"{header}.{payload}.signature"


class FakeAdmin:
    def __init__(self):
        self.sign_out_calls: list[tuple[str, str]] = []

    def sign_out(self, token: str, scope: str) -> None:
        self.sign_out_calls.append((token, scope))


class FakeAuth:
    def __init__(self):
        self.user = SimpleNamespace(
            id="supabase-user-1",
            email="user@example.com",
            email_confirmed_at="2026-08-02T12:00:00Z",
            identities=[{"id": "identity-1"}],
            deleted_at=None,
            banned_until=None,
            user_metadata={"email_verified": False},
        )
        self.admin = FakeAdmin()
        self.signup_response = SimpleNamespace(user=self.user, session=None)
        self.password_response = SimpleNamespace(user=self.user, session=_session())
        self.callback_response = SimpleNamespace(user=self.user, session=_session("callback-access", "callback-refresh"))
        self.refresh_response = SimpleNamespace(user=self.user, session=_session("refreshed-access", "rotated-refresh"))
        self.set_session_response = SimpleNamespace(user=self.user, session=None)
        self.get_user_error: Exception | None = None
        self.password_error: Exception | None = None
        self.signup_error: Exception | None = None
        self.calls: dict[str, list] = {
            "signup": [],
            "password": [],
            "otp": [],
            "resend": [],
            "exchange": [],
            "refresh": [],
            "reset_request": [],
            "set_session": [],
            "update_user": [],
            "http": [],
        }

    def get_user(self, _token: str) -> SimpleNamespace:
        if self.get_user_error:
            raise self.get_user_error
        return SimpleNamespace(user=self.user)

    def sign_up(self, credentials: dict) -> SimpleNamespace:
        self.calls["signup"].append(credentials)
        if self.signup_error:
            raise self.signup_error
        return self.signup_response

    def sign_in_with_password(self, credentials: dict) -> SimpleNamespace:
        self.calls["password"].append(credentials)
        if self.password_error:
            raise self.password_error
        return self.password_response

    def sign_in_with_otp(self, credentials: dict) -> None:
        self.calls["otp"].append(credentials)

    def resend(self, credentials: dict) -> None:
        self.calls["resend"].append(credentials)

    def exchange_code_for_session(self, params: dict) -> SimpleNamespace:
        self.calls["exchange"].append(params)
        return self.callback_response

    def refresh_session(self, refresh_token: str) -> SimpleNamespace:
        self.calls["refresh"].append(refresh_token)
        return self.refresh_response

    def reset_password_for_email(self, email: str, options: dict) -> None:
        self.calls["reset_request"].append((email, options))

    def set_session(self, access_token: str, refresh_token: str) -> SimpleNamespace:
        self.calls["set_session"].append((access_token, refresh_token))
        return self.set_session_response

    def update_user(self, attributes: dict) -> SimpleNamespace:
        self.calls["update_user"].append(attributes)
        return SimpleNamespace(user=self.user)


@pytest.fixture
def auth_context():
    temp_dir = tempfile.TemporaryDirectory()
    db_path = str(Path(temp_dir.name) / "auth.db")
    env = {
        "FURUFLOW_DB_PATH": db_path,
        "SUPABASE_URL": PROJECT_URL,
        "SUPABASE_ANON_KEY": PUBLISHABLE_KEY,
        "SUPABASE_REDIRECT_URL_TEST": "http://localhost:8501/auth/callback",
        "ENVIRONMENT": "test",
        "DEV_MODE": "false",
    }
    session_state: dict[str, object] = {}
    with patch.dict(os.environ, env, clear=False):
        import auth_session
        import db
        import furuflow_auth

        db = importlib.reload(db)
        db.init_db()
        auth_session = importlib.reload(auth_session)
        furuflow_auth = importlib.reload(furuflow_auth)
        fake_auth = FakeAuth()
        fake_client = SimpleNamespace(auth=fake_auth)

        def fake_http_post(endpoint: str, body: dict, redirect_to: str) -> dict:
            fake_auth.calls["http"].append((endpoint, body, redirect_to))
            if endpoint == "signup":
                if fake_auth.signup_error:
                    raise fake_auth.signup_error
                response = fake_auth.signup_response
                payload = {
                    "id": fake_auth.user.id,
                    "email": fake_auth.user.email,
                    "identities": fake_auth.user.identities,
                }
                if response.session:
                    payload = {
                        "access_token": response.session.access_token,
                        "refresh_token": response.session.refresh_token,
                        "user": payload,
                    }
                return payload
            return {}

        with patch.object(st, "session_state", session_state):
            with patch.object(furuflow_auth, "_client", return_value=fake_client):
                with patch.object(furuflow_auth, "_auth_http_post", side_effect=fake_http_post):
                    with furuflow_auth._PKCE_FLOW_LOCK:
                        furuflow_auth._PKCE_FLOWS.clear()
                    yield SimpleNamespace(
                        module=furuflow_auth,
                        db=db,
                        state=session_state,
                        auth=fake_auth,
                        client=fake_client,
                        db_path=db_path,
                        temp_dir=temp_dir.name,
                    )
    temp_dir.cleanup()


def _callback_query(auth_context, action: str, code: str) -> dict[str, str]:
    state, _verifier, _challenge = auth_context.module._create_pkce_flow(action)
    return {"code": code, "auth_action": action, "auth_state": state}


def test_signup_pending_verification_uses_explicit_redirect(auth_context) -> None:
    result = auth_context.module.signup("User@Example.com", "long-enough-password")

    assert result == {"status": "verification_required"}
    endpoint, body, redirect = auth_context.auth.calls["http"][0]
    assert endpoint == "signup"
    assert body["email"] == "user@example.com"
    assert body["code_challenge_method"] == "s256"
    assert parse_qs(urlparse(redirect).query)["auth_action"] == ["verify"]
    assert parse_qs(urlparse(redirect).query)["auth_state"]
    assert "supabase_access_token" not in auth_context.state


def test_duplicate_email_is_handled_without_account_enumeration(auth_context) -> None:
    auth_context.auth.user.identities = []
    auth_context.auth.signup_response = SimpleNamespace(user=auth_context.auth.user, session=None)

    result = auth_context.module.signup("user@example.com", "long-enough-password")

    assert result == {"status": "verification_required"}


def test_duplicate_email_provider_error_has_same_public_state(auth_context) -> None:
    auth_context.auth.signup_error = RuntimeError("User already registered")

    result = auth_context.module.signup("user@example.com", "long-enough-password")

    assert result == {"status": "verification_required"}


def test_signup_with_immediate_verified_session_signs_in(auth_context) -> None:
    auth_context.auth.signup_response = SimpleNamespace(
        user=auth_context.auth.user,
        session=_session("signup-access", "signup-refresh"),
    )

    result = auth_context.module.signup("user@example.com", "long-enough-password")

    assert result["status"] == "signed_in"
    assert auth_context.state["supabase_access_token"] == "signup-access"


def test_authoritative_verification_ignores_mutable_user_metadata(auth_context) -> None:
    auth_context.auth.user.email_confirmed_at = None
    auth_context.auth.user.user_metadata = {"email_verified": True}

    with pytest.raises(auth_context.module.AuthSessionError, match="Verify your email"):
        auth_context.module.validate_supabase_session("access-token")


def test_password_login_stores_server_session_without_creating_sqlite_authority(auth_context) -> None:
    identity = auth_context.module.sign_in_with_password("User@Example.com", "password")

    assert identity["provider_user_id"] == "supabase-user-1"
    assert auth_context.state["supabase_access_token"] == "access-token"
    assert auth_context.state["supabase_refresh_token"] == "refresh-token"
    assert auth_context.db.get_user_by_provider_user_id("supabase-user-1") is None


def test_password_login_returns_useful_safe_error(auth_context) -> None:
    auth_context.auth.password_error = RuntimeError("Invalid login credentials")

    with pytest.raises(auth_context.module.AuthSessionError, match="incorrect") as exc_info:
        auth_context.module.sign_in_with_password("user@example.com", "wrong")

    assert exc_info.value.code == "invalid_credentials"


def test_magic_link_request_disables_implicit_signup_and_sets_redirect(auth_context) -> None:
    auth_context.module.request_magic_link("user@example.com")

    endpoint, body, redirect = auth_context.auth.calls["http"][0]
    assert endpoint == "otp"
    assert body["create_user"] is False
    assert body["code_challenge_method"] == "s256"
    assert parse_qs(urlparse(redirect).query)["auth_action"] == ["signin"]


def test_verification_resend_uses_explicit_redirect(auth_context) -> None:
    auth_context.module.resend_verification("user@example.com")

    endpoint, body, redirect = auth_context.auth.calls["http"][0]
    assert endpoint == "resend"
    assert body["type"] == "signup"
    assert parse_qs(urlparse(redirect).query)["auth_action"] == ["verify"]


def test_callback_exchanges_code_and_scrubs_sensitive_url_state(auth_context) -> None:
    query = _callback_query(auth_context, "signin", "single-use-code")
    query["page"] = "scanner"

    result = auth_context.module.handle_auth_callback(query)

    assert result["status"] == "signed_in"
    assert auth_context.auth.calls["exchange"][0]["auth_code"] == "single-use-code"
    assert auth_context.auth.calls["exchange"][0]["code_verifier"]
    assert "code" not in query
    assert "auth_action" not in query
    assert "auth_state" not in query
    assert query["page"] == "scanner"
    assert auth_context.state["supabase_access_token"] == "callback-access"


def test_callback_rejects_query_tokens_and_removes_them(auth_context) -> None:
    query = {"access_token": "must-not-remain", "refresh_token": "must-not-remain"}

    with pytest.raises(auth_context.module.AuthSessionError) as exc_info:
        auth_context.module.handle_auth_callback(query)

    assert exc_info.value.code == "unsafe_callback"
    assert query == {}


def test_callback_requires_single_use_pkce_state(auth_context) -> None:
    with pytest.raises(auth_context.module.AuthSessionError) as missing_state:
        auth_context.module.handle_auth_callback({"code": "code", "auth_action": "signin"})
    assert missing_state.value.code == "missing_callback_state"

    query = _callback_query(auth_context, "signin", "first-code")
    state = query["auth_state"]
    auth_context.module.handle_auth_callback(query)
    with pytest.raises(auth_context.module.AuthSessionError) as replay:
        auth_context.module.handle_auth_callback(
            {"code": "second-code", "auth_action": "signin", "auth_state": state}
        )
    assert replay.value.code == "invalid_callback_state"


def test_callback_rejects_state_action_tampering(auth_context) -> None:
    state, _verifier, _challenge = auth_context.module._create_pkce_flow("verify")

    with pytest.raises(auth_context.module.AuthSessionError) as exc_info:
        auth_context.module.handle_auth_callback(
            {"code": "code", "auth_action": "recovery", "auth_state": state}
        )

    assert exc_info.value.code == "invalid_callback_state"


def test_refresh_rotates_tokens_and_preserves_identity(auth_context) -> None:
    auth_context.state["supabase_access_token"] = "old-access"
    auth_context.state["supabase_refresh_token"] = "old-refresh"

    identity = auth_context.module.refresh_session()

    assert identity["provider_user_id"] == "supabase-user-1"
    assert auth_context.auth.calls["refresh"] == ["old-refresh"]
    assert auth_context.state["supabase_access_token"] == "refreshed-access"
    assert auth_context.state["supabase_refresh_token"] == "rotated-refresh"


def test_expired_access_token_refreshes_before_identity_validation(auth_context) -> None:
    auth_context.state["supabase_access_token"] = _expired_token()
    auth_context.state["supabase_refresh_token"] = "old-refresh"

    identity = auth_context.module.validate_authenticated_session()

    assert identity["provider_user_id"] == "supabase-user-1"
    assert auth_context.auth.calls["refresh"] == ["old-refresh"]


def test_revoked_or_deleted_user_is_rejected_and_tokens_are_cleared(auth_context) -> None:
    auth_context.auth.user.deleted_at = "2026-08-02T12:00:00Z"
    auth_context.state["supabase_access_token"] = "revoked-access"
    auth_context.state["supabase_refresh_token"] = "revoked-refresh"

    with pytest.raises(auth_context.module.AuthSessionError) as exc_info:
        auth_context.module.validate_authenticated_session()

    assert exc_info.value.code == "account_unavailable"
    assert "supabase_access_token" not in auth_context.state
    assert "supabase_refresh_token" not in auth_context.state


def test_logout_revokes_provider_session_and_always_clears_local_tokens(auth_context) -> None:
    auth_context.state["supabase_access_token"] = "logout-access"
    auth_context.state["supabase_refresh_token"] = "logout-refresh"

    revoked = auth_context.module.provider_sign_out()

    assert revoked
    assert auth_context.auth.admin.sign_out_calls == [("logout-access", "global")]
    assert "supabase_access_token" not in auth_context.state
    assert "supabase_refresh_token" not in auth_context.state


def test_forgot_password_uses_recovery_redirect(auth_context) -> None:
    auth_context.module.request_password_reset("user@example.com")

    endpoint, body, redirect = auth_context.auth.calls["http"][0]
    assert endpoint == "recover"
    assert body["email"] == "user@example.com"
    assert body["code_challenge_method"] == "s256"
    assert parse_qs(urlparse(redirect).query)["auth_action"] == ["recovery"]


def test_forgot_password_does_not_disclose_unknown_account(auth_context) -> None:
    with patch.object(auth_context.module, "_auth_http_post", side_effect=RuntimeError("User not found")):
        auth_context.module.request_password_reset("unknown@example.com")


def test_magic_link_does_not_disclose_unknown_account(auth_context) -> None:
    with patch.object(auth_context.module, "_auth_http_post", side_effect=RuntimeError("User not found")):
        auth_context.module.request_magic_link("unknown@example.com")


def test_password_recovery_callback_and_completion(auth_context) -> None:
    query = _callback_query(auth_context, "recovery", "recovery-code")
    result = auth_context.module.handle_auth_callback(query)
    assert result["status"] == "password_recovery"
    assert auth_context.state[auth_context.module.PASSWORD_RECOVERY_KEY] is True

    identity = auth_context.module.complete_password_reset("a-new-long-password")

    assert identity["provider_user_id"] == "supabase-user-1"
    assert auth_context.auth.calls["set_session"] == [("callback-access", "callback-refresh")]
    assert auth_context.auth.calls["update_user"] == [{"password": "a-new-long-password"}]
    assert auth_context.state[auth_context.module.PASSWORD_RECOVERY_KEY] is False


def test_provider_tokens_never_enter_local_files(auth_context) -> None:
    sentinel_access = "SENTINEL-ACCESS-TOKEN-DO-NOT-PERSIST"
    sentinel_refresh = "SENTINEL-REFRESH-TOKEN-DO-NOT-PERSIST"
    auth_context.auth.password_response = SimpleNamespace(
        user=auth_context.auth.user,
        session=_session(sentinel_access, sentinel_refresh),
    )

    auth_context.module.sign_in_with_password("user@example.com", "password")

    for path in Path(auth_context.temp_dir).rglob("*"):
        if path.is_file():
            content = path.read_bytes()
            assert sentinel_access.encode() not in content
            assert sentinel_refresh.encode() not in content


def test_provider_tokens_never_enter_auth_logs(auth_context, caplog) -> None:
    sentinel_access = "SENTINEL-LOG-ACCESS-TOKEN"
    sentinel_refresh = "SENTINEL-LOG-REFRESH-TOKEN"
    auth_context.auth.password_response = SimpleNamespace(
        user=auth_context.auth.user,
        session=_session(sentinel_access, sentinel_refresh),
    )

    with caplog.at_level("INFO"):
        auth_context.module.sign_in_with_password("user@example.com", "password")
        auth_context.module.provider_sign_out()

    assert sentinel_access not in caplog.text
    assert sentinel_refresh not in caplog.text
    assert "user@example.com" not in caplog.text


def test_streamlit_session_store_survives_rerun_mapping_but_not_new_browser_state(auth_context) -> None:
    auth_context.state["supabase_access_token"] = "server-memory-access"
    auth_context.state["supabase_refresh_token"] = "server-memory-refresh"

    first = auth_context.module.get_auth_session_store().load()
    second = auth_context.module.get_auth_session_store().load()

    assert first == second
    assert first.access_token == "server-memory-access"
    from auth_session import StreamlitMemorySessionStore

    assert StreamlitMemorySessionStore({}).load() is None
