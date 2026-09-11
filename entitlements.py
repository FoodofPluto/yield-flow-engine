"""Compatibility imports for Supabase-authoritative entitlement decisions."""

from __future__ import annotations

from account_control import ServiceRoleAccountClient
from auth_service import can_access_pro


def grant_lifetime_access(*, user_id: str, actor_user_id: str, reason: str) -> bool:
    """Grant compatibility-only lifetime access by verified Supabase UUID."""

    return ServiceRoleAccountClient().set_entitlement(
        target_user_id=user_id,
        entitlement="lifetime",
        enabled=True,
        actor_user_id=actor_user_id,
        reason=reason,
    )


__all__ = ["can_access_pro", "grant_lifetime_access"]
