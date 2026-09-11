from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest
import telegram_worker

from automation.models import NotificationRule, ScanOutcome, TelegramDeliveryError, TelegramReceipt
from automation.store import AutomationStoreError, SupabaseAutomationStore, UserNotificationClient
from automation.telegram import TelegramClient
from automation.worker import AutomationWorker, WorkerConfig


NOW = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)
RULE = NotificationRule(id="rule-1", user_id=None, telegram_chat_id="chat-1", cooldown_minutes=60)
SIGNAL = {
    "pool_id": "pool-1",
    "name": "Pool One",
    "chain": "Base",
    "category": "Stablecoin",
    "apy": 12.5,
    "tvl": 2_000_000,
    "strength_score": 70,
    "strength_label": "Strong",
    "risk_label": "Moderate",
    "tier": "Pro",
}


class MemoryStore:
    def __init__(self, rules: list[NotificationRule] | None = None) -> None:
        self.rules = list(rules if rules is not None else [RULE])
        self.runs: dict[str, dict[str, Any]] = {}
        self.deliveries: list[dict[str, Any]] = []
        self.delivery_keys: set[str] = set()
        self.attempts: list[tuple[str, int, str]] = []
        self.heartbeats: list[str] = []
        self.tests: deque[dict[str, Any]] = deque()
        self.system_rule_upserts = 0
        self.evaluations: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = []

    def begin_run(self, *, invocation_key: str, worker_id: str, scheduled_for: datetime) -> dict[str, Any]:
        if invocation_key in self.runs:
            return {"id": self.runs[invocation_key]["id"], "claimed": False}
        run = {"id": f"run-{len(self.runs) + 1}", "claimed": True, "outcome": None}
        self.runs[invocation_key] = run
        return dict(run)

    def heartbeat(self, *, run_id: str | None, worker_id: str, state: str) -> None:
        self.heartbeats.append(state)

    def finish_scan(
        self, *, run_id: str, outcome: ScanOutcome, signal_count: int, error_code: str | None = None
    ) -> None:
        for run in self.runs.values():
            if run["id"] == run_id:
                run.update(outcome=outcome.value, signal_count=signal_count, error_code=error_code)

    def list_rules(self, *, environment: str) -> list[NotificationRule]:
        return self.rules

    def upsert_system_rule(self, *, chat_id: str, enabled: bool) -> None:
        self.system_rule_upserts += 1

    def record_rule_evaluations(
        self, *, run_id: str, evaluated_rule_ids: list[str], triggered_rule_ids: list[str]
    ) -> None:
        self.evaluations.append((run_id, tuple(evaluated_rule_ids), tuple(triggered_rule_ids)))

    def enqueue_delivery(self, **values: Any) -> bool:
        key = values["logical_delivery_key"]
        if key in self.delivery_keys:
            return False
        self.delivery_keys.add(key)
        self.deliveries.append(
            {
                "id": f"delivery-{len(self.deliveries) + 1}",
                "key": key,
                "state": "queued",
                "attempt_count": 0,
                "telegram_chat_id": next(rule.telegram_chat_id for rule in self.rules if rule.id == values["rule_id"]),
                "message_text": values["message_text"],
                **values,
            }
        )
        return True

    def recover_abandoned(self, *, stale_seconds: int) -> int:
        recovered = 0
        for delivery in self.deliveries:
            if delivery["state"] == "sending":
                delivery["state"] = "dead_letter"
                delivery["ambiguous"] = True
                recovered += 1
        return recovered

    def claim_test_request(self, *, worker_id: str) -> dict[str, Any] | None:
        return self.tests.popleft() if self.tests else None

    def finish_test_request(self, *, request_id: str, succeeded: bool, error_code: str | None = None) -> None:
        return None

    def claim_delivery(self, *, worker_id: str) -> dict[str, Any] | None:
        for delivery in self.deliveries:
            if delivery["state"] in {"queued", "retry"} and delivery["attempt_count"] < 3:
                delivery["state"] = "sending"
                delivery["attempt_count"] += 1
                delivery["worker_id"] = worker_id
                return {
                    "id": delivery["id"],
                    "attempt_count": delivery["attempt_count"],
                    "telegram_chat_id": delivery["telegram_chat_id"],
                    "message_text": delivery["message_text"],
                }
        return None

    def finish_delivery(self, **values: Any) -> str:
        delivery = next(item for item in self.deliveries if item["id"] == values["delivery_id"])
        receipt = values.get("receipt")
        error = values.get("error")
        if receipt:
            delivery["state"] = "delivered"
            delivery["provider_message_id"] = receipt.message_id
        elif error and error.retryable and not error.ambiguous and values.get("retry_at") and delivery["attempt_count"] < 3:
            delivery["state"] = "retry"
        else:
            delivery["state"] = "dead_letter"
            delivery["ambiguous"] = bool(error and error.ambiguous)
        self.attempts.append((delivery["id"], delivery["attempt_count"], delivery["state"]))
        return delivery["state"]


class FakeTelegram:
    def __init__(self, outcomes: list[Any] | None = None) -> None:
        self.outcomes = deque(outcomes or [TelegramReceipt(message_id="100")])
        self.calls: list[tuple[str, str]] = []

    def send(self, *, chat_id: str, text: str) -> TelegramReceipt:
        self.calls.append((chat_id, text))
        outcome = self.outcomes.popleft()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def worker(
    store: MemoryStore,
    telegram: FakeTelegram,
    scanner=lambda: [dict(SIGNAL)],
    *,
    worker_id: str = "worker-a",
) -> AutomationWorker:
    return AutomationWorker(
        store=store,
        telegram=telegram,
        scanner=scanner,
        config=WorkerConfig(retry_backoff_seconds=(1, 1)),
        worker_id=worker_id,
        clock=lambda: NOW,
    )


def test_successful_scan_enqueues_and_delivers_once() -> None:
    store, telegram = MemoryStore(), FakeTelegram()
    result = worker(store, telegram).run_scan()
    assert result["outcome"] == "succeeded"
    assert result["enqueued"] == result["delivered"] == 1
    assert len(store.deliveries) == len(telegram.calls) == 1
    assert store.deliveries[0]["state"] == "delivered"


def test_zero_signal_scan_is_success_and_does_not_send() -> None:
    store, telegram = MemoryStore(), FakeTelegram()
    result = worker(store, telegram, scanner=lambda: []).run_scan()
    assert result["outcome"] == "zero_signals"
    assert result["delivered"] == 0
    assert not telegram.calls
    assert store.evaluations == [("run-1", (RULE.id,), ())]


def test_provider_failure_is_distinct_and_does_not_send() -> None:
    def fail() -> list[dict[str, Any]]:
        raise RuntimeError("provider response included something unsafe")

    store, telegram = MemoryStore(), FakeTelegram()
    result = worker(store, telegram, scanner=fail).run_scan()
    assert result["outcome"] == "provider_failed"
    assert next(iter(store.runs.values()))["error_code"] == "market_provider_unavailable"
    assert not telegram.calls


def test_retryable_failure_succeeds_without_duplicate_logical_delivery() -> None:
    retry = TelegramDeliveryError("telegram_http_500", retryable=True)
    store, telegram = MemoryStore(), FakeTelegram([retry, TelegramReceipt(message_id="101")])
    result = worker(store, telegram).run_scan()
    assert result["delivered"] == 1
    assert len(store.deliveries) == 1
    assert len(store.delivery_keys) == 1
    assert store.attempts == [("delivery-1", 1, "retry"), ("delivery-1", 2, "delivered")]


def test_retry_exhaustion_dead_letters_after_exactly_three_attempts() -> None:
    failures = [TelegramDeliveryError("telegram_http_503", retryable=True) for _ in range(3)]
    store, telegram = MemoryStore(), FakeTelegram(failures)
    result = worker(store, telegram).run_scan()
    assert result["retried"] == 2
    assert result["dead_lettered"] == 1
    assert len(telegram.calls) == 3
    assert store.deliveries[0]["state"] == "dead_letter"


def test_permanent_and_ambiguous_failures_are_not_retried() -> None:
    for error in (
        TelegramDeliveryError("telegram_http_403", retryable=False),
        TelegramDeliveryError("telegram_timeout_unknown_outcome", retryable=False, ambiguous=True),
    ):
        store, telegram = MemoryStore(), FakeTelegram([error])
        result = worker(store, telegram).run_scan(invocation_key=error.code)
        assert result["dead_lettered"] == 1
        assert len(telegram.calls) == 1
        assert store.deliveries[0]["state"] == "dead_letter"
        assert store.deliveries[0].get("ambiguous", False) is error.ambiguous


def test_duplicate_scheduler_and_concurrent_worker_invocations_are_noops() -> None:
    store, telegram = MemoryStore(), FakeTelegram()
    first = worker(store, telegram, worker_id="worker-a").run_scan(invocation_key="schedule-slot")
    second = worker(store, telegram, worker_id="worker-b").run_scan(invocation_key="schedule-slot")
    assert first["claimed"] is True
    assert second == {"run_id": "run-1", "claimed": False, "outcome": "duplicate_invocation"}
    assert len(store.deliveries) == len(telegram.calls) == 1


def test_same_signal_in_cooldown_window_has_database_style_delivery_deduplication() -> None:
    store, telegram = MemoryStore(), FakeTelegram([TelegramReceipt("1")])
    first_worker = worker(store, telegram)
    first_worker.run_scan(invocation_key="one")
    second = first_worker.run_scan(invocation_key="two")
    assert second["enqueued"] == 0
    assert len(store.deliveries) == len(telegram.calls) == 1


def test_abandoned_sending_claim_is_dead_lettered_without_resend() -> None:
    store, telegram = MemoryStore(), FakeTelegram()
    run = store.begin_run(invocation_key="crash", worker_id="crashed", scheduled_for=NOW)
    store.enqueue_delivery(
        run_id=run["id"],
        rule_id=RULE.id,
        signal_fingerprint="a" * 64,
        logical_delivery_key="b" * 64,
        signal=dict(SIGNAL),
        message_text="message",
        available_at=NOW,
    )
    assert store.claim_delivery(worker_id="crashed") is not None
    summary = worker(store, telegram).drain_deliveries()
    assert summary["abandoned_dead_lettered"] == 1
    assert not telegram.calls


def test_entitlement_and_demo_boundaries_block_external_user_delivery() -> None:
    free_user = NotificationRule(id="free-user", user_id="user-1", telegram_chat_id="chat", entitled_to_pro=False)
    demo_user = NotificationRule(
        id="demo-user", user_id="user-2", telegram_chat_id="chat", entitled_to_pro=True, demo_active=True
    )
    store, telegram = MemoryStore([free_user, demo_user]), FakeTelegram()
    result = worker(store, telegram).run_scan()
    assert result["enqueued"] == 0
    assert not telegram.calls


def test_pool_alert_matches_only_exact_canonical_pool_and_complete_supported_signal() -> None:
    pool_rule = NotificationRule(
        id="pool-rule",
        user_id="user-1",
        telegram_chat_id="chat",
        target_type="pool",
        target_pool_id="pool-1",
        minimum_strength=60,
        entitled_to_pro=True,
    )
    store, telegram = MemoryStore([pool_rule]), FakeTelegram()
    result = worker(store, telegram).run_scan()
    assert result["enqueued"] == 1
    assert store.evaluations[-1][2] == ("pool-rule",)
    assert "FuruFlow pool alert matched" in telegram.calls[0][1]

    other_store, other_telegram = MemoryStore([pool_rule]), FakeTelegram()
    other = {**SIGNAL, "pool_id": "other-pool"}
    assert worker(other_store, other_telegram, scanner=lambda: [other]).run_scan()["enqueued"] == 0
    assert not other_telegram.calls

    incomplete_store, incomplete_telegram = MemoryStore([pool_rule]), FakeTelegram()
    incomplete = {**SIGNAL, "strength_score": None}
    assert worker(incomplete_store, incomplete_telegram, scanner=lambda: [incomplete]).run_scan()["enqueued"] == 0
    assert not incomplete_telegram.calls


def test_paused_pool_alert_never_matches() -> None:
    paused = NotificationRule(
        id="paused",
        user_id="user-1",
        telegram_chat_id="chat",
        enabled=False,
        target_type="pool",
        target_pool_id="pool-1",
        entitled_to_pro=True,
    )
    store, telegram = MemoryStore([paused]), FakeTelegram()
    assert worker(store, telegram).run_scan()["enqueued"] == 0
    assert not telegram.calls


def test_quiet_hours_and_digest_are_durably_deferred() -> None:
    quiet = NotificationRule(
        id="quiet", user_id=None, telegram_chat_id="chat", quiet_hours_start="11:00", quiet_hours_end="13:00"
    )
    digest = NotificationRule(id="digest", user_id=None, telegram_chat_id="chat", delivery_mode="digest")
    automation = worker(MemoryStore([quiet, digest]), FakeTelegram())
    assert automation._available_at(quiet, NOW) > NOW
    assert automation._available_at(digest, NOW) > NOW


def test_test_delivery_request_uses_same_durable_pipeline_even_with_zero_signals() -> None:
    store, telegram = MemoryStore(), FakeTelegram()
    store.tests.append({"id": "test-1", "rule_id": RULE.id})
    result = worker(store, telegram, scanner=lambda: []).run_scan()
    assert result["test_enqueued"] == result["delivered"] == 1
    assert store.deliveries[0]["kind"] == "test"


def test_missing_managed_secrets_fail_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
        TelegramClient()
    with pytest.raises(AutomationStoreError, match="SERVICE_ROLE"):
        SupabaseAutomationStore()
    with pytest.raises(ValueError, match="TELEGRAM_CHAT_ID"):
        AutomationWorker(
            store=MemoryStore(),
            telegram=FakeTelegram(),
            scanner=lambda: [],
            config=WorkerConfig(system_rule_enabled=True, system_chat_id=""),
        )


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls = 0

    def post(self, *args: Any, **kwargs: Any) -> FakeResponse:
        self.calls += 1
        return self.response


def test_transport_has_explicit_test_boundary_and_classifies_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FURUFLOW_DISABLE_EXTERNAL_SIDE_EFFECTS", "false")
    success = FakeSession(FakeResponse(200, {"result": {"message_id": 42, "chat": {"id": "chat"}}}))
    assert TelegramClient(token="managed-token", session=success).send(chat_id="chat", text="safe").message_id == "42"
    denied = FakeSession(FakeResponse(403, {"ok": False}))
    with pytest.raises(TelegramDeliveryError) as captured:
        TelegramClient(token="managed-token", session=denied).send(chat_id="chat", text="safe")
    assert captured.value.code == "telegram_http_403"
    assert captured.value.retryable is False


def test_new_transport_side_effect_guard_blocks_even_fake_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FURUFLOW_DISABLE_EXTERNAL_SIDE_EFFECTS", "true")
    session = FakeSession(FakeResponse(200, {"result": {"message_id": 42}}))
    with pytest.raises(RuntimeError, match="disabled"):
        TelegramClient(token="managed-token", session=session).send(chat_id="chat", text="safe")
    assert session.calls == 0


def test_user_preference_client_cannot_choose_another_user_id() -> None:
    observed: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return httpx.Response(200, json={"id": "rule", "target_pool_id": "pool-1"})

    client = UserNotificationClient(
        project_url="https://project.supabase.co",
        anon_key="anon",
        access_token="user-token",
        transport=httpx.MockTransport(handler),
    )
    row = client.create_rule(
        {
            "target_pool_id": "pool-1",
            "client_request_key": "request-key-123",
            "telegram_chat_id": "attacker-chat",
            "user_id": "attacker-selected-user",
        }
    )
    assert row["target_pool_id"] == "pool-1"
    assert b"attacker-selected-user" not in observed[0].content
    assert b"attacker-chat" not in observed[0].content


def test_trusted_link_command_uses_managed_environment_and_never_prints_routing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[dict[str, Any]] = []

    class FakeOperatorStore:
        def set_user_telegram_connection(self, **values: Any) -> str:
            calls.append(values)
            return "connection-id"

    monkeypatch.setattr(telegram_worker, "SupabaseAutomationStore", FakeOperatorStore)
    monkeypatch.setenv("FURUFLOW_LINK_USER_ID", "user-1")
    monkeypatch.setenv("FURUFLOW_LINK_TELEGRAM_CHAT_ID", "sensitive-chat")
    monkeypatch.setattr("sys.argv", ["telegram_worker.py", "link-user"])

    assert telegram_worker.main() == 0
    assert calls == [{"user_id": "user-1", "chat_id": "sensitive-chat", "linked": True}]
    output = capsys.readouterr().out
    assert output.strip() == '{"outcome": "linked"}'
    assert "user-1" not in output
    assert "sensitive-chat" not in output


def test_migration_enforces_rls_transactions_attempt_limit_and_retention() -> None:
    sql = (
        Path(__file__).parents[1] / "supabase/migrations/202608150001_prompt5_telegram_automation.sql"
    ).read_text(encoding="utf-8").lower()
    for table in (
        "automation_runs",
        "automation_heartbeats",
        "notification_rules",
        "signal_snapshots",
        "notification_deliveries",
        "notification_delivery_attempts",
        "notification_test_requests",
    ):
        assert f"alter table public.{table} enable row level security" in sql
    assert "logical_delivery_key text not null unique" in sql
    assert "attempt_count between 0 and 3" in sql
    assert "for update of d skip locked" in sql
    assert "on conflict(logical_delivery_key) do nothing" in sql
    assert "ambiguous_delivery_outcome" in sql
    assert "cleanup_automation_history" in sql
    assert "grant execute on function public.request_notification_test(uuid) to authenticated" in sql
    assert "grant all on table public.automation_runs" not in sql.split("to authenticated")[-1]
