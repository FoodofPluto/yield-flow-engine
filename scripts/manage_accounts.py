from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from uuid import UUID

from account_control import AccountOperationError, ServiceRoleAccountClient


def _uuid(value: str) -> str:
    return str(UUID(value))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Service-role-only FuruFlow account administration.")
    sub = parser.add_subparsers(dest="command", required=True)
    bootstrap = sub.add_parser("bootstrap-admin")
    bootstrap.add_argument("--user-id", required=True, type=_uuid)
    bootstrap.add_argument("--reason", default="first_admin_bootstrap")
    change = sub.add_parser("set")
    change.add_argument("--user-id", required=True, type=_uuid)
    change.add_argument("--actor-user-id", required=True, type=_uuid)
    change.add_argument("--entitlement", required=True, choices=("admin", "pro", "lifetime", "demo"))
    change.add_argument("--enabled", required=True, choices=("true", "false"))
    change.add_argument("--reason", required=True)
    change.add_argument("--environment", choices=("development", "staging", "test"))
    change.add_argument("--demo-minutes", type=int, default=60)
    sub.add_parser("cleanup-demos")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        client = ServiceRoleAccountClient()
        if args.command == "bootstrap-admin":
            changed = client.bootstrap_first_admin(args.user_id, args.reason)
            print("First-admin bootstrap applied." if changed else "First-admin bootstrap already applied; no change.")
        elif args.command == "cleanup-demos":
            print(f"Expired demo entitlements cleaned: {client.cleanup_expired_demos()}")
        else:
            enabled = args.enabled == "true"
            if args.entitlement == "admin" and not enabled and args.user_id == args.actor_user_id:
                raise AccountOperationError("Use a different verified admin to remove this admin role.")
            expiry = None
            if args.entitlement == "demo" and enabled:
                if not args.environment or not 5 <= args.demo_minutes <= 1440:
                    raise AccountOperationError("Enabled demos require an environment and 5-1440 minutes.")
                expiry = (datetime.now(timezone.utc) + timedelta(minutes=args.demo_minutes)).isoformat()
            changed = client.set_entitlement(
                target_user_id=args.user_id,
                entitlement=args.entitlement,
                enabled=enabled,
                actor_user_id=args.actor_user_id,
                reason=args.reason,
                demo_expiry=expiry,
                environment=args.environment,
            )
            print("Entitlement changed and audited." if changed else "Entitlement already matched; no change.")
        return 0
    except (AccountOperationError, ValueError) as exc:
        print(f"Account operation failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
