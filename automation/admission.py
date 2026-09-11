"""Synchronize the existing server beta authority before accepting traffic."""

from __future__ import annotations

from typing import Mapping

import httpx

from automation.store import SupabaseAutomationStore
from beta_readiness import beta_config


def synchronize_beta_admission(
    source: Mapping[str, str], *, transport: httpx.BaseTransport | None = None
) -> None:
    config = beta_config(source)
    if config.errors or not str(source.get("FURUFLOW_BETA_ENABLED") or "").strip():
        raise RuntimeError("Invalid closed-beta configuration; admission was not synchronized.")
    store = SupabaseAutomationStore(
        project_url=source.get("SUPABASE_URL"),
        service_role_key=source.get("SUPABASE_SERVICE_ROLE_KEY"),
        transport=transport,
    )
    result = store._rpc(
        "service_sync_beta_admission",
        beta_enabled=config.enabled,
        approved_user_ids=sorted(config.allowed_user_ids),
    )
    if result is not True:
        raise RuntimeError("Beta admission synchronization was not acknowledged.")
