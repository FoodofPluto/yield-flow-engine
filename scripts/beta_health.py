"""Read-only closed-beta readiness report. Run in the trusted web-service shell.

No dotenv loading, credential output, participant queries, or provider mutations.
Exit 0 healthy, 1 degraded, 2 blocked, 3 insufficient evidence.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import sys
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from automation.store import SupabaseAutomationStore  # noqa: E402

CANONICAL = "https://beta.furuflow.com"
SHA = re.compile(r"[0-9a-f]{40}")
STATES = {"healthy": 0, "degraded": 1, "insufficient_evidence": 3, "blocked": 2}


def age(value: Any, now: datetime) -> float | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        seconds = (now - parsed).total_seconds()
        return seconds if seconds >= 0 else None
    except (AttributeError, TypeError, ValueError):
        return None


def check(state: str, **metadata: Any) -> dict[str, Any]:
    return {"state": state, **metadata}


def hosted_signup(project_url: str, anon_key: str, get: Any = requests.get) -> dict[str, Any]:
    # Credentials may only go to the configured hosted Supabase origin.
    if not re.fullmatch(r"https://[a-z0-9]+\.supabase\.co", project_url) or not anon_key:
        return check("insufficient_evidence")
    try:
        response = get(project_url + "/auth/v1/settings", headers={"apikey": anon_key},
                       timeout=15, allow_redirects=False)
        if response.status_code != 200:
            return check("insufficient_evidence")
        value = response.json().get("disable_signup")
        # Only a literal boolean true satisfies the mandatory provider gate.
        return check("healthy" if value is True else "blocked", disable_signup=value if type(value) is bool else None)
    except Exception:
        return check("insufficient_evidence")


def endpoint(url: str, expected: int, get: Any = requests.get) -> dict[str, Any]:
    try:
        response = get(url, timeout=15, allow_redirects=False)
        return check("healthy" if response.status_code == expected else "blocked", http_status=response.status_code)
    except Exception:
        return check("blocked")


def worker_checks(raw: dict[str, Any], now: datetime) -> dict[str, Any]:
    heartbeat_age = age(raw.get("heartbeat_at"), now)
    scan_age = age(raw.get("last_successful_scan_at"), now)
    outcome = raw.get("last_run_outcome")
    worker_state = raw.get("worker_state")
    heartbeat = "insufficient_evidence"
    if heartbeat_age is not None:
        heartbeat = "healthy" if heartbeat_age <= 1200 and worker_state in {"idle", "running"} else "blocked"
    scan = "insufficient_evidence"
    if scan_age is not None:
        scan = "healthy" if scan_age <= 1800 and outcome in {"succeeded", "zero_signals"} else "degraded"
    result = {
        "worker": check(heartbeat, heartbeat_age_seconds=heartbeat_age),
        "scan": check(scan, successful_scan_age_seconds=scan_age,
                      outcome=outcome if outcome in {"succeeded", "zero_signals", "provider_failed", "infrastructure_failed"} else None),
    }
    for key in ("pending_retries", "dead_letter_count_24h", "recent_scan_failures"):
        value = raw.get(key)
        valid = type(value) is int and value >= 0
        result[key] = check(("healthy" if value == 0 else "degraded") if valid else "insufficient_evidence",
                            count=value if valid else None)
    return result


def data_status(path: Path, now: datetime) -> dict[str, Any]:
    """Aggregate the existing ephemeral history; never output pool/user identities."""
    try:
        if path.stat().st_size > 64 * 1024 * 1024:
            return check("insufficient_evidence")
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not raw:
            return check("insufficient_evidence", pools=0)
        fresh = observed = history = 0
        for points in raw.values():
            if not isinstance(points, list) or not points or not all(isinstance(p, dict) for p in points):
                continue
            ages = [a for p in points if (a := age(p.get("timestamp"), now)) is not None]
            fresh += bool(ages and min(ages) <= 1800)
            valid = [p for p in points if age(p.get("timestamp"), now) is not None and all(
                type(p.get(k)) in {int, float} and math.isfinite(p[k]) for k in ("apy", "tvlUsd"))]
            observed += bool(valid)
            history += len({p["timestamp"] for p in valid}) >= 14
        state = "healthy" if fresh == len(raw) and observed == len(raw) else "degraded"
        return check(state, pools=len(raw), fresh_pools=fresh, pools_with_core_observations=observed,
                     pools_with_14_core_observations=history,
                     confidence="not_assessed", scope="web_instance_ephemeral_history")
    except Exception:
        return check("insufficient_evidence")


def report(expected_sha: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    runtime = os.getenv("RENDER_GIT_COMMIT", "")
    valid_runtime = bool(SHA.fullmatch(runtime))
    signup = os.getenv("FURUFLOW_BETA_ALLOW_SIGNUP")
    checks = {
        "build": check("healthy" if runtime == expected_sha else "blocked" if valid_runtime else "insufficient_evidence",
                       expected_sha=expected_sha, runtime_sha=runtime if valid_runtime else None),
        "application_signup": check("healthy" if signup == "false" else "blocked" if signup is not None else "insufficient_evidence"),
        "provider_signup": hosted_signup(os.getenv("SUPABASE_URL", "").rstrip("/"), os.getenv("SUPABASE_ANON_KEY", "")),
        "nginx_tls": endpoint(CANONICAL + "/healthz", 200),
        "streamlit_tls": endpoint(CANONICAL + "/_stcore/health", 200),
        "private_session_boundary": endpoint(CANONICAL + "/v1/session/restore", 404),
        "broker_rejects_anonymous": endpoint("http://127.0.0.1:8510/v1/session/restore", 401),
        "data": data_status(Path(os.getenv("FURUFLOW_HISTORY_PATH", "/tmp/furuflow/pool_history.json")), now),
    }
    try:
        checks.update(worker_checks(SupabaseAutomationStore().health(stale_after_seconds=1200), now))
    except Exception:
        checks.update(worker_checks({}, now))
    states = {value["state"] for value in checks.values()}
    state = next(s for s in ("blocked", "insufficient_evidence", "degraded", "healthy") if s in states)
    return {"observed_at": now.isoformat(), "state": state, "checks": checks,
            "operator_alerts": [name for name, value in checks.items() if value["state"] != "healthy"]}


def scheduled_report() -> dict[str, Any]:
    """Extend the existing worker schedule; failures use Render job notifications.

    This narrower report does not attest web runtime settings, build, or history.
    The existing worker credential stays within its own Supabase project.
    """
    now = datetime.now(timezone.utc)
    checks = {
        "provider_signup": hosted_signup(os.getenv("SUPABASE_URL", "").rstrip("/"),
                                         os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")),
        "nginx_tls": endpoint(CANONICAL + "/healthz", 200),
        "streamlit_tls": endpoint(CANONICAL + "/_stcore/health", 200),
    }
    try:
        checks.update(worker_checks(SupabaseAutomationStore().health(stale_after_seconds=1200), now))
    except Exception:
        checks.update(worker_checks({}, now))
    states = {value["state"] for value in checks.values()}
    state = next(s for s in ("blocked", "insufficient_evidence", "degraded", "healthy") if s in states)
    return {"observed_at": now.isoformat(), "scope": "scheduled_worker_and_public_health", "state": state,
            "checks": checks, "operator_alerts": [name for name, value in checks.items() if value["state"] != "healthy"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--expected-sha")
    mode.add_argument("--scheduled", action="store_true")
    args = parser.parse_args()
    if args.expected_sha and not SHA.fullmatch(args.expected_sha):
        parser.error("expected SHA must be 40 lowercase hexadecimal characters")
    result = scheduled_report() if args.scheduled else report(args.expected_sha)
    print(json.dumps(result, sort_keys=True))
    return STATES[result["state"]]


if __name__ == "__main__":
    raise SystemExit(main())
