from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

import httpx

from auth_session import get_auth_session_store
from supabase_client import load_auth_config


class SavedPoolStoreError(RuntimeError):
    """Safe, user-facing failure for authenticated saved-pool operations."""


@dataclass(frozen=True)
class SavedPool:
    pool_id: str
    created_at: str | None = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "SavedPool":
        return cls(
            pool_id=str(row["pool_id"]),
            created_at=str(row["created_at"]) if row.get("created_at") else None,
        )


def deterministic_saved_pools(entries: Iterable[SavedPool]) -> tuple[SavedPool, ...]:
    """Most recently saved first, then canonical pool ID for stable ties."""

    by_pool: dict[str, SavedPool] = {}
    for entry in entries:
        pool_id = entry.pool_id.strip()
        if pool_id:
            by_pool[pool_id] = SavedPool(pool_id=pool_id, created_at=entry.created_at)
    ordered = sorted(by_pool.values(), key=lambda entry: entry.pool_id)
    ordered.sort(key=lambda entry: entry.created_at or "", reverse=True)
    return tuple(ordered)


class UserSavedPoolsClient:
    """Authenticated RPC client whose database functions derive ownership from auth.uid()."""

    def __init__(
        self,
        *,
        project_url: str,
        anon_key: str,
        access_token: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = f"{project_url.rstrip('/')}/rest/v1"
        self._anon_key = anon_key
        self._access_token = access_token
        self._transport = transport

    def _rpc(self, name: str, **body: Any) -> Any:
        headers = {
            "apikey": self._anon_key,
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=10.0, transport=self._transport) as client:
                response = client.post(f"{self._base_url}/rpc/{name}", headers=headers, json=body)
        except httpx.HTTPError as exc:
            raise SavedPoolStoreError("Saved pools are temporarily unavailable.") from exc
        if response.status_code < 200 or response.status_code >= 300:
            raise SavedPoolStoreError("The saved-pool operation was rejected.")
        return response.json() if response.content else None

    def list_saved_pools(self) -> tuple[SavedPool, ...]:
        value = self._rpc("list_my_saved_pools")
        if not isinstance(value, list):
            raise SavedPoolStoreError("Saved pools returned an invalid response.")
        return deterministic_saved_pools(SavedPool.from_row(row) for row in value if isinstance(row, Mapping))

    def save_pool(self, pool_id: str) -> SavedPool:
        value = self._rpc("save_my_pool", requested_pool_id=str(pool_id))
        if not isinstance(value, Mapping):
            raise SavedPoolStoreError("The pool was not saved.")
        return SavedPool.from_row(value)

    def remove_pool(self, pool_id: str) -> bool:
        return bool(self._rpc("delete_my_saved_pool", requested_pool_id=str(pool_id)))


def current_user_saved_pools_client() -> UserSavedPoolsClient:
    config = load_auth_config()
    tokens = get_auth_session_store().load()
    if not tokens:
        raise SavedPoolStoreError("Saved pools are unavailable for this authenticated session.")
    return UserSavedPoolsClient(
        project_url=config.project_url,
        anon_key=config.anon_key,
        access_token=tokens.access_token,
    )
