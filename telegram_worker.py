from __future__ import annotations

import argparse
import json
import logging
import os

from automation.store import SupabaseAutomationStore
from automation.telegram import TelegramClient
from automation.worker import AutomationWorker, WorkerConfig, default_scanner


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the durable FuruFlow Telegram automation worker.")
    parser.add_argument("command", nargs="?", choices=("run", "drain", "health", "test"), default="run")
    parser.add_argument("--invocation-key", help="Stable scheduler key; defaults to the current schedule slot.")
    parser.add_argument("--test-key", help="Operator-supplied idempotency key for one controlled staging test.")
    return parser


def main() -> int:
    args = _parser().parse_args()
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(levelname)s %(message)s")
    config = WorkerConfig.from_env()
    store = SupabaseAutomationStore()
    if args.command == "health":
        print(json.dumps(store.health(stale_after_seconds=config.health_stale_after_seconds), sort_keys=True))
        return 0
    if not config.enabled:
        store.heartbeat(run_id=None, worker_id="disabled", state="disabled")
        print(json.dumps({"outcome": "disabled"}, sort_keys=True))
        return 0

    if args.command == "test":
        if config.environment not in {"development", "staging", "test"}:
            raise RuntimeError("Controlled test delivery is forbidden outside development, staging, or test.")
        if os.getenv("FURUFLOW_ALLOW_TEST_DELIVERY", "").strip().lower() not in {"1", "true", "yes", "on"}:
            raise RuntimeError("FURUFLOW_ALLOW_TEST_DELIVERY=true is required for a controlled test.")
        chat_id = os.getenv("FURUFLOW_TEST_TELEGRAM_CHAT_ID", "").strip()
        test_key = (args.test_key or os.getenv("FURUFLOW_TEST_NOTIFICATION_KEY") or "").strip()
        if not chat_id or len(test_key) < 8:
            raise RuntimeError("FURUFLOW_TEST_TELEGRAM_CHAT_ID and an 8+ character test key are required.")
        inserted = store.enqueue_staging_test(chat_id=chat_id, test_key=test_key, environment=config.environment)
        worker = AutomationWorker(
            store=store, telegram=TelegramClient(), scanner=lambda: [], config=config
        )
        result = worker.drain_deliveries()
        print(json.dumps({"enqueued": int(inserted), **result}, sort_keys=True))
        return 0

    worker = AutomationWorker(
        store=store,
        telegram=TelegramClient(),
        scanner=default_scanner,
        config=config,
    )
    result = worker.run_scan(invocation_key=args.invocation_key) if args.command == "run" else worker.drain_deliveries()
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
