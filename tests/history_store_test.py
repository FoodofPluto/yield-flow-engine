from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pandas as pd

import history_store


def _frame(timestamp: str, count: int = 5, *, apy: float = 5.0) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "pool": [f"pool-{index}" for index in range(count)],
            "apy": [apy] * count,
            "apyBase": [apy - 1] * count,
            "apyReward": [1.0] * count,
            "tvlUsd": [1_000_000.0] * count,
        }
    )
    frame.attrs["retrieved_at"] = timestamp
    return frame


def test_snapshot_store_bounds_pool_count_and_prunes_stale_pools(tmp_path, monkeypatch) -> None:
    destination = tmp_path / "pool_history.json"
    destination.write_text(json.dumps({"stale-pool": [{"timestamp": "old"}]}), encoding="utf-8")
    monkeypatch.setattr(history_store, "HISTORY_FILE", destination)
    monkeypatch.setattr(history_store, "MAX_TRACKED_POOLS", 3)

    history_store.save_snapshot(_frame("2026-08-18T20:00:00+00:00"))

    stored = json.loads(destination.read_text(encoding="utf-8"))
    assert tuple(stored) == ("pool-0", "pool-1", "pool-2")
    assert all(len(points) == 1 for points in stored.values())


def test_snapshot_store_replaces_duplicate_provider_snapshot(tmp_path, monkeypatch) -> None:
    destination = tmp_path / "pool_history.json"
    monkeypatch.setattr(history_store, "HISTORY_FILE", destination)

    history_store.save_snapshot(_frame("2026-08-18T20:00:00+00:00", count=2, apy=5.0))
    history_store.save_snapshot(_frame("2026-08-18T20:00:00+00:00", count=2, apy=6.0))

    stored = json.loads(destination.read_text(encoding="utf-8"))
    assert all(len(points) == 1 for points in stored.values())
    assert stored["pool-0"][0]["apy"] == 6.0


def test_snapshot_store_keeps_only_the_latest_bounded_points(tmp_path, monkeypatch) -> None:
    destination = tmp_path / "pool_history.json"
    monkeypatch.setattr(history_store, "HISTORY_FILE", destination)
    monkeypatch.setattr(history_store, "MAX_POINTS_PER_POOL", 3)

    for minute in range(5):
        history_store.save_snapshot(_frame(f"2026-08-18T20:0{minute}:00+00:00", count=1, apy=float(minute)))

    stored = json.loads(destination.read_text(encoding="utf-8"))
    assert [point["apy"] for point in stored["pool-0"]] == [2.0, 3.0, 4.0]


def test_configured_nested_history_path_is_used_for_save_load_and_replacement(tmp_path, monkeypatch) -> None:
    destination = tmp_path / "nested" / "runtime" / "pool_history.json"
    monkeypatch.setenv(history_store.HISTORY_PATH_ENV, str(destination))

    history_store.save_snapshot(_frame("2026-08-18T20:00:00+00:00", count=1, apy=5.0))

    assert destination.is_file()
    assert not destination.with_suffix(".json.tmp").exists()
    assert history_store.load_history("pool-0")["apy"].tolist() == [5.0]

    history_store.save_snapshot(_frame("2026-08-18T20:01:00+00:00", count=1, apy=6.0))

    stored = json.loads(destination.read_text(encoding="utf-8"))
    assert [point["apy"] for point in stored["pool-0"]] == [5.0, 6.0]
    assert history_store.load_history("pool-0")["apy"].tolist() == [5.0, 6.0]
    assert not destination.with_suffix(".json.tmp").exists()


def test_default_history_path_remains_compatible_without_override(tmp_path, monkeypatch) -> None:
    destination = tmp_path / "pool_history.json"
    monkeypatch.delenv(history_store.HISTORY_PATH_ENV, raising=False)
    monkeypatch.setattr(history_store, "HISTORY_FILE", destination)

    history_store.save_snapshot(_frame("2026-08-18T20:00:00+00:00", count=1))

    assert destination.is_file()
    assert history_store.load_history("pool-0").shape[0] == 1


def test_snapshot_store_retains_configured_pool_limit(tmp_path, monkeypatch) -> None:
    destination = tmp_path / "pool_history.json"
    monkeypatch.setattr(history_store, "HISTORY_FILE", destination)

    history_store.save_snapshot(_frame("2026-08-18T20:00:00+00:00", count=2_001))

    stored = json.loads(destination.read_text(encoding="utf-8"))
    assert history_store.MAX_TRACKED_POOLS == 2_000
    assert len(stored) == 2_000


def test_snapshot_store_retains_configured_point_limit(tmp_path, monkeypatch) -> None:
    destination = tmp_path / "pool_history.json"
    monkeypatch.setattr(history_store, "HISTORY_FILE", destination)

    for minute in range(91):
        timestamp = (datetime(2026, 8, 18, 20, tzinfo=timezone.utc) + timedelta(minutes=minute)).isoformat()
        history_store.save_snapshot(_frame(timestamp, count=1, apy=float(minute)))

    stored = json.loads(destination.read_text(encoding="utf-8"))
    assert history_store.MAX_POINTS_PER_POOL == 90
    assert len(stored["pool-0"]) == 90
    assert stored["pool-0"][0]["apy"] == 1.0
