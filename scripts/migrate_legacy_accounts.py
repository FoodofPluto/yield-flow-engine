from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx

from account_control import AccountOperationError, ServiceRoleAccountClient


PRIVILEGES = ("pro", "lifetime", "admin")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _verified_auth_user(user_id: str, service_key: str) -> dict[str, Any]:
    project_url = os.environ["SUPABASE_URL"].rstrip("/")
    response = httpx.get(
        f"{project_url}/auth/v1/admin/users/{user_id}",
        headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"},
        timeout=10.0,
    )
    if response.status_code != 200:
        raise AccountOperationError("Mapped Supabase identity could not be verified.")
    body = response.json()
    if str(body.get("id")) != user_id or not body.get("email_confirmed_at") or body.get("deleted_at"):
        raise AccountOperationError("Mapped Supabase identity is not verified and active.")
    return body


def _legacy_rows(sqlite_path: Path) -> dict[str, sqlite3.Row]:
    uri = f"file:{sqlite_path.resolve().as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        return {str(row["user_id"]): row for row in connection.execute("select * from users")}
    finally:
        connection.close()


def _validate_mapping(entry: dict[str, Any]) -> tuple[str, str, dict[str, bool]]:
    legacy_id = str(entry["legacy_user_id"])
    target_id = str(UUID(entry["supabase_user_id"]))
    reviewed = entry.get("reviewed_entitlements")
    if not isinstance(reviewed, dict) or set(reviewed) != set(PRIVILEGES) or not all(
        isinstance(reviewed[name], bool) for name in PRIVILEGES
    ):
        raise ValueError("Every mapping requires explicit boolean admin, pro, and lifetime review decisions.")
    return legacy_id, target_id, reviewed


def migrate(args: argparse.Namespace) -> int:
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not service_key:
        raise AccountOperationError("SUPABASE_SERVICE_ROLE_KEY is required in this trusted CLI only.")
    mappings = _load_json(args.mapping)
    if not isinstance(mappings, list):
        raise ValueError("Mapping must be a JSON list.")
    legacy = _legacy_rows(args.sqlite)
    client = ServiceRoleAccountClient(service_role_key=service_key)
    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(args.sqlite),
        "applied": bool(args.apply),
        "records": [],
    }
    rollback: dict[str, Any] = {"generated_at": report["generated_at"], "records": []}
    seen_targets: set[str] = set()
    for entry in mappings:
        legacy_id, target_id, reviewed = _validate_mapping(entry)
        if target_id == args.actor_user_id and not reviewed["admin"]:
            raise ValueError("The migration cannot remove its own verified administrator actor.")
        if target_id in seen_targets:
            raise ValueError("Each Supabase user ID may appear only once.")
        seen_targets.add(target_id)
        row = legacy.get(legacy_id)
        if row is None:
            raise ValueError(f"Legacy user ID {legacy_id} does not exist.")
        auth_user = _verified_auth_user(target_id, service_key)
        if (auth_user.get("email") or "").strip().lower() != (row["email"] or "").strip().lower():
            raise AccountOperationError("Reviewed UUID mapping does not match the verified legacy account email.")
        prior = client.get_entitlement(target_id)
        rollback["records"].append(
            {
                "supabase_user_id": target_id,
                "entitlements": {
                    "admin": bool(prior.get("is_admin")),
                    "pro": bool(prior.get("pro_active")),
                    "lifetime": bool(prior.get("lifetime_access")),
                },
            }
        )
        record = {
            "legacy_user_id": legacy_id,
            "supabase_user_id": target_id,
            "reviewed_entitlements": reviewed,
            "legacy_privileges_observed": {
                "admin": bool(row["is_admin"]),
                "pro": bool(row["pro_active"]),
                "lifetime": bool(row["lifetime_access"]),
            },
            "result": "planned",
        }
        if args.apply:
            for name in PRIVILEGES:
                client.set_entitlement(
                    target_user_id=target_id,
                    entitlement=name,
                    enabled=reviewed[name],
                    actor_user_id=args.actor_user_id,
                    reason="reviewed_legacy_migration",
                    source="legacy_migration",
                )
            record["result"] = "applied"
        report["records"].append(record)
    _write_json(args.report, report)
    _write_json(args.rollback_out, rollback)
    print(f"Migration records reviewed: {len(report['records'])}; applied: {args.apply}")
    return 0


def rollback(args: argparse.Namespace) -> int:
    records = _load_json(args.rollback)["records"]
    client = ServiceRoleAccountClient()
    for record in records:
        target_id = str(UUID(record["supabase_user_id"]))
        for name in PRIVILEGES:
            client.set_entitlement(
                target_user_id=target_id,
                entitlement=name,
                enabled=bool(record["entitlements"][name]),
                actor_user_id=args.actor_user_id,
                reason="legacy_migration_rollback",
            )
    print(f"Rollback records applied: {len(records)}")
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Reviewed, UUID-bound SQLite-to-Supabase account migration.")
    sub = result.add_subparsers(dest="command", required=True)
    run = sub.add_parser("migrate")
    run.add_argument("--sqlite", type=Path, required=True)
    run.add_argument("--mapping", type=Path, required=True)
    run.add_argument("--report", type=Path, required=True)
    run.add_argument("--rollback-out", type=Path, required=True)
    run.add_argument("--actor-user-id", type=str, required=True)
    run.add_argument("--apply", action="store_true")
    undo = sub.add_parser("rollback")
    undo.add_argument("--rollback", type=Path, required=True)
    undo.add_argument("--actor-user-id", type=str, required=True)
    return result


def main() -> int:
    args = parser().parse_args()
    args.actor_user_id = str(UUID(args.actor_user_id))
    try:
        return migrate(args) if args.command == "migrate" else rollback(args)
    except (AccountOperationError, KeyError, ValueError, json.JSONDecodeError, sqlite3.Error, httpx.HTTPError) as exc:
        print(f"Migration failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
