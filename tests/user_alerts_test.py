from __future__ import annotations

from user_alerts import (
    UserAlert,
    alert_creation_prerequisites_met,
    alert_explanation,
    deterministic_pool_options,
    format_alert_time,
    pool_label_mapping,
    safe_pool_label,
)

from product_capabilities import ProductTier, can_use_alerts, capabilities_for_tier


def test_user_alert_from_rpc_row_preserves_persistent_controls() -> None:
    alert = UserAlert.from_row(
        {
            "id": "alert-1",
            "target_pool_id": "pool-1",
            "enabled": True,
            "minimum_strength": 72,
            "signal_tier": "free",
            "delivery_mode": "digest",
            "quiet_hours_start": "22:00:00",
            "quiet_hours_end": "07:00:00",
            "timezone": "America/New_York",
            "cooldown_minutes": 10080,
            "last_evaluated_at": "2026-08-16T12:00:00Z",
            "last_triggered_at": "2026-08-16T12:01:00Z",
            "last_delivery_state": "delivered",
        }
    )

    assert alert.target_pool_id == "pool-1"
    assert alert.enabled
    assert alert.minimum_strength == 72
    assert alert.delivery_mode == "digest"
    assert alert.timezone_name == "America/New_York"
    assert alert.cooldown_minutes == 10080
    assert alert.last_delivery_state == "delivered"


def test_alert_explanation_is_specific_to_tier_strength_and_existing_signal_pipeline() -> None:
    alert = UserAlert(
        id="alert-1",
        target_pool_id="pool-1",
        enabled=True,
        minimum_strength=65,
        signal_tier="pro",
        delivery_mode="immediate",
        quiet_hours_start=None,
        quiet_hours_end=None,
        timezone_name="UTC",
        cooldown_minutes=1440,
    )

    assert alert_explanation(alert) == (
        "Notify me when this pool qualifies as a Pro-tier FuruFlow signal "
        "with signal strength of at least 65/100."
    )


def test_pool_labels_use_canonical_ids_and_fail_safe_when_market_data_is_missing() -> None:
    labels = pool_label_mapping(
        [{"pool": "pool-1", "project": "Aave", "symbol": "USDC", "chain": "Ethereum"}]
    )

    assert labels == {"pool-1": "Aave · USDC · Ethereum"}
    assert safe_pool_label("pool-1", labels) == "Aave · USDC · Ethereum"
    assert safe_pool_label("unavailable-canonical-pool", labels) == "Pool unavailable-…"


def test_duplicate_pool_labels_use_strategy_without_changing_canonical_keys() -> None:
    general_id = "aa70268e-4b52-42bf-a116-608b370f9501"
    prime_id = "effcb4a4-4dcb-45e5-935d-f15542c13e6b"
    labels = pool_label_mapping(
        [
            {
                "pool": general_id,
                "project": "aave-v3",
                "symbol": "USDC",
                "chain": "Ethereum",
                "strategy_type": "General",
            },
            {
                "pool": prime_id,
                "project": "aave-v3",
                "symbol": "USDC",
                "chain": "Ethereum",
                "strategy_type": "Prime Instance",
            },
        ]
    )

    assert labels == {
        general_id: "aave-v3 · USDC · Ethereum · General",
        prime_id: "aave-v3 · USDC · Ethereum · Prime Instance",
    }
    assert len(set(labels.values())) == 2


def test_duplicate_pool_labels_fall_back_to_canonical_id_only_when_metadata_still_collides() -> None:
    labels = pool_label_mapping(
        [
            {
                "pool": "pool-a",
                "project": "aave-v3",
                "symbol": "USDC",
                "chain": "Ethereum",
                "strategy_type": "General",
            },
            {
                "pool": "pool-b",
                "project": "aave-v3",
                "symbol": "USDC",
                "chain": "Ethereum",
                "strategy_type": "General",
            },
        ]
    )

    assert labels == {
        "pool-a": "aave-v3 · USDC · Ethereum · General · pool-a",
        "pool-b": "aave-v3 · USDC · Ethereum · General · pool-b",
    }
    assert len(set(labels.values())) == 2


def test_alert_pool_options_are_meaningful_and_deterministic() -> None:
    labels = {
        "pool-z": "Morpho · USDC · Base",
        "pool-b": "Aave · USDT · Ethereum",
        "pool-a": "Aave · USDT · Ethereum",
    }

    assert deterministic_pool_options(labels) == ("pool-a", "pool-b", "pool-z")


def test_alert_creation_requires_entitlement_and_explicitly_available_telegram() -> None:
    expected_by_tier = {
        ProductTier.FREE: False,
        ProductTier.CORE: False,
        ProductTier.PLUS: True,
        ProductTier.PRO: True,
    }

    for tier, entitled in expected_by_tier.items():
        assert can_use_alerts(capabilities_for_tier(tier)) is entitled
        assert (
            alert_creation_prerequisites_met(
                alerts_entitled=entitled,
                telegram_status={"available": True, "status": "linked"},
            )
            is entitled
        )
        assert not alert_creation_prerequisites_met(
            alerts_entitled=entitled,
            telegram_status={"available": False, "status": "not_linked"},
        )


def test_alert_creation_fails_closed_for_missing_or_malformed_availability() -> None:
    for status in ({}, {"available": None}, {"available": "true"}, {"available": 1}):
        assert not alert_creation_prerequisites_met(
            alerts_entitled=True,
            telegram_status=status,
        )


def test_alert_timestamps_are_utc_and_malformed_values_do_not_leak() -> None:
    assert format_alert_time("2026-08-16T08:30:00-04:00") == "2026-08-16 12:30 UTC"
    assert format_alert_time(None) == "Not yet"
    assert format_alert_time("not-a-timestamp") == "Unavailable"
