from __future__ import annotations

from product_capabilities import (
    PLANNED_TIERS,
    ProductTier,
    can_export_csv,
    can_use_alerts,
    can_use_pro_tools,
    can_use_research_modeling,
    can_use_watchlists,
    capabilities_for_tier,
    capabilities_from_current_entitlement,
    required_tier_name,
)


def test_current_free_and_pro_map_to_capabilities_without_inventing_billing_state() -> None:
    free = capabilities_from_current_entitlement(is_pro=False)
    pro = capabilities_from_current_entitlement(is_pro=True)

    assert free.tier is ProductTier.FREE
    assert not can_use_watchlists(free)
    assert not can_use_alerts(free)
    assert not can_use_research_modeling(free)
    assert not can_use_pro_tools(free)
    assert pro.tier is ProductTier.PRO
    assert can_use_watchlists(pro)
    assert can_use_alerts(pro)
    assert can_use_research_modeling(pro)
    assert can_use_pro_tools(pro)
    assert can_export_csv(pro)


def test_future_capability_ladder_is_additive_and_centralized() -> None:
    free = capabilities_for_tier("free")
    core = capabilities_for_tier("core")
    plus = capabilities_for_tier("plus")
    pro = capabilities_for_tier("pro")

    assert free.enabled < core.enabled < plus.enabled < pro.enabled
    assert can_use_watchlists(core)
    assert not can_use_alerts(core)
    assert can_use_alerts(plus)
    assert can_use_research_modeling(plus)
    assert not can_use_pro_tools(plus)
    assert required_tier_name(next(iter(core.enabled - free.enabled))) == "Core"


def test_csv_export_is_exclusively_the_future_top_tier_capability() -> None:
    matrix = {tier: can_export_csv(capabilities_for_tier(tier)) for tier in ProductTier}

    assert matrix == {
        ProductTier.FREE: False,
        ProductTier.CORE: False,
        ProductTier.PLUS: False,
        ProductTier.PRO: True,
    }
    assert can_export_csv(capabilities_from_current_entitlement(is_pro=True))


def test_planned_prices_are_presentation_metadata_not_checkout_identifiers() -> None:
    assert [(tier.name, tier.monthly_price) for tier in PLANNED_TIERS] == [
        ("Free", "$0"),
        ("Core", "$9.99/month"),
        ("Plus", "$14.99/month"),
        ("Pro", "$24.99/month"),
    ]
    assert all("price_" not in tier.monthly_price for tier in PLANNED_TIERS)
