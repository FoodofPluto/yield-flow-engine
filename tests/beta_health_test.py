from datetime import datetime, timedelta, timezone
import json

import pytest

from scripts import beta_health as health

NOW = datetime(2026, 9, 11, 12, tzinfo=timezone.utc)


@pytest.mark.parametrize("value,state", [(True, "healthy"), (False, "blocked"), (None, "blocked"),
                                        ("true", "blocked"), (1, "blocked")])
def test_hosted_gate_requires_literal_true(value, state):
    class Response:
        status_code = 200

        def json(self):
            return {"disable_signup": value, "secret": "never-output"}

    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    result = health.hosted_signup("https://project.supabase.co", "test-key", get)
    assert result["state"] == state
    assert calls[0][1]["allow_redirects"] is False
    assert "never-output" not in json.dumps(result)


def test_hosted_gate_redacts_network_errors_and_rejects_credential_redirects():
    def fail(*args, **kwargs):
        raise RuntimeError("secret-token")

    result = health.hosted_signup("https://project.supabase.co", "test-key", fail)
    assert result == {"state": "insufficient_evidence"}
    assert health.hosted_signup("https://project.supabase.co.evil.test", "test-key", fail) == result


def test_worker_missing_stale_failed_and_retry_evidence():
    assert all(c["state"] == "insufficient_evidence" for c in health.worker_checks({}, NOW).values())
    raw = {"heartbeat_at": (NOW - timedelta(minutes=30)).isoformat(), "worker_state": "idle",
           "last_successful_scan_at": (NOW - timedelta(hours=1)).isoformat(), "last_run_outcome": "provider_failed",
           "pending_retries": 2, "dead_letter_count_24h": 1, "recent_scan_failures": 1, "user_id": "private"}
    result = health.worker_checks(raw, NOW)
    assert result["worker"]["state"] == "blocked"
    assert result["scan"]["state"] == "degraded"
    assert result["pending_retries"]["state"] == "degraded"
    assert "private" not in json.dumps(result)


def test_data_is_aggregate_and_does_not_claim_confidence(tmp_path):
    path = tmp_path / "history.json"
    assert health.data_status(path, NOW)["state"] == "insufficient_evidence"
    path.write_text(json.dumps({"private-pool": [{"timestamp": NOW.isoformat(), "apy": 2, "tvlUsd": 100}]}))
    result = health.data_status(path, NOW)
    assert result["fresh_pools"] == 1
    assert result["pools_with_14_core_observations"] == 0
    assert result["confidence"] == "not_assessed"
    assert "private-pool" not in json.dumps(result)
    path.write_text(json.dumps({"pool": [{"timestamp": (NOW - timedelta(hours=2)).isoformat(), "apy": None}]}))
    assert health.data_status(path, NOW)["state"] == "degraded"


def test_future_and_naive_timestamps_are_not_fresh():
    assert health.age((NOW + timedelta(seconds=1)).isoformat(), NOW) is None
    assert health.age("2026-09-11T12:00:00", NOW) is None


def test_report_missing_runtime_cannot_pass_and_never_outputs_environment(monkeypatch):
    monkeypatch.setattr(health, "endpoint", lambda *a: health.check("healthy"))
    monkeypatch.setattr(health, "hosted_signup", lambda *a: health.check("healthy"))
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "private-credential")
    monkeypatch.setattr(health, "SupabaseAutomationStore", lambda: (_ for _ in ()).throw(RuntimeError("secret")))
    result = health.report("a" * 40)
    assert result["state"] != "healthy"
    assert result["checks"]["build"]["runtime_sha"] is None
    assert "private-credential" not in json.dumps(result)


def test_scheduled_signup_drift_fails_even_when_worker_and_web_are_healthy(monkeypatch):
    monkeypatch.setattr(health, "endpoint", lambda *a: health.check("healthy"))
    monkeypatch.setattr(health, "hosted_signup", lambda *a: health.check("blocked", disable_signup=False))
    monkeypatch.setattr(health, "worker_checks", lambda *a: {"worker": health.check("healthy")})
    monkeypatch.setattr(health, "SupabaseAutomationStore", lambda: (_ for _ in ()).throw(RuntimeError()))
    result = health.scheduled_report()
    assert result["state"] == "blocked"
    assert result["operator_alerts"] == ["provider_signup"]
