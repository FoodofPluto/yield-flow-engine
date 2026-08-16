from __future__ import annotations

import json

import httpx
import pytest

from saved_pools import SavedPool, SavedPoolStoreError, UserSavedPoolsClient, deterministic_saved_pools


def test_saved_pool_order_is_recent_first_with_canonical_tie_breaker_and_deduplication() -> None:
    entries = deterministic_saved_pools(
        [
            SavedPool("pool-b", "2026-08-16T12:00:00+00:00"),
            SavedPool("pool-z", "2026-08-17T12:00:00+00:00"),
            SavedPool("pool-a", "2026-08-16T12:00:00+00:00"),
            SavedPool("pool-z", "2026-08-17T12:00:00+00:00"),
        ]
    )

    assert [entry.pool_id for entry in entries] == ["pool-z", "pool-a", "pool-b"]


def test_authenticated_client_save_list_duplicate_and_remove_use_only_saved_pool_rpcs() -> None:
    rows: dict[str, dict[str, str]] = {}
    requests_seen: list[tuple[str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        name = request.url.path.rsplit("/", 1)[-1]
        requests_seen.append((name, body))
        assert request.headers["authorization"] == "Bearer access-token"
        assert request.headers["apikey"] == "anon-key"
        if name == "save_my_pool":
            pool_id = body["requested_pool_id"]
            rows.setdefault(pool_id, {"pool_id": pool_id, "created_at": "2026-08-16T12:00:00+00:00"})
            return httpx.Response(200, json=rows[pool_id])
        if name == "list_my_saved_pools":
            return httpx.Response(200, json=list(rows.values()))
        if name == "delete_my_saved_pool":
            return httpx.Response(200, json=rows.pop(body["requested_pool_id"], None) is not None)
        raise AssertionError(f"Unexpected RPC: {name}")

    client = UserSavedPoolsClient(
        project_url="https://project.example",
        anon_key="anon-key",
        access_token="access-token",
        transport=httpx.MockTransport(handler),
    )

    client.save_pool("canonical-pool-x")
    client.save_pool("canonical-pool-x")
    assert [entry.pool_id for entry in client.list_saved_pools()] == ["canonical-pool-x"]
    assert client.remove_pool("canonical-pool-x") is True
    assert client.list_saved_pools() == ()
    assert [name for name, _ in requests_seen] == [
        "save_my_pool",
        "save_my_pool",
        "list_my_saved_pools",
        "delete_my_saved_pool",
        "list_my_saved_pools",
    ]
    assert not any("alert" in name or "telegram" in name or "delivery" in name for name, _ in requests_seen)


def test_authenticated_client_exposes_only_safe_watchlist_errors() -> None:
    client = UserSavedPoolsClient(
        project_url="https://project.example",
        anon_key="anon-key",
        access_token="secret-access-token",
        transport=httpx.MockTransport(lambda _request: httpx.Response(403, json={"message": "private detail"})),
    )

    with pytest.raises(SavedPoolStoreError, match="operation was rejected") as exc_info:
        client.save_pool("canonical-pool-x")

    assert "private detail" not in str(exc_info.value)
    assert "secret-access-token" not in str(exc_info.value)
