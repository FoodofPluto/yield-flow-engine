from __future__ import annotations

import csv
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List

from engine.history import SIGNAL_HISTORY_FILE


def _read_rows(path: Path | str = SIGNAL_HISTORY_FILE) -> List[Dict[str, str]]:
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _rows_since(days: int, path: Path | str = SIGNAL_HISTORY_FILE) -> List[Dict[str, str]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows: List[Dict[str, str]] = []
    for row in _read_rows(path):
        try:
            ts = datetime.fromisoformat(str(row.get("timestamp") or "").replace("Z", "+00:00"))
        except Exception:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts >= cutoff:
            rows.append(row)
    return rows


def _signal_key(row: Dict[str, str]) -> str:
    # Prefer the most unique identifier available.
    return (
        row.get("pool_id")
        or row.get("link")
        or f"{row.get('name','')}|{row.get('chain','')}"
    )


def _sort_key(row: Dict[str, str]):
    return (
        int(float(row.get("strength_score") or 0)),
        float(row.get("apy") or 0.0),
        float(row.get("tvl") or 0.0),
        str(row.get("timestamp") or ""),
    )


def _dedupe_rows(rows: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    best_by_key: Dict[str, Dict[str, str]] = {}

    for row in rows:
        key = _signal_key(row)
        existing = best_by_key.get(key)
        if existing is None or _sort_key(row) > _sort_key(existing):
            best_by_key[key] = row

    return list(best_by_key.values())


def _top_by_score(rows: Iterable[Dict[str, str]], limit: int = 3) -> List[Dict[str, str]]:
    items = _dedupe_rows(rows)
    items.sort(key=_sort_key, reverse=True)
    return items[:limit]


def build_daily_recap(path: Path | str = SIGNAL_HISTORY_FILE) -> str:
    rows = _rows_since(1, path)
    if not rows:
        return "No signals were logged in the last 24 hours."

    unique_rows = _dedupe_rows(rows)
    top = _top_by_score(unique_rows, 3)
    chains = Counter((row.get("chain") or "Unknown") for row in unique_rows)
    best_chain, best_chain_count = chains.most_common(1)[0]

    lines = ["🔥 FuruFlow Daily Recap", ""]
    for idx, row in enumerate(top, start=1):
        lines.extend([
            f"{idx}. {row.get('name') or 'Unknown'}",
            f"   Chain: {row.get('chain') or 'Unknown'}",
            f"   APY: {float(row.get('apy') or 0.0):.2f}% | TVL: ${float(row.get('tvl') or 0.0):,.0f}",
            f"   Score: {int(float(row.get('strength_score') or 0))}/100 | Tier: {row.get('tier') or 'Free'}",
            f"   Risk: {row.get('risk_label') or 'Unknown'}",
            "",
        ])
    lines.append(f"Best chain today: {best_chain} ({best_chain_count} qualifying signal{'s' if best_chain_count != 1 else ''})")
    lines.append("#FuruFlow #YieldSignals")
    return "\n".join(lines)


def build_weekly_recap(path: Path | str = SIGNAL_HISTORY_FILE) -> str:
    rows = _rows_since(7, path)
    if not rows:
        return "No signals were logged in the last 7 days."

    unique_rows = _dedupe_rows(rows)
    top = _top_by_score(unique_rows, 5)
    chains = Counter((row.get("chain") or "Unknown") for row in unique_rows)
    tiers = Counter((row.get("tier") or "Unknown") for row in unique_rows)

    lines = [
        "📈 FuruFlow Weekly Recap",
        "",
        f"Signals logged: {len(unique_rows)}",
        f"Free vs Pro: {tiers.get('Free', 0)} Free / {tiers.get('Pro', 0)} Pro",
        "",
    ]
    for idx, row in enumerate(top, start=1):
        lines.append(
            f"{idx}. {row.get('name') or 'Unknown'} — {float(row.get('apy') or 0.0):.2f}% APY | {row.get('chain') or 'Unknown'} | {int(float(row.get('strength_score') or 0))}/100"
        )
    lines.append("")
    lines.append("Top chains: " + ", ".join(f"{name} ({count})" for name, count in chains.most_common(3)))
    lines.append("#FuruFlow #YieldSignals")
    return "\n".join(lines)