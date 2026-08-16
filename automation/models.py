from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ScanOutcome(str, Enum):
    SUCCEEDED = "succeeded"
    ZERO_SIGNALS = "zero_signals"
    PROVIDER_FAILED = "provider_failed"
    INFRASTRUCTURE_FAILED = "infrastructure_failed"


class DeliveryDisposition(str, Enum):
    DELIVERED = "delivered"
    RETRY = "retry"
    DEAD_LETTER = "dead_letter"


@dataclass(frozen=True)
class TelegramReceipt:
    message_id: str
    provider_chat_id: str | None = None


class TelegramDeliveryError(RuntimeError):
    """A redacted Telegram failure with safe retry semantics."""

    def __init__(
        self,
        code: str,
        *,
        retryable: bool,
        ambiguous: bool = False,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code[:64]
        self.retryable = retryable
        self.ambiguous = ambiguous
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True)
class NotificationRule:
    id: str
    user_id: str | None
    telegram_chat_id: str
    enabled: bool = True
    minimum_strength: int = 0
    signal_tier: str = "all"
    delivery_mode: str = "immediate"
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None
    timezone_name: str = "UTC"
    cooldown_minutes: int = 1440
    entitled_to_pro: bool = False
    demo_active: bool = False
    rule_kind: str = "market"
    target_type: str = "any_signal"
    target_pool_id: str | None = None
    condition_type: str = "signal_qualified"

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "NotificationRule":
        return cls(
            id=str(row["id"]),
            user_id=str(row["user_id"]) if row.get("user_id") else None,
            telegram_chat_id=str(row.get("telegram_chat_id") or ""),
            enabled=bool(row.get("enabled", True)),
            minimum_strength=int(row.get("minimum_strength") or 0),
            signal_tier=str(row.get("signal_tier") or "all").lower(),
            delivery_mode=str(row.get("delivery_mode") or "immediate").lower(),
            quiet_hours_start=row.get("quiet_hours_start"),
            quiet_hours_end=row.get("quiet_hours_end"),
            timezone_name=str(row.get("timezone") or "UTC"),
            cooldown_minutes=max(int(row.get("cooldown_minutes") or 1440), 1),
            entitled_to_pro=bool(row.get("entitled_to_pro")),
            demo_active=bool(row.get("demo_active")),
            rule_kind=str(row.get("rule_kind") or "market"),
            target_type=str(row.get("target_type") or "any_signal"),
            target_pool_id=str(row["target_pool_id"]) if row.get("target_pool_id") else None,
            condition_type=str(row.get("condition_type") or "signal_qualified"),
        )


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
