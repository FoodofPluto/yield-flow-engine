from __future__ import annotations

import hashlib
import logging
import os
import socket
import uuid
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Any, Callable, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from automation.models import NotificationRule, ScanOutcome, TelegramDeliveryError, TelegramReceipt, utc_now
from signal_formatter import format_signal

logger = logging.getLogger(__name__)


class AutomationStore(Protocol):
    def begin_run(self, *, invocation_key: str, worker_id: str, scheduled_for: datetime) -> dict[str, Any]: ...
    def heartbeat(self, *, run_id: str | None, worker_id: str, state: str) -> None: ...
    def finish_scan(
        self, *, run_id: str, outcome: ScanOutcome, signal_count: int, error_code: str | None = None
    ) -> None: ...
    def list_rules(self, *, environment: str) -> list[NotificationRule]: ...
    def upsert_system_rule(self, *, chat_id: str, enabled: bool) -> None: ...
    def record_rule_evaluations(
        self, *, run_id: str, evaluated_rule_ids: list[str], triggered_rule_ids: list[str]
    ) -> None: ...
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
    ) -> bool: ...
    def recover_abandoned(self, *, stale_seconds: int) -> int: ...
    def claim_test_request(self, *, worker_id: str) -> dict[str, Any] | None: ...
    def finish_test_request(self, *, request_id: str, succeeded: bool, error_code: str | None = None) -> None: ...
    def claim_delivery(self, *, worker_id: str) -> dict[str, Any] | None: ...
    def finish_delivery(
        self,
        *,
        delivery_id: str,
        worker_id: str,
        receipt: TelegramReceipt | None = None,
        error: TelegramDeliveryError | None = None,
        retry_at: datetime | None = None,
    ) -> str: ...


class TelegramTransport(Protocol):
    def send(self, *, chat_id: str, text: str) -> TelegramReceipt: ...


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class WorkerConfig:
    enabled: bool = True
    environment: str = "development"
    schedule_minutes: int = 15
    max_delivery_attempts: int = 3
    retry_backoff_seconds: tuple[int, int] = (60, 300)
    abandoned_after_seconds: int = 300
    health_stale_after_seconds: int = 1200
    maximum_deliveries_per_run: int = 100
    system_rule_enabled: bool = False
    system_chat_id: str = ""

    @classmethod
    def from_env(cls) -> "WorkerConfig":
        attempts = int(os.getenv("FURUFLOW_TELEGRAM_MAX_ATTEMPTS", "3"))
        if attempts != 3:
            raise ValueError("FURUFLOW_TELEGRAM_MAX_ATTEMPTS must be exactly 3")
        return cls(
            enabled=_truthy(os.getenv("FURUFLOW_AUTOMATION_ENABLED", "true")),
            environment=(os.getenv("ENVIRONMENT") or "development").strip().lower(),
            schedule_minutes=max(int(os.getenv("FURUFLOW_AUTOMATION_SCHEDULE_MINUTES", "15")), 1),
            max_delivery_attempts=attempts,
            retry_backoff_seconds=(
                max(int(os.getenv("FURUFLOW_TELEGRAM_RETRY_1_SECONDS", "60")), 1),
                max(int(os.getenv("FURUFLOW_TELEGRAM_RETRY_2_SECONDS", "300")), 1),
            ),
            abandoned_after_seconds=max(int(os.getenv("FURUFLOW_AUTOMATION_STALE_CLAIM_SECONDS", "300")), 60),
            health_stale_after_seconds=max(
                int(os.getenv("FURUFLOW_AUTOMATION_HEALTH_STALE_SECONDS", "1200")), 60
            ),
            maximum_deliveries_per_run=max(int(os.getenv("FURUFLOW_AUTOMATION_MAX_DELIVERIES", "100")), 1),
            system_rule_enabled=_truthy(os.getenv("FURUFLOW_SYSTEM_TELEGRAM_RULE_ENABLED")),
            system_chat_id=(os.getenv("TELEGRAM_CHAT_ID") or "").strip(),
        )


class AutomationWorker:
    def __init__(
        self,
        *,
        store: AutomationStore,
        telegram: TelegramTransport,
        scanner: Callable[[], list[dict[str, Any]]],
        config: WorkerConfig | None = None,
        worker_id: str | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.store = store
        self.telegram = telegram
        self.scanner = scanner
        self.config = config or WorkerConfig.from_env()
        self.worker_id = worker_id or f"{socket.gethostname()}-{uuid.uuid4().hex[:12]}"
        self.clock = clock
        if self.config.system_rule_enabled and not self.config.system_chat_id:
            raise ValueError("TELEGRAM_CHAT_ID is required when FURUFLOW_SYSTEM_TELEGRAM_RULE_ENABLED=true")

    def _scheduled_time(self, value: datetime | None = None) -> datetime:
        current = (value or self.clock()).astimezone(timezone.utc)
        minute = current.minute - (current.minute % self.config.schedule_minutes)
        return current.replace(minute=minute, second=0, microsecond=0)

    def _invocation_key(self, scheduled_for: datetime) -> str:
        return f"scan:{self.config.environment}:{scheduled_for.isoformat()}"

    @staticmethod
    def _signal_fingerprint(signal: dict[str, Any]) -> str:
        identity = str(signal.get("pool_id") or "").strip().lower()
        if not identity:
            identity = "|".join(
                str(signal.get(key) or "").strip().lower() for key in ("name", "chain", "category")
            )
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    @staticmethod
    def _rule_matches(rule: NotificationRule, signal: dict[str, Any]) -> bool:
        if not rule.enabled or not rule.telegram_chat_id or rule.demo_active:
            return False
        if rule.condition_type != "signal_qualified":
            return False
        if rule.target_type == "pool":
            signal_pool_id = str(signal.get("pool_id") or "").strip()
            if not rule.target_pool_id or not signal_pool_id or signal_pool_id != rule.target_pool_id:
                return False
        elif rule.target_type != "any_signal":
            return False
        if signal.get("strength_score") is None or not str(signal.get("tier") or "").strip():
            return False
        try:
            strength = int(float(signal["strength_score"]))
        except (TypeError, ValueError):
            return False
        if strength < rule.minimum_strength:
            return False
        tier = str(signal.get("tier") or "free").strip().lower()
        if tier == "pro" and rule.user_id is not None and not rule.entitled_to_pro:
            return False
        return rule.signal_tier == "all" or rule.signal_tier == tier

    @staticmethod
    def _parse_local_time(value: str | None) -> time | None:
        if not value:
            return None
        try:
            return time.fromisoformat(value)
        except ValueError:
            return None

    def _available_at(self, rule: NotificationRule, now: datetime) -> datetime:
        try:
            zone: ZoneInfo | timezone = ZoneInfo(rule.timezone_name)
        except ZoneInfoNotFoundError:
            zone = timezone.utc
        local_now = now.astimezone(zone)
        start = self._parse_local_time(rule.quiet_hours_start)
        end = self._parse_local_time(rule.quiet_hours_end)
        if rule.delivery_mode == "digest":
            digest = datetime.combine(local_now.date(), time(9, 0), zone)
            if digest <= local_now:
                digest += timedelta(days=1)
            return digest.astimezone(timezone.utc)
        if start is None or end is None or start == end:
            return now
        local_time = local_now.timetz().replace(tzinfo=None)
        in_quiet_hours = start <= local_time < end if start < end else local_time >= start or local_time < end
        if not in_quiet_hours:
            return now
        end_date = local_now.date()
        if start > end and local_time >= start:
            end_date += timedelta(days=1)
        return datetime.combine(end_date, end, zone).astimezone(timezone.utc)

    @staticmethod
    def _delivery_key(rule: NotificationRule, signal_fingerprint: str, scheduled_for: datetime) -> str:
        window_seconds = max(rule.cooldown_minutes, 1) * 60
        window = int(scheduled_for.timestamp()) // window_seconds
        raw = f"{rule.id}|{signal_fingerprint}|{window}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def run_scan(self, *, scheduled_for: datetime | None = None, invocation_key: str | None = None) -> dict[str, Any]:
        schedule_time = self._scheduled_time(scheduled_for)
        claim = self.store.begin_run(
            invocation_key=invocation_key or self._invocation_key(schedule_time),
            worker_id=self.worker_id,
            scheduled_for=schedule_time,
        )
        run_id = str(claim["id"])
        if not bool(claim.get("claimed")):
            return {"run_id": run_id, "claimed": False, "outcome": "duplicate_invocation"}

        self.store.heartbeat(run_id=run_id, worker_id=self.worker_id, state="scanning")
        try:
            test_enqueued = self._enqueue_test_requests(run_id=run_id)
        except Exception:
            logger.exception("automation_event=test_enqueue outcome=infrastructure_failed")
            self.store.finish_scan(
                run_id=run_id,
                outcome=ScanOutcome.INFRASTRUCTURE_FAILED,
                signal_count=0,
                error_code="test_request_persistence_failed",
            )
            self.store.heartbeat(run_id=None, worker_id=self.worker_id, state="degraded")
            return {"run_id": run_id, "claimed": True, "outcome": ScanOutcome.INFRASTRUCTURE_FAILED.value}
        try:
            signals = self.scanner()
        except Exception:
            logger.exception("automation_event=scan outcome=provider_failed")
            self.store.finish_scan(
                run_id=run_id,
                outcome=ScanOutcome.PROVIDER_FAILED,
                signal_count=0,
                error_code="market_provider_unavailable",
            )
            delivery_summary = self.drain_deliveries(run_id=run_id)
            self.store.heartbeat(run_id=None, worker_id=self.worker_id, state="idle")
            return {
                "run_id": run_id,
                "claimed": True,
                "outcome": ScanOutcome.PROVIDER_FAILED.value,
                "test_enqueued": test_enqueued,
                **delivery_summary,
            }

        try:
            if self.config.system_rule_enabled:
                self.store.upsert_system_rule(chat_id=self.config.system_chat_id, enabled=True)
            rules = self.store.list_rules(environment=self.config.environment)
            evaluated_rule_ids = [rule.id for rule in rules]
            if not signals:
                self.store.record_rule_evaluations(
                    run_id=run_id, evaluated_rule_ids=evaluated_rule_ids, triggered_rule_ids=[]
                )
                self.store.finish_scan(run_id=run_id, outcome=ScanOutcome.ZERO_SIGNALS, signal_count=0)
                delivery_summary = self.drain_deliveries(run_id=run_id)
                self.store.heartbeat(run_id=None, worker_id=self.worker_id, state="idle")
                return {
                    "run_id": run_id,
                    "claimed": True,
                    "outcome": ScanOutcome.ZERO_SIGNALS.value,
                    "enqueued": 0,
                    "test_enqueued": test_enqueued,
                    **delivery_summary,
                }
            enqueued = 0
            triggered_rule_ids: set[str] = set()
            now = self.clock().astimezone(timezone.utc)
            for signal in signals:
                fingerprint = self._signal_fingerprint(signal)
                for rule in rules:
                    if not self._rule_matches(rule, signal):
                        continue
                    triggered_rule_ids.add(rule.id)
                    message_text = format_signal(signal)
                    if rule.user_id is not None and rule.target_type == "pool":
                        message_text = (
                            "FuruFlow pool alert matched\n\n"
                            f"Condition: qualified signal with strength at least {rule.minimum_strength}/100.\n\n"
                            f"{message_text}"
                        )
                    if self.store.enqueue_delivery(
                        run_id=run_id,
                        rule_id=rule.id,
                        signal_fingerprint=fingerprint,
                        logical_delivery_key=self._delivery_key(rule, fingerprint, schedule_time),
                        signal=signal,
                        message_text=message_text,
                        available_at=self._available_at(rule, now),
                    ):
                        enqueued += 1
            self.store.record_rule_evaluations(
                run_id=run_id,
                evaluated_rule_ids=evaluated_rule_ids,
                triggered_rule_ids=sorted(triggered_rule_ids),
            )
            self.store.finish_scan(run_id=run_id, outcome=ScanOutcome.SUCCEEDED, signal_count=len(signals))
        except Exception:
            logger.exception("automation_event=scan outcome=infrastructure_failed")
            self.store.finish_scan(
                run_id=run_id,
                outcome=ScanOutcome.INFRASTRUCTURE_FAILED,
                signal_count=len(signals),
                error_code="automation_persistence_failed",
            )
            self.store.heartbeat(run_id=None, worker_id=self.worker_id, state="degraded")
            return {"run_id": run_id, "claimed": True, "outcome": ScanOutcome.INFRASTRUCTURE_FAILED.value}

        delivery_summary = self.drain_deliveries(run_id=run_id)
        self.store.heartbeat(run_id=None, worker_id=self.worker_id, state="idle")
        return {
            "run_id": run_id,
            "claimed": True,
            "outcome": ScanOutcome.SUCCEEDED.value,
            "signals": len(signals),
            "enqueued": enqueued,
            "test_enqueued": test_enqueued,
            **delivery_summary,
        }

    def _enqueue_test_requests(self, *, run_id: str) -> int:
        enqueued = 0
        for _ in range(20):
            request = self.store.claim_test_request(worker_id=self.worker_id)
            if request is None:
                break
            request_id = str(request["id"])
            rule_id = str(request["rule_id"])
            fingerprint = hashlib.sha256(f"test:{request_id}".encode("utf-8")).hexdigest()
            delivery_key = hashlib.sha256(f"test-delivery:{request_id}".encode("utf-8")).hexdigest()
            try:
                inserted = self.store.enqueue_delivery(
                    run_id=run_id,
                    rule_id=rule_id,
                    signal_fingerprint=fingerprint,
                    logical_delivery_key=delivery_key,
                    signal={"kind": "test", "tier": "free", "request_id": request_id},
                    message_text="FuruFlow Telegram test: delivery configuration is working.",
                    available_at=self.clock().astimezone(timezone.utc),
                    kind="test",
                )
            except Exception:
                self.store.finish_test_request(
                    request_id=request_id, succeeded=False, error_code="test_delivery_enqueue_failed"
                )
                raise
            self.store.finish_test_request(request_id=request_id, succeeded=True)
            if inserted:
                enqueued += 1
        return enqueued

    def _retry_time(self, *, attempt_count: int, error: TelegramDeliveryError) -> datetime:
        configured = self.config.retry_backoff_seconds[min(max(attempt_count - 1, 0), 1)]
        seconds = max(configured, error.retry_after_seconds or 0)
        return self.clock().astimezone(timezone.utc) + timedelta(seconds=seconds)

    def drain_deliveries(self, *, run_id: str | None = None) -> dict[str, int]:
        recovered = self.store.recover_abandoned(stale_seconds=self.config.abandoned_after_seconds)
        delivered = retried = dead_lettered = 0
        self.store.heartbeat(run_id=run_id, worker_id=self.worker_id, state="delivering")
        for _ in range(self.config.maximum_deliveries_per_run):
            delivery = self.store.claim_delivery(worker_id=self.worker_id)
            if delivery is None:
                break
            delivery_id = str(delivery["id"])
            attempt_count = int(delivery.get("attempt_count") or 1)
            try:
                receipt = self.telegram.send(
                    chat_id=str(delivery.get("telegram_chat_id") or ""),
                    text=str(delivery.get("message_text") or ""),
                )
            except TelegramDeliveryError as error:
                retryable = error.retryable and not error.ambiguous and attempt_count < self.config.max_delivery_attempts
                disposition = self.store.finish_delivery(
                    delivery_id=delivery_id,
                    worker_id=self.worker_id,
                    error=error,
                    retry_at=self._retry_time(attempt_count=attempt_count, error=error) if retryable else None,
                )
                if disposition == "retry":
                    retried += 1
                else:
                    dead_lettered += 1
            else:
                disposition = self.store.finish_delivery(
                    delivery_id=delivery_id,
                    worker_id=self.worker_id,
                    receipt=receipt,
                )
                if disposition == "delivered":
                    delivered += 1
        return {
            "delivered": delivered,
            "retried": retried,
            "dead_lettered": dead_lettered,
            "abandoned_dead_lettered": recovered,
        }


def default_scanner() -> list[dict[str, Any]]:
    """Reuse the established Prompt 4 scanner/scoring/enrichment pipeline."""

    from post_real_signals import get_real_furuflow_signals

    return get_real_furuflow_signals()
