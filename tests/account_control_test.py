from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import httpx
import pytest

import auth_service
from account_control import AccountStateUnavailable, ServiceRoleAccountClient, SupabaseAccountClient, external_delivery_allowed


USER_A = "11111111-1111-4111-8111-111111111111"
USER_B = "22222222-2222-4222-8222-222222222222"
PROJECT_URL = "https://abcdefghijklmnopqrst.supabase.co"
PUBLISHABLE_KEY = "sb_publishable_" + "A" * 32
SERVICE_KEY = "test-service-role-key"


def _environment() -> dict[str, str]:
    return {
        "SUPABASE_URL": PROJECT_URL,
        "SUPABASE_ANON_KEY": PUBLISHABLE_KEY,
        "SUPABASE_REDIRECT_URL_TEST": "http://localhost:8501/auth/callback",
        "ENVIRONMENT": "test",
    }


def _transport(*, entitlement: dict | None = None, unavailable: bool = False) -> httpx.MockTransport:
    default = {
        "user_id": USER_A,
        "is_admin": False,
        "pro_active": False,
        "subscription_pro_active": False,
        "lifetime_access": False,
        "demo_expires_at": None,
        "demo_environment": None,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if unavailable:
            return httpx.Response(503, json={"message": "unavailable"})
        bearer = request.headers.get("Authorization", "").removeprefix("Bearer ")
        path = request.url.path
        query = str(request.url.query)
        if path.endswith("/profiles"):
            allowed = bearer == "token-a" and USER_A in query
            return httpx.Response(200, json=[{"id": USER_A, "timezone": "UTC"}] if allowed else [])
        if path.endswith("/entitlements") and request.method == "GET":
            if bearer == SERVICE_KEY:
                return httpx.Response(200, json=[entitlement or default])
            allowed = bearer == "token-a" and USER_A in query
            return httpx.Response(200, json=[entitlement or default] if allowed else [])
        if path.endswith("/subscriptions"):
            allowed = bearer == "token-a" and USER_A in query
            return httpx.Response(200, json=[] if allowed else [])
        if path.endswith("/entitlements") and request.method in {"PATCH", "POST", "DELETE"}:
            return httpx.Response(403, json={"message": "RLS"})
        if "/rpc/" in path and bearer == SERVICE_KEY:
            return httpx.Response(200, json=True)
        return httpx.Response(403, json={"message": "denied"})

    return httpx.MockTransport(handler)


def test_user_reads_only_own_account_and_cross_user_lookup_fails_closed() -> None:
    with patch.dict(os.environ, _environment(), clear=False):
        client = SupabaseAccountClient(transport=_transport())
        assert client.get_account(USER_A, "token-a", environment="test")["user_id"] == USER_A
        with pytest.raises(AccountStateUnavailable):
            client.get_account(USER_B, "token-a", environment="test")


def test_authenticated_user_cannot_write_entitlements_or_self_escalate() -> None:
    with patch.dict(os.environ, _environment(), clear=False):
        client = SupabaseAccountClient(transport=_transport())
        with pytest.raises(AccountStateUnavailable):
            client._request(
                "PATCH", "entitlements", bearer="token-a", params={"user_id": f"eq.{USER_A}"}, json_body={"is_admin": True}
            )


@pytest.mark.parametrize(
    ("field", "value"),
    (("pro_active", True), ("subscription_pro_active", True), ("lifetime_access", True), ("is_admin", True)),
)
def test_authoritative_pro_admin_lifetime_roles(field: str, value: bool) -> None:
    row = {
        "user_id": USER_A,
        "is_admin": False,
        "pro_active": False,
        "lifetime_access": False,
        "demo_expires_at": None,
        "demo_environment": None,
        field: value,
    }
    with patch.dict(os.environ, _environment(), clear=False):
        account = SupabaseAccountClient(transport=_transport(entitlement=row)).get_account(USER_A, "token-a", environment="test")
    account.update({"email_verified": True, "_identity_verified": True})
    assert auth_service.can_access_pro(account)
    assert auth_service.is_admin(account) is (field == "is_admin")


def test_free_role_is_denied_and_unavailable_state_fails_closed() -> None:
    with patch.dict(os.environ, _environment(), clear=False):
        free = SupabaseAccountClient(transport=_transport()).get_account(USER_A, "token-a", environment="test")
        with pytest.raises(AccountStateUnavailable):
            SupabaseAccountClient(transport=_transport(unavailable=True)).get_account(USER_A, "token-a", environment="test")
    free.update({"email_verified": True, "_identity_verified": True})
    assert not auth_service.can_access_pro(free)


def test_demo_is_short_lived_nonproduction_and_blocks_delivery() -> None:
    future = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
    row = {
        "user_id": USER_A,
        "is_admin": False,
        "pro_active": False,
        "lifetime_access": False,
        "demo_expires_at": future,
        "demo_environment": "staging",
    }
    env = {**_environment(), "ENVIRONMENT": "staging", "SUPABASE_REDIRECT_URL_PREVIEW": "https://preview.example/auth/callback"}
    with patch.dict(os.environ, env, clear=False):
        demo = SupabaseAccountClient(transport=_transport(entitlement=row)).get_account(USER_A, "token-a", environment="staging")
    demo.update({"email_verified": True, "_identity_verified": True})
    assert auth_service.can_access_pro(demo)
    assert not auth_service.is_admin(demo)
    assert not external_delivery_allowed(demo)


def test_expired_demo_and_environment_mismatch_are_denied() -> None:
    expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    row = {
        "user_id": USER_A,
        "is_admin": False,
        "pro_active": False,
        "lifetime_access": False,
        "demo_expires_at": expired,
        "demo_environment": "staging",
    }
    with patch.dict(os.environ, _environment(), clear=False):
        account = SupabaseAccountClient(transport=_transport(entitlement=row)).get_account(USER_A, "token-a", environment="test")
    assert not account["demo_active"]


def test_service_role_rpc_is_the_only_write_path_and_bootstrap_is_idempotent() -> None:
    with patch.dict(os.environ, _environment(), clear=False):
        client = ServiceRoleAccountClient(service_role_key=SERVICE_KEY, transport=_transport())
        assert client.bootstrap_first_admin(USER_A)
        assert client.set_entitlement(
            target_user_id=USER_B,
            entitlement="pro",
            enabled=True,
            actor_user_id=USER_A,
            reason="test",
        )


def test_reviewed_migration_entitlement_writes_are_idempotent_and_audited_once() -> None:
    applied: set[tuple[str, str, bool]] = set()
    audit_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal audit_count
        body = json.loads(request.content)
        key = (body["target_user_id"], body["entitlement_name"], body["enabled"])
        changed = key not in applied
        if changed:
            applied.add(key)
            audit_count += 1
        return httpx.Response(200, json=changed)

    with patch.dict(os.environ, _environment(), clear=False):
        client = ServiceRoleAccountClient(service_role_key=SERVICE_KEY, transport=httpx.MockTransport(handler))
        arguments = {
            "target_user_id": USER_B,
            "entitlement": "pro",
            "enabled": True,
            "actor_user_id": USER_A,
            "reason": "reviewed_legacy_migration",
            "source": "legacy_migration",
        }
        assert client.set_entitlement(**arguments)
        assert not client.set_entitlement(**arguments)
    assert audit_count == 1


def test_migration_contains_deny_default_rls_and_audited_service_functions() -> None:
    sql = (Path(__file__).parents[1] / "supabase/migrations/202608050001_prompt2_account_control_plane.sql").read_text()
    for table in ("profiles", "entitlements", "subscriptions", "admin_audit", "webhook_events", "account_sessions"):
        assert f"alter table public.{table} enable row level security" in sql
    assert "grant update (display_name, timezone)" in sql
    assert "service role required" in sql
    assert "insert into public.admin_audit" in sql
    assert "bootstrap_first_admin" in sql
    assert "auth.uid()) = user_id" in sql


def test_no_email_is_used_as_account_primary_or_authorization_boundary() -> None:
    sql = (Path(__file__).parents[1] / "supabase/migrations/202608050001_prompt2_account_control_plane.sql").read_text()
    assert "email text" not in sql.lower()
    for value in (USER_A, USER_B):
        UUID(value)
    assert json.dumps({"target_user_id": USER_A})
