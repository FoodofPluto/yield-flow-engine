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


def format_signal(signal: Dict[str, Any]) -> str:
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

    return (
        f"🔥 FuruFlow Signal\n\n"
        f"Pool: {name}\n"
        f"Chain: {chain}\n"
        f"APY: {apy}%\n"
        f"TVL: {tvl}\n"
        f"Category: {category}\n"
        f"Source: {source}\n"
        f"Signal: {trend}\n"
        f"Strength: {strength_score}/100 ({strength_label})\n"
        f"Risk: {risk}\n"
        f"Risk tags: {tags}\n\n"
        f"Reason: {reason}\n"
        f"Trend: {trend_summary}\n\n"
        f"#FuruFlow #DeFi #Yield"
    )


def format_multiple_signals(signals: List[Dict[str, Any]]) -> str:
    if not signals:
        return "No FuruFlow signals found right now."

    lines = ["🔥 FuruFlow Signals", ""]
    for i, s in enumerate(signals[:5], start=1):
        name = s.get("name", "Unknown Pool")
        chain = s.get("chain", "Unknown")
        apy = s.get("apy", "N/A")
        tvl = format_usd(s.get("tvl", 0))
        risk = s.get("risk_label", "Unknown")
        signal_name = s.get("signal", "Steady")
        strength_score = s.get("strength_score", 0)
        strength_label = s.get("strength_label", "Watch")
        reason = s.get("reason", "Matched FuruFlow filters")
        trend_summary = s.get("trend_summary", "")
        tags = _safe_tags(s.get("risk_tags", []))
        tier = s.get("tier", "Free")
        link = s.get("pool_url") or s.get("llama_pool_url") or s.get("protocol_url") or ""
        lines.extend(
            [
                f"{i}. {name}",
                f"   Chain: {chain}",
                f"   APY: {apy}% | TVL: {tvl}",
                f"   Signal: {signal_name}",
                f"   Strength: {strength_score}/100 ({strength_label})",
                f"   Risk: {risk} | Tags: {tags}",
                f"   Tier: {tier}",
                f"   Why: {reason}",
                f"   Trend: {trend_summary}",
                *( [f"   Link: {link}"] if link else [] ),
                "",
            ]
        )

    lines.append("#FuruFlow #YieldSignals")
    return "\n".join(lines)
