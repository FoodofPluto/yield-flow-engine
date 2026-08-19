from __future__ import annotations

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
