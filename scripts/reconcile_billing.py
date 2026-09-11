from __future__ import annotations

import argparse
from uuid import UUID

from account_control import AccountOperationError, ServiceRoleAccountClient


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reconcile subscription-derived Pro with the stored authoritative Stripe subscription state."
    )
    parser.add_argument("--user-id", required=True, help="Verified Supabase Auth user UUID")
    args = parser.parse_args()
    try:
        user_id = str(UUID(args.user_id))
        changed = ServiceRoleAccountClient().reconcile_subscription_entitlement(user_id)
    except (AccountOperationError, ValueError) as exc:
        print(f"Billing reconciliation failed: {exc}")
        return 1
    print("Subscription entitlement repaired." if changed else "Subscription entitlement already matched stored state.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

