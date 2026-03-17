from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

HISTORY_FILE = Path(__file__).with_name("pool_history.json")
MAX_POINTS_PER_POOL = 90


def _read_raw() -> dict:
    if not HISTORY_FILE.exists():
        return {}
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_history(pool_id: str) -> pd.DataFrame:
    history = _read_raw().get(str(pool_id), [])
    if not history:
        return pd.DataFrame(columns=["timestamp", "apy", "apyBase", "apyReward", "tvlUsd"])
    frame = pd.DataFrame(history)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce", utc=True).dt.tz_localize(None)
    for col in ["apy", "apyBase", "apyReward", "tvlUsd"]:
        if col not in frame.columns:
            frame[col] = 0.0
        frame[col] = pd.to_numeric(frame[col], errors="coerce").fillna(0.0)
    return frame.dropna(subset=["timestamp"]).sort_values("timestamp")


def save_snapshot(df: pd.DataFrame) -> None:
    if df is None or df.empty:
        return
    history = _read_raw()
    timestamp = pd.Timestamp.utcnow().isoformat()
    for _, row in df.iterrows():
        pool_id = str(row.get("pool", "")).strip()
        if not pool_id:
            continue
        points = history.setdefault(pool_id, [])
        points.append({
            "timestamp": timestamp,
            "apy": round(float(row.get("apy", 0.0) or 0.0), 4),
            "apyBase": round(float(row.get("apyBase", 0.0) or 0.0), 4),
            "apyReward": round(float(row.get("apyReward", 0.0) or 0.0), 4),
            "tvlUsd": round(float(row.get("tvlUsd", 0.0) or 0.0), 2),
        })
        history[pool_id] = points[-MAX_POINTS_PER_POOL:]
    HISTORY_FILE.write_text(json.dumps(history, separators=(",", ":")), encoding="utf-8")
