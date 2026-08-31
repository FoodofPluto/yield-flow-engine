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


def _meaningful_pool_detail(value: Any) -> str:
    detail = str(value or "").strip()
    return "" if detail.casefold() in {"", "nan", "none", "unknown"} else detail


def pool_label_mapping(rows: list[Mapping[str, Any]]) -> dict[str, str]:
    pool_details: dict[str, tuple[str, str, str]] = {}
    for row in rows:
        pool_id = str(row.get("pool") or "").strip()
        if not pool_id:
            continue
        project = str(row.get("project") or "Unknown protocol")
        symbol = str(row.get("symbol") or "Unknown assets")
        chain = str(row.get("chain") or "Unknown chain")
        base_label = f"{project} · {symbol} · {chain}"
        strategy = _meaningful_pool_detail(row.get("strategy_type") or row.get("poolMeta"))
        exposure = _meaningful_pool_detail(row.get("exposure"))
        pool_details[pool_id] = (base_label, strategy, exposure)

    base_counts: dict[str, int] = {}
    for base_label, _strategy, _exposure in pool_details.values():
        base_counts[base_label] = base_counts.get(base_label, 0) + 1

    labels: dict[str, str] = {}
    for pool_id, (base_label, strategy, _exposure) in pool_details.items():
        labels[pool_id] = (
            base_label
            if base_counts[base_label] == 1
            else f"{base_label} · {strategy or 'Strategy unavailable'}"
        )

    label_counts: dict[str, int] = {}
    for label in labels.values():
        label_counts[label] = label_counts.get(label, 0) + 1
    for pool_id, label in tuple(labels.items()):
        if label_counts[label] > 1:
            exposure = pool_details[pool_id][2]
            labels[pool_id] = f"{label} · {exposure}" if exposure else label

    label_counts.clear()
    for label in labels.values():
        label_counts[label] = label_counts.get(label, 0) + 1
    for pool_id, label in tuple(labels.items()):
        if label_counts[label] > 1:
            labels[pool_id] = f"{label} · {pool_id}"
    return labels


def deterministic_pool_options(pool_labels: Mapping[str, str]) -> tuple[str, ...]:
    """Order alert targets by meaningful label with canonical ID tie-breaking."""

    return tuple(
        sorted(
            (str(pool_id) for pool_id in pool_labels),
            key=lambda pool_id: (str(pool_labels[pool_id]).casefold(), pool_id.casefold()),
        )
    )


def alert_creation_prerequisites_met(
    *, alerts_entitled: bool, telegram_status: Mapping[str, Any]
) -> bool:
    """Require both trusted product access and an explicitly usable destination."""

    return alerts_entitled and telegram_status.get("available") is True


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
