from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest

from account_control import AccountStateUnavailable, SupabaseAccountClient
from auth_service import can_access_pro
from automation.admission import synchronize_beta_admission
from automation.store import AutomationStoreError
from beta_readiness import beta_access, beta_config


USER_ID = "18f00000-0000-4000-8000-000000000001"
SOURCE = {
    "SUPABASE_URL": "https://abcdefghijklmnopqrst.supabase.co",
    "SUPABASE_SERVICE_ROLE_KEY": "fixture-service-key",
    "FURUFLOW_BETA_ENABLED": "true",
    "FURUFLOW_BETA_ALLOWED_USER_IDS": USER_ID,
}


def test_startup_sync_uses_validated_server_source_and_service_authority() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=True)

    synchronize_beta_admission(SOURCE, transport=httpx.MockTransport(handler))
    assert len(requests) == 1
    assert requests[0].url.path == "/rest/v1/rpc/service_sync_beta_admission"
    assert requests[0].headers["Authorization"] == "Bearer fixture-service-key"
    assert json.loads(requests[0].content) == {"beta_enabled": True, "approved_user_ids": [USER_ID]}


@pytest.mark.parametrize("response", [False, None, {}, "true"])
def test_startup_sync_requires_explicit_acknowledgment(response: object) -> None:
    with pytest.raises(RuntimeError, match="acknowledged"):
        synchronize_beta_admission(SOURCE, transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response)))


def test_startup_sync_network_failure_is_redacted_and_blocks_startup() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sensitive upstream details", request=request)

    with pytest.raises(AutomationStoreError) as failure:
        synchronize_beta_admission(SOURCE, transport=httpx.MockTransport(handler))
    assert "sensitive" not in str(failure.value)
    assert "fixture-service-key" not in str(failure.value)


def test_invalid_allowlist_never_reaches_database() -> None:
    with pytest.raises(RuntimeError, match="Invalid closed-beta"):
        synchronize_beta_admission({**SOURCE, "FURUFLOW_BETA_ALLOWED_USER_IDS": "not-a-uuid"})


def test_missing_admission_configuration_cannot_default_to_open_access() -> None:
    with pytest.raises(RuntimeError, match="Invalid closed-beta"):
        synchronize_beta_admission({key: value for key, value in SOURCE.items() if key != "FURUFLOW_BETA_ENABLED"})


def test_supervisor_does_not_start_any_child_when_admission_sync_fails() -> None:
    from deploy.render import supervise

    with patch.object(supervise, "build_child_environments", return_value=({}, {}, {})), \
         patch.object(supervise, "synchronize_beta_admission", side_effect=RuntimeError("sync failed")), \
         patch.object(supervise.subprocess, "Popen") as spawn:
        assert supervise.main() == 1
    spawn.assert_not_called()


@pytest.mark.parametrize("admitted", [False, True])
@pytest.mark.parametrize("paid", [False, True])
def test_application_obeys_database_admission_and_paid_decisions(admitted: bool, paid: bool) -> None:
    # Stale process allowlist and flags must not override newer database truth.
    config = beta_config(SOURCE)
    user = {
        "provider_user_id": USER_ID, "_identity_verified": True, "_account_authority": "supabase",
        "_beta_admission": admitted, "_paid_authorized": paid,
        "is_admin": not paid, "subscription_pro_active": not paid,
        "pro_active": not paid, "lifetime_access": not paid,
    }
    assert beta_access(config, user).allowed is admitted
    assert can_access_pro(user) is paid


@pytest.mark.parametrize("authorization", [None, {}, True, {"beta_approved": "true"}])
def test_account_reconstruction_fails_closed_without_typed_rpc_authority(authorization: object) -> None:
    client = object.__new__(SupabaseAccountClient)
    responses = [[{"id": USER_ID}], [{"user_id": USER_ID}], [], authorization]
    with patch.object(client, "_request", side_effect=responses):
        with pytest.raises(AccountStateUnavailable, match="Authoritative Alert access"):
            client.get_account(USER_ID, "fixture-token", environment="test")


def test_unverified_or_untrusted_account_cannot_use_database_looking_flags() -> None:
    user = {"_paid_authorized": True, "_beta_admission": True}
    assert not can_access_pro(user)
    assert not beta_access(beta_config(SOURCE), user).allowed
