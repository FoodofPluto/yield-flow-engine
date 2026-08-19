from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import tempfile
import threading
import uuid

import pandas as pd

LOGGER = logging.getLogger(__name__)
HISTORY_PATH_ENV = "FURUFLOW_HISTORY_PATH"
RUNTIME_DATA_DIR_ENV = "FURUFLOW_RUNTIME_DATA_DIR"
HISTORY_FILE = Path(tempfile.gettempdir()) / "furuflow" / "pool_history.json"
MAX_POINTS_PER_POOL = 90
MAX_TRACKED_POOLS = 2_000
_HISTORY_LOCK = threading.Lock()


def _history_file() -> Path:
    configured = os.getenv(HISTORY_PATH_ENV, "").strip()
    if configured:
        return Path(configured)
    runtime_directory = os.getenv(RUNTIME_DATA_DIR_ENV, "").strip()
    if runtime_directory:
        return Path(runtime_directory) / "pool_history.json"
    return HISTORY_FILE


def _read_raw(history_file: Path | None = None) -> dict:
    history_file = history_file or _history_file()
    if not history_file.exists():
        return {}
    try:
        value = json.loads(history_file.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        LOGGER.warning("History snapshot could not be loaded (%s).", type(exc).__name__)
        return {}


def _temporary_history_file(history_file: Path) -> Path:
    return history_file.with_name(f".{history_file.name}.{uuid.uuid4().hex}.tmp")


def _replace_history_file(temporary: Path, history_file: Path) -> None:
    for attempt in range(3):
        try:
            temporary.replace(history_file)
            return
        except PermissionError:
            # Windows file scanners can briefly hold a just-written file.
            # Bounded immediate retries preserve atomicity without delaying UI.
            if attempt == 2:
                raise


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


def save_snapshot(df: pd.DataFrame) -> bool:
    if df is None or df.empty:
        return True

    snapshot = df.head(MAX_TRACKED_POOLS)
    timestamp = str(df.attrs.get("retrieved_at") or pd.Timestamp.utcnow().isoformat())
    pool_ids = tuple(dict.fromkeys(str(value).strip() for value in snapshot["pool"] if str(value).strip()))

    with _HISTORY_LOCK:
        history_file = _history_file()
        existing = _read_raw(history_file)
        history = {pool_id: list(existing.get(pool_id, [])) for pool_id in pool_ids}
        for _, row in snapshot.iterrows():
            pool_id = str(row.get("pool", "")).strip()
            if not pool_id:
                continue
            point = {
                "timestamp": timestamp,
                "apy": round(float(row.get("apy", 0.0) or 0.0), 4),
                "apyBase": round(float(row.get("apyBase", 0.0) or 0.0), 4),
                "apyReward": round(float(row.get("apyReward", 0.0) or 0.0), 4),
                "tvlUsd": round(float(row.get("tvlUsd", 0.0) or 0.0), 2),
            }
            points = history.setdefault(pool_id, [])
            if points and points[-1].get("timestamp") == timestamp:
                points[-1] = point
            else:
                points.append(point)
            history[pool_id] = points[-MAX_POINTS_PER_POOL:]

        temporary = _temporary_history_file(history_file)
        operation = "directory preparation"
        try:
            history_file.parent.mkdir(parents=True, exist_ok=True)
            operation = "temporary write"
            temporary.write_text(json.dumps(history, separators=(",", ":")), encoding="utf-8")
            operation = "atomic replace"
            _replace_history_file(temporary, history_file)
        except OSError as exc:
            LOGGER.warning("History snapshot could not be persisted during %s (%s).", operation, type(exc).__name__)
            try:
                temporary.unlink(missing_ok=True)
            except OSError as cleanup_exc:
                LOGGER.warning("Incomplete history snapshot cleanup failed (%s).", type(cleanup_exc).__name__)
            return False
    return True
