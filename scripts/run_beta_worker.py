"""Run the existing worker, then read-only readiness checks, without shell parsing."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    worker = subprocess.run([sys.executable, str(root / "telegram_worker.py"), "run"], check=False, cwd=root)
    if worker.returncode:
        return worker.returncode
    health = subprocess.run([sys.executable, str(root / "scripts/beta_health.py"), "--scheduled"],
                            check=False, cwd=root)
    return health.returncode


if __name__ == "__main__":
    raise SystemExit(main())
