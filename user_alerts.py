from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from automation.store import AutomationStoreError, UserNotificationClient
from auth_session import get_auth_session_store
from supabase_client import load_auth_config


SUPPORTED_ALERT_CONDITION = "signal_qualified"


@dataclass(frozen=True)
class UserAlert:
    id: str
    target_pool_id: str
    enabled: bool
    minimum_strength: int
    signal_tier: str
    delivery_mode: str
    quiet_hours_start: str | None
    quiet_hours_end: str | None
    timezone_name: str
    cooldown_minutes: int
    condition_type: str = SUPPORTED_ALERT_CONDITION
    last_evaluated_at: str | None = None
    last_triggered_at: str | None = None
    last_delivery_state: str | None = None
    last_delivered_at: str | None = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "UserAlert":
        return cls(
            id=str(row["id"]),
            target_pool_id=str(row["target_pool_id"]),
            enabled=bool(row.get("enabled")),
            minimum_strength=int(row.get("minimum_strength") or 0),
            signal_tier=str(row.get("signal_tier") or "all"),
            delivery_mode=str(row.get("delivery_mode") or "immediate"),
            quiet_hours_start=row.get("quiet_hours_start"),
            quiet_hours_end=row.get("quiet_hours_end"),
            timezone_name=str(row.get("timezone") or "UTC"),
            cooldown_minutes=int(row.get("cooldown_minutes") or 1440),
            condition_type=str(row.get("condition_type") or SUPPORTED_ALERT_CONDITION),
            last_evaluated_at=row.get("last_evaluated_at"),
            last_triggered_at=row.get("last_triggered_at"),
            last_delivery_state=row.get("last_delivery_state"),
            last_delivered_at=row.get("last_delivered_at"),
        )


def alert_explanation(alert: UserAlert) -> str:
    tier = {
        "all": "an eligible FuruFlow signal",
        "free": "a Free-tier FuruFlow signal",
        "pro": "a Pro-tier FuruFlow signal",
    }.get(alert.signal_tier, "an eligible FuruFlow signal")
    return (
        f"Notify me when this pool qualifies as {tier} with signal strength "
        f"of at least {alert.minimum_strength}/100."
    )


def safe_pool_label(pool_id: str, pool_labels: Mapping[str, str]) -> str:
    return pool_labels.get(pool_id) or f"Pool {pool_id[:12]}…"


def pool_label_mapping(rows: list[Mapping[str, Any]]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for row in rows:
        pool_id = str(row.get("pool") or "").strip()
        if not pool_id:
            continue
        project = str(row.get("project") or "Unknown protocol")
        symbol = str(row.get("symbol") or "Unknown assets")
        chain = str(row.get("chain") or "Unknown chain")
        labels[pool_id] = f"{project} · {symbol} · {chain}"
    return labels


def deterministic_pool_options(pool_labels: Mapping[str, str]) -> tuple[str, ...]:
    """Order alert targets by meaningful label with canonical ID tie-breaking."""

    return tuple(
        sorted(
            (str(pool_id) for pool_id in pool_labels),
            key=lambda pool_id: (str(pool_labels[pool_id]).casefold(), pool_id.casefold()),
        )
    )


def format_alert_time(value: str | None) -> str:
    if not value:
        return "Not yet"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return "Unavailable"
    return parsed.strftime("%Y-%m-%d %H:%M UTC")


def current_user_notification_client() -> UserNotificationClient:
    config = load_auth_config()
    tokens = get_auth_session_store().load()
    if not tokens:
        raise AutomationStoreError("Authenticated notification controls are unavailable for this session.")
    return UserNotificationClient(
        project_url=config.project_url,
        anon_key=config.anon_key,
        access_token=tokens.access_token,
    )
