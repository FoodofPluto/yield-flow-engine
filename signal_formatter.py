from __future__ import annotations

from typing import Any, Dict, List


def format_usd(value: Any) -> str:
    try:
        value = float(value)
        if value >= 1_000_000_000:
            return f"${value / 1_000_000_000:.2f}B"
        if value >= 1_000_000:
            return f"${value / 1_000_000:.2f}M"
        if value >= 1_000:
            return f"${value / 1_000:.2f}K"
        return f"${value:.2f}"
    except Exception:
        return str(value)


def _safe_tags(tags: List[str]) -> str:
    cleaned = [str(tag).strip() for tag in tags if str(tag).strip()]
    return ", ".join(cleaned[:3]) if cleaned else "none"


def signal_lane(signal: Dict[str, Any]) -> str:
    risk_score = float(signal.get("risk_score") or 0.0)
    strength_score = float(signal.get("strength_score") or 0.0)
    apy = float(signal.get("apy") or 0.0)
    risk_label = str(signal.get("risk_label") or "").strip().lower()

    if risk_score >= 90 or risk_label in {"extreme", "very high"}:
        return "degen"
    if strength_score >= 60 or apy >= 25:
        return "strong"
    return "watch"


def lane_title(lane: str) -> str:
    titles = {
        "strong": "🚨 FuruFlow Strong Alerts",
        "watch": "👀 FuruFlow Watchlist",
        "degen": "💀 FuruFlow Degen Radar",
    }
    return titles.get(lane, "🔥 FuruFlow Signals")


def _lane_note(lane: str) -> str:
    notes = {
        "strong": "High-conviction setups with strong yield + liquidity.",
        "watch": "Worth monitoring, but not top-tier conviction yet.",
        "degen": "Extreme-risk pools for APY hunters. Speculative, volatile, and not safe plays.",
    }
    return notes.get(lane, "")


def format_signal(signal: Dict[str, Any]) -> str:
    lane = signal_lane(signal)
    name = signal.get("name", "Unknown Pool")
    chain = signal.get("chain", "Unknown")
    apy = signal.get("apy", "N/A")
    tvl = format_usd(signal.get("tvl", 0))
    category = signal.get("category", "Unknown")
    source = signal.get("source", "Unknown")
    reason = signal.get("reason", "Matched FuruFlow filters")
    risk = signal.get("risk_label", "Unknown")
    strength_score = signal.get("strength_score", 0)
    strength_label = signal.get("strength_label", "Watch")
    trend = signal.get("signal", "Steady")
    trend_summary = signal.get("trend_summary", "")
    tags = _safe_tags(signal.get("risk_tags", []))
    link = signal.get("pool_url") or signal.get("llama_pool_url") or signal.get("protocol_url") or ""

    parts = [
        lane_title(lane),
        "",
        _lane_note(lane),
        "",
        f"Pool: {name}",
        f"Chain: {chain}",
        f"APY: {apy}%",
        f"TVL: {tvl}",
        f"Category: {category}",
        f"Source: {source}",
        f"Signal: {trend}",
        f"Strength: {strength_score}/100 ({strength_label})",
        f"Risk: {risk}",
        f"Risk tags: {tags}",
        "",
        f"Why: {reason}",
        f"Trend: {trend_summary}",
    ]
    if link:
        parts += ["", link]
    if lane == "degen":
        parts += ["", "⚠️ Degen Radar = attention, not endorsement."]
    parts += ["", "#FuruFlow #DeFi #Yield"]
    return "\n".join(parts)


def _format_signal_lines(index: int, signal: Dict[str, Any]) -> List[str]:
    name = signal.get("name", "Unknown Pool")
    chain = signal.get("chain", "Unknown")
    apy = signal.get("apy", "N/A")
    tvl = format_usd(signal.get("tvl", 0))
    risk = signal.get("risk_label", "Unknown")
    signal_name = signal.get("signal", "Steady")
    strength_score = signal.get("strength_score", 0)
    strength_label = signal.get("strength_label", "Watch")
    reason = signal.get("reason", "Matched FuruFlow filters")
    trend_summary = signal.get("trend_summary", "")
    tags = _safe_tags(signal.get("risk_tags", []))
    tier = signal.get("tier", "Free")
    link = signal.get("pool_url") or signal.get("llama_pool_url") or signal.get("protocol_url") or ""
    lane = signal_lane(signal)

    label = {
        "strong": "🚨 Strong Alert",
        "watch": "👀 Watchlist",
        "degen": "💀 Degen Radar",
    }.get(lane, "🔥 Signal")

    lines = [
        f"{index}. {name}",
        f"   Label: {label}",
        f"   Chain: {chain}",
        f"   APY: {apy}% | TVL: {tvl}",
        f"   Signal: {signal_name}",
        f"   Strength: {strength_score}/100 ({strength_label})",
        f"   Risk: {risk} | Tags: {tags}",
        f"   Tier: {tier}",
        f"   Why: {reason}",
        f"   Trend: {trend_summary}",
    ]
    if link:
        lines.append(f"   Link: {link}")
    if lane == "degen":
        lines.append("   Warning: speculative pool, not a safe play")
    lines.append("")
    return lines


def format_multiple_signals(signals: List[Dict[str, Any]]) -> str:
    if not signals:
        return "No FuruFlow signals found right now."

    lanes = [signal_lane(s) for s in signals[:5]]
    unique_lanes: List[str] = []
    for lane in lanes:
        if lane not in unique_lanes:
            unique_lanes.append(lane)

    if len(unique_lanes) == 1:
        header = lane_title(unique_lanes[0])
        note = _lane_note(unique_lanes[0])
        lines = [header, "", note, ""] if note else [header, ""]
    else:
        lines = [
            "🔥 FuruFlow Signals",
            "",
            "Mixed board: strong setups, watchlist names, and higher-risk pools.",
            "",
        ]

    for i, s in enumerate(signals[:5], start=1):
        lines.extend(_format_signal_lines(i, s))

    if "degen" in unique_lanes:
        lines.extend(["⚠️ Degen Radar entries are posted for visibility, not endorsement.", ""])

    lines.append("#FuruFlow #YieldSignals")
    return "\n".join(lines)
