from __future__ import annotations

from typing import Any, Dict, Iterable, List


def _fmt_tvl(value: Any) -> str:
    try:
        num = float(value or 0.0)
    except Exception:
        return str(value)
    if num >= 1_000_000_000:
        return f"${num/1_000_000_000:.2f}B"
    if num >= 1_000_000:
        return f"${num/1_000_000:.2f}M"
    if num >= 1_000:
        return f"${num/1_000:.2f}K"
    return f"${num:.0f}"


def format_x_signal_post(signal: Dict[str, Any], include_link: bool = False) -> str:
    name = str(signal.get("name") or "Unknown")
    chain = str(signal.get("chain") or "Unknown")
    apy = float(signal.get("apy") or 0.0)
    tvl = _fmt_tvl(signal.get("tvl") or 0.0)
    strength = int(signal.get("strength_score") or 0)
    risk = str(signal.get("risk_label") or "Unknown")
    why = str(signal.get("reason") or "Matched FuruFlow filters")
    parts = [
        "🔥 FuruFlow Signal",
        "",
        f"{name}",
        f"Chain: {chain}",
        f"APY: {apy:.2f}% | TVL: {tvl}",
        f"Strength: {strength}/100",
        f"Risk: {risk}",
        "",
        f"Why: {why}",
    ]
    link = str(signal.get("pool_url") or signal.get("llama_pool_url") or signal.get("protocol_url") or "").strip()
    if include_link and link:
        parts += ["", link]
    parts += ["", "#FuruFlow #YieldSignals"]
    return "\n".join(parts)


def format_x_recap_post(title: str, rows: Iterable[Dict[str, Any]], limit: int = 3) -> str:
    lines: List[str] = [title, ""]
    for i, row in enumerate(list(rows)[:limit], start=1):
        name = str(row.get("name") or row.get("project") or "Unknown")
        apy = float(row.get("apy") or 0.0)
        chain = str(row.get("chain") or "Unknown")
        score = int(float(row.get("strength_score") or row.get("score") or 0))
        lines.append(f"{i}. {name} — {apy:.2f}% | {chain} | {score}/100")
    lines += ["", "Track more in Telegram + app", "#FuruFlow #YieldSignals"]
    return "\n".join(lines)
