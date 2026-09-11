from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

import pytest

from account_control import AccountOperationError
from billing_service import (
    BillingConfig,
    BillingConfigurationError,
    BillingOperationError,
    BillingService,
    BillingWebhookInvalid,
)


USER_A = "11111111-1111-4111-8111-111111111111"
USER_B = "22222222-2222-4222-8222-222222222222"


def _config() -> BillingConfig:
    return BillingConfig(
        environment="test",
        secret_key="sk_test_" + "S" * 32,
        webhook_secret="whsec_" + "W" * 32,
        price_id="price_" + "P" * 24,
        product_id="prod_" + "R" * 24,
        public_origin="http://localhost:8501",
    )


def _identity(user_id: str = USER_A, *, email: str = "member@example.test") -> dict[str, Any]:
    return {
        "id": user_id,
        "email": email,
        "email_confirmed_at": "2026-08-17T00:00:00+00:00",
        "is_anonymous": False,
    }


def _subscription(
    config: BillingConfig,
    *,
    status: str = "active",
    user_id: str = USER_A,
    customer_id: str = "cus_AAAAAAAAAAAAAAAA",
    cancel_at_period_end: bool = False,
) -> dict[str, Any]:
    return {
        "id": "sub_AAAAAAAAAAAAAAAA",
        "customer": customer_id,
        "status": status,
        "metadata": {"furuflow_user_id": user_id},
        "current_period_end": 1800000000,
        "cancel_at_period_end": cancel_at_period_end,
        "items": {"data": [{"price": {"id": config.price_id, "product": config.product_id}}]},
    }


class FakeAccounts:
    def __init__(self) -> None:
        self.entitlements = {
            USER_A: {"user_id": USER_A, "pro_active": True, "subscription_pro_active": False, "demo_expires_at": None},
            USER_B: {"user_id": USER_B, "pro_active": False, "subscription_pro_active": False, "demo_expires_at": None},
        }
        self.mappings: dict[str, dict[str, Any]] = {}
        self.events: dict[str, str] = {}
        self.applies = 0

    def get_entitlement(self, user_id: str) -> dict[str, Any]:
        return self.entitlements[user_id]

    def get_stripe_mapping(self, user_id: str) -> dict[str, Any] | None:
        return self.mappings.get(user_id)

    def set_stripe_customer(self, *, user_id: str, customer_id: str) -> bool:
        for owner, mapping in self.mappings.items():
            if owner != user_id and mapping.get("provider_customer_id") == customer_id:
                raise AccountOperationError("mapped")
        mapping = self.mappings.setdefault(
            user_id, {"user_id": user_id, "provider": "stripe", "status": "inactive"}
        )
        existing = mapping.get("provider_customer_id")
        if existing and existing != customer_id:
            raise AccountOperationError("different")
        mapping["provider_customer_id"] = customer_id
        return existing is None

    def begin_webhook_event(self, event_id: str, _event_type: str) -> bool:
        if self.events.get(event_id) == "processed":
            return False
        self.events[event_id] = "processing"
        return True

    def finish_webhook_event(self, event_id: str, *, succeeded: bool, error_code: str | None = None) -> None:
        self.events[event_id] = "processed" if succeeded else f"failed:{error_code}"

    def apply_stripe_subscription(self, **values: Any) -> str:
        target = values.get("user_id")
        customer = values.get("customer_id")
        subscription = values.get("subscription_id")
        mapped_owner = next(
            (
                owner
                for owner, mapping in self.mappings.items()
                if mapping.get("provider_customer_id") == customer
                or mapping.get("provider_subscription_id") == subscription
            ),
            None,
        )
        owner = mapped_owner or target
        if not owner or (target and target != owner):
            raise AccountOperationError("mapping mismatch")
        mapping = self.mappings.setdefault(owner, {"user_id": owner, "provider": "stripe"})
        existing_customer = mapping.get("provider_customer_id")
        if existing_customer and customer and existing_customer != customer:
            raise AccountOperationError("customer mapping mismatch")
        prior = (mapping.get("event_created", 0), mapping.get("event_id", ""))
        incoming = (values["event_created"], values["event_id"])
        if incoming <= prior:
            return owner
        mapping.update(
            {
                "provider_customer_id": customer or mapping.get("provider_customer_id"),
                "provider_subscription_id": subscription or mapping.get("provider_subscription_id"),
                "latest_checkout_session_id": values.get("checkout_session_id")
                or mapping.get("latest_checkout_session_id"),
                "status": values["status"],
                "current_period_end": values.get("period_end"),
                "cancel_at_period_end": values.get("cancel_at_period_end", False),
                "event_created": values["event_created"],
                "event_id": values["event_id"],
            }
        )
        self.entitlements[owner]["subscription_pro_active"] = values["status"] == "active"
        self.applies += 1
        return owner


class FakeGateway:
    def __init__(self, config: BillingConfig) -> None:
        self.config = config
        self.customer_calls = 0
        self.customer_params: list[dict[str, str]] = []
        self.checkout_params: list[dict[str, Any]] = []
        self.portal_params: list[dict[str, Any]] = []
        self.retrieve_calls: list[str] = []
        self.construct_calls = 0
        self.event: Mapping[str, Any] | None = None
        self.subscription = _subscription(config)

    def create_customer(self, *, email: str, user_id: str, idempotency_key: str) -> Mapping[str, Any]:
        self.customer_calls += 1
        self.customer_params.append(
            {"email": email, "user_id": user_id, "idempotency_key": idempotency_key}
        )
        suffix = "A" if user_id == USER_A else "B"
        return {"id": "cus_" + suffix * 16}

    def create_checkout(self, **params: Any) -> Mapping[str, Any]:
        self.checkout_params.append(params)
        return {"url": "https://checkout.stripe.com/c/pay_test_safe"}

    def create_portal(self, **params: Any) -> Mapping[str, Any]:
        self.portal_params.append(params)
        return {"url": "https://billing.stripe.com/p/session/test_safe"}

    def retrieve_subscription(self, subscription_id: str) -> Mapping[str, Any]:
        self.retrieve_calls.append(subscription_id)
        return self.subscription

    def construct_event(self, _payload: bytes, signature: str, _secret: str) -> Mapping[str, Any]:
        self.construct_calls += 1
        if signature != "valid" or self.event is None:
            raise ValueError("invalid")
        return self.event


def _service() -> tuple[BillingService, FakeAccounts, FakeGateway]:
    config = _config()
    accounts = FakeAccounts()
    gateway = FakeGateway(config)
    return BillingService(config=config, accounts=accounts, gateway=gateway), accounts, gateway  # type: ignore[arg-type]


def _mapping(user_id: str, customer: str, subscription: str | None = None, *, status: str = "inactive") -> dict[str, Any]:
    return {
        "user_id": user_id,
        "provider": "stripe",
        "provider_customer_id": customer,
        "provider_subscription_id": subscription,
        "status": status,
    }


def test_verified_checkout_derives_identity_and_reuses_one_customer_mapping() -> None:
    service, accounts, gateway = _service()
    assert service.create_checkout(_identity()).startswith("https://checkout.stripe.com/")
    assert service.create_checkout(_identity()).startswith("https://checkout.stripe.com/")
    assert gateway.customer_calls == 1
    assert accounts.mappings[USER_A]["provider_customer_id"].startswith("cus_")
    assert len(gateway.checkout_params) == 2
    params = gateway.checkout_params[0]
    assert params["client_reference_id"] == USER_A
    assert params["customer"] == accounts.mappings[USER_A]["provider_customer_id"]
    assert params["line_items"] == [{"price": service.config.price_id, "quantity": 1}]
    assert "user" not in params["success_url"] and "customer" not in params["success_url"]


@pytest.mark.parametrize(
    "identity",
    [
        {},
        {**_identity(), "email_confirmed_at": None},
        {**_identity(), "is_anonymous": True},
    ],
)
def test_anonymous_unverified_and_anonymous_provider_users_cannot_checkout(identity: dict[str, Any]) -> None:
    service, accounts, gateway = _service()
    with pytest.raises(BillingOperationError, match="verified account"):
        service.create_checkout(identity)
    assert not accounts.mappings
    assert gateway.customer_calls == 0


def test_demo_user_cannot_create_customer_or_checkout() -> None:
    service, accounts, gateway = _service()
    accounts.entitlements[USER_A]["demo_expires_at"] = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    with pytest.raises(BillingOperationError, match="Demo"):
        service.create_checkout(_identity())
    assert gateway.customer_calls == 0
    assert not gateway.checkout_params


def test_mismatched_entitlement_owner_fails_before_any_stripe_call() -> None:
    service, accounts, gateway = _service()
    accounts.entitlements[USER_A]["user_id"] = USER_B
    with pytest.raises(BillingOperationError, match="account state"):
        service.create_checkout(_identity())
    assert gateway.customer_calls == 0
    assert not gateway.checkout_params


@pytest.mark.parametrize(
    "mapping",
    [
        _mapping(USER_B, "cus_BBBBBBBBBBBBBBBB"),
        _mapping(USER_A, "not-a-customer"),
        {**_mapping(USER_A, "cus_AAAAAAAAAAAAAAAA"), "provider": "other"},
    ],
)
def test_foreign_or_malformed_mapping_fails_before_customer_or_checkout(mapping: dict[str, Any]) -> None:
    service, accounts, gateway = _service()
    accounts.mappings[USER_A] = mapping
    with pytest.raises(BillingOperationError, match="setup"):
        service.create_checkout(_identity())
    assert gateway.customer_calls == 0
    assert not gateway.checkout_params


def test_portal_uses_only_server_mapping_and_free_state_fails_safely() -> None:
    service, accounts, gateway = _service()
    with pytest.raises(BillingOperationError, match="No managed subscription"):
        service.create_portal(_identity())
    accounts.mappings[USER_A] = _mapping(
        USER_A, "cus_AAAAAAAAAAAAAAAA", "sub_AAAAAAAAAAAAAAAA", status="active"
    )
    assert service.create_portal(_identity()).startswith("https://billing.stripe.com/")
    assert gateway.portal_params == [
        {"customer": "cus_AAAAAAAAAAAAAAAA", "return_url": "http://localhost:8501/?billing=return"}
    ]


def test_demo_and_foreign_mapping_cannot_create_portal_session() -> None:
    service, accounts, gateway = _service()
    accounts.mappings[USER_A] = _mapping(
        USER_B, "cus_BBBBBBBBBBBBBBBB", "sub_BBBBBBBBBBBBBBBB", status="active"
    )
    with pytest.raises(BillingOperationError, match="management"):
        service.create_portal(_identity())
    accounts.mappings[USER_A] = _mapping(
        USER_A, "cus_AAAAAAAAAAAAAAAA", "sub_AAAAAAAAAAAAAAAA", status="active"
    )
    accounts.entitlements[USER_A]["demo_expires_at"] = (
        datetime.now(timezone.utc) + timedelta(minutes=10)
    ).isoformat()
    with pytest.raises(BillingOperationError, match="Demo"):
        service.create_portal(_identity())
    assert not gateway.portal_params


def test_equal_emails_do_not_override_uuid_customer_ownership() -> None:
    service, accounts, gateway = _service()
    accounts.mappings[USER_A] = _mapping(USER_A, "cus_AAAAAAAAAAAAAAAA")
    accounts.mappings[USER_B] = _mapping(USER_B, "cus_BBBBBBBBBBBBBBBB")
    shared_email = "same-address@example.test"
    service.create_checkout(_identity(USER_A, email=shared_email))
    service.create_checkout(_identity(USER_B, email=shared_email))
    assert [params["customer"] for params in gateway.checkout_params] == [
        "cus_AAAAAAAAAAAAAAAA",
        "cus_BBBBBBBBBBBBBBBB",
    ]
    assert [params["client_reference_id"] for params in gateway.checkout_params] == [USER_A, USER_B]
    assert gateway.customer_calls == 0


def test_invalid_signature_is_rejected_before_durable_event_write() -> None:
    service, accounts, _gateway = _service()
    with pytest.raises(BillingWebhookInvalid):
        service.handle_webhook(b"{}", "invalid")
    assert not accounts.events


def test_unknown_event_is_recorded_and_duplicate_is_idempotent() -> None:
    service, accounts, gateway = _service()
    gateway.event = {"id": "evt_unknown", "type": "customer.created", "created": 100, "data": {"object": {}}}
    assert service.handle_webhook(b"{}", "valid")
    assert not service.handle_webhook(b"{}", "valid")
    assert accounts.events["evt_unknown"] == "processed"
    assert accounts.applies == 0


def test_active_then_canceled_changes_only_subscription_derived_access() -> None:
    service, accounts, gateway = _service()
    accounts.mappings[USER_A] = _mapping(USER_A, "cus_AAAAAAAAAAAAAAAA")
    gateway.event = {
        "id": "evt_active",
        "type": "customer.subscription.created",
        "created": 100,
        "data": {"object": _subscription(service.config, status="active")},
    }
    assert service.handle_webhook(b"{}", "valid")
    assert accounts.entitlements[USER_A]["subscription_pro_active"]
    assert accounts.entitlements[USER_A]["pro_active"]  # independent manual grant

    gateway.event = {
        "id": "evt_canceled",
        "type": "customer.subscription.deleted",
        "created": 200,
        "data": {"object": _subscription(service.config, status="canceled")},
    }
    assert service.handle_webhook(b"{}", "valid")
    assert not accounts.entitlements[USER_A]["subscription_pro_active"]
    assert accounts.entitlements[USER_A]["pro_active"]


def test_checkout_completion_activates_only_the_durable_owner_and_is_idempotent() -> None:
    service, accounts, gateway = _service()
    accounts.mappings[USER_A] = _mapping(USER_A, "cus_AAAAAAAAAAAAAAAA")
    gateway.event = {
        "id": "evt_checkout_complete",
        "type": "checkout.session.completed",
        "created": 100,
        "data": {
            "object": {
                "id": "cs_AAAAAAAAAAAAAAAA",
                "mode": "subscription",
                "subscription": "sub_AAAAAAAAAAAAAAAA",
                "client_reference_id": USER_A,
                "metadata": {"furuflow_user_id": USER_A},
            }
        },
    }

    assert service.handle_webhook(b"{}", "valid")
    assert not service.handle_webhook(b"{}", "valid")
    assert gateway.retrieve_calls == ["sub_AAAAAAAAAAAAAAAA"]
    assert accounts.applies == 1
    assert accounts.mappings[USER_A]["latest_checkout_session_id"] == "cs_AAAAAAAAAAAAAAAA"
    assert accounts.entitlements[USER_A]["subscription_pro_active"]
    assert not accounts.entitlements[USER_B]["subscription_pro_active"]


def test_checkout_completion_cannot_redirect_a_subscription_to_a_foreign_user() -> None:
    service, accounts, gateway = _service()
    accounts.mappings[USER_A] = _mapping(USER_A, "cus_AAAAAAAAAAAAAAAA")
    gateway.event = {
        "id": "evt_foreign_checkout",
        "type": "checkout.session.completed",
        "created": 100,
        "data": {
            "object": {
                "id": "cs_AAAAAAAAAAAAAAAA",
                "mode": "subscription",
                "subscription": "sub_AAAAAAAAAAAAAAAA",
                "client_reference_id": USER_B,
                "metadata": {"furuflow_user_id": USER_B},
            }
        },
    }

    with pytest.raises(BillingOperationError, match="mapping is inconsistent"):
        service.handle_webhook(b"{}", "valid")
    assert accounts.applies == 0
    assert not accounts.entitlements[USER_B]["subscription_pro_active"]


@pytest.mark.parametrize(
    ("status", "expected_pro"),
    [
        ("inactive", False),
        ("incomplete", False),
        ("incomplete_expired", False),
        ("trialing", False),
        ("active", True),
        ("past_due", False),
        ("canceled", False),
        ("unpaid", False),
        ("paused", False),
    ],
)
def test_every_supported_subscription_status_has_one_deterministic_entitlement_result(
    status: str, expected_pro: bool
) -> None:
    service, accounts, gateway = _service()
    accounts.mappings[USER_A] = _mapping(USER_A, "cus_AAAAAAAAAAAAAAAA")
    gateway.event = {
        "id": f"evt_{status}",
        "type": "customer.subscription.updated",
        "created": 100,
        "data": {"object": _subscription(service.config, status=status)},
    }

    service.handle_webhook(b"{}", "valid")

    assert accounts.mappings[USER_A]["status"] == status
    assert accounts.entitlements[USER_A]["subscription_pro_active"] is expected_pro
    assert not accounts.entitlements[USER_B]["subscription_pro_active"]


def test_scheduled_cancellation_preserves_pro_until_terminal_cancellation() -> None:
    service, accounts, gateway = _service()
    accounts.mappings[USER_A] = _mapping(USER_A, "cus_AAAAAAAAAAAAAAAA")
    gateway.event = {
        "id": "evt_cancel_scheduled",
        "type": "customer.subscription.updated",
        "created": 100,
        "data": {
            "object": _subscription(
                service.config,
                status="active",
                cancel_at_period_end=True,
            )
        },
    }
    service.handle_webhook(b"{}", "valid")
    assert accounts.mappings[USER_A]["status"] == "active"
    assert accounts.mappings[USER_A]["cancel_at_period_end"] is True
    assert accounts.mappings[USER_A]["current_period_end"] is not None
    assert accounts.entitlements[USER_A]["subscription_pro_active"]

    gateway.event = {
        "id": "evt_cancel_terminal",
        "type": "customer.subscription.deleted",
        "created": 200,
        "data": {"object": _subscription(service.config, status="canceled")},
    }
    service.handle_webhook(b"{}", "valid")
    assert accounts.mappings[USER_A]["status"] == "canceled"
    assert not accounts.entitlements[USER_A]["subscription_pro_active"]


def test_delinquency_recovery_updates_one_subscription_without_affecting_user_b() -> None:
    service, accounts, gateway = _service()
    accounts.mappings[USER_A] = _mapping(USER_A, "cus_AAAAAAAAAAAAAAAA")
    stable_mapping = accounts.mappings[USER_A]
    for created, status in ((100, "active"), (200, "past_due"), (300, "active")):
        gateway.event = {
            "id": f"evt_{created}_{status}",
            "type": "customer.subscription.updated",
            "created": created,
            "data": {"object": _subscription(service.config, status=status)},
        }
        service.handle_webhook(b"{}", "valid")

    assert len(accounts.mappings) == 1
    assert accounts.mappings[USER_A] is stable_mapping
    assert accounts.mappings[USER_A]["provider_subscription_id"] == "sub_AAAAAAAAAAAAAAAA"
    assert accounts.mappings[USER_A]["status"] == "active"
    assert accounts.entitlements[USER_A]["subscription_pro_active"]
    assert not accounts.entitlements[USER_B]["subscription_pro_active"]


def test_invoice_failure_and_recovery_reconcile_the_current_subscription() -> None:
    service, accounts, gateway = _service()
    accounts.mappings[USER_A] = _mapping(
        USER_A, "cus_AAAAAAAAAAAAAAAA", "sub_AAAAAAAAAAAAAAAA", status="active"
    )
    accounts.entitlements[USER_A]["subscription_pro_active"] = True
    gateway.subscription = _subscription(service.config, status="past_due")
    gateway.event = {
        "id": "evt_invoice_failed",
        "type": "invoice.payment_failed",
        "created": 200,
        "data": {"object": {"subscription": "sub_AAAAAAAAAAAAAAAA"}},
    }
    service.handle_webhook(b"{}", "valid")
    assert not accounts.entitlements[USER_A]["subscription_pro_active"]

    gateway.subscription = _subscription(service.config, status="active")
    gateway.event = {
        "id": "evt_invoice_recovered",
        "type": "invoice.paid",
        "created": 300,
        "data": {
            "object": {
                "parent": {"subscription_details": {"subscription": "sub_AAAAAAAAAAAAAAAA"}}
            }
        },
    }
    service.handle_webhook(b"{}", "valid")
    assert gateway.retrieve_calls == ["sub_AAAAAAAAAAAAAAAA", "sub_AAAAAAAAAAAAAAAA"]
    assert accounts.entitlements[USER_A]["subscription_pro_active"]


@pytest.mark.parametrize("status", ["active", "canceled"])
def test_duplicate_subscription_lifecycle_event_has_exactly_one_effect(status: str) -> None:
    service, accounts, gateway = _service()
    accounts.mappings[USER_A] = _mapping(USER_A, "cus_AAAAAAAAAAAAAAAA")
    gateway.event = {
        "id": f"evt_duplicate_{status}",
        "type": "customer.subscription.updated" if status == "active" else "customer.subscription.deleted",
        "created": 100,
        "data": {"object": _subscription(service.config, status=status)},
    }
    assert service.handle_webhook(b"{}", "valid")
    assert not service.handle_webhook(b"{}", "valid")
    assert accounts.applies == 1


def test_older_cancellation_cannot_revoke_a_newer_active_state() -> None:
    service, accounts, gateway = _service()
    accounts.mappings[USER_A] = _mapping(USER_A, "cus_AAAAAAAAAAAAAAAA")
    gateway.event = {
        "id": "evt_new_active",
        "type": "customer.subscription.updated",
        "created": 200,
        "data": {"object": _subscription(service.config, status="active")},
    }
    service.handle_webhook(b"{}", "valid")
    gateway.event = {
        "id": "evt_old_canceled",
        "type": "customer.subscription.deleted",
        "created": 100,
        "data": {"object": _subscription(service.config, status="canceled")},
    }
    service.handle_webhook(b"{}", "valid")
    assert accounts.mappings[USER_A]["status"] == "active"
    assert accounts.entitlements[USER_A]["subscription_pro_active"]


def test_stale_event_cannot_overwrite_newer_authoritative_state() -> None:
    service, accounts, gateway = _service()
    accounts.mappings[USER_A] = _mapping(USER_A, "cus_AAAAAAAAAAAAAAAA")
    gateway.event = {
        "id": "evt_new",
        "type": "customer.subscription.updated",
        "created": 200,
        "data": {"object": _subscription(service.config, status="canceled")},
    }
    service.handle_webhook(b"{}", "valid")
    gateway.event = {
        "id": "evt_old",
        "type": "customer.subscription.updated",
        "created": 100,
        "data": {"object": _subscription(service.config, status="active")},
    }
    service.handle_webhook(b"{}", "valid")
    assert accounts.mappings[USER_A]["status"] == "canceled"
    assert not accounts.entitlements[USER_A]["subscription_pro_active"]


def test_webhook_for_mapped_customer_cannot_modify_another_user() -> None:
    service, accounts, gateway = _service()
    accounts.mappings[USER_A] = _mapping(USER_A, "cus_AAAAAAAAAAAAAAAA")
    gateway.event = {
        "id": "evt_cross_user",
        "type": "customer.subscription.created",
        "created": 100,
        "data": {"object": _subscription(service.config, status="active", user_id=USER_B)},
    }
    with pytest.raises(BillingOperationError):
        service.handle_webhook(b"{}", "valid")
    assert not accounts.entitlements[USER_B]["subscription_pro_active"]


def test_signed_webhook_cannot_replace_existing_customer_mapping() -> None:
    service, accounts, gateway = _service()
    accounts.mappings[USER_A] = _mapping(
        USER_A, "cus_AAAAAAAAAAAAAAAA", "sub_AAAAAAAAAAAAAAAA", status="active"
    )
    accounts.entitlements[USER_A]["subscription_pro_active"] = True
    before_mapping = deepcopy(accounts.mappings)
    before_entitlements = deepcopy(accounts.entitlements)
    gateway.event = {
        "id": "evt_customer_conflict",
        "type": "customer.subscription.updated",
        "created": 500,
        "data": {
            "object": _subscription(
                service.config,
                user_id=USER_A,
                customer_id="cus_REPLACEMENTCUSTOMER",
            )
        },
    }
    with pytest.raises(BillingOperationError):
        service.handle_webhook(b"{}", "valid")
    assert accounts.mappings == before_mapping
    assert accounts.entitlements == before_entitlements
    assert accounts.applies == 0


def test_environment_separation_rejects_live_key_outside_production() -> None:
    with pytest.raises(BillingConfigurationError, match="Non-production"):
        replace(_config(), secret_key="sk_live_" + "L" * 32).validate()
    with pytest.raises(BillingConfigurationError, match="explicit live-mode"):
        replace(_config(), environment="production", public_origin="https://app.example").validate()
    with pytest.raises(BillingConfigurationError, match="placeholder"):
        replace(_config(), price_id="price_REPLACE_WITH_REAL_VALUE").validate()
