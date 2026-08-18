from __future__ import annotations

import json
import os
from unittest.mock import patch

import httpx
from cryptography.fernet import Fernet

from session_broker import BrokerStore, create_app


USER_ID = "11111111-1111-4111-8111-111111111111"


def _env() -> dict[str, str]:
    return {
        "SUPABASE_URL": "https://abcdefghijklmnopqrst.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "service-role-test-value",
        "FURUFLOW_SESSION_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "FURUFLOW_SESSION_BRIDGE_KEY": "B" * 32,
        "FURUFLOW_SESSION_BROKER_PUBLIC_ORIGIN": "https://app.invalid",
    }


def test_broker_persists_only_ciphertext_and_hashes() -> None:
    writes: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        writes.append(body)
        if request.url.path.endswith("/browser_sessions"):
            return httpx.Response(201, json=[{"id": "33333333-3333-4333-8333-333333333333"}])
        return httpx.Response(201)

    with patch.dict(os.environ, _env(), clear=False):
        ticket = BrokerStore(transport=httpx.MockTransport(handler)).issue(
            user_id=USER_ID, access_token="SENTINEL-ACCESS", refresh_token="SENTINEL-REFRESH"
        )
    encoded = json.dumps(writes)
    assert "SENTINEL-ACCESS" not in encoded
    assert "SENTINEL-REFRESH" not in encoded
    assert ticket not in encoded
    assert len(writes[0]["opaque_hash"]) == 64
    assert len(writes[1]["ticket_hash"]) == 64


class FakeStore:
    def consume_ticket(self, ticket: str) -> str | None:
        return "opaque-session" if ticket == "single-use" else None


class FakeBillingStore(FakeStore):
    def verified_identity(self, opaque: str) -> dict | None:
        if opaque != "opaque-session":
            return None
        return {
            "id": USER_ID,
            "email": "verified@example.test",
            "email_confirmed_at": "2026-08-17T00:00:00+00:00",
        }


class FakeBilling:
    def __init__(self) -> None:
        self.identities: list[dict] = []

    def create_checkout(self, identity: dict) -> str:
        self.identities.append(identity)
        return "https://checkout.stripe.com/c/pay_test_safe"

    def create_portal(self, identity: dict) -> str:
        self.identities.append(identity)
        return "https://billing.stripe.com/p/session/test_safe"


def test_activation_sets_secure_httponly_host_cookie() -> None:
    with patch.dict(os.environ, _env(), clear=False):
        client = create_app(FakeStore()).test_client()
        response = client.get("/auth/session/activate?ticket=single-use")
    cookie = response.headers["Set-Cookie"]
    assert "__Host-furuflow_session=opaque-session" in cookie
    assert "Secure" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie
    assert "Path=/" in cookie


def test_billing_routes_require_same_origin_authenticated_cookie_and_ignore_browser_user_ids() -> None:
    billing = FakeBilling()
    with patch.dict(os.environ, _env(), clear=False):
        client = create_app(FakeBillingStore(), billing).test_client()
        assert client.post("/billing/checkout", headers={"Origin": "https://evil.invalid"}).status_code == 403
        assert client.post("/billing/checkout", headers={"Origin": "https://app.invalid"}).status_code == 401
        client.set_cookie("__Host-furuflow_session", "opaque-session", secure=True)
        response = client.post(
            "/billing/checkout",
            json={"user_id": "22222222-2222-4222-8222-222222222222"},
            headers={"Origin": "https://app.invalid"},
        )
    assert response.status_code == 303
    assert response.headers["Location"].startswith("https://checkout.stripe.com/")
    assert billing.identities == [
        {"id": USER_ID, "email": "verified@example.test", "email_confirmed_at": "2026-08-17T00:00:00+00:00"}
    ]
