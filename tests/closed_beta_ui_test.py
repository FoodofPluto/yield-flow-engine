from __future__ import annotations

import requests
import streamlit as st
from streamlit.testing.v1 import AppTest


PARTICIPANT_ID = "9dadb18d-37bd-4b48-b6f0-f5947fab6e85"


def _rendered(app: AppTest) -> str:
    return "\n".join(element.value for element in app.markdown)


def test_fresh_session_sees_closed_beta_identity_onboarding_and_invitation_only_auth(monkeypatch) -> None:
    monkeypatch.setenv("FURUFLOW_BETA_ENABLED", "true")
    monkeypatch.setenv("FURUFLOW_BETA_ALLOWED_USER_IDS", PARTICIPANT_ID)
    monkeypatch.setenv("FURUFLOW_BETA_ALLOW_SIGNUP", "false")
    monkeypatch.setenv("FURUFLOW_BETA_LABEL", "Closed Beta")
    st.cache_data.clear()

    app = AppTest.from_file("app.py", default_timeout=60).run()

    assert not app.exception
    rendered = _rendered(app)
    assert "Closed Beta" in rendered
    assert "Find → Understand → Compare → Monitor → Act" in rendered
    assert any("does not execute investments" in caption.value for caption in app.caption)
    assert any("invitation-only" in caption.value for caption in app.caption)
    assert not any(tab.label == "Create" for tab in app.tabs)

    next(button for button in app.button if button.label == "Got it — start exploring").click().run()
    assert not app.exception
    assert "Welcome to the FuruFlow Closed Beta" not in _rendered(app)


class _RateLimitedResponse:
    status_code = 429


def test_market_rate_limit_stops_fallback_amplification_and_gives_recovery(monkeypatch) -> None:
    calls: list[str] = []

    def rate_limited(url: str, **_kwargs):
        calls.append(url)
        return _RateLimitedResponse()

    monkeypatch.delenv("FURUFLOW_MARKET_SAMPLE_MODE", raising=False)
    monkeypatch.delenv("FURUFLOW_BETA_ENABLED", raising=False)
    monkeypatch.setattr(requests, "get", rate_limited)
    st.cache_data.clear()

    app = AppTest.from_file("app.py", default_timeout=60).run()

    assert not app.exception
    rendered = _rendered(app)
    assert "Temporarily busy" in rendered
    assert "stopped this refresh instead of retrying repeatedly" in rendered
    assert "Wait a short time, then retry once" in rendered
    assert len(calls) == 1


def test_maintenance_mode_is_clear_and_stops_before_market_provider_calls(monkeypatch) -> None:
    monkeypatch.setenv("FURUFLOW_BETA_ENABLED", "true")
    monkeypatch.setenv("FURUFLOW_BETA_ALLOWED_USER_IDS", PARTICIPANT_ID)
    monkeypatch.setenv("FURUFLOW_MAINTENANCE_MESSAGE", "Scheduled beta maintenance. Try again after the window.")
    monkeypatch.delenv("FURUFLOW_MARKET_SAMPLE_MODE", raising=False)
    provider_request = monkeypatch.setattr(
        requests, "get", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError())
    )
    st.cache_data.clear()

    app = AppTest.from_file("app.py", default_timeout=60).run()

    assert provider_request is None
    assert not app.exception
    rendered = _rendered(app)
    assert "Temporarily unavailable for maintenance" in rendered
    assert "Scheduled beta maintenance" in rendered
    assert "Welcome to the FuruFlow Closed Beta" not in rendered


def test_unapproved_paid_identity_cannot_reach_account_billing_workflow(monkeypatch) -> None:
    import auth_service

    user = {
        "email": "member@example.invalid",
        "provider_user_id": "ab22f72e-161b-4533-a727-866680d8af45",
        "_identity_verified": True,
        "_account_authority": "supabase",
        "_account_available": True,
        "email_verified": True,
        "is_admin": False,
        "pro_active": True,
    }
    monkeypatch.setenv("FURUFLOW_BETA_ENABLED", "true")
    monkeypatch.setenv("FURUFLOW_BETA_ALLOWED_USER_IDS", PARTICIPANT_ID)
    monkeypatch.setattr(auth_service, "get_current_user", lambda: user)
    monkeypatch.setattr(auth_service, "claim_session", lambda: None)
    monkeypatch.setattr(auth_service, "validate_session", lambda: True)
    monkeypatch.setattr(auth_service, "can_access_pro", lambda _user: True)
    monkeypatch.setattr(auth_service, "is_admin", lambda _user: False)
    st.cache_data.clear()

    app = AppTest.from_file("app.py", default_timeout=60)
    app.query_params["page"] = "Account & Billing"
    app.run()

    assert not app.exception
    rendered = _rendered(app)
    assert "Closed-beta access unavailable" in rendered
    assert "not approved for account-bearing beta workflows" in rendered
    assert any(button.key == "beta_access_denied_signout" for button in app.button)
    assert not any("checkout" in button.label.lower() or "upgrade" in button.label.lower() for button in app.button)
