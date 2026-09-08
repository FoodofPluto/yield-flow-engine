from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import httpx

from supabase_client import load_auth_config


class AccountStateUnavailable(RuntimeError):
    """The authoritative account control plane could not return safe state."""


class AccountOperationError(RuntimeError):
    """A trusted account-control operation was rejected."""


def _canonical_user_id(value: Any) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise AccountOperationError("Billing account identifier is invalid.") from exc


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


class SupabaseAccountClient:
    def __init__(self, *, service_role_key: str | None = None, transport: httpx.BaseTransport | None = None):
        if service_role_key:
            project_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
            parsed = urlparse(project_url)
            if parsed.scheme != "https" or not parsed.netloc or parsed.path not in {"", "/"}:
                raise AccountOperationError("SUPABASE_URL must be the HTTPS project root.")
            self._base_url = f"{project_url}/rest/v1"
            self._anon_key = ""
        else:
            config = load_auth_config()
            self._base_url = f"{config.project_url}/rest/v1"
            self._anon_key = config.anon_key
        self._service_role_key = service_role_key
        self._transport = transport

    def _request(
        self,
        method: str,
        path: str,
        *,
        bearer: str,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        prefer: str | None = None,
    ) -> Any:
        headers = {
            "apikey": self._service_role_key or self._anon_key,
            "Authorization": f"Bearer {bearer}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        try:
            with httpx.Client(timeout=10.0, transport=self._transport) as client:
                response = client.request(method, f"{self._base_url}/{path}", headers=headers, params=params, json=json_body)
        except httpx.HTTPError as exc:
            raise AccountStateUnavailable("Authoritative account state is unavailable.") from exc
        if response.status_code < 200 or response.status_code >= 300:
            if self._service_role_key:
                raise AccountOperationError(f"Account operation was rejected (HTTP {response.status_code}).")
            raise AccountStateUnavailable("Authoritative account state was rejected; access is denied.")
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise AccountStateUnavailable("Authoritative account state returned an invalid response.") from exc

    def get_account(self, user_id: str, access_token: str, *, environment: str) -> dict[str, Any]:
        profile = self._request("GET", "profiles", bearer=access_token, params={"id": f"eq.{user_id}", "select": "*"})
        entitlement = self._request(
            "GET", "entitlements", bearer=access_token, params={"user_id": f"eq.{user_id}", "select": "*"}
        )
        subscriptions = self._request(
            "GET",
            "subscriptions",
            bearer=access_token,
            params={
                "user_id": f"eq.{user_id}",
                "select": "user_id,status,current_period_end,cancel_at_period_end,updated_at",
                "order": "updated_at.desc",
                "limit": "1",
            },
        )
        if not isinstance(profile, list) or len(profile) != 1 or profile[0].get("id") != user_id:
            raise AccountStateUnavailable("The verified account profile is missing; access is denied.")
        if not isinstance(entitlement, list) or len(entitlement) != 1 or entitlement[0].get("user_id") != user_id:
            raise AccountStateUnavailable("The verified account entitlement is missing; access is denied.")
        row = entitlement[0]
        demo_expiry = _parse_time(row.get("demo_expires_at"))
        demo_active = bool(
            demo_expiry
            and demo_expiry > datetime.now(timezone.utc)
            and environment in {"development", "staging", "test"}
            and row.get("demo_environment") == environment
        )
        subscription = subscriptions[0] if isinstance(subscriptions, list) and subscriptions else {}
        return {
            "user_id": user_id,
            "provider_user_id": user_id,
            "display_name": profile[0].get("display_name"),
            "timezone": profile[0].get("timezone", "UTC"),
            "is_admin": bool(row.get("is_admin")),
            "pro_active": bool(row.get("pro_active")),
            "subscription_pro_active": bool(row.get("subscription_pro_active")),
            "lifetime_access": bool(row.get("lifetime_access")),
            "demo_active": demo_active,
            "demo_expires_at": row.get("demo_expires_at"),
            "subscription_status": subscription.get("status"),
            "subscription_period_end": subscription.get("current_period_end"),
            "subscription_cancel_at_period_end": bool(subscription.get("cancel_at_period_end")),
            "_account_authority": "supabase",
        }

    def claim_session(self, access_token: str, raw_session_id: str, ttl_seconds: int = 86400) -> str:
        value = self._request(
            "POST",
            "rpc/claim_account_session",
            bearer=access_token,
            json_body={"raw_session_id": raw_session_id, "ttl_seconds": ttl_seconds},
        )
        if not isinstance(value, str):
            raise AccountStateUnavailable("The account session could not be established.")
        return value

    def touch_session(self, access_token: str, raw_session_id: str) -> bool:
        return self._request(
            "POST", "rpc/touch_account_session", bearer=access_token, json_body={"raw_session_id": raw_session_id}
        ) is True

    def revoke_session(self, access_token: str, raw_session_id: str) -> bool:
        return self._request(
            "POST", "rpc/revoke_account_session", bearer=access_token, json_body={"raw_session_id": raw_session_id}
        ) is True


class ServiceRoleAccountClient(SupabaseAccountClient):
    def __init__(self, *, service_role_key: str | None = None, transport: httpx.BaseTransport | None = None):
        key = (service_role_key or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
        if not key or key == os.getenv("SUPABASE_ANON_KEY", "").strip():
            raise AccountOperationError("SUPABASE_SERVICE_ROLE_KEY must be configured only in the trusted backend/CLI.")
        super().__init__(service_role_key=key, transport=transport)
        self._key = key

    def bootstrap_first_admin(self, target_user_id: str, reason: str = "first_admin_bootstrap") -> bool:
        return self._request(
            "POST",
            "rpc/bootstrap_first_admin",
            bearer=self._key,
            json_body={"target_user_id": target_user_id, "change_reason": reason},
        ) is True

    def get_entitlement(self, user_id: str) -> dict[str, Any]:
        user_id = _canonical_user_id(user_id)
        rows = self._request(
            "GET", "entitlements", bearer=self._key, params={"user_id": f"eq.{user_id}", "select": "*", "limit": "1"}
        )
        if not isinstance(rows, list) or len(rows) != 1 or rows[0].get("user_id") != user_id:
            raise AccountOperationError("Target entitlement record is unavailable.")
        return rows[0]

    def set_entitlement(
        self,
        *,
        target_user_id: str,
        entitlement: str,
        enabled: bool,
        actor_user_id: str,
        reason: str,
        demo_expiry: str | None = None,
        environment: str | None = None,
        source: str = "admin_cli",
    ) -> bool:
        return self._request(
            "POST",
            "rpc/service_set_entitlement",
            bearer=self._key,
            json_body={
                "target_user_id": target_user_id,
                "entitlement_name": entitlement,
                "enabled": enabled,
                "actor_user_id": actor_user_id,
                "change_reason": reason,
                "demo_expiry": demo_expiry,
                "target_environment": environment,
                "change_source": source,
            },
        ) is True

    def cleanup_expired_demos(self) -> int:
        value = self._request("POST", "rpc/cleanup_expired_demo_entitlements", bearer=self._key, json_body={})
        return int(value)

    def begin_webhook_event(self, event_id: str, event_type: str) -> bool:
        return self._request(
            "POST",
            "rpc/service_begin_webhook_event",
            bearer=self._key,
            json_body={"event_provider": "stripe", "incoming_event_id": event_id, "incoming_type": event_type},
        ) is True

    def get_stripe_mapping(self, user_id: str) -> dict[str, Any] | None:
        user_id = _canonical_user_id(user_id)
        rows = self._request(
            "GET",
            "subscriptions",
            bearer=self._key,
            params={"user_id": f"eq.{user_id}", "provider": "eq.stripe", "select": "*", "limit": "1"},
        )
        if not isinstance(rows, list):
            raise AccountOperationError("Billing mapping is unavailable.")
        if not rows:
            return None
        if len(rows) != 1 or rows[0].get("user_id") != user_id or rows[0].get("provider") != "stripe":
            raise AccountOperationError("Billing mapping ownership is invalid.")
        return rows[0]

    def set_stripe_customer(self, *, user_id: str, customer_id: str) -> bool:
        return self._request(
            "POST",
            "rpc/service_set_stripe_customer",
            bearer=self._key,
            json_body={"target_user_id": user_id, "customer_id": customer_id},
        ) is True

    def finish_webhook_event(self, event_id: str, *, succeeded: bool, error_code: str | None = None) -> None:
        self._request(
            "POST",
            "rpc/service_finish_webhook_event",
            bearer=self._key,
            json_body={
                "event_provider": "stripe",
                "incoming_event_id": event_id,
                "succeeded": succeeded,
                "error_code": error_code,
            },
        )

    def apply_stripe_subscription(
        self,
        *,
        user_id: str | None,
        customer_id: str | None,
        subscription_id: str | None,
        status: str,
        event_created: int,
        event_id: str,
        checkout_session_id: str | None = None,
        period_end: str | None = None,
        cancel_at_period_end: bool = False,
    ) -> str:
        value = self._request(
            "POST",
            "rpc/service_apply_stripe_subscription",
            bearer=self._key,
            json_body={
                "target_user_id": user_id,
                "customer_id": customer_id,
                "subscription_id": subscription_id,
                "subscription_status": status,
                "checkout_session_id": checkout_session_id,
                "period_end": period_end,
                "cancels_at_period_end": cancel_at_period_end,
                "provider_event_created": event_created,
                "provider_event_id": event_id,
            },
        )
        return str(value)

    def reconcile_subscription_entitlement(self, user_id: str) -> bool:
        return self._request(
            "POST",
            "rpc/service_reconcile_subscription_entitlement",
            bearer=self._key,
            json_body={"target_user_id": user_id},
        ) is True


def external_delivery_allowed(user: dict[str, Any] | None) -> bool:
    return bool(user and user.get("_account_authority") == "supabase" and not user.get("demo_active"))
