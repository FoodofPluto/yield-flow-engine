"""Evidence coverage and analytical confidence for reported pool metrics.

Reported APY magnitude is deliberately absent from this model.  Confidence
describes the evidence supporting an assessment, not the attractiveness,
safety, or expected return of a pool.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any, Mapping

import pandas as pd


class EvidenceCoverage(str, Enum):
    NONE = "No evidence"
    INSUFFICIENT = "Insufficient evidence"
    PARTIAL = "Partial evidence"
    SUFFICIENT = "Sufficient evidence"


class ConfidenceLevel(str, Enum):
    UNAVAILABLE = "Unavailable"
    LOW = "Low"
    MODERATE = "Moderate"
    HIGH = "High"


@dataclass(frozen=True)
class EvidenceThresholds:
    partial_observations: int = 2
    moderate_observations: int = 14
    moderate_duration_days: float = 7.0
    moderate_continuity: float = 0.70
    high_observations: int = 30
    high_duration_days: float = 30.0
    high_continuity: float = 0.80
    decomposition_observations: int = 14
    max_history_age_hours: float = 48.0


DEFAULT_THRESHOLDS = EvidenceThresholds()


@dataclass(frozen=True)
class HistoricalEvidence:
    apy_observations: int = 0
    tvl_observations: int = 0
    base_apy_observations: int = 0
    reward_apy_observations: int = 0
    duration_days: float = 0.0
    continuity: float | None = None
    latest_observed_at: datetime | None = None
    signal_history_available: bool = False


@dataclass(frozen=True)
class ConfidenceAssessment:
    confidence: ConfidenceLevel
    coverage: EvidenceCoverage
    available: tuple[str, ...]
    missing: tuple[str, ...]
    limiting_factors: tuple[str, ...]
    interpretation: str


def _finite_number(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _valid_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(dtype="float64")
    values = pd.to_numeric(frame[column], errors="coerce")
    return values.where(values.map(lambda value: _finite_number(value) is not None)).dropna()


def historical_evidence(frame: pd.DataFrame | None, *, signal_history_available: bool = False) -> HistoricalEvidence:
    """Summarize real observations without zero-filling missing values."""
    if frame is None or frame.empty:
        return HistoricalEvidence(signal_history_available=signal_history_available)

    if "timestamp" in frame.columns:
        raw_timestamps = pd.to_datetime(frame["timestamp"], errors="coerce", utc=True)
        apy_values = pd.to_numeric(frame.get("apy", pd.Series(index=frame.index, dtype="float64")), errors="coerce")
        tvl_values = pd.to_numeric(frame.get("tvlUsd", pd.Series(index=frame.index, dtype="float64")), errors="coerce")
        finite_core = apy_values.map(lambda value: _finite_number(value) is not None) & tvl_values.map(
            lambda value: _finite_number(value) is not None
        )
        timestamps = raw_timestamps[finite_core].dropna().sort_values().drop_duplicates()
    else:
        timestamps = pd.Series(dtype="datetime64[ns, UTC]")
    duration_days = 0.0
    continuity: float | None = None
    latest: datetime | None = None
    if not timestamps.empty:
        latest_value = timestamps.iloc[-1]
        latest = latest_value.to_pydatetime()
        if len(timestamps) >= 2:
            duration_days = max(0.0, float((timestamps.iloc[-1] - timestamps.iloc[0]).total_seconds()) / 86400.0)
            gaps = timestamps.diff().dropna().dt.total_seconds()
            positive_gaps = gaps[gaps > 0]
            if not positive_gaps.empty:
                median_gap = float(positive_gaps.median())
                allowed_gap = max(48 * 3600.0, median_gap * 3.0)
                continuity = float((positive_gaps <= allowed_gap).sum() / len(positive_gaps))

    return HistoricalEvidence(
        apy_observations=len(_valid_series(frame, "apy")),
        tvl_observations=len(_valid_series(frame, "tvlUsd")),
        base_apy_observations=len(_valid_series(frame, "apyBase")),
        reward_apy_observations=len(_valid_series(frame, "apyReward")),
        duration_days=duration_days,
        continuity=continuity,
        latest_observed_at=latest,
        signal_history_available=signal_history_available,
    )


def serialize_evidence(evidence: HistoricalEvidence) -> dict[str, Any]:
    return {
        "evidence_apy_observations": evidence.apy_observations,
        "evidence_tvl_observations": evidence.tvl_observations,
        "evidence_base_observations": evidence.base_apy_observations,
        "evidence_reward_observations": evidence.reward_apy_observations,
        "evidence_duration_days": evidence.duration_days,
        "evidence_continuity": evidence.continuity,
        "evidence_latest_observed_at": evidence.latest_observed_at,
        "evidence_signal_history": evidence.signal_history_available,
    }


def evidence_from_mapping(row: Mapping[str, Any]) -> HistoricalEvidence:
    def count(key: str) -> int:
        value = _finite_number(row.get(key))
        return max(0, int(value)) if value is not None else 0

    try:
        latest = pd.to_datetime(row.get("evidence_latest_observed_at"), errors="coerce", utc=True)
    except (TypeError, ValueError, OverflowError):
        latest = None
    latest_value = latest.to_pydatetime() if isinstance(latest, pd.Timestamp) and not pd.isna(latest) else None
    continuity = _finite_number(row.get("evidence_continuity"))
    signal_value = row.get("evidence_signal_history", False)
    signal_available = (
        bool(signal_value)
        if pd.api.types.is_scalar(signal_value) and signal_value is not None and not bool(pd.isna(signal_value))
        else False
    )
    return HistoricalEvidence(
        apy_observations=count("evidence_apy_observations"),
        tvl_observations=count("evidence_tvl_observations"),
        base_apy_observations=count("evidence_base_observations"),
        reward_apy_observations=count("evidence_reward_observations"),
        duration_days=max(0.0, _finite_number(row.get("evidence_duration_days")) or 0.0),
        continuity=continuity,
        latest_observed_at=latest_value,
        signal_history_available=signal_available,
    )


def assess_confidence(
    evidence: HistoricalEvidence,
    *,
    provider_availability: str = "available",
    freshness: str = "Current",
    now: datetime | None = None,
    thresholds: EvidenceThresholds = DEFAULT_THRESHOLDS,
) -> ConfidenceAssessment:
    """Assess evidence using prerequisites that positive unrelated fields cannot override."""
    core_counts = (evidence.apy_observations, evidence.tvl_observations)
    any_history = (
        any(
            count > 0
            for count in (
                evidence.apy_observations,
                evidence.tvl_observations,
                evidence.base_apy_observations,
                evidence.reward_apy_observations,
            )
        )
        or evidence.signal_history_available
    )
    both_partial = all(count >= thresholds.partial_observations for count in core_counts)
    moderate_history = (
        all(count >= thresholds.moderate_observations for count in core_counts)
        and evidence.duration_days >= thresholds.moderate_duration_days - 1e-6
        and evidence.continuity is not None
        and evidence.continuity >= thresholds.moderate_continuity
    )
    high_history = (
        all(count >= thresholds.high_observations for count in core_counts)
        and evidence.duration_days >= thresholds.high_duration_days - 1e-6
        and evidence.continuity is not None
        and evidence.continuity >= thresholds.high_continuity
    )
    decomposition = (
        evidence.base_apy_observations >= thresholds.decomposition_observations
        and evidence.reward_apy_observations >= thresholds.decomposition_observations
    )

    if not any_history:
        coverage = EvidenceCoverage.NONE
    elif moderate_history:
        coverage = EvidenceCoverage.SUFFICIENT
    elif both_partial:
        coverage = EvidenceCoverage.PARTIAL
    else:
        coverage = EvidenceCoverage.INSUFFICIENT

    available: list[str] = []
    missing: list[str] = []
    if evidence.apy_observations:
        available.append(f"APY history ({evidence.apy_observations} observations)")
    else:
        missing.append("APY history")
    if evidence.tvl_observations:
        available.append(f"TVL history ({evidence.tvl_observations} observations)")
    else:
        missing.append("TVL history")
    if decomposition:
        available.append("Base and reward APY history")
    else:
        missing.append("Base and reward APY history")
    if evidence.signal_history_available:
        available.append("Signal-history classification")
    else:
        missing.append("Signal history")

    limiting: list[str] = []
    availability = provider_availability.strip().lower()
    freshness_label = freshness.strip().lower()
    provider_usable = availability in {"available", "partial"}
    if not provider_usable:
        limiting.append("Current provider data is unavailable or sample-only")
    elif availability == "partial":
        limiting.append("The current provider response is partial")
    if freshness_label in {"stale", "unavailable"}:
        limiting.append("The newest provider retrieval is stale or unavailable")

    clock = now or datetime.now(timezone.utc)
    latest_stale = False
    if evidence.latest_observed_at is not None:
        latest = evidence.latest_observed_at
        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=timezone.utc)
        age_hours = max(
            0.0, (clock.astimezone(timezone.utc) - latest.astimezone(timezone.utc)).total_seconds() / 3600.0
        )
        latest_stale = age_hours > thresholds.max_history_age_hours
        if latest_stale:
            limiting.append("The newest historical observation is stale")

    if not moderate_history:
        if min(core_counts) < thresholds.moderate_observations:
            limiting.append(f"APY and TVL each need at least {thresholds.moderate_observations} valid observations")
        if evidence.duration_days < thresholds.moderate_duration_days:
            limiting.append(f"History must span at least {thresholds.moderate_duration_days:g} days")
        if evidence.continuity is None or evidence.continuity < thresholds.moderate_continuity:
            limiting.append("Historical continuity is insufficient")

    if not any_history or not provider_usable:
        confidence = ConfidenceLevel.UNAVAILABLE
    elif not moderate_history or latest_stale or freshness_label in {"stale", "unavailable"}:
        confidence = ConfidenceLevel.LOW
    elif (
        high_history
        and decomposition
        and evidence.signal_history_available
        and freshness_label == "current"
        and availability == "available"
    ):
        confidence = ConfidenceLevel.HIGH
    else:
        confidence = ConfidenceLevel.MODERATE
        if not high_history:
            limiting.append(
                f"High confidence requires {thresholds.high_observations} APY and TVL observations spanning "
                f"{thresholds.high_duration_days:g} days"
            )
        if not decomposition:
            limiting.append("Base and reward persistence are not sufficiently observed")
        if not evidence.signal_history_available:
            limiting.append("Signal history is unavailable")
        if freshness_label != "current":
            limiting.append("The current provider retrieval is not fresh enough for High confidence")

    if confidence is ConfidenceLevel.UNAVAILABLE:
        interpretation = (
            "FuruFlow does not yet have enough historical evidence to judge whether the reported yield is persistent."
        )
    elif confidence is ConfidenceLevel.LOW:
        interpretation = "FuruFlow has limited historical evidence; conclusions about persistence remain weak."
    elif confidence is ConfidenceLevel.MODERATE:
        interpretation = (
            "FuruFlow has enough core history for a cautious assessment, with important limitations still present."
        )
    else:
        interpretation = (
            "FuruFlow has broad, current historical evidence for this assessment; future returns remain uncertain."
        )

    return ConfidenceAssessment(
        confidence=confidence,
        coverage=coverage,
        available=tuple(available),
        missing=tuple(missing),
        limiting_factors=tuple(dict.fromkeys(limiting)),
        interpretation=interpretation,
    )
