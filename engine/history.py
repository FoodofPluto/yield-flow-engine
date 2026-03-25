from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

SIGNAL_HISTORY_FILE = Path("signal_history.csv")

FIELDNAMES = [
    "timestamp",
    "date",
    "week",
    "pool_id",
    "name",
    "project",
    "symbol",
    "chain",
    "category",
    "source",
    "apy",
    "tvl",
    "strength_score",
    "strength_label",
    "risk_score",
    "risk_label",
    "signal",
    "trend_score",
    "tier",
    "protocol_url",
    "pool_url",
    "reason",
    "risk_tags",
]


def _normalize_row(signal: Dict[str, Any], timestamp: datetime | None = None) -> Dict[str, Any]:
    ts = timestamp or datetime.now(timezone.utc)
    return {
        "timestamp": ts.isoformat(),
        "date": ts.date().isoformat(),
        "week": f"{ts.isocalendar().year}-W{ts.isocalendar().week:02d}",
        "pool_id": str(signal.get("pool_id") or "").strip(),
        "name": str(signal.get("name") or "").strip(),
        "project": str(signal.get("project") or "").strip(),
        "symbol": str(signal.get("symbol") or "").strip(),
        "chain": str(signal.get("chain") or "").strip(),
        "category": str(signal.get("category") or "").strip(),
        "source": str(signal.get("source") or "").strip(),
        "apy": float(signal.get("apy") or 0.0),
        "tvl": float(signal.get("tvl") or 0.0),
        "strength_score": int(signal.get("strength_score") or 0),
        "strength_label": str(signal.get("strength_label") or "").strip(),
        "risk_score": int(signal.get("risk_score") or 0),
        "risk_label": str(signal.get("risk_label") or "").strip(),
        "signal": str(signal.get("signal") or "").strip(),
        "trend_score": float(signal.get("trend_score") or 0.0),
        "tier": str(signal.get("tier") or "").strip(),
        "protocol_url": str(signal.get("protocol_url") or "").strip(),
        "pool_url": str(signal.get("pool_url") or signal.get("llama_pool_url") or "").strip(),
        "reason": str(signal.get("reason") or "").strip(),
        "risk_tags": ", ".join([str(tag).strip() for tag in (signal.get("risk_tags") or []) if str(tag).strip()]),
    }


def append_signal_history(signals: Iterable[Dict[str, Any]], path: Path | str = SIGNAL_HISTORY_FILE) -> Path:
    path = Path(path)
    rows: List[Dict[str, Any]] = [_normalize_row(signal) for signal in signals]
    if not rows:
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)
    return path
