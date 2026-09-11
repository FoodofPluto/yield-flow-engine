from __future__ import annotations

from pathlib import Path

import pytest

from engine.performance import SignalHistoryReadError, latest_signal_history, load_signal_history


def test_missing_signal_history_is_a_legitimate_empty_state(tmp_path) -> None:
    assert load_signal_history(tmp_path / "missing.csv").empty


def test_populated_signal_history_remains_readable_and_ranked(tmp_path) -> None:
    history_file = tmp_path / "signals.csv"
    history_file.write_text(
        "pool_id,name,chain,apy,tvl,strength_score,risk_score,trend_score,tier,timestamp\n"
        "pool-a,Pool A,Ethereum,5.0,1000000,40,20,30,Free,2026-08-18T20:00:00+00:00\n"
        "pool-b,Pool B,Base,7.0,2000000,60,30,40,Pro,2026-08-18T21:00:00+00:00\n",
        encoding="utf-8",
    )
    populated = latest_signal_history(limit=1, path=history_file)

    assert populated["pool_id"].tolist() == ["pool-b"]


def test_signal_history_storage_failure_is_not_reported_as_empty(tmp_path, monkeypatch) -> None:
    history_file = tmp_path / "signals.csv"
    history_file.write_text("pool_id,name\npool-a,Pool A\n", encoding="utf-8")

    def denied_open(_path: Path, *_args, **_kwargs):
        raise PermissionError("simulated storage outage")

    monkeypatch.setattr(Path, "open", denied_open)

    with pytest.raises(SignalHistoryReadError, match="temporarily unavailable"):
        load_signal_history(history_file)
