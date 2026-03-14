from __future__ import annotations

from typing import Any, Dict, List

import requests


YIELDS_URL = "https://yields.llama.fi/pools"


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _protocol_url(project: str | None) -> str:
    if not project:
        return ""
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in project).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return f"https://defillama.com/protocol/{slug}"


def get_yields(limit: int = 200) -> List[Dict[str, Any]]:
    """Return a normalized slice of DeFiLlama pools."""
    resp = requests.get(YIELDS_URL, timeout=25)
    resp.raise_for_status()
    data = resp.json().get("data", [])
    ranked = sorted(
        data,
        key=lambda x: (_safe_float(x.get("tvlUsd")), _safe_float(x.get("apy"))),
        reverse=True,
    )[:limit]

    rows: List[Dict[str, Any]] = []
    for d in ranked:
        rows.append(
            {
                "name": d.get("project") or d.get("poolMeta") or d.get("symbol") or "Unknown",
                "apy": _safe_float(d.get("apy")),
                "apyBase": d.get("apyBase"),
                "apyReward": d.get("apyReward"),
                "apyPct1D": d.get("apyPct1D"),
                "apyPct7D": d.get("apyPct7D"),
                "apyPct30D": d.get("apyPct30D"),
                "tvlUsd": _safe_float(d.get("tvlUsd")),
                "chain": d.get("chain"),
                "project": d.get("project"),
                "pool": d.get("pool"),
                "poolMeta": d.get("poolMeta"),
                "symbol": d.get("symbol"),
                "stablecoin": bool(d.get("stablecoin")),
                "ilRisk": d.get("ilRisk"),
                "category": d.get("category"),
                "exposure": d.get("exposure"),
                "protocol_url": _protocol_url(d.get("project")),
                "llama_pool_url": f"https://defillama.com/yields/pool/{d.get('pool')}" if d.get("pool") else "",
            }
        )
    return rows
