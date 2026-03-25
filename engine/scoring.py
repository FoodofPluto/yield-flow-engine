from __future__ import annotations

from math import log10
from typing import Any, Dict


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


RISK_BUCKETS = (
    (0, 29, "Low"),
    (30, 54, "Moderate"),
    (55, 74, "Elevated"),
    (75, 100, "Speculative"),
)


def score_signal(signal: Dict[str, Any]) -> int:
    apy = float(signal.get("apy") or 0.0)
    tvl = float(signal.get("tvl") or 0.0)
    trend_score = float(signal.get("trend_score") or 0.0)
    stablecoin = bool(signal.get("stablecoin") or False)
    chain = str(signal.get("chain") or "").lower()
    category = str(signal.get("category") or "").lower()
    provider_risk = int(signal.get("risk_score") or 5)

    apy_component = clamp(apy / 40.0, 0.0, 1.0) * 32.0
    tvl_component = clamp(log10(max(tvl, 1.0)) / 9.0, 0.0, 1.0) * 24.0
    trend_component = ((clamp(trend_score, -100.0, 100.0) + 100.0) / 200.0) * 18.0
    stability_component = 8.0 if stablecoin else 0.0
    chain_component = 8.0 if chain in {"ethereum", "base", "arbitrum", "optimism", "polygon"} else 4.0
    category_component = 6.0 if any(term in category for term in ["lend", "dex", "lp"]) else 3.0
    risk_penalty = clamp(provider_risk / 10.0, 0.0, 1.0) * 20.0

    score = int(round(clamp(
        apy_component + tvl_component + trend_component + stability_component + chain_component + category_component - risk_penalty,
        0.0,
        100.0,
    )))
    return score


def strength_label(score: int) -> str:
    if score >= 80:
        return "High conviction"
    if score >= 65:
        return "Strong"
    if score >= 50:
        return "Watch"
    return "Speculative"


def public_risk_label(signal: Dict[str, Any], score: int | None = None) -> str:
    score = score if score is not None else score_signal(signal)
    risk_value = 100 - int(score)
    for low, high, label in RISK_BUCKETS:
        if low <= risk_value <= high:
            return label
    return "Speculative"
