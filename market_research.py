"""Pure market-research models used by the canonical Streamlit application.

This module deliberately owns no provider calls, Streamlit state, identity, or
entitlement decisions.  It turns normalized pool rows into deterministic
discovery, comparison, provenance, yield, and risk presentation models.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import math
from statistics import median
from typing import Any, Callable, Iterable, Mapping

import pandas as pd


COMPARISON_LIMIT = 4
MARKET_CACHE_SECONDS = 15 * 60
CURRENT_SECONDS = 20 * 60
AGING_SECONDS = 60 * 60

SORT_OPTIONS = (
    "Highest APY",
    "Largest TVL",
    "FuruFlow rank",
    "Lowest risk",
    "Highest 24h volume",
    "Largest signal move",
)

FILTER_QUERY_KEYS = frozenset(
    {"q", "chains", "protocols", "strategies", "signals", "stable", "min_tvl", "max_risk", "min_apy", "sort"}
)
SENSITIVE_QUERY_KEYS = frozenset(
    {
        "access_token",
        "refresh_token",
        "jwt",
        "session_ticket",
        "browser_session_secret",
        "telegram_chat_id",
        "stripe_secret",
        "webhook_secret",
        "database_url",
    }
)
MAX_FILTER_SEARCH_LENGTH = 200
MAX_FILTER_SELECTIONS = 50
MAX_FILTER_TVL = 500_000_000.0
MAX_FILTER_APY = 250.0

# Canonical signal metric labels intentionally distinguish evidence coverage,
# evaluated universe size, and non-steady classifications.
OBSERVED_SIGNAL_EVIDENCE_LABEL = "Observed signal evidence"
POOLS_EVALUATED_LABEL = "Pools evaluated"
NON_STEADY_CLASSIFICATIONS_LABEL = "Non-steady classifications"


@dataclass(frozen=True)
class ComparisonWeights:
    yield_weight: int = 35
    liquidity_weight: int = 25
    risk_weight: int = 25
    signal_weight: int = 15

    def as_dict(self) -> dict[str, int]:
        return {
            "yield": max(0, int(self.yield_weight)),
            "liquidity": max(0, int(self.liquidity_weight)),
            "risk": max(0, int(self.risk_weight)),
            "signal": max(0, int(self.signal_weight)),
        }


# Presets are presentation conveniences, not forecasts or investment profiles.
COMPARISON_SCENARIOS = {
    "Yield Seeking": ComparisonWeights(55, 20, 15, 10),
    "Balanced": ComparisonWeights(35, 25, 25, 15),
    "Conservative": ComparisonWeights(15, 35, 40, 10),
}


@dataclass(frozen=True)
class DiscoveryFilters:
    search: str = ""
    chains: tuple[str, ...] = ()
    protocols: tuple[str, ...] = ()
    strategies: tuple[str, ...] = ()
    signals: tuple[str, ...] = ()
    stablecoin_only: bool = False
    min_tvl: float = 5_000_000.0
    max_risk: int = 70
    min_apy: float = 0.0
    sort_by: str = "Highest APY"


DEFAULT_FILTERS = DiscoveryFilters()


def all_pools_filters(filters: DiscoveryFilters) -> DiscoveryFilters:
    """Apply Discover controls without turning All Pools into Opportunities.

    The opportunity defaults intentionally require material TVL and cap the
    existing risk heuristic.  Those defaults would silently hide legitimate
    provider rows in the broader All Pools workspace, so they become neutral
    there.  Any non-default threshold chosen by the user remains authoritative,
    as do search, classification, stablecoin, and sorting controls.
    """

    return replace(
        filters,
        min_tvl=0.0 if filters.min_tvl == DEFAULT_FILTERS.min_tvl else filters.min_tvl,
        max_risk=100 if filters.max_risk == DEFAULT_FILTERS.max_risk else filters.max_risk,
    )


@dataclass(frozen=True)
class DataStatus:
    source: str
    retrieved_at: datetime | None
    availability: str = "available"
    degraded: bool = False
    detail: str = ""
    cache_seconds: int = MARKET_CACHE_SECONDS


@dataclass(frozen=True)
class CoverageMetric:
    label: str
    available: int
    total: int

    @property
    def percent(self) -> float | None:
        return (self.available / self.total * 100.0) if self.total else None


@dataclass(frozen=True)
class MarketStatusSummary:
    pools: int
    networks: int
    protocols: int
    assets: int
    coverage: tuple[CoverageMetric, ...]


def _utc(value: datetime | str | pd.Timestamp | None) -> datetime | None:
    if value is None or value == "":
        return None
    parsed = pd.Timestamp(value)
    if pd.isna(parsed):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize("UTC")
    return parsed.tz_convert("UTC").to_pydatetime()


def data_status_from_attrs(attrs: Mapping[str, Any]) -> DataStatus:
    status = str(attrs.get("source_status") or "unavailable")
    availability = {
        "live": "available",
        "partial": "partial",
        "sample": "sample",
        "degraded": "unavailable",
        "unavailable": "unavailable",
    }.get(status, "unavailable")
    errors = attrs.get("errors") or []
    detail = "; ".join(str(item) for item in errors if item)
    return DataStatus(
        source=str(attrs.get("source_label") or "Unknown provider"),
        retrieved_at=_utc(attrs.get("retrieved_at")),
        availability=availability,
        degraded=status in {"partial", "sample", "degraded", "unavailable"},
        detail=detail,
        cache_seconds=int(attrs.get("cache_seconds") or MARKET_CACHE_SECONDS),
    )


def freshness(status: DataStatus, *, now: datetime | None = None) -> dict[str, str]:
    """Return centralized, user-facing freshness terminology.

    Current includes the 15-minute market cache plus five minutes of delivery
    tolerance. Aging lasts through one hour. Older observations are stale.
    """

    if status.availability == "unavailable" or status.retrieved_at is None:
        return {"label": "Unavailable", "kind": "error", "age": "No usable observation time"}
    observed = status.retrieved_at
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    seconds = max(0.0, (clock - observed).total_seconds())
    if status.availability == "sample":
        return {"label": "Sample", "kind": "degraded", "age": "Development fixture; not observed market data"}
    if seconds <= CURRENT_SECONDS:
        label, kind = "Current", "success"
    elif seconds <= AGING_SECONDS:
        label, kind = "Aging", "warning"
    else:
        label, kind = "Stale", "stale"
    if seconds < 60:
        age = "Retrieved less than a minute ago"
    elif seconds < 3600:
        age = f"Retrieved {int(seconds // 60)} minutes ago"
    else:
        age = f"Retrieved {int(seconds // 3600)} hours ago"
    return {"label": label, "kind": kind, "age": age}


def parse_filter_query(
    params: Mapping[str, Any],
    *,
    allowed_values: Mapping[str, Iterable[str]] | None = None,
) -> DiscoveryFilters:
    """Decode only the allowlisted, bounded Discover presentation state."""

    def text(name: str) -> str:
        value = params.get(name, "")
        if isinstance(value, list):
            value = value[0] if value else ""
        return str(value or "").strip()[:MAX_FILTER_SEARCH_LENGTH]

    def many(name: str) -> tuple[str, ...]:
        values = {part.strip() for part in text(name).split(",") if part.strip()}
        if allowed_values is not None and name in allowed_values:
            allowed = {str(value) for value in allowed_values[name]}
            values &= allowed
        return tuple(sorted(values))[:MAX_FILTER_SELECTIONS]

    def number(name: str, default: float) -> float:
        try:
            value = float(text(name)) if text(name) else default
            return value if math.isfinite(value) else default
        except ValueError:
            return default

    sort_by = text("sort") or DEFAULT_FILTERS.sort_by
    if sort_by not in SORT_OPTIONS:
        sort_by = DEFAULT_FILTERS.sort_by
    return DiscoveryFilters(
        search=text("q"),
        chains=many("chains"),
        protocols=many("protocols"),
        strategies=many("strategies"),
        signals=many("signals"),
        stablecoin_only=text("stable").lower() in {"1", "true", "yes"},
        min_tvl=max(0.0, min(MAX_FILTER_TVL, number("min_tvl", DEFAULT_FILTERS.min_tvl))),
        max_risk=max(1, min(100, int(number("max_risk", DEFAULT_FILTERS.max_risk)))),
        min_apy=max(0.0, min(MAX_FILTER_APY, number("min_apy", DEFAULT_FILTERS.min_apy))),
        sort_by=sort_by,
    )


def sensitive_query_keys(params: Mapping[str, Any]) -> tuple[str, ...]:
    """Identify known credential/session fields so Discover never persists them."""

    return tuple(key for key in params if str(key).casefold() in SENSITIVE_QUERY_KEYS)


def market_status_summary(frame: pd.DataFrame) -> MarketStatusSummary:
    """Derive current coverage counts without fabricating unavailable values."""

    total = len(frame)

    def count_flag(flag: str, value: str | None = None) -> int:
        if flag in frame:
            return int(frame[flag].fillna(False).astype(bool).sum())
        if value and value in frame:
            return int(frame[value].notna().sum())
        return 0

    def count_text(column: str) -> int:
        if column not in frame:
            return 0
        values = frame[column].fillna("").astype(str).str.strip()
        return int(values.ne("").sum())

    return MarketStatusSummary(
        pools=total,
        networks=int(frame["chain"].dropna().nunique()) if "chain" in frame else 0,
        protocols=int(frame["project"].dropna().nunique()) if "project" in frame else 0,
        assets=int(frame["symbol"].dropna().nunique()) if "symbol" in frame else 0,
        coverage=(
            CoverageMetric("APY", count_flag("apy_available", "apy"), total),
            CoverageMetric("TVL", count_flag("tvl_available", "tvlUsd"), total),
            CoverageMetric("Modeled risk", count_flag("risk_available", "risk_score"), total),
            CoverageMetric(OBSERVED_SIGNAL_EVIDENCE_LABEL, count_flag("signal_available"), total),
            CoverageMetric("External pool links", count_text("pool_url"), total),
        ),
    )


def filter_query(filters: DiscoveryFilters) -> dict[str, str]:
    """Serialize only meaningful non-default discovery state."""

    result: dict[str, str] = {}
    if filters.search:
        result["q"] = filters.search
    for key, values in (
        ("chains", filters.chains),
        ("protocols", filters.protocols),
        ("strategies", filters.strategies),
        ("signals", filters.signals),
    ):
        if values:
            result[key] = ",".join(sorted(values))
    if filters.stablecoin_only:
        result["stable"] = "1"
    if filters.min_tvl != DEFAULT_FILTERS.min_tvl:
        result["min_tvl"] = f"{filters.min_tvl:g}"
    if filters.max_risk != DEFAULT_FILTERS.max_risk:
        result["max_risk"] = str(filters.max_risk)
    if filters.min_apy != DEFAULT_FILTERS.min_apy:
        result["min_apy"] = f"{filters.min_apy:g}"
    if filters.sort_by != DEFAULT_FILTERS.sort_by:
        result["sort"] = filters.sort_by
    return result


def active_filters(filters: DiscoveryFilters) -> tuple[tuple[str, str], ...]:
    active: list[tuple[str, str]] = []
    if filters.search:
        active.append(("search", f'Search: "{filters.search}"'))
    for key, label, values in (
        ("chains", "Chain", filters.chains),
        ("protocols", "Protocol", filters.protocols),
        ("strategies", "Strategy", filters.strategies),
        ("signals", "Signal", filters.signals),
    ):
        active.extend((f"{key}:{value}", f"{label}: {value}") for value in values)
    if filters.stablecoin_only:
        active.append(("stablecoin_only", "Stablecoin pools only"))
    if filters.min_tvl != DEFAULT_FILTERS.min_tvl:
        active.append(("min_tvl", f"Minimum TVL: ${filters.min_tvl:,.0f}"))
    if filters.max_risk != DEFAULT_FILTERS.max_risk:
        active.append(("max_risk", f"Maximum risk: {filters.max_risk}"))
    if filters.min_apy != DEFAULT_FILTERS.min_apy:
        active.append(("min_apy", f"Minimum APY: {filters.min_apy:g}%"))
    if filters.sort_by != DEFAULT_FILTERS.sort_by:
        active.append(("sort_by", f"Sort: {filters.sort_by}"))
    return tuple(active)


def remove_filter(filters: DiscoveryFilters, key: str) -> DiscoveryFilters:
    if ":" in key:
        field, value = key.split(":", 1)
        if field == "chains":
            return replace(filters, chains=tuple(item for item in filters.chains if item != value))
        if field == "protocols":
            return replace(filters, protocols=tuple(item for item in filters.protocols if item != value))
        if field == "strategies":
            return replace(filters, strategies=tuple(item for item in filters.strategies if item != value))
        if field == "signals":
            return replace(filters, signals=tuple(item for item in filters.signals if item != value))
        return filters
    if key == "search":
        return replace(filters, search=DEFAULT_FILTERS.search)
    if key == "stablecoin_only":
        return replace(filters, stablecoin_only=DEFAULT_FILTERS.stablecoin_only)
    if key == "min_tvl":
        return replace(filters, min_tvl=DEFAULT_FILTERS.min_tvl)
    if key == "max_risk":
        return replace(filters, max_risk=DEFAULT_FILTERS.max_risk)
    if key == "min_apy":
        return replace(filters, min_apy=DEFAULT_FILTERS.min_apy)
    if key == "sort_by":
        return replace(filters, sort_by=DEFAULT_FILTERS.sort_by)
    return filters


def apply_discovery_filters(frame: pd.DataFrame, filters: DiscoveryFilters) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    out = frame.copy()
    if filters.search:
        needle = filters.search.casefold()
        searchable = pd.Series(False, index=out.index)
        for column in ("project", "symbol", "chain", "pool", "poolMeta"):
            if column in out:
                searchable |= out[column].fillna("").astype(str).str.casefold().str.contains(needle, regex=False)
        out = out[searchable]
    for column, values in (
        ("chain", filters.chains),
        ("project", filters.protocols),
        ("strategy_type", filters.strategies),
        ("signal", filters.signals),
    ):
        if values:
            out = out[out[column].isin(values)]
    if filters.stablecoin_only:
        out = out[out["stablecoin"].eq(True)]  # noqa: E712

    if filters.min_tvl > 0:
        known = out.get("tvl_available", pd.Series(True, index=out.index)).astype(bool)
        out = out[known & out["tvlUsd"].ge(filters.min_tvl)]
    if filters.min_apy > 0:
        known = out.get("apy_available", pd.Series(True, index=out.index)).astype(bool)
        out = out[known & out["apy"].ge(filters.min_apy)]
    out = out[out["risk_score"].le(filters.max_risk)]
    return sort_pools(out, filters.sort_by)


def sort_pools(frame: pd.DataFrame, sort_by: str) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    rules = {
        "Highest APY": (["apy", "tvlUsd", "pool"], [False, False, True]),
        "Largest TVL": (["tvlUsd", "apy", "pool"], [False, False, True]),
        "Lowest risk": (["risk_score", "apy", "tvlUsd", "pool"], [True, False, False, True]),
        "Highest 24h volume": (["volumeUsd1d", "apy", "pool"], [False, False, True]),
        "Largest signal move": (["apy_delta_7", "tvl_delta_7_pct", "pool"], [False, False, True]),
        "FuruFlow rank": (["rank_score", "apy", "tvlUsd", "pool"], [False, False, False, True]),
    }
    columns, ascending = rules.get(sort_by, rules[DEFAULT_FILTERS.sort_by])
    return frame.sort_values(columns, ascending=ascending, na_position="last", kind="mergesort")


def pool_universe(frame: pd.DataFrame, search: str = "") -> pd.DataFrame:
    """Return the legitimate provider universe in stable identity-first order.

    Unlike Discover filtering, this browser does not impose yield, TVL, risk,
    ranking, or entitlement thresholds. Search is presentation-only and keeps
    canonical provider pool IDs intact.
    """

    if frame.empty:
        return frame.copy()
    out = frame.drop_duplicates(subset=["pool"], keep="first").copy()
    needle = str(search or "").strip().casefold()
    if needle:
        matches = pd.Series(False, index=out.index)
        for column in ("project", "symbol", "chain", "pool", "poolMeta"):
            if column in out:
                matches |= out[column].fillna("").astype(str).str.casefold().str.contains(needle, regex=False)
        out = out[matches]
    return out.sort_values(
        ["project", "chain", "symbol", "pool"],
        ascending=[True, True, True, True],
        key=lambda values: values.fillna("").astype(str).str.casefold(),
        kind="mergesort",
    )


def update_comparison(selected: Iterable[str], pool_id: str, *, selected_state: bool) -> tuple[str, ...]:
    values = list(dict.fromkeys(str(item) for item in selected if item))
    pool_id = str(pool_id)
    if selected_state and pool_id not in values:
        if len(values) >= COMPARISON_LIMIT:
            raise ValueError(f"Compare supports up to {COMPARISON_LIMIT} pools")
        values.append(pool_id)
    if not selected_state:
        values = [item for item in values if item != pool_id]
    return tuple(values)


def comparison_rows(frame: pd.DataFrame, selected: Iterable[str]) -> list[dict[str, Any]]:
    by_pool = {str(row["pool"]): row for _, row in frame.iterrows()}
    rows: list[dict[str, Any]] = []
    for pool_id in selected:
        row = by_pool.get(str(pool_id))
        if row is None:
            continue
        rows.append(
            {
                "pool": str(row["pool"]),
                "Pool / assets": str(row.get("symbol") or "Unknown"),
                "Protocol": str(row.get("project") or "Unknown"),
                "Chain": str(row.get("chain") or "Unknown"),
                "APY": _known(row, "apy", "apy_available"),
                "Base APY": _known(row, "apyBase", "apy_base_available"),
                "Reward APY": _known(row, "apyReward", "apy_reward_available"),
                "TVL (USD)": _known(row, "tvlUsd", "tvl_available"),
                "Risk": str(row.get("risk_band") or "Unknown"),
                "Signal": str(row.get("signal") or "Unavailable"),
                "Signal evidence": "Observed" if bool(row.get("signal_available", False)) else "Insufficient evidence",
                "Evidence coverage": str(row.get("evidence_coverage") or "No evidence"),
                "Confidence": str(row.get("confidence_level") or "Unavailable"),
            }
        )
    return rows


def comparison_analysis(
    frame: pd.DataFrame,
    selected: Iterable[str],
    weights: ComparisonWeights = COMPARISON_SCENARIOS["Balanced"],
) -> dict[str, Any]:
    """Rank selected pools with transparent within-set normalization.

    APY, TVL, existing risk score, and existing signal strength are min-max
    normalized only across selected pools. Lower existing risk is better.
    Equal known values receive a neutral 0.5. Missing dimensions are excluded
    from that pool's weighted denominator and disclosed through coverage.
    """

    selected_ids = list(dict.fromkeys(str(pool_id) for pool_id in selected if pool_id))[:COMPARISON_LIMIT]
    by_pool = {str(row["pool"]): row for _, row in frame.iterrows()}
    candidates = [by_pool[pool_id] for pool_id in selected_ids if pool_id in by_pool]
    dimension_weights = weights.as_dict()
    raw: dict[str, dict[str, float | None]] = {}
    for row in candidates:
        pool_id = str(row["pool"])
        risk_value = row.get("risk_score")
        signal_value = row.get("signal_strength")
        raw[pool_id] = {
            "yield": _known(row, "apy", "apy_available"),
            "liquidity": _known(row, "tvlUsd", "tvl_available"),
            "risk": None if risk_value is None or bool(pd.isna(risk_value)) else -float(risk_value),
            "signal": None if signal_value is None or bool(pd.isna(signal_value)) else float(signal_value),
        }

    normalized: dict[str, dict[str, float | None]] = {pool_id: {} for pool_id in raw}
    for dimension in dimension_weights:
        known = [values[dimension] for values in raw.values() if values[dimension] is not None]
        low = min(known) if known else None
        high = max(known) if known else None
        for pool_id, values in raw.items():
            value = values[dimension]
            if value is None or low is None or high is None:
                normalized[pool_id][dimension] = None
            elif high == low:
                normalized[pool_id][dimension] = 0.5
            else:
                normalized[pool_id][dimension] = (value - low) / (high - low)

    apy_values = [values["yield"] for values in raw.values() if values["yield"] is not None]
    tvl_values = [values["liquidity"] for values in raw.values() if values["liquidity"] is not None]
    median_apy = median(apy_values) if apy_values else None
    median_tvl = median(tvl_values) if tvl_values else None
    metric_ranks = {
        "yield": _metric_ranks(raw, "yield"),
        "liquidity": _metric_ranks(raw, "liquidity"),
        "risk": _metric_ranks(raw, "risk"),
        "signal": _metric_ranks(raw, "signal"),
    }
    rows: list[dict[str, Any]] = []
    total_configured_weight = sum(dimension_weights.values())
    labels = {"yield": "yield", "liquidity": "liquidity", "risk": "lower modeled risk", "signal": "signal momentum"}
    for row in candidates:
        pool_id = str(row["pool"])
        available = {
            dimension: score
            for dimension, score in normalized[pool_id].items()
            if score is not None and dimension_weights[dimension] > 0
        }
        available_weight = sum(dimension_weights[dimension] for dimension in available)
        score = (
            sum(available[dimension] * dimension_weights[dimension] for dimension in available) / available_weight * 100
            if available_weight
            else None
        )
        strongest = max(available, key=lambda dimension: (available[dimension], dimension_weights[dimension], dimension)) if available else None
        weakest = min(available, key=lambda dimension: (available[dimension], -dimension_weights[dimension], dimension)) if available else None
        reason = "No comparable weighted dimensions are available."
        if strongest:
            reason = f"Its strongest selected-set contribution is {labels[strongest]}."
            if weakest and weakest != strongest:
                reason += f" Its clearest tradeoff is {labels[weakest]}."
        apy = raw[pool_id]["yield"]
        tvl = raw[pool_id]["liquidity"]
        rows.append(
            {
                "pool": pool_id,
                "Pool": f"{row.get('project', 'Unknown')} · {row.get('symbol', 'Unknown')} · {row.get('chain', 'Unknown')}",
                "Protocol": str(row.get("project") or "Unknown"),
                "Network": str(row.get("chain") or "Unknown"),
                "APY": apy,
                "APY rank": metric_ranks["yield"].get(pool_id),
                "APY vs median": None if apy is None or median_apy is None else apy - median_apy,
                "TVL (USD)": tvl,
                "TVL rank": metric_ranks["liquidity"].get(pool_id),
                "TVL vs median %": None if tvl is None or not median_tvl else (tvl - median_tvl) / median_tvl * 100,
                "Risk": None if raw[pool_id]["risk"] is None else -raw[pool_id]["risk"],
                "Risk rank": metric_ranks["risk"].get(pool_id),
                "Signal": str(row.get("signal") or "Unavailable"),
                "Signal rank": metric_ranks["signal"].get(pool_id),
                "Evidence coverage": str(row.get("evidence_coverage") or "No evidence"),
                "Confidence": str(row.get("confidence_level") or "Unavailable"),
                "Score": None if score is None else round(score, 2),
                "Coverage %": round(available_weight / total_configured_weight * 100, 1) if total_configured_weight else 0.0,
                "Reason": reason,
                "Normalized": {
                    dimension: None if value is None else round(value * 100, 1)
                    for dimension, value in normalized[pool_id].items()
                },
            }
        )

    ranked = sorted(rows, key=lambda item: (item["Score"] is None, -(item["Score"] or 0), item["pool"]))
    for index, row in enumerate(ranked, start=1):
        row["Overall rank"] = index if row["Score"] is not None else None
    leaders = {
        "highest_yield": _leader(rows, "APY", higher=True),
        "strongest_liquidity": _leader(rows, "TVL (USD)", higher=True),
        "lowest_risk": _leader(rows, "Risk", higher=False),
        "strongest_signal": next((row for row in ranked if row["Signal rank"] == 1), None),
    }
    winner = next((row for row in ranked if row["Score"] is not None), None)
    protocols = sorted({row["Protocol"] for row in rows})
    networks = sorted({row["Network"] for row in rows})
    return {
        "rows": ranked,
        "winner": winner,
        "leaders": {key: value["pool"] if value else None for key, value in leaders.items()},
        "apy_spread": max(apy_values) - min(apy_values) if len(apy_values) >= 2 else None,
        "median_apy": median_apy,
        "median_tvl": median_tvl,
        "protocols": protocols,
        "networks": networks,
        "diversification": (
            f"The selected set spans {len(protocols)} protocol{'s' if len(protocols) != 1 else ''} and "
            f"{len(networks)} network{'s' if len(networks) != 1 else ''}."
        ),
        "weights": dimension_weights,
    }


def _metric_ranks(raw: Mapping[str, Mapping[str, float | None]], dimension: str) -> dict[str, int]:
    known = [(pool_id, values[dimension]) for pool_id, values in raw.items() if values[dimension] is not None]
    ordered = sorted(known, key=lambda item: (-float(item[1]), item[0]))
    return {pool_id: index for index, (pool_id, _) in enumerate(ordered, start=1)}


def _leader(rows: Iterable[Mapping[str, Any]], key: str, *, higher: bool) -> Mapping[str, Any] | None:
    known = [row for row in rows if row.get(key) is not None]
    if not known:
        return None
    return sorted(known, key=lambda row: ((-1 if higher else 1) * float(row[key]), str(row["pool"])))[0]


def strategy_match_explanation(
    row: Mapping[str, Any],
    *,
    stable_only: bool,
    min_apy: float,
    min_tvl: float,
    max_risk: int,
    signal_preference: str,
) -> str:
    constraints = [f"APY {float(row['apy']):.2f}% ≥ {min_apy:.2f}%", f"TVL ${float(row['tvlUsd']):,.0f} ≥ ${min_tvl:,.0f}"]
    constraints.append(f"risk {int(row['risk_score'])} ≤ {max_risk}")
    if stable_only:
        constraints.append("stablecoin-labelled")
    if signal_preference != "Any":
        constraints.append(f"signal is {signal_preference}")
    return "Matched because " + "; ".join(constraints) + ". Review reward dependence, liquidity, and protocol context as tradeoffs."


def _known(row: Mapping[str, Any], value_key: str, available_key: str) -> float | None:
    if available_key in row and not bool(row.get(available_key)):
        return None
    value = row.get(value_key)
    if value is None or bool(pd.isna(value)):
        return None
    return float(value)


def yield_explanation(row: Mapping[str, Any]) -> dict[str, Any]:
    total = _known(row, "apy", "apy_available")
    base = _known(row, "apyBase", "apy_base_available")
    reward = _known(row, "apyReward", "apy_reward_available")
    if total is None:
        mode = "unavailable"
    elif base is None and reward is None:
        mode = "aggregate_only"
    else:
        mode = "decomposed"
    reconciles: bool | None = None
    discrepancy: float | None = None
    if total is not None and base is not None and reward is not None:
        discrepancy = round(total - base - reward, 6)
        reconciles = abs(discrepancy) <= 0.02
    return {
        "mode": mode,
        "total": total,
        "base": base,
        "reward": reward,
        "total_origin": "reported" if total is not None else "unavailable",
        "base_origin": "reported" if base is not None else "unavailable",
        "reward_origin": "reported" if reward is not None else "unavailable",
        "reconciles": reconciles,
        "discrepancy": discrepancy,
    }


def risk_explanation(row: Mapping[str, Any]) -> dict[str, Any]:
    factors: list[dict[str, str]] = []
    if bool(row.get("tvl_available", True)):
        tvl = float(row.get("tvlUsd") or 0.0)
        status = "Deep" if tvl >= 100_000_000 else "Moderate" if tvl >= 10_000_000 else "Light"
        factors.append({"factor": "Liquidity / TVL", "status": status, "detail": f"Reported TVL is ${tvl:,.0f}."})
    else:
        factors.append({"factor": "Liquidity / TVL", "status": "Unknown", "detail": "The provider did not report TVL."})

    stable = row.get("stablecoin")
    if pd.isna(stable):
        factors.append({"factor": "Pool composition", "status": "Unknown", "detail": "Stablecoin exposure is unavailable."})
    else:
        factors.append(
            {
                "factor": "Pool composition",
                "status": "Stablecoin-labelled" if bool(stable) else "Directional / mixed",
                "detail": "This is provider metadata, not a guarantee of price stability.",
            }
        )

    reward = _known(row, "apyReward", "apy_reward_available")
    total = _known(row, "apy", "apy_available")
    if reward is None:
        factors.append({"factor": "Reward dependence", "status": "Unknown", "detail": "Reward APY was not reported."})
    else:
        share = reward / total * 100 if total and total > 0 else None
        detail = f"Reported reward APY is {reward:.2f}%."
        if share is not None:
            detail += f" It represents about {share:.0f}% of reported total APY."
        factors.append({"factor": "Reward dependence", "status": "Known", "detail": detail})

    if total is None:
        factors.append({"factor": "Yield characteristics", "status": "Unknown", "detail": "Total APY is unavailable."})
    elif total >= 80:
        factors.append({"factor": "Yield characteristics", "status": "Very high", "detail": "Very high reported APY merits incentive and durability review."})
    elif total >= 30:
        factors.append({"factor": "Yield characteristics", "status": "Elevated", "detail": "Elevated reported APY may be incentive-dependent."})
    else:
        factors.append({"factor": "Yield characteristics", "status": "Observed", "detail": f"Reported total APY is {total:.2f}%."})

    missing = [factor for factor in factors if factor["status"] == "Unknown"]
    raw_score = row.get("risk_score")
    return {
        "label": "Unknown" if missing else str(row.get("risk_band") or "Unknown"),
        "score": None if missing or raw_score is None else int(raw_score),
        "factors": factors,
        "method": "Existing FuruFlow heuristic; factors explain available inputs and do not predict loss.",
    }


def yield_spreads(frame: pd.DataFrame, *, minimum_difference: float = 3.0) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    clean = frame.copy()
    known = clean.get("apy_available", pd.Series(True, index=clean.index)).astype(bool)
    clean = clean[known & clean["apy"].notna()].copy()
    clean["asset_key"] = clean["symbol"].fillna("").astype(str).str.upper().str.replace(" ", "", regex=False)
    rows: list[dict[str, Any]] = []
    for asset, sub in clean.groupby("asset_key", sort=True):
        if not asset or sub["chain"].nunique() < 2 or len(sub) < 2:
            continue
        ordered = sort_pools(sub, "Highest APY")
        top = ordered.iloc[0]
        low = ordered.sort_values(["apy", "pool"], ascending=[True, True], kind="mergesort").iloc[0]
        difference = float(top["apy"] - low["apy"])
        if difference < minimum_difference:
            continue
        rows.append(
            {
                "Asset": asset,
                "Higher pool ID": str(top["pool"]),
                "Higher chain": top["chain"],
                "Higher protocol": top["project"],
                "Higher APY": float(top["apy"]),
                "Higher TVL": _known(top, "tvlUsd", "tvl_available"),
                "Higher risk": None if pd.isna(top.get("risk_score")) else float(top["risk_score"]),
                "Higher signal": str(top.get("signal") or "Unavailable"),
                "Higher link": top["pool_url"],
                "Lower pool ID": str(low["pool"]),
                "Lower chain": low["chain"],
                "Lower protocol": low["project"],
                "Lower APY": float(low["apy"]),
                "Lower TVL": _known(low, "tvlUsd", "tvl_available"),
                "Lower risk": None if pd.isna(low.get("risk_score")) else float(low["risk_score"]),
                "Lower signal": str(low.get("signal") or "Unavailable"),
                "Lower link": low["pool_url"],
                "APY difference": difference,
                "Execution costs": "Not modeled",
            }
        )
    return pd.DataFrame(rows).sort_values(["APY difference", "Asset"], ascending=[False, True], kind="mergesort") if rows else pd.DataFrame()


EventSink = Callable[[dict[str, Any]], None]


def track_research_event(name: str, properties: Mapping[str, Any] | None = None, *, sink: EventSink | None = None) -> dict[str, Any]:
    """Create a local structured event without identity or session material."""

    allowed = {"view", "filter", "count", "pool", "source", "action"}
    event = {
        "name": str(name),
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "properties": {key: value for key, value in (properties or {}).items() if key in allowed},
    }
    if sink is not None:
        sink(event)
    return event
