from __future__ import annotations

from datetime import datetime, timezone

import requests
import streamlit as st
from streamlit.testing.v1 import AppTest

from saved_pools import SavedPool


class FakeSavedPoolsClient:
    def __init__(self, pool_ids: tuple[str, ...] = ()) -> None:
        self.rows: dict[str, SavedPool] = {
            pool_id: SavedPool(pool_id, f"2026-08-16T12:00:{index:02d}+00:00")
            for index, pool_id in enumerate(pool_ids)
        }
        self.save_calls: list[str] = []
        self.remove_calls: list[str] = []

    def list_saved_pools(self) -> tuple[SavedPool, ...]:
        return tuple(sorted(self.rows.values(), key=lambda entry: (entry.created_at or "", entry.pool_id), reverse=True))

    def save_pool(self, pool_id: str) -> SavedPool:
        self.save_calls.append(pool_id)
        self.rows.setdefault(pool_id, SavedPool(pool_id, datetime.now(timezone.utc).isoformat()))
        return self.rows[pool_id]

    def remove_pool(self, pool_id: str) -> bool:
        self.remove_calls.append(pool_id)
        return self.rows.pop(pool_id, None) is not None


class FakeMarketResponse:
    def __init__(self, pool_id: str = "canonical-pool-1") -> None:
        self.pool_id = pool_id

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "data": [
                {
                    "pool": self.pool_id,
                    "chain": "Ethereum",
                    "project": "aave-v3",
                    "symbol": "USDC",
                    "apy": 5.0,
                    "apyBase": 5.0,
                    "apyReward": 0.0,
                    "tvlUsd": 10_000_000,
                    "stablecoin": True,
                }
            ]
        }


def _authenticated_app(
    monkeypatch,
    client: FakeSavedPoolsClient,
    *,
    page: str,
    market_pool_id: str = "canonical-pool-1",
    is_pro: bool = False,
) -> AppTest:
    import auth_service
    import saved_pools

    user = {
        "id": "user-a",
        "email": "member@example.invalid",
        "_identity_verified": True,
        "is_admin": False,
        "pro_active": False,
        "lifetime_access": False,
        "demo_active": False,
        "timezone": "UTC",
    }
    monkeypatch.setattr(auth_service, "get_current_user", lambda: user)
    monkeypatch.setattr(auth_service, "claim_session", lambda: None)
    monkeypatch.setattr(auth_service, "validate_session", lambda: True)
    monkeypatch.setattr(auth_service, "can_access_pro", lambda _user: is_pro)
    monkeypatch.setattr(saved_pools, "current_user_saved_pools_client", lambda: client)
    monkeypatch.setattr(requests, "get", lambda *_args, **_kwargs: FakeMarketResponse(market_pool_id))
    monkeypatch.delenv("FURUFLOW_MARKET_SAMPLE_MODE", raising=False)
    st.cache_data.clear()
    app = AppTest.from_file("app.py", default_timeout=60)
    app.query_params["page"] = page
    return app.run()


def _button(app: AppTest, label: str):
    return next(button for button in app.button if button.label == label)


def test_discover_save_is_durable_idempotent_and_restored_in_a_later_session(monkeypatch) -> None:
    client = FakeSavedPoolsClient()
    app = _authenticated_app(monkeypatch, client, page="Discover")

    _button(app, "Watch").click().run()
    assert client.save_calls == ["canonical-pool-1"]
    assert tuple(client.rows) == ("canonical-pool-1",)
    assert any(button.label == "Remove" for button in app.button)

    app.run()
    assert client.save_calls == ["canonical-pool-1"]
    assert len(client.rows) == 1

    # A new AppTest models a later authenticated browser session against the
    # same durable backend, including a logout/login cycle.
    later = _authenticated_app(monkeypatch, client, page="Watchlists")
    assert not later.exception
    assert any(button.label == "Remove" for button in later.button)
    assert any(button.label == "View details" for button in later.button)


def test_watchlist_opens_existing_pool_detail_and_back_returns_to_watchlist(monkeypatch) -> None:
    client = FakeSavedPoolsClient(("canonical-pool-1",))
    app = _authenticated_app(monkeypatch, client, page="Watchlists")

    _button(app, "View details").click().run()
    assert app.query_params["page"] == ["Pool Detail"]
    assert app.query_params["pool"] == ["canonical-pool-1"]
    assert any(button.label == "← Back to Watchlist" for button in app.button)

    _button(app, "← Back to Watchlist").click().run()
    assert app.query_params["page"] == ["Watchlists"]
    assert "canonical-pool-1" in client.rows


def test_pool_detail_save_and_remove_do_not_invoke_alert_or_delivery_clients(monkeypatch) -> None:
    client = FakeSavedPoolsClient()
    app = _authenticated_app(monkeypatch, client, page="Pool Detail")
    app.query_params["pool"] = "canonical-pool-1"
    app.run()

    _button(app, "Add to Watchlist").click().run()
    assert tuple(client.rows) == ("canonical-pool-1",)
    _button(app, "Remove from Watchlist").click().run()
    assert not client.rows
    assert client.save_calls == ["canonical-pool-1"]
    assert client.remove_calls == ["canonical-pool-1"]


def test_missing_provider_pool_stays_saved_shows_degraded_state_and_can_be_removed(monkeypatch) -> None:
    client = FakeSavedPoolsClient(("saved-pool-now-missing",))
    app = _authenticated_app(monkeypatch, client, page="Watchlists", market_pool_id="different-current-pool")

    assert "saved-pool-now-missing" in client.rows
    assert any("current data unavailable" in markdown.value.lower() for markdown in app.markdown)

    _button(app, "Remove from Watchlist").click().run()
    assert "saved-pool-now-missing" not in client.rows
    assert any("Your watchlist is empty" in markdown.value for markdown in app.markdown)


def test_strategy_results_actions_use_canonical_watchlist_and_pool_detail_primitives(monkeypatch) -> None:
    client = FakeSavedPoolsClient()
    app = _authenticated_app(monkeypatch, client, page="Pro Tools", is_pro=True)
    next(slider for slider in app.slider if slider.label == "Strategy minimum APY").set_value(0.0).run()
    next(slider for slider in app.slider if slider.label == "Strategy minimum TVL").set_value(0).run()
    next(slider for slider in app.slider if slider.label == "Strategy maximum risk").set_value(100).run()
    strategy_tables = [element.value for element in app.dataframe if "Risk" in element.value.columns]
    assert strategy_tables
    assert strategy_tables[-1].columns[0] == "Pool"

    _button(app, "Save to Watchlist").click().run()
    assert client.save_calls == ["canonical-pool-1"]
    assert tuple(client.rows) == ("canonical-pool-1",)

    _button(app, "Open Pool Detail").click().run()
    assert app.query_params["page"] == ["Pool Detail"]
    assert app.query_params["pool"] == ["canonical-pool-1"]
    assert any(button.label == "← Back to Strategy Results" for button in app.button)

    _button(app, "← Back to Strategy Results").click().run()
    assert app.query_params["page"] == ["Pro Tools"]
    assert client.rows["canonical-pool-1"].pool_id == "canonical-pool-1"


def test_signal_engine_renders_pool_link_as_first_visible_table_column(monkeypatch) -> None:
    app = _authenticated_app(monkeypatch, FakeSavedPoolsClient(), page="Discover", is_pro=True)
    next(radio for radio in app.radio if radio.label == "Discover view").set_value("Signals").run()

    signal_tables = [element.value for element in app.dataframe if "Strength" in element.value.columns]
    assert signal_tables
    assert signal_tables[-1].columns[0] == "Pool"
