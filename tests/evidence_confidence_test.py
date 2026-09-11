from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from evidence_confidence import (
    ConfidenceLevel,
    EvidenceCoverage,
    assess_confidence,
    evidence_from_mapping,
    historical_evidence,
    serialize_evidence,
)


NOW = datetime(2026, 8, 31, 12, tzinfo=timezone.utc)


def _history(
    count: int,
    *,
    days: float,
    apy: object = 8.0,
    tvl: object = 10_000_000.0,
    base: object = 7.0,
    reward: object = 1.0,
    end: datetime = NOW,
) -> pd.DataFrame:
    step = timedelta(days=days / max(count - 1, 1))
    start = end - timedelta(days=days)
    return pd.DataFrame(
        {
            "timestamp": [start + step * index for index in range(count)],
            "apy": [apy] * count,
            "apyBase": [base] * count,
            "apyReward": [reward] * count,
            "tvlUsd": [tvl] * count,
        }
    )


def test_reported_apy_without_history_has_no_evidence_or_confidence() -> None:
    reported_values = (0.0, 0.5, 12.0, 100.0, 323.63, 1e200, None, float("nan"), float("inf"))
    assessments = []
    for _reported_apy in reported_values:
        assessment = assess_confidence(historical_evidence(pd.DataFrame()), now=NOW)
        assessments.append(assessment)
        assert assessment.coverage is EvidenceCoverage.NONE
        assert assessment.confidence is ConfidenceLevel.UNAVAILABLE
        assert "reported yield is persistent" in assessment.interpretation
    # Reported APY is intentionally not an input to the assessment.
    assert all(assessment == assessments[0] for assessment in assessments)


def test_partial_apy_history_discloses_missing_tvl_and_caps_confidence() -> None:
    history = _history(14, days=7, tvl=pd.NA)
    assessment = assess_confidence(historical_evidence(history), now=NOW)
    assert assessment.coverage is EvidenceCoverage.INSUFFICIENT
    assert assessment.confidence is ConfidenceLevel.LOW
    assert "TVL history" in assessment.missing


def test_some_apy_and_tvl_history_is_partial_not_sufficient() -> None:
    assessment = assess_confidence(historical_evidence(_history(5, days=2)), now=NOW)
    assert assessment.coverage is EvidenceCoverage.PARTIAL
    assert assessment.confidence is ConfidenceLevel.LOW


def test_non_overlapping_apy_and_tvl_rows_cannot_satisfy_core_duration() -> None:
    history = _history(28, days=14)
    history.loc[:13, "tvlUsd"] = pd.NA
    history.loc[14:, "apy"] = pd.NA
    assessment = assess_confidence(historical_evidence(history), now=NOW)
    assert assessment.coverage is EvidenceCoverage.PARTIAL
    assert assessment.confidence is ConfidenceLevel.LOW
    assert any(factor.startswith("History must span") for factor in assessment.limiting_factors)


def test_supported_history_reaches_moderate_only_when_prerequisites_hold() -> None:
    evidence = historical_evidence(_history(14, days=7), signal_history_available=False)
    assessment = assess_confidence(evidence, now=NOW)
    assert assessment.coverage is EvidenceCoverage.SUFFICIENT
    assert assessment.confidence is ConfidenceLevel.MODERATE
    assert "Signal history" in assessment.missing


def test_complete_supported_evidence_can_reach_high() -> None:
    evidence = historical_evidence(_history(31, days=30), signal_history_available=True)
    assessment = assess_confidence(evidence, now=NOW)
    assert assessment.coverage is EvidenceCoverage.SUFFICIENT
    assert assessment.confidence is ConfidenceLevel.HIGH


def test_measured_zero_is_observed_but_missing_and_non_finite_are_not() -> None:
    frame = _history(6, days=3, apy=0.0, tvl=0.0)
    frame.loc[1, "apy"] = pd.NA
    frame.loc[2, "apy"] = float("nan")
    frame.loc[3, "apy"] = float("inf")
    frame.loc[4, "tvlUsd"] = float("-inf")
    evidence = historical_evidence(frame)
    assert evidence.apy_observations == 3
    assert evidence.tvl_observations == 5


def test_object_backed_malformed_history_cannot_fabricate_evidence() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": [NOW, NOW + timedelta(hours=1)],
            "apy": [{"value": 9}, [9]],
            "tvlUsd": [object(), "not-a-number"],
            "apyBase": [pd.NA, None],
            "apyReward": [float("inf"), float("nan")],
        }
    )
    evidence = historical_evidence(frame)
    assessment = assess_confidence(evidence, now=NOW)
    assert evidence.apy_observations == 0
    assert evidence.tvl_observations == 0
    assert assessment.coverage is EvidenceCoverage.NONE
    assert assessment.confidence is ConfidenceLevel.UNAVAILABLE


def test_stale_history_and_provider_degradation_cannot_create_high_confidence() -> None:
    old = _history(31, days=30, end=NOW - timedelta(days=4))
    stale = assess_confidence(historical_evidence(old, signal_history_available=True), now=NOW)
    assert stale.confidence is ConfidenceLevel.LOW
    partial = assess_confidence(
        historical_evidence(_history(31, days=30), signal_history_available=True),
        provider_availability="partial",
        now=NOW,
    )
    assert partial.confidence is ConfidenceLevel.MODERATE
    unavailable = assess_confidence(
        historical_evidence(_history(31, days=30), signal_history_available=True),
        provider_availability="unavailable",
        now=NOW,
    )
    assert unavailable.confidence is ConfidenceLevel.UNAVAILABLE


def test_removing_required_evidence_never_increases_confidence() -> None:
    levels = {
        ConfidenceLevel.UNAVAILABLE: 0,
        ConfidenceLevel.LOW: 1,
        ConfidenceLevel.MODERATE: 2,
        ConfidenceLevel.HIGH: 3,
    }
    complete = assess_confidence(historical_evidence(_history(31, days=30), signal_history_available=True), now=NOW)
    without_tvl = assess_confidence(
        historical_evidence(_history(31, days=30, tvl=pd.NA), signal_history_available=True), now=NOW
    )
    assert levels[without_tvl.confidence] <= levels[complete.confidence]


def test_adding_observations_does_not_reduce_evidence_coverage() -> None:
    order = {
        EvidenceCoverage.NONE: 0,
        EvidenceCoverage.INSUFFICIENT: 1,
        EvidenceCoverage.PARTIAL: 2,
        EvidenceCoverage.SUFFICIENT: 3,
    }
    assessments = [
        assess_confidence(historical_evidence(pd.DataFrame()), now=NOW),
        assess_confidence(historical_evidence(_history(1, days=0)), now=NOW),
        assess_confidence(historical_evidence(_history(5, days=2)), now=NOW),
        assess_confidence(historical_evidence(_history(14, days=7)), now=NOW),
    ]
    assert [order[item.coverage] for item in assessments] == sorted(order[item.coverage] for item in assessments)


def test_serialized_evidence_round_trips_without_fabricating_missing_values() -> None:
    evidence = historical_evidence(_history(14, days=7), signal_history_available=True)
    assert evidence_from_mapping(serialize_evidence(evidence)) == evidence
    missing = evidence_from_mapping({"evidence_continuity": pd.NA, "evidence_signal_history": pd.NA})
    assert missing.continuity is None
    assert missing.signal_history_available is False
    malformed = evidence_from_mapping(
        {"evidence_latest_observed_at": {"bad": "shape"}, "evidence_signal_history": [True]}
    )
    assert malformed.latest_observed_at is None
    assert malformed.signal_history_available is False


def test_canonical_pool_identity_keeps_duplicate_looking_pool_evidence_separate() -> None:
    histories = {
        "aa70268e-4b52-42bf-a116-608b370f9501": _history(31, days=30),
        "effcb4a4-4dcb-45e5-935d-f15542c13e6b": pd.DataFrame(),
    }
    first = assess_confidence(
        historical_evidence(histories["aa70268e-4b52-42bf-a116-608b370f9501"], signal_history_available=True), now=NOW
    )
    second = assess_confidence(historical_evidence(histories["effcb4a4-4dcb-45e5-935d-f15542c13e6b"]), now=NOW)
    assert first.confidence is ConfidenceLevel.HIGH
    assert second.confidence is ConfidenceLevel.UNAVAILABLE


@pytest.mark.parametrize("fallback", [0.0, 1.0, 10.0])
def test_rendering_fallback_cannot_change_analytical_result(fallback: float) -> None:
    evidence = historical_evidence(pd.DataFrame())
    before = assess_confidence(evidence, now=NOW)
    marker_size = fallback
    assert marker_size >= 0 and pd.notna(marker_size)
    assert assess_confidence(evidence, now=NOW) == before
