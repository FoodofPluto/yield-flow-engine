"""Run only in trusted operator shell; link is printed exactly once, never stored."""

from __future__ import annotations
import argparse
from pathlib import Path
import secrets
import sys
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from account_control import ServiceRoleAccountClient  # noqa: E402
from beta_invitations import digest  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("create", "revoke"))
    parser.add_argument("--actor-user-id", required=True, type=UUID)
    parser.add_argument("--invitation-id", type=UUID)
    args = parser.parse_args()
    try:
        client = ServiceRoleAccountClient()
        if args.command == "create":
            token = secrets.token_urlsafe(32)
            identifier = client._request(
                "POST",
                "rpc/service_create_beta_invitation",
                bearer=client._key,
                json_body={"actor_user_id": str(args.actor_user_id), "invitation_digest": digest(token)},
            )
            UUID(str(identifier))
            print("Invitation ID:", identifier, "(expires in 24 hours)")
            print("https://beta.furuflow.com/create-account?invite=" + token)
        else:
            if not args.invitation_id:
                parser.error("revoke requires --invitation-id")
            revoked = client._request(
                "POST",
                "rpc/service_revoke_beta_invitation",
                bearer=client._key,
                json_body={"actor_user_id": str(args.actor_user_id), "invitation_id": str(args.invitation_id)},
            )
            print("Revoked." if revoked else "No active invitation changed.")
        return 0
    except Exception:
        print("Invitation operation unavailable. No sensitive diagnostics retained.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
