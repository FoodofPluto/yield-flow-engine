from __future__ import annotations

import hashlib
import json
import logging
from unittest.mock import Mock

import httpx
import pytest
from flask import Flask

from beta_invitations import INVITATION_COOKIE, InvitationService, digest, register_invitation_routes
from session_broker import _RedactActivationTicket

TOKEN = "A" * 43
USER_ID = "19c10000-0000-4000-8000-000000000010"


@pytest.mark.parametrize("token", ["", None, "short", "A" * 42, "A" * 44, "!" * 43, "A" * 43 + "&role=admin"])
def test_malformed_tokens_fail_closed_without_database(token):
    store = Mock()
    service = InvitationService(store)
    assert not service.valid(token)
    assert not service.register(token, "p1@example.invalid", "long-password-example")
    store._request.assert_not_called()


def test_hash_only_claim_and_unconfirmed_free_provider_creation():
    sent = []

    def provider(request):
        sent.append(json.loads(request.content))
        assert request.url.path == "/auth/v1/admin/users"
        return httpx.Response(201, json={"id": USER_ID, "email_confirmed_at": None})

    store = Mock(_transport=httpx.MockTransport(provider), _project_url="https://unit.supabase.co", _key="synthetic")
    store._request.return_value = USER_ID
    assert InvitationService(store).register(TOKEN, "p1@example.invalid", "long-password-example")
    assert store._request.call_args.kwargs["body"] == {"invitation_digest": hashlib.sha256(TOKEN.encode()).hexdigest()}
    assert sent == [
        {"id": USER_ID, "email": "p1@example.invalid", "password": "long-password-example", "email_confirm": False}
    ]
    assert TOKEN not in json.dumps(sent)
    assert "app_metadata" not in sent[0] and "role" not in sent[0]


@pytest.mark.parametrize("result", [None, False, {}, "invalid-uuid"])
def test_rejected_claim_never_calls_auth(result):
    store = Mock()
    store._request.return_value = result
    assert not InvitationService(store).register(TOKEN, "p1@example.invalid", "long-password-example")
    assert store._request.call_count == 1


def test_ambiguous_provider_failure_never_releases_or_retries_claim(caplog):
    def provider(request):
        raise httpx.ReadTimeout("secret must not escape: " + TOKEN)

    store = Mock(_transport=httpx.MockTransport(provider), _project_url="https://unit.supabase.co", _key="synthetic")
    store._request.return_value = USER_ID
    assert not InvitationService(store).register(TOKEN, "p1@example.invalid", "long-password-example")
    assert store._request.call_count == 1
    assert TOKEN not in caplog.text


def app_for(service):
    app = Flask(__name__)
    register_invitation_routes(app, service, lambda: False)
    return app.test_client()


def test_invitation_capture_removes_url_without_rendering_secret():
    service = Mock()
    service.valid.return_value = True
    response = app_for(service).get("/create-account?invite=" + TOKEN)
    body = response.get_data(as_text=True)
    assert TOKEN not in body
    assert 'history.replaceState(null,"","/create-account")' in body
    assert 'location.replace("/?page=Account&beta_invite=1")' in body
    cookie = response.headers["Set-Cookie"]
    assert INVITATION_COOKIE in cookie and "Secure" in cookie and "HttpOnly" in cookie and "SameSite=Lax" in cookie
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    "query",
    ["", "?invite=bad", "?invite=" + TOKEN + "&invite=" + TOKEN, "?invite=" + TOKEN + "&next=https://evil.invalid"],
)
def test_bad_entry_never_validates_or_exposes_reason(query):
    service = Mock()
    response = app_for(service).get("/create-account" + query)
    service.valid.assert_not_called()
    assert "beta_invite=unavailable" in response.get_data(as_text=True)


def test_private_registration_requires_bridge_and_completion_clears_cookie():
    service = Mock()
    client = app_for(service)
    assert client.post("/v1/invitations/register", json={"invitation": TOKEN}).status_code == 401
    assert client.post("/v1/invitations/validate", json={"invitation": TOKEN}).status_code == 401
    service.register.assert_not_called()
    response = client.get("/create-account/complete")
    assert "Max-Age=0" in response.headers["Set-Cookie"]


def test_invite_query_log_redaction():
    record = logging.LogRecord("werkzeug", logging.ERROR, "", 0, "GET /create-account?invite=%s", (TOKEN,), None)
    assert _RedactActivationTicket().filter(record)
    assert TOKEN not in record.getMessage()


def test_untrusted_ui_marker_cannot_enable_signup(monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("FURUFLOW_BETA_ALLOW_SIGNUP", "false")
    app = AppTest.from_string("from auth import login_form\nlogin_form(allow_registration=False)")
    app.query_params["beta_invite"] = "1"
    app.run()
    assert not app.exception
    assert not any(b.label == "Create account" for b in app.button)
    assert any("invitation is unavailable" in w.value for w in app.warning)


def test_validation_budget_bounds_database_requests():
    store = Mock()
    store._request.return_value = True
    service = InvitationService(store)
    for _ in range(60):
        assert service.valid(TOKEN)
    assert not service.valid(TOKEN)
    assert store._request.call_count == 60


def test_valid_ui_reuses_verification(monkeypatch):
    import auth
    from streamlit.testing.v1 import AppTest

    calls = []
    monkeypatch.setattr(auth, "_invitation_token", lambda: TOKEN)
    monkeypatch.setattr(auth, "invitation_bridge", lambda action, token, **fields: True)
    monkeypatch.setattr(auth, "resend_verification", lambda email: calls.append(email))
    app = AppTest.from_string("from auth import login_form\nlogin_form(allow_registration=False)")
    app.query_params["beta_invite"] = "1"
    app.run()
    assert not app.exception
    app.text_input[0].set_value("p1@example.invalid")
    app.text_input[1].set_value("a-long-synthetic-password")
    app.text_input[2].set_value("a-long-synthetic-password")
    next(b for b in app.button if b.label == "Create account").click().run()
    assert not app.exception
    assert calls == ["p1@example.invalid"]
    assert any("Check your email" in s.value for s in app.success)
