from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple


def signal_tier(signal: Dict[str, Any]) -> str:
    score = int(float(signal.get("strength_score") or 0))
    trend_score = float(signal.get("trend_score") or 0.0)

    # Cleaner first monetization split:
    # Pro if score is solid, or if score is close and trend is meaningfully positive.
    if score >= 60 or (score >= 56 and trend_score >= 10):
        return "Pro"
    return "Free"


def split_signal_tiers(
    signals: Iterable[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    free: List[Dict[str, Any]] = []
    pro: List[Dict[str, Any]] = []

    for signal in signals:
        tier = signal_tier(signal)
        signal["tier"] = tier  # force consistency instead of trusting stale stored values
        if tier == "Pro":
            pro.append(signal)
        else:
            free.append(signal)

    return free, pro