from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

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
    def __init__(self, pool_id: str = "canonical-pool-1", rows: list[dict[str, object]] | None = None) -> None:
        self.pool_id = pool_id
        self.rows = rows

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "data": self.rows or [
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
    market_rows: list[dict[str, object]] | None = None,
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
    monkeypatch.setattr(requests, "get", lambda *_args, **_kwargs: FakeMarketResponse(market_pool_id, market_rows))
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
    assert any(button.label == "Create alert" for button in later.button)
    assert any(button.label == "Research" for button in later.button)


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
    assert any(button.label == "Research" for button in app.button)

    _button(app, "Open Pool Detail").click().run()
    assert app.query_params["page"] == ["Pool Detail"]
    assert app.query_params["pool"] == ["canonical-pool-1"]
    assert any(button.label == "← Back to Strategy Results" for button in app.button)

    _button(app, "← Back to Strategy Results").click().run()
    assert app.query_params["page"] == ["Pro Tools"]
    assert client.rows["canonical-pool-1"].pool_id == "canonical-pool-1"

def test_pro_tools_renders_only_pro_workflows_and_preserves_both_tools(monkeypatch) -> None:
    app = _authenticated_app(monkeypatch, FakeSavedPoolsClient(), page="Pro Tools", is_pro=True)

    assert not any(expander.label in {"Discover Filters", "Advanced filters & sorting"} for expander in app.expander)
    assert any(slider.label == "Strategy minimum APY" for slider in app.slider)
    assert any("Strategy builder" in markdown.value for markdown in app.markdown)

    next(radio for radio in app.radio if radio.label == "Pro tools view").set_value("Yield Spreads").run()

    assert not app.exception
    assert any("Yield spreads" in markdown.value for markdown in app.markdown)
    assert not any("Discovery guidance" in markdown.value for markdown in app.markdown)


def test_strategy_result_carries_canonical_pool_into_research(monkeypatch) -> None:
    app = _authenticated_app(monkeypatch, FakeSavedPoolsClient(), page="Pro Tools", is_pro=True)
    next(slider for slider in app.slider if slider.label == "Strategy minimum APY").set_value(0.0).run()
    next(slider for slider in app.slider if slider.label == "Strategy minimum TVL").set_value(0).run()
    next(slider for slider in app.slider if slider.label == "Strategy maximum risk").set_value(100).run()

    next(button for button in app.button if button.key == "strategy_result_research").click().run()
    assert app.query_params["page"] == ["Research"]
    selection = next(multiselect for multiselect in app.multiselect if multiselect.label == "Selected pools")
    assert selection.value == ["canonical-pool-1"]


def test_opportunities_table_puts_canonical_contextual_pool_link_first(monkeypatch) -> None:
    app = _authenticated_app(monkeypatch, FakeSavedPoolsClient(), page="Discover", is_pro=True)
    opportunity_tables = [element.value for element in app.dataframe if "Strategy" in element.value.columns]

    assert opportunity_tables
    opportunities = opportunity_tables[-1]
    assert opportunities.columns[0] == "Pool"
    parsed = urlparse(opportunities.iloc[0, 0])
    assert f"{parsed.scheme}://{parsed.netloc}" == "http://localhost:8501"
    assert parse_qs(parsed.query) == {
        "page": ["Pool Detail"],
        "pool": ["canonical-pool-1"],
        "return_route": ["Discover"],
        "return_view": ["Opportunities"],
    }


def test_signal_engine_renders_pool_link_as_first_visible_table_column(monkeypatch) -> None:
    app = _authenticated_app(monkeypatch, FakeSavedPoolsClient(), page="Signals", is_pro=True)

    signal_tables = [element.value for element in app.dataframe if "Strength" in element.value.columns]
    assert signal_tables
    assert signal_tables[-1].columns[0] == "Pool"
    parsed = urlparse(signal_tables[-1].iloc[0]["Pool"])
    assert parse_qs(parsed.query)["return_route"] == ["Signals"]
    assert any(button.label == "Research" for button in app.button)
    rendered = "\n".join(markdown.value for markdown in app.markdown)
    assert "evidence to investigate, not a recommendation" in rendered


def test_discover_all_pools_reaches_non_curated_pool_with_canonical_actions(monkeypatch) -> None:
    rows = [
        {
            "pool": "curated-pool",
            "chain": "Ethereum",
            "project": "aave-v3",
            "symbol": "USDC",
            "apy": 5.0,
            "apyBase": 5.0,
            "apyReward": 0.0,
            "tvlUsd": 10_000_000,
            "stablecoin": True,
        },
        {
            "pool": "broader-pool",
            "chain": "Base",
            "project": "zeta-protocol",
            "symbol": "ETH",
            "apy": 2.0,
            "apyBase": 2.0,
            "apyReward": 0.0,
            "tvlUsd": 100_000,
            "stablecoin": False,
        },
    ]
    client = FakeSavedPoolsClient()
    app = _authenticated_app(
        monkeypatch,
        client,
        page="Discover",
        is_pro=True,
        market_rows=rows,
    )

    curated_tables = [element.value for element in app.dataframe if "Strategy" in element.value.columns]
    assert curated_tables[-1]["Protocol"].tolist() == ["aave-v3"]

    next(radio for radio in app.radio if radio.label == "Discover view").set_value("All Pools").run()
    assert not app.exception
    assert not any(expander.label == "Discover Filters" for expander in app.expander)
    universe_tables = [element.value for element in app.dataframe if "Strategy" in element.value.columns]
    assert universe_tables[-1]["Protocol"].tolist() == ["aave-v3", "zeta-protocol"]
    broader_url = universe_tables[-1].loc[universe_tables[-1]["Protocol"] == "zeta-protocol", "Pool"].iloc[0]
    parsed = urlparse(broader_url)
    assert parse_qs(parsed.query) == {
        "page": ["Pool Detail"],
        "pool": ["broader-pool"],
        "return_route": ["Discover"],
        "return_view": ["All Pools"],
    }
    action_pool = next(selectbox for selectbox in app.selectbox if selectbox.label == "Pool actions")
    action_pool.set_value("broader-pool").run()
    assert any(button.label == "Watch" for button in app.button)
    assert any(button.label == "Create alert" for button in app.button)
    _button(app, "Watch").click().run()
    assert client.save_calls == ["broader-pool"]
    assert "broader-pool" in client.rows
    _button(app, "View details").click().run()
    assert app.query_params["pool"] == ["broader-pool"]
    assert any(button.label == "← Back to All Pools" for button in app.button)


def test_research_is_selected_pool_analysis_not_discover_repeated(monkeypatch) -> None:
    rows = [
        {
            "pool": "pool-a",
            "chain": "Ethereum",
            "project": "aave-v3",
            "symbol": "USDC",
            "apy": 5.0,
            "apyBase": 4.0,
            "apyReward": 1.0,
            "tvlUsd": 10_000_000,
            "stablecoin": True,
        },
        {
            "pool": "pool-b",
            "chain": "Base",
            "project": "morpho",
            "symbol": "USDC",
            "apy": 7.0,
            "apyBase": 7.0,
            "apyReward": 0.0,
            "tvlUsd": 20_000_000,
            "stablecoin": True,
        },
    ]
    app = _authenticated_app(
        monkeypatch,
        FakeSavedPoolsClient(("pool-a",)),
        page="Research",
        is_pro=True,
        market_rows=rows,
    )

    assert not any(expander.label in {"Discover Filters", "Advanced filters & sorting"} for expander in app.expander)
    assert not any(radio.label == "Research view" for radio in app.radio)
    selected = next(multiselect for multiselect in app.multiselect if multiselect.label == "Selected pools")
    selected.set_value(["pool-a", "pool-b"]).run()
    assert not app.exception
    assert any("Observed current metrics" in markdown.value for markdown in app.markdown)
    assert any("Calculated context" in markdown.value for markdown in app.markdown)
    research_tables = [element.value for element in app.dataframe if "Strategy" in element.value.columns]
    parsed = urlparse(research_tables[-1].iloc[0]["Pool"])
    assert parse_qs(parsed.query)["return_route"] == ["Research"]
    assert any(button.label == "Create alert" for button in app.button)


def test_pool_detail_carries_pool_into_research_without_pool_url_state(monkeypatch) -> None:
    app = _authenticated_app(monkeypatch, FakeSavedPoolsClient(), page="Pool Detail")
    app.query_params["pool"] = "canonical-pool-1"
    app.run()

    next(button for button in app.button if str(button.key).startswith("pool_research_")).click().run()
    assert not app.exception
    assert app.query_params["page"] == ["Research"]
    assert "pool" not in app.query_params
    selection = next(multiselect for multiselect in app.multiselect if multiselect.label == "Selected pools")
    assert selection.value == ["canonical-pool-1"]


def test_methodology_documents_actual_product_model_and_limitations(monkeypatch) -> None:
    app = _authenticated_app(monkeypatch, FakeSavedPoolsClient(), page="Methodology & Data Status")
    rendered = "\n".join(markdown.value for markdown in app.markdown)

    for concept in (
        "Data sources and freshness",
        "Pool identity",
        "Metrics",
        "Discovery methodology",
        "Signals methodology",
        "Risk interpretation",
        "Watchlists and alerts",
        "Pro Tools",
        "Limitations",
    ):
        assert concept in rendered
    assert "DeFiLlama Yields" in rendered
    assert "descriptive, not predictive" in rendered
