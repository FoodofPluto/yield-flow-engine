"""Central product capabilities for the future four-tier FuruFlow ladder.

Prompt 12 deliberately does not change billing or persisted entitlements.  The
trusted production account model still resolves to Free or Pro; this adapter
maps that result onto feature capabilities that later billing work can target.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ProductTier(str, Enum):
    FREE = "free"
    CORE = "core"
    PLUS = "plus"
    PRO = "pro"


class Capability(str, Enum):
    BROWSE_POOLS = "browse_pools"
    BASIC_SIGNALS = "basic_signals"
    WATCHLISTS = "watchlists"
    ALERTS = "alerts"
    RESEARCH_MODELING = "research_modeling"
    PRO_TOOLS = "pro_tools"
    FULL_SIGNALS = "full_signals"
    ADVANCED_SORTING = "advanced_sorting"
    DATA_EXPORT = "data_export"


@dataclass(frozen=True)
class TierDefinition:
    tier: ProductTier
    name: str
    monthly_price: str
    purpose: str
    features: tuple[str, ...]


@dataclass(frozen=True)
class ProductCapabilities:
    tier: ProductTier
    enabled: frozenset[Capability]

    def allows(self, capability: Capability) -> bool:
        return capability in self.enabled


FREE_CAPABILITIES = frozenset({Capability.BROWSE_POOLS, Capability.BASIC_SIGNALS})
CORE_CAPABILITIES = FREE_CAPABILITIES | {Capability.WATCHLISTS}
PLUS_CAPABILITIES = CORE_CAPABILITIES | {Capability.ALERTS, Capability.RESEARCH_MODELING}
PRO_CAPABILITIES = PLUS_CAPABILITIES | {
    Capability.PRO_TOOLS,
    Capability.FULL_SIGNALS,
    Capability.ADVANCED_SORTING,
    Capability.DATA_EXPORT,
}

CAPABILITIES_BY_TIER = {
    ProductTier.FREE: FREE_CAPABILITIES,
    ProductTier.CORE: CORE_CAPABILITIES,
    ProductTier.PLUS: PLUS_CAPABILITIES,
    ProductTier.PRO: PRO_CAPABILITIES,
}

MINIMUM_TIER_BY_CAPABILITY = {
    Capability.BROWSE_POOLS: ProductTier.FREE,
    Capability.BASIC_SIGNALS: ProductTier.FREE,
    Capability.WATCHLISTS: ProductTier.CORE,
    Capability.ALERTS: ProductTier.PLUS,
    Capability.RESEARCH_MODELING: ProductTier.PLUS,
    Capability.PRO_TOOLS: ProductTier.PRO,
    Capability.FULL_SIGNALS: ProductTier.PRO,
    Capability.ADVANCED_SORTING: ProductTier.PRO,
    Capability.DATA_EXPORT: ProductTier.PRO,
}

PLANNED_TIERS = (
    TierDefinition(
        ProductTier.FREE,
        "Free",
        "$0",
        "Find viable pools",
        ("Home and Discover", "Curated Opportunities and All Pools", "Pool Detail and basic signals"),
    ),
    TierDefinition(
        ProductTier.CORE,
        "Core",
        "$9.99/month",
        "Organize opportunities",
        ("Everything in Free", "Durable Watchlists"),
    ),
    TierDefinition(
        ProductTier.PLUS,
        "Plus",
        "$14.99/month",
        "Monitor and compare",
        ("Everything in Core", "Alerts", "Research comparison and modeling"),
    ),
    TierDefinition(
        ProductTier.PRO,
        "Pro",
        "$24.99/month",
        "Optimize the workflow",
        ("Everything in Plus", "Strategy Builder", "Yield Spreads", "Advanced workflow actions"),
    ),
)


def capabilities_for_tier(tier: ProductTier | str) -> ProductCapabilities:
    resolved = tier if isinstance(tier, ProductTier) else ProductTier(str(tier).strip().lower())
    return ProductCapabilities(resolved, frozenset(CAPABILITIES_BY_TIER[resolved]))


def capabilities_from_current_entitlement(*, is_pro: bool) -> ProductCapabilities:
    """Map today's trusted Free/Pro result without claiming future billing tiers.

    Current Free -> future Free capabilities.
    Current Pro  -> all Prompt 12 capabilities.
    """

    return capabilities_for_tier(ProductTier.PRO if is_pro else ProductTier.FREE)


def can_use_watchlists(capabilities: ProductCapabilities) -> bool:
    return capabilities.allows(Capability.WATCHLISTS)


def can_use_alerts(capabilities: ProductCapabilities) -> bool:
    return capabilities.allows(Capability.ALERTS)


def can_use_research_modeling(capabilities: ProductCapabilities) -> bool:
    return capabilities.allows(Capability.RESEARCH_MODELING)


def can_use_pro_tools(capabilities: ProductCapabilities) -> bool:
    return capabilities.allows(Capability.PRO_TOOLS)


def can_use_full_signals(capabilities: ProductCapabilities) -> bool:
    return capabilities.allows(Capability.FULL_SIGNALS)


def can_use_advanced_sorting(capabilities: ProductCapabilities) -> bool:
    return capabilities.allows(Capability.ADVANCED_SORTING)


def can_export_data(capabilities: ProductCapabilities) -> bool:
    return capabilities.allows(Capability.DATA_EXPORT)


def required_tier_name(capability: Capability) -> str:
    return MINIMUM_TIER_BY_CAPABILITY[capability].value.title()
