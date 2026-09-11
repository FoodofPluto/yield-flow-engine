from __future__ import annotations

import os
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from automation.models import NotificationRule, ScanOutcome, TelegramDeliveryError, TelegramReceipt


class AutomationStoreError(RuntimeError):
    """Redacted durable-store failure."""


class SupabaseAutomationStore:
    """Service-role-only adapter for transactional automation RPCs."""

    def __init__(
        self,
        *,
        project_url: str | None = None,
        service_role_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        root = (project_url or os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
        parsed = urlparse(root)
        if parsed.scheme != "https" or not parsed.netloc or parsed.path not in {"", "/"}:
            raise AutomationStoreError("SUPABASE_URL must be the HTTPS project root.")
        self._key = (service_role_key or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
        if not self._key or self._key == (os.getenv("SUPABASE_ANON_KEY") or "").strip():
            raise AutomationStoreError("SUPABASE_SERVICE_ROLE_KEY is required by the trusted automation worker.")
        self._base_url = f"{root}/rest/v1"
        self._transport = transport

    def _request(self, method: str, path: str, *, body: dict[str, Any] | None = None) -> Any:
        headers = {
            "apikey": self._key,
            "Authorization": f"Bearer {self._key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=15.0, transport=self._transport) as client:
                response = client.request(method, f"{self._base_url}/{path}", headers=headers, json=body)
        except httpx.HTTPError as exc:
            raise AutomationStoreError("Automation persistence is unavailable.") from exc
        if response.status_code < 200 or response.status_code >= 300:
            raise AutomationStoreError(f"Automation persistence rejected the operation (HTTP {response.status_code}).")
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise AutomationStoreError("Automation persistence returned an invalid response.") from exc

    def _rpc(self, name: str, **body: Any) -> Any:
        return self._request("POST", f"rpc/{name}", body=body)

    def begin_run(self, *, invocation_key: str, worker_id: str, scheduled_for: datetime) -> dict[str, Any]:
        value = self._rpc(
            "service_begin_automation_run",
            logical_invocation_key=invocation_key,
            worker_instance=worker_id,
            scheduled_time=scheduled_for.isoformat(),
        )
        if not isinstance(value, dict) or "id" not in value:
            raise AutomationStoreError("Automation run claim returned an invalid response.")
        return value

    def heartbeat(self, *, run_id: str | None, worker_id: str, state: str) -> None:
        self._rpc("service_automation_heartbeat", active_run_id=run_id, worker_instance=worker_id, worker_state=state)

    def finish_scan(
        self,
        *,
        run_id: str,
        outcome: ScanOutcome,
        signal_count: int,
        error_code: str | None = None,
    ) -> None:
        self._rpc(
            "service_finish_automation_scan",
            automation_run_id=run_id,
            scan_outcome=outcome.value,
            generated_signal_count=signal_count,
            safe_error_code=error_code,
        )

    def list_rules(self, *, environment: str) -> list[NotificationRule]:
        value = self._rpc("service_list_notification_rules", target_environment=environment)
        if not isinstance(value, list):
            raise AutomationStoreError("Notification rule query returned an invalid response.")
        return [NotificationRule.from_row(row) for row in value if isinstance(row, dict)]

    def upsert_system_rule(self, *, chat_id: str, enabled: bool) -> None:
        self._rpc("service_upsert_system_notification_rule", destination_chat_id=chat_id, rule_enabled=enabled)

    def set_user_telegram_connection(self, *, user_id: str, chat_id: str, linked: bool = True) -> str:
        value = self._rpc(
            "service_set_user_telegram_connection",
            target_user_id=user_id,
            destination_chat_id=chat_id,
            connection_linked=linked,
        )
        if not isinstance(value, str):
            raise AutomationStoreError("Telegram connection update returned an invalid response.")
        return value

    def enqueue_staging_test(self, *, chat_id: str, test_key: str, environment: str) -> bool:
        value = self._rpc(
            "service_enqueue_staging_notification_test",
            destination_chat_id=chat_id,
            test_idempotency_key=test_key,
            target_environment=environment,
        )
        return bool(value)

    def enqueue_delivery(
        self,
        *,
        run_id: str,
        rule_id: str,
        signal_fingerprint: str,
        logical_delivery_key: str,
        signal: dict[str, Any],
        message_text: str,
        available_at: datetime,
        kind: str = "signal",
    ) -> bool:
        value = self._rpc(
            "service_enqueue_telegram_delivery",
            automation_run_id=run_id,
            notification_rule_id=rule_id,
            stable_signal_fingerprint=signal_fingerprint,
            delivery_idempotency_key=logical_delivery_key,
            signal_payload=signal,
            rendered_message=message_text,
            not_before=available_at.isoformat(),
            delivery_kind=kind,
        )
        return bool(value)

    def record_rule_evaluations(self, *, run_id: str, evaluated_rule_ids: list[str], triggered_rule_ids: list[str]) -> None:
        self._rpc(
            "service_record_notification_rule_evaluations",
            automation_run_id=run_id,
            evaluated_rule_ids=evaluated_rule_ids,
            triggered_rule_ids=triggered_rule_ids,
        )

    def recover_abandoned(self, *, stale_seconds: int) -> int:
        value = self._rpc("service_recover_abandoned_deliveries", stale_after_seconds=stale_seconds)
        return int(value or 0)

    def claim_test_request(self, *, worker_id: str) -> dict[str, Any] | None:
        value = self._rpc("service_claim_notification_test", worker_instance=worker_id)
        if value is None:
            return None
        if not isinstance(value, dict):
            raise AutomationStoreError("Notification test claim returned an invalid response.")
        return value

    def finish_test_request(self, *, request_id: str, succeeded: bool, error_code: str | None = None) -> None:
        self._rpc(
            "service_finish_notification_test",
            notification_test_request_id=request_id,
            succeeded=succeeded,
            safe_error_code=error_code,
        )

    def claim_delivery(self, *, worker_id: str) -> dict[str, Any] | None:
        value = self._rpc("service_claim_telegram_delivery", worker_instance=worker_id)
        if value is None:
            return None
        if not isinstance(value, dict):
            raise AutomationStoreError("Delivery claim returned an invalid response.")
        return value

    def finish_delivery(
        self,
        *,
        delivery_id: str,
        worker_id: str,
        receipt: TelegramReceipt | None = None,
        error: TelegramDeliveryError | None = None,
        retry_at: datetime | None = None,
    ) -> str:
        value = self._rpc(
            "service_finish_telegram_delivery",
            claimed_delivery_id=delivery_id,
            worker_instance=worker_id,
            delivered=receipt is not None,
            provider_message_id=receipt.message_id if receipt else None,
            safe_error_code=error.code if error else None,
            retryable=bool(error and error.retryable and not error.ambiguous),
            ambiguous_outcome=bool(error and error.ambiguous),
            retry_time=retry_at.isoformat() if retry_at else None,
        )
        return str(value)

    def health(self, *, stale_after_seconds: int) -> dict[str, Any]:
        value = self._rpc("service_automation_health", stale_after_seconds=stale_after_seconds)
        if not isinstance(value, dict):
            raise AutomationStoreError("Automation health query returned an invalid response.")
        return value


class UserNotificationClient:
    """Authenticated, RLS-constrained preference and delivery-history API."""

    def __init__(
        self,
        *,
        project_url: str,
        anon_key: str,
        access_token: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = f"{project_url.rstrip('/')}/rest/v1"
        self._anon_key = anon_key
        self._access_token = access_token
        self._transport = transport

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        prefer: str | None = None,
    ) -> Any:
        headers = {
            "apikey": self._anon_key,
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        try:
            with httpx.Client(timeout=10.0, transport=self._transport) as client:
                response = client.request(method, f"{self._base_url}/{path}", headers=headers, json=body)
        except httpx.HTTPError as exc:
            raise AutomationStoreError("Notification preferences are unavailable.") from exc
        if response.status_code < 200 or response.status_code >= 300:
            raise AutomationStoreError("Notification preference operation was rejected.")
        return response.json() if response.content else None

    def _rpc(self, name: str, **body: Any) -> Any:
        return self._request("POST", f"rpc/{name}", body=body)

    def telegram_status(self) -> dict[str, Any]:
        value = self._rpc("get_my_telegram_status")
        if not isinstance(value, dict):
            raise AutomationStoreError("Telegram connection status returned an invalid response.")
        return value

    def list_alerts(self) -> list[dict[str, Any]]:
        value = self._rpc("list_my_pool_alerts")
        return value if isinstance(value, list) else []

    def create_pool_alert(
        self,
        *,
        target_pool_id: str,
        minimum_strength: int,
        signal_tier: str,
        delivery_mode: str,
        quiet_hours_start: str | None,
        quiet_hours_end: str | None,
        timezone_name: str,
        cooldown_minutes: int,
        client_request_key: str,
    ) -> dict[str, Any]:
        value = self._rpc(
            "create_my_pool_alert",
            requested_target_pool_id=target_pool_id,
            requested_minimum_strength=minimum_strength,
            requested_signal_tier=signal_tier,
            requested_delivery_mode=delivery_mode,
            requested_quiet_hours_start=quiet_hours_start,
            requested_quiet_hours_end=quiet_hours_end,
            requested_timezone=timezone_name,
            requested_cooldown_minutes=cooldown_minutes,
            request_key=client_request_key,
        )
        if not isinstance(value, dict):
            raise AutomationStoreError("Alert was not created.")
        return value

    def update_pool_alert(
        self,
        *,
        alert_id: str,
        minimum_strength: int,
        signal_tier: str,
        delivery_mode: str,
        quiet_hours_start: str | None,
        quiet_hours_end: str | None,
        timezone_name: str,
        cooldown_minutes: int,
    ) -> dict[str, Any]:
        value = self._rpc(
            "update_my_pool_alert",
            notification_rule_id=alert_id,
            requested_minimum_strength=minimum_strength,
            requested_signal_tier=signal_tier,
            requested_delivery_mode=delivery_mode,
            requested_quiet_hours_start=quiet_hours_start,
            requested_quiet_hours_end=quiet_hours_end,
            requested_timezone=timezone_name,
            requested_cooldown_minutes=cooldown_minutes,
        )
        if not isinstance(value, dict):
            raise AutomationStoreError("Alert was not updated.")
        return value

    def set_alert_enabled(self, alert_id: str, enabled: bool) -> bool:
        return bool(
            self._rpc("set_my_pool_alert_enabled", notification_rule_id=alert_id, alert_enabled=enabled)
        )

    def delete_alert(self, alert_id: str) -> bool:
        return bool(self._rpc("delete_my_pool_alert", notification_rule_id=alert_id))

    def list_rules(self) -> list[dict[str, Any]]:
        return self.list_alerts()

    def create_rule(self, values: dict[str, Any]) -> dict[str, Any]:
        return self.create_pool_alert(
            target_pool_id=str(values["target_pool_id"]),
            minimum_strength=int(values.get("minimum_strength") or 0),
            signal_tier=str(values.get("signal_tier") or "all"),
            delivery_mode=str(values.get("delivery_mode") or "immediate"),
            quiet_hours_start=values.get("quiet_hours_start"),
            quiet_hours_end=values.get("quiet_hours_end"),
            timezone_name=str(values.get("timezone") or "UTC"),
            cooldown_minutes=int(values.get("cooldown_minutes") or 1440),
            client_request_key=str(values["client_request_key"]),
        )

    def disable_rule(self, rule_id: str) -> bool:
        return self.set_alert_enabled(rule_id, False)

    def delivery_history(self, *, limit: int = 50) -> list[dict[str, Any]]:
        safe_limit = min(max(limit, 1), 100)
        value = self._request(
            "GET",
            f"notification_delivery_history?select=*&order=created_at.desc&limit={safe_limit}",
        )
        return value if isinstance(value, list) else []

    def request_test_delivery(self, rule_id: str) -> str:
        value = self._request("POST", "rpc/request_notification_test", body={"notification_rule_id": rule_id})
        if not isinstance(value, str):
            raise AutomationStoreError("Test notification request was rejected.")
        return value
