"""Run redacted Supabase configuration and connectivity diagnostics."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from supabase_client import AuthConfigurationError, diagnose_auth_connectivity, healthcheck_auth  # noqa: E402


def main() -> int:
    configuration = healthcheck_auth()
    print(f"configuration: {'pass' if configuration['ok'] else 'fail'}")
    for error in configuration["configuration_errors"]:
        print(f"  - {error}")
    if not configuration["ok"]:
        return 1

    try:
        result = diagnose_auth_connectivity()
    except AuthConfigurationError as exc:
        print("connectivity: not run")
        for error in exc.errors:
            print(f"  - {error}")
        return 1

    for check in result["checks"]:
        state = "pass" if check["ok"] else "fail"
        print(f"{check['name']}: {state} ({check['detail']})")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
