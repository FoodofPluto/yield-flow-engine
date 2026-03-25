from __future__ import annotations

from dataclasses import dataclass
from math import log10
from typing import Any, Dict, Iterable, List

import pandas as pd

from history_store import load_history


@dataclass
class SignalTrend:
    signal: str
    apy_delta_7: float
    tvl_delta_7_pct: float
    apy_volatility: float
    trend_score: float
    trend_summary: str


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def compute_chart_signal_from_history(pool_id: str) -> SignalTrend:
    chart = load_history(pool_id)
    if chart.empty:
        return SignalTrend(
            signal="Steady",
            apy_delta_7=0.0,
            tvl_delta_7_pct=0.0,
            apy_volatility=0.0,
            trend_score=0.0,
            trend_summary="No local history yet.",
        )

    recent = chart.dropna(subset=["timestamp"]).sort_values("timestamp").tail(30).copy()
    if recent.empty:
        return SignalTrend(
            signal="Steady",
            apy_delta_7=0.0,
            tvl_delta_7_pct=0.0,
            apy_volatility=0.0,
            trend_score=0.0,
            trend_summary="History was empty after cleaning.",
        )

    recent["apy_change"] = recent["apy"].pct_change().replace([float("inf"), float("-inf")], 0).fillna(0)
    recent["tvl_change"] = recent["tvlUsd"].pct_change().replace([float("inf"), float("-inf")], 0).fillna(0)

    lookback_idx = max(0, len(recent) - 8)
    apy_last = float(recent["apy"].iloc[-1])
    apy_prev = float(recent["apy"].iloc[lookback_idx])
    tvl_last = float(recent["tvlUsd"].iloc[-1])
    tvl_prev = float(recent["tvlUsd"].iloc[lookback_idx])

    apy_delta = apy_last - apy_prev
    tvl_delta_pct = ((tvl_last - tvl_prev) / tvl_prev * 100.0) if tvl_prev > 0 else 0.0
    apy_vol = float(recent["apy_change"].std() * 100.0) if len(recent) > 3 else 0.0

    signal = "Steady"
    if apy_delta > 18:
        signal = "APY spike"
    elif tvl_delta_pct > 25 and apy_last > 8:
        signal = "Whale inflow"
    elif apy_delta > 8 and tvl_delta_pct > 10:
        signal = "Emerging pool"
    elif apy_delta < -12 and tvl_delta_pct < -10:
        signal = "Farm rotation"

    trend_score = clamp((apy_delta * 1.4) + (tvl_delta_pct * 0.6) - (apy_vol * 0.35), -100.0, 100.0)
    trend_summary = f"7d APY Δ {apy_delta:+.2f}, TVL Δ {tvl_delta_pct:+.1f}%, volatility {apy_vol:.1f}."
    return SignalTrend(
        signal=signal,
        apy_delta_7=round(apy_delta, 2),
        tvl_delta_7_pct=round(tvl_delta_pct, 2),
        apy_volatility=round(apy_vol, 2),
        trend_score=round(trend_score, 2),
        trend_summary=trend_summary,
    )


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

    score = int(round(clamp(apy_component + tvl_component + risk_component + trend_component + stability_bonus, 0.0, 100.0)))
    return score


def strength_label(score: int) -> str:
    if score >= 80:
        return "High conviction"
    if score >= 65:
        return "Strong"
    if score >= 50:
        return "Watch"
    return "Speculative"


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


def enrich_signals(signals: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    enriched: List[Dict[str, Any]] = []
    for raw in signals:
        signal = dict(raw)
        pool_id = str(signal.get("pool_id") or "")
        trend = compute_chart_signal_from_history(pool_id) if pool_id else SignalTrend(
            signal="Steady",
            apy_delta_7=0.0,
            tvl_delta_7_pct=0.0,
            apy_volatility=0.0,
            trend_score=0.0,
            trend_summary="No pool history available.",
        )
        signal.update(
            {
                "signal": trend.signal,
                "apy_delta_7": trend.apy_delta_7,
                "tvl_delta_7_pct": trend.tvl_delta_7_pct,
                "apy_volatility": trend.apy_volatility,
                "trend_score": trend.trend_score,
                "trend_summary": trend.trend_summary,
            }
        )
        signal["risk_tags"] = risk_tags(signal)
        signal["strength_score"] = signal_strength_score(signal)
        signal["strength_label"] = strength_label(int(signal["strength_score"]))
        signal["reason"] = build_reason(signal)
        enriched.append(signal)

    enriched.sort(
        key=lambda s: (
            float(s.get("strength_score") or 0.0),
            float(s.get("apy") or 0.0),
            float(s.get("tvl") or 0.0),
        ),
        reverse=True,
    )
    return enriched


def snapshots_dataframe(signals: Iterable[Dict[str, Any]]) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for signal in signals:
        rows.append(
            {
                "pool": signal.get("pool_id") or "",
                "apy": float(signal.get("apy") or 0.0),
                "apyBase": float(signal.get("apy_base") or 0.0),
                "apyReward": float(signal.get("apy_reward") or 0.0),
                "tvlUsd": float(signal.get("tvl") or 0.0),
            }
        )
    return pd.DataFrame(rows)
