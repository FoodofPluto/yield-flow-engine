from __future__ import annotations

from math import log10
from typing import Any, Dict, List


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


PROVIDER_RISK_LABELS = {
    range(0, 3): "Low",
    range(3, 6): "Moderate",
    range(6, 8): "Elevated",
    range(8, 11): "High",
}


MAJOR_CHAINS = {
    "ethereum": 0,
    "bitcoin": 0,
    "base": 1,
    "arbitrum": 1,
    "optimism": 1,
    "polygon": 1,
    "avalanche": 1,
    "solana": 1,
    "bnb chain": 2,
    "bsc": 2,
    "fantom": 2,
}


EXOTIC_CATEGORY_PENALTIES = {
    "leveraged": 3,
    "options": 2,
    "delta neutral": 2,
    "basis trading": 2,
    "yield looping": 3,
    "lsd": 1,
    "lst": 1,
    "lp": 1,
}


def provider_risk_label(score: int) -> str:
    for score_range, label in PROVIDER_RISK_LABELS.items():
        if score in score_range:
            return label
    return "High"


def compute_provider_risk(meta: Dict[str, Any]) -> Dict[str, Any]:
    tvl = float(meta.get("tvlUsd") or 0.0)
    apy = float(meta.get("apy") or 0.0)
    stable = bool(meta.get("stablecoin") or False)
    il_risk = str(meta.get("ilRisk") or "").lower()
    chain = str(meta.get("chain") or "").lower()
    category = str(meta.get("category") or "").lower()
    project = str(meta.get("project") or "")

    score = 1
    reasons: List[str] = []

    chain_penalty = MAJOR_CHAINS.get(chain, 2)
    score += chain_penalty
    if chain_penalty >= 2 and chain:
        reasons.append(f"less battle-tested chain: {meta.get('chain')}")

    if tvl < 1_000_000:
        score += 3
        reasons.append("very low TVL")
    elif tvl < 10_000_000:
        score += 2
        reasons.append("modest TVL")
    elif tvl < 100_000_000:
        score += 1
        reasons.append("mid TVL")

    if apy >= 80:
        score += 3
        reasons.append("very high APY")
    elif apy >= 30:
        score += 2
        reasons.append("high APY")
    elif apy >= 15:
        score += 1
        reasons.append("above-market APY")

    if not stable:
        score += 1
        reasons.append("volatile asset exposure")

    if il_risk and il_risk not in {"no", "none", "n/a"}:
        score += 1
        reasons.append(f"impermanent loss risk: {meta.get('ilRisk')}")

    for key, penalty in EXOTIC_CATEGORY_PENALTIES.items():
        if key in category:
            score += penalty
            reasons.append(f"strategy category: {meta.get('category')}")
            break

    if not project:
        score += 1
        reasons.append("missing protocol metadata")

    score = max(1, min(int(score), 10))
    return {
        "risk_score": score,
        "risk_label": provider_risk_label(score),
        "risk_reasons": "; ".join(reasons[:4]) if reasons else "Large-chain, high-liquidity pool profile.",
    }


def score_tvl_stability(tvl: float) -> int:
    tvl = float(tvl or 0)
    if tvl >= 1_000_000_000:
        return 95
    if tvl >= 250_000_000:
        return 86
    if tvl >= 100_000_000:
        return 78
    if tvl >= 25_000_000:
        return 65
    if tvl >= 10_000_000:
        return 54
    if tvl >= 1_000_000:
        return 38
    return 24


def score_pool_volatility(row: Dict[str, Any]) -> int:
    apy = float(row.get("apy", 0) or 0)
    rewards = float(row.get("apyReward", 0) or 0)
    stablecoin = bool(row.get("stablecoin", False))
    exposure = str(row.get("exposure", "")).lower()
    strategy = str(row.get("poolMeta", "")).lower()
    vol = 22
    if apy > 120:
        vol += 42
    elif apy > 60:
        vol += 28
    elif apy > 25:
        vol += 14
    if rewards > 10:
        vol += 10
    if not stablecoin:
        vol += 8
    if exposure in {"multi", "lp"}:
        vol += 6
    if any(word in strategy for word in ["farm", "loop", "lever", "dex", "vault"]):
        vol += 8
    return max(5, min(100, int(round(vol))))


def score_pool(row: Dict[str, Any]) -> int:
    apy = float(row.get("apy", 0) or 0)
    tvl_stability = int(row.get("tvl_stability_score", 50) or 50)
    audit = int(row.get("audit_score", 55) or 55)
    age = int(row.get("protocol_age_score", 55) or 55)
    volatility = int(row.get("pool_volatility_score", 45) or 45)
    stablecoin = bool(row.get("stablecoin", False))
    rewards = float(row.get("apyReward", 0) or 0)

    risk = 58
    risk += max(0, min(28, apy / 5))
    risk += max(0, min(12, rewards / 2))
    risk += (100 - tvl_stability) * 0.22
    risk += (100 - audit) * 0.18
    risk += (100 - age) * 0.10
    risk += volatility * 0.22
    if stablecoin:
        risk -= 8
    return max(1, min(100, int(round(risk))))


def label_pool_risk(score: int) -> str:
    if score <= 28:
        return "Low"
    if score <= 45:
        return "Moderate"
    if score <= 65:
        return "High"
    return "Speculative"


def score_signal_movement(apy_delta_7: Any, tvl_delta_7_pct: Any, apy_volatility: Any) -> float:
    return round(
        abs(float(apy_delta_7 or 0.0)) * 0.6
        + abs(float(tvl_delta_7_pct or 0.0)) * 0.3
        + float(apy_volatility or 0.0) * 0.1,
        1,
    )


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


def risk_tags(signal: Dict[str, Any]) -> List[str]:
    tags: List[str] = []
    tvl = float(signal.get("tvl") or 0.0)
    apy = float(signal.get("apy") or 0.0)
    risk_score = int(signal.get("risk_score") or 0)
    risk_label = str(signal.get("risk_label") or "")
    stablecoin = bool(signal.get("stablecoin") or False)
    category = str(signal.get("category") or "")

    if tvl < 2_000_000:
        tags.append("low liquidity")
    elif tvl >= 100_000_000:
        tags.append("deep liquidity")

    if apy >= 40:
        tags.append("very high APY")
    elif apy >= 20:
        tags.append("elevated APY")

    if risk_score >= 8 or risk_label.lower() == "high":
        tags.append("high risk")
    elif risk_score <= 3 or risk_label.lower() == "low":
        tags.append("lower risk")

    if stablecoin:
        tags.append("stable exposure")
    else:
        tags.append("volatile exposure")

    lowered = category.lower()
    if any(term in lowered for term in ["lp", "dex"]):
        tags.append("LP strategy")
    elif lowered:
        tags.append(category)

    deduped: List[str] = []
    seen = set()
    for tag in tags:
        key = tag.lower().strip()
        if key and key not in seen:
            seen.add(key)
            deduped.append(tag)
    return deduped[:4]


def signal_strength_score(signal: Dict[str, Any]) -> int:
    apy = float(signal.get("apy") or 0.0)
    tvl = float(signal.get("tvl") or 0.0)
    risk_score = int(signal.get("risk_score") or 5)
    trend_score = float(signal.get("trend_score") or 0.0)
    stablecoin = bool(signal.get("stablecoin") or False)

    apy_component = clamp(apy / 35.0, 0.0, 1.0) * 28.0
    tvl_component = clamp(log10(max(tvl, 1.0)) / 9.0, 0.0, 1.0) * 24.0
    risk_component = clamp((10.0 - risk_score) / 9.0, 0.0, 1.0) * 24.0
    trend_component = ((clamp(trend_score, -100.0, 100.0) + 100.0) / 200.0) * 20.0
    stability_bonus = 4.0 if stablecoin else 0.0

    return int(round(clamp(
        apy_component + tvl_component + risk_component + trend_component + stability_bonus,
        0.0,
        100.0,
    )))


def build_reason(signal: Dict[str, Any]) -> str:
    parts: List[str] = []
    signal_name = str(signal.get("signal") or "Steady")
    strength = str(signal.get("strength_label") or "Watch")
    apy = float(signal.get("apy") or 0.0)
    tvl = float(signal.get("tvl") or 0.0)
    risk_label = str(signal.get("risk_label") or "Unknown")

    if signal_name != "Steady":
        parts.append(signal_name)
    parts.append(f"{strength.lower()} setup")
    parts.append(f"{apy:.2f}% APY")
    if tvl > 0:
        if tvl >= 1_000_000_000:
            parts.append("institutional-scale TVL")
        elif tvl >= 100_000_000:
            parts.append("large TVL base")
        elif tvl >= 10_000_000:
            parts.append("healthy liquidity")
        else:
            parts.append("smaller liquidity base")
    parts.append(f"{risk_label.lower()} risk profile")
    return " • ".join(parts[:5])


# Backward-compatible aliases for older call sites.
label_risk = label_pool_risk
compute_risk = compute_provider_risk
