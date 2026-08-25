from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from market_research import (
    COMPARISON_LIMIT,
    COMPARISON_SCENARIOS,
    DEFAULT_FILTERS,
    ComparisonWeights,
    DataStatus,
    active_filters,
    apply_discovery_filters,
    comparison_rows,
    comparison_analysis,
    data_status_from_attrs,
    filter_query,
    freshness,
    parse_filter_query,
    pool_universe,
    remove_filter,
    risk_explanation,
    strategy_match_explanation,
    track_research_event,
    update_comparison,
    yield_explanation,
    yield_spreads,
)


def pools() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "pool": "a",
                "chain": "Base",
                "project": "Morpho",
                "symbol": "USDC",
                "poolMeta": "Lending",
                "strategy_type": "Lending",
                "signal": "Steady",
                "stablecoin": True,
                "apy": 8.0,
                "apyBase": 7.0,
                "apyReward": 1.0,
                "tvlUsd": 20_000_000.0,
                "risk_score": 30,
                "risk_band": "Moderate",
                "rank_score": 70.0,
                "volumeUsd1d": 10.0,
                "apy_delta_7": 1.0,
                "tvl_delta_7_pct": 2.0,
                "pool_url": "https://example.test/a",
                "apy_available": True,
                "apy_base_available": True,
                "apy_reward_available": True,
                "tvl_available": True,
            },
            {
                "pool": "b",
                "chain": "Arbitrum",
                "project": "Aave",
                "symbol": "USDC",
                "poolMeta": "Lending",
                "strategy_type": "Lending",
                "signal": "APY spike",
                "stablecoin": True,
                "apy": 4.0,
                "apyBase": float("nan"),
                "apyReward": float("nan"),
                "tvlUsd": 100_000_000.0,
                "risk_score": 25,
                "risk_band": "Low",
                "rank_score": 80.0,
                "volumeUsd1d": float("nan"),
                "apy_delta_7": 8.0,
                "tvl_delta_7_pct": 4.0,
                "pool_url": "https://example.test/b",
                "apy_available": True,
                "apy_base_available": False,
                "apy_reward_available": False,
                "tvl_available": True,
            },
            {
                "pool": "c",
                "chain": "Base",
                "project": "Unknown",
                "symbol": "ETH",
                "poolMeta": "LP",
                "strategy_type": "LP",
                "signal": "Steady",
                "stablecoin": False,
                "apy": float("nan"),
                "apyBase": float("nan"),
                "apyReward": float("nan"),
                "tvlUsd": float("nan"),
                "risk_score": 65,
                "risk_band": "High",
                "rank_score": 5.0,
                "volumeUsd1d": float("nan"),
                "apy_delta_7": 0.0,
                "tvl_delta_7_pct": 0.0,
                "pool_url": "https://example.test/c",
                "apy_available": False,
                "apy_base_available": False,
                "apy_reward_available": False,
                "tvl_available": False,
            },
        ]
    )


def test_filter_defaults_round_trip_and_active_removal_reset() -> None:
    assert parse_filter_query({}) == DEFAULT_FILTERS
    selected = replace(DEFAULT_FILTERS, search="morpho", chains=("Base",), stablecoin_only=True, min_apy=5)
    assert parse_filter_query(filter_query(selected)) == selected
    assert [label for _, label in active_filters(selected)] == [
        'Search: "morpho"',
        "Chain: Base",
        "Stablecoin pools only",
        "Minimum APY: 5%",
    ]
    assert remove_filter(selected, "chains:Base").chains == ()
    assert remove_filter(selected, "search").search == ""
    assert remove_filter(selected, "min_apy").min_apy == DEFAULT_FILTERS.min_apy


def test_discovery_search_filters_sort_and_zero_results_are_deterministic() -> None:
    frame = pools()
    filtered = apply_discovery_filters(frame, replace(DEFAULT_FILTERS, search="morpho", min_tvl=0))
    assert filtered["pool"].tolist() == ["a"]
    filtered = apply_discovery_filters(frame, replace(DEFAULT_FILTERS, min_tvl=0, sort_by="Highest APY"))
    assert filtered["pool"].tolist() == ["a", "b", "c"]
    assert apply_discovery_filters(frame, replace(DEFAULT_FILTERS, search="no match", min_tvl=0)).empty
    assert apply_discovery_filters(frame, replace(DEFAULT_FILTERS, min_apy=5, min_tvl=0))["pool"].tolist() == ["a"]


def test_pool_universe_ignores_discovery_thresholds_and_orders_canonical_rows() -> None:
    frame = pools()
    duplicate = frame.iloc[[0]].copy()
    duplicate["apy"] = 99.0
    universe = pool_universe(pd.concat([frame, duplicate], ignore_index=True))

    assert universe["pool"].tolist() == ["b", "a", "c"]
    assert universe["pool"].is_unique
    assert pool_universe(frame, "unknown")["pool"].tolist() == ["c"]
    assert pool_universe(frame, "c")["pool"].tolist() == ["b", "a", "c"]


def test_provenance_fresh_aging_stale_and_unavailable() -> None:
    now = datetime(2026, 8, 10, 12, tzinfo=timezone.utc)
    assert freshness(DataStatus("Provider", now - timedelta(minutes=5)), now=now)["label"] == "Current"
    assert freshness(DataStatus("Provider", now - timedelta(minutes=30)), now=now)["label"] == "Aging"
    assert freshness(DataStatus("Provider", now - timedelta(hours=2)), now=now)["label"] == "Stale"
    assert freshness(DataStatus("Provider", None, availability="unavailable"), now=now)["label"] == "Unavailable"
    sample = freshness(DataStatus("Fixture", now, availability="sample", degraded=True), now=now)
    assert sample["label"] == "Sample"
    partial = data_status_from_attrs(
        {"source_status": "partial", "source_label": "Provider", "retrieved_at": now.isoformat(), "errors": ["one row dropped"]}
    )
    assert partial.availability == "partial"
    assert partial.degraded is True
    assert partial.detail == "one row dropped"


def test_yield_explanation_handles_decomposition_aggregate_missing_and_discrepancy() -> None:
    decomposed = yield_explanation(pools().iloc[0])
    assert decomposed["mode"] == "decomposed"
    assert decomposed["reconciles"] is True
    aggregate = yield_explanation(pools().iloc[1])
    assert aggregate["mode"] == "aggregate_only"
    assert aggregate["base"] is None
    assert yield_explanation(pools().iloc[2])["mode"] == "unavailable"
    mismatch = pools().iloc[0].copy()
    mismatch["apyReward"] = 4.0
    assert yield_explanation(mismatch)["reconciles"] is False


def test_missing_risk_inputs_remain_unknown_not_low() -> None:
    known = risk_explanation(pools().iloc[0])
    assert known["label"] == "Moderate"
    assert known["score"] == 30
    unknown = risk_explanation(pools().iloc[2])
    assert unknown["label"] == "Unknown"
    assert unknown["score"] is None
    assert any(factor["status"] == "Unknown" for factor in unknown["factors"])


def test_comparison_limit_removal_and_missing_values() -> None:
    selected: tuple[str, ...] = ()
    for pool_id in ("a", "b", "c", "d"):
        selected = update_comparison(selected, pool_id, selected_state=True)
    assert len(selected) == COMPARISON_LIMIT
    with pytest.raises(ValueError, match="up to 4"):
        update_comparison(selected, "e", selected_state=True)
    selected = update_comparison(selected, "b", selected_state=False)
    assert selected == ("a", "c", "d")
    compared = comparison_rows(pools(), ("a", "c"))
    assert compared[1]["APY"] is None
    assert compared[1]["TVL (USD)"] is None


def test_selected_set_model_is_deterministic_explainable_and_preserves_identity() -> None:
    frame = pools()
    frame["signal_strength"] = [2.0, 10.0, float("nan")]
    balanced = comparison_analysis(frame, ("a", "b", "c"), COMPARISON_SCENARIOS["Balanced"])
    repeated = comparison_analysis(frame, ("a", "b", "c"), COMPARISON_SCENARIOS["Balanced"])

    assert balanced == repeated
    assert [row["pool"] for row in balanced["rows"]] == ["b", "a", "c"]
    assert balanced["winner"]["pool"] == "b"
    assert balanced["apy_spread"] == 4.0
    assert balanced["protocols"] == ["Aave", "Morpho", "Unknown"]
    assert balanced["networks"] == ["Arbitrum", "Base"]
    assert "strongest selected-set contribution" in balanced["winner"]["Reason"]
    assert next(row for row in balanced["rows"] if row["pool"] == "c")["Coverage %"] < 100


def test_weighting_presets_change_rank_predictably_without_changing_inputs() -> None:
    frame = pools().iloc[:2].copy()
    frame["signal_strength"] = [2.0, 10.0]
    yield_seeking = comparison_analysis(frame, ("a", "b"), COMPARISON_SCENARIOS["Yield Seeking"])
    conservative = comparison_analysis(frame, ("a", "b"), COMPARISON_SCENARIOS["Conservative"])

    assert yield_seeking["winner"]["pool"] == "a"
    assert conservative["winner"]["pool"] == "b"
    assert COMPARISON_SCENARIOS == {
        "Yield Seeking": ComparisonWeights(55, 20, 15, 10),
        "Balanced": ComparisonWeights(35, 25, 25, 15),
        "Conservative": ComparisonWeights(15, 35, 40, 10),
    }


def test_comparison_model_degrades_safely_when_every_weight_or_value_is_missing() -> None:
    frame = pools().iloc[[2]].copy()
    analysis = comparison_analysis(frame, ("c",), ComparisonWeights(0, 0, 0, 0))

    assert analysis["winner"] is None
    assert analysis["rows"][0]["Score"] is None
    assert analysis["rows"][0]["Coverage %"] == 0.0
    assert analysis["rows"][0]["Reason"] == "No comparable weighted dimensions are available."


def test_strategy_explanation_reports_existing_constraints_without_new_score() -> None:
    explanation = strategy_match_explanation(
        pools().iloc[0],
        stable_only=True,
        min_apy=5.0,
        min_tvl=10_000_000,
        max_risk=40,
        signal_preference="Any",
    )

    assert "APY 8.00% ≥ 5.00%" in explanation
    assert "TVL $20,000,000 ≥ $10,000,000" in explanation
    assert "risk 30 ≤ 40" in explanation
    assert "stablecoin-labelled" in explanation


def test_yield_spreads_are_explicit_and_do_not_fill_missing_values() -> None:
    spreads = yield_spreads(pools())
    assert len(spreads) == 1
    assert spreads.iloc[0]["Asset"] == "USDC"
    assert spreads.iloc[0]["APY difference"] == 4.0
    assert spreads.iloc[0]["Higher pool ID"] == "a"
    assert spreads.iloc[0]["Lower pool ID"] == "b"
    assert spreads.iloc[0]["Higher TVL"] == 20_000_000.0
    assert spreads.iloc[0]["Lower risk"] == 25.0
    assert spreads.iloc[0]["Execution costs"] == "Not modeled"


def test_analytics_event_is_local_allowlisted_and_contains_no_session_material() -> None:
    events: list[dict] = []
    event = track_research_event(
        "filter_applied",
        {"filter": "chain", "count": 2, "email": "private@example.test", "session": "secret"},
        sink=events.append,
    )
    assert events == [event]
    assert event["properties"] == {"filter": "chain", "count": 2}
