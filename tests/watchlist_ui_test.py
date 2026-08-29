from __future__ import annotations

from datetime import datetime, timezone
import html
from pathlib import Path
import re
from urllib.parse import parse_qs, urlparse

import requests
import streamlit as st
from streamlit.testing.v1 import AppTest

from saved_pools import SavedPool


def _internal_tables(app: AppTest, heading: str) -> list[str]:
    marker = f"<th>{heading}</th>"
    return [element.value for element in app.markdown if "ff-pool-table" in element.value and marker in element.value]


def _first_internal_url(table_html: str, pool_id: str | None = None) -> str:
    pattern = rf'href="([^"]*{re.escape(pool_id)}[^"]*)"' if pool_id else r'href="([^"]+)"'
    match = re.search(pattern, table_html)
    assert match
    return html.unescape(match.group(1))


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
    def __init__(
        self,
        pool_id: str = "canonical-pool-1",
        rows: list[dict[str, object]] | None = None,
        *,
        chart: bool = False,
    ) -> None:
        self.pool_id = pool_id
        self.rows = rows
        self.chart = chart

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        if self.chart:
            return {
                "data": [
                    {"timestamp": 1_787_788_800, "apy": 4.0, "tvlUsd": 9_000_000},
                    {"timestamp": 1_787_875_200, "apy": 5.0, "tvlUsd": 10_000_000},
                ]
            }
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
    is_pro: bool = True,
    query_params: dict[str, str] | None = None,
    signal_history: bool = False,
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
    monkeypatch.setattr(
        requests,
        "get",
        lambda url, *_args, **_kwargs: FakeMarketResponse(
            market_pool_id,
            market_rows,
            chart=signal_history and ("/chart/" in str(url) or "/chartLendBorrow/" in str(url)),
        ),
    )
    monkeypatch.delenv("FURUFLOW_MARKET_SAMPLE_MODE", raising=False)
    st.cache_data.clear()
    app = AppTest.from_file("app.py", default_timeout=60)
    app.query_params["page"] = page
    for key, value in (query_params or {}).items():
        app.query_params[key] = value
    return app.run()


def _button(app: AppTest, label: str):
    return next(button for button in app.button if button.label == label)


def test_current_free_capabilities_keep_discovery_useful_without_invalid_actions(monkeypatch) -> None:
    app = _authenticated_app(monkeypatch, FakeSavedPoolsClient(), page="Discover", is_pro=False)

    labels = [button.label for button in app.button]
    assert "Watchlist" not in labels
    assert "Alerts" not in labels
    assert "Pro tools" not in labels
    assert _button(app, "View details").disabled is False
    assert _button(app, "Watchlists · Core").disabled is True
    assert _button(app, "Alerts · Plus").disabled is True
    assert _button(app, "Research · Plus").disabled is True


def test_home_routes_primary_actions_and_opens_canonical_pool_first(monkeypatch) -> None:
    app = _authenticated_app(monkeypatch, FakeSavedPoolsClient(), page="Home", is_pro=True)
    home_tables = _internal_tables(app, "Network")

    assert home_tables
    assert home_tables[-1].index("<th>Pool</th>") < home_tables[-1].index("<th>Asset</th>")
    assert ">aave-v3 · USDC</a>" in home_tables[-1]
    parsed = urlparse(_first_internal_url(home_tables[-1]))
    assert parse_qs(parsed.query)["return_route"] == ["Home"]
    assert 'target="_self"' in home_tables[-1]
    _button(app, "Browse All Pools").click().run()
    assert app.query_params["page"] == ["Discover"]
    assert next(radio for radio in app.radio if radio.label == "Discover view").value == "All Pools"

    signals_app = _authenticated_app(monkeypatch, FakeSavedPoolsClient(), page="Home", is_pro=False)
    _button(signals_app, "View Signals").click().run()
    assert signals_app.query_params["page"] == ["Signals"]


def test_expired_pool_detail_session_recovers_without_hiding_public_data(monkeypatch) -> None:
    import auth_service

    app = _authenticated_app(monkeypatch, FakeSavedPoolsClient(), page="Pool Detail", is_pro=True)
    app.query_params["page"] = "Pool Detail"
    app.query_params["pool"] = "canonical-pool-1"
    app.run()
    assert any({"Metric", "Value"} <= set(table.value.columns) for table in app.dataframe)

    monkeypatch.setattr(auth_service, "validate_session", lambda: False)
    app.run()

    assert not app.exception
    assert any("Session expired" in markdown.value for markdown in app.markdown)
    assert _button(app, "Sign In Again").disabled is False
    assert _button(app, "Continue to Home").disabled is False
    assert any({"Metric", "Value"} <= set(table.value.columns) for table in app.dataframe)
    assert _button(app, "Sign in to save").disabled is True
    assert _button(app, "Sign in for alerts").disabled is True
    assert set(app.query_params) == {"page", "pool"}

    _button(app, "Continue to Home").click().run()
    assert app.query_params["page"] == ["Home"]
    assert "pool" not in app.query_params


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
    assert not {"pool", "return_route", "return_view"} & set(app.query_params)
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


def test_watchlist_empty_state_routes_to_broader_discovery(monkeypatch) -> None:
    app = _authenticated_app(monkeypatch, FakeSavedPoolsClient(), page="Watchlists")

    _button(app, "Explore pools to save").click().run()
    assert app.query_params["page"] == ["Discover"]
    assert next(radio for radio in app.radio if radio.label == "Discover view").value == "All Pools"


def test_strategy_results_actions_use_canonical_watchlist_and_pool_detail_primitives(monkeypatch) -> None:
    client = FakeSavedPoolsClient()
    app = _authenticated_app(monkeypatch, client, page="Pro Tools", is_pro=True)
    next(slider for slider in app.slider if slider.label == "Strategy minimum APY").set_value(0.0).run()
    next(slider for slider in app.slider if slider.label == "Strategy minimum TVL").set_value(0).run()
    next(slider for slider in app.slider if slider.label == "Strategy maximum risk").set_value(100).run()
    strategy_tables = _internal_tables(app, "Risk")
    assert strategy_tables
    assert strategy_tables[-1].index("<th>Pool</th>") < strategy_tables[-1].index("<th>Protocol</th>")

    _button(app, "Save to Watchlist").click().run()
    assert client.save_calls == ["canonical-pool-1"]
    assert tuple(client.rows) == ("canonical-pool-1",)
    assert any(button.label == "Compare / Research" for button in app.button)

    _button(app, "Open Pool").click().run()
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


def test_yield_spread_pair_carries_both_canonical_pools_into_research(monkeypatch) -> None:
    rows = [
        {
            "pool": "higher-pool",
            "chain": "Ethereum",
            "project": "aave-v3",
            "symbol": "USDC",
            "apy": 10.0,
            "apyBase": 10.0,
            "apyReward": 0.0,
            "tvlUsd": 20_000_000,
            "stablecoin": True,
        },
        {
            "pool": "lower-pool",
            "chain": "Base",
            "project": "morpho",
            "symbol": "USDC",
            "apy": 4.0,
            "apyBase": 4.0,
            "apyReward": 0.0,
            "tvlUsd": 40_000_000,
            "stablecoin": True,
        },
    ]
    app = _authenticated_app(
        monkeypatch,
        FakeSavedPoolsClient(),
        page="Pro Tools",
        is_pro=True,
        market_rows=rows,
    )
    next(radio for radio in app.radio if radio.label == "Pro tools view").set_value("Yield Spreads").run()

    assert any(selectbox.label == "Yield spread pair" for selectbox in app.selectbox)
    assert any(button.label == "Create Alert" for button in app.button)
    _button(app, "Compare pair in Research").click().run()
    assert app.query_params["page"] == ["Research"]
    selection = next(multiselect for multiselect in app.multiselect if multiselect.label == "Selected pools")
    assert set(selection.value) == {"higher-pool", "lower-pool"}


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
    opportunity_tables = _internal_tables(app, "Strategy")

    assert opportunity_tables
    opportunities = opportunity_tables[-1]
    assert opportunities.index("<th>Pool</th>") < opportunities.index("<th>Asset</th>")
    assert ">aave-v3 · USDC</a>" in opportunities
    parsed = urlparse(_first_internal_url(opportunities))
    assert f"{parsed.scheme}://{parsed.netloc}" == "http://localhost:8501"
    assert parse_qs(parsed.query) == {
        "page": ["Pool Detail"],
        "pool": ["canonical-pool-1"],
        "return_route": ["Discover"],
        "return_view": ["Opportunities"],
    }


def test_discover_advanced_filters_and_sort_reconstruct_in_a_fresh_browser_session(monkeypatch) -> None:
    client = FakeSavedPoolsClient()
    app = _authenticated_app(monkeypatch, client, page="Discover", is_pro=True)

    next(multiselect for multiselect in app.multiselect if multiselect.label == "Chains").set_value(["Ethereum"]).run()
    next(multiselect for multiselect in app.multiselect if multiselect.label == "Protocols").set_value(["aave-v3"]).run()
    strategy_value = next(item for item in app.multiselect if item.label == "Strategy type").options[0]
    signal_value = next(item for item in app.multiselect if item.label == "Signal").options[0]
    next(multiselect for multiselect in app.multiselect if multiselect.label == "Strategy type").set_value([strategy_value]).run()
    next(multiselect for multiselect in app.multiselect if multiselect.label == "Signal").set_value([signal_value]).run()
    next(slider for slider in app.slider if slider.label == "Minimum TVL").set_value(0).run()
    next(slider for slider in app.slider if slider.label == "Maximum risk score").set_value(90).run()
    next(slider for slider in app.slider if slider.label == "Minimum APY").set_value(2.0).run()
    next(selectbox for selectbox in app.selectbox if selectbox.label == "Sort by").set_value("Largest TVL").run()

    persisted = {
        key: str(app.query_params[key][0])
        for key in ("chains", "protocols", "strategies", "signals", "min_tvl", "max_risk", "min_apy", "sort")
        if key in app.query_params
    }
    refreshed = _authenticated_app(
        monkeypatch,
        client,
        page="Discover",
        is_pro=True,
        query_params=persisted,
    )

    assert next(item for item in refreshed.multiselect if item.label == "Chains").value == ["Ethereum"]
    assert next(item for item in refreshed.multiselect if item.label == "Protocols").value == ["aave-v3"]
    assert next(item for item in refreshed.multiselect if item.label == "Strategy type").value == [strategy_value]
    assert next(item for item in refreshed.multiselect if item.label == "Signal").value == [signal_value]
    assert next(item for item in refreshed.slider if item.label == "Minimum TVL").value == 0
    assert next(item for item in refreshed.slider if item.label == "Maximum risk score").value == 90
    assert next(item for item in refreshed.slider if item.label == "Minimum APY").value == 2.0
    assert next(item for item in refreshed.selectbox if item.label == "Sort by").value == "Largest TVL"

    _button(refreshed, "Home").click().run()
    assert refreshed.query_params["page"] == ["Home"]
    assert not {"chains", "protocols", "strategies", "signals", "min_tvl", "max_risk", "min_apy", "sort"} & set(
        refreshed.query_params
    )


def test_signal_engine_renders_pool_link_as_first_visible_table_column(monkeypatch) -> None:
    app = _authenticated_app(
        monkeypatch,
        FakeSavedPoolsClient(),
        page="Signals",
        is_pro=True,
        signal_history=True,
    )

    signal_tables = _internal_tables(app, "Strength")
    assert signal_tables
    assert signal_tables[-1].index("<th>Pool</th>") < signal_tables[-1].index("<th>Protocol</th>")
    parsed = urlparse(_first_internal_url(signal_tables[-1]))
    assert parse_qs(parsed.query)["return_route"] == ["Signals"]
    assert any(button.label == "Research" for button in app.button)
    rendered = "\n".join(markdown.value for markdown in app.markdown)
    assert "evidence to investigate, not a recommendation" in rendered
    assert "Observed signal evidence" in rendered
    assert "Pools evaluated" in rendered
    assert "Non-steady classifications" in rendered


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

    curated_tables = _internal_tables(app, "Strategy")
    assert "aave-v3" in curated_tables[-1]
    assert "zeta-protocol" not in curated_tables[-1]

    next(radio for radio in app.radio if radio.label == "Discover view").set_value("All Pools").run()
    assert not app.exception
    assert any(expander.label == "Discover Filters" for expander in app.expander)
    assert any(expander.label == "Advanced filters & sorting" for expander in app.expander)
    universe_tables = _internal_tables(app, "Strategy")
    assert universe_tables[-1].index("aave-v3") < universe_tables[-1].index("zeta-protocol")
    parsed = urlparse(_first_internal_url(universe_tables[-1], "broader-pool"))
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
    _button(app, "Yield Seeking").click().run()
    weights = {slider.label: slider.value for slider in app.slider if "weight" in slider.label.lower()}
    assert weights == {
        "Yield weight": 55,
        "Liquidity weight": 20,
        "Risk weight": 15,
        "Signal / momentum weight": 10,
    }
    assert any("Observed current metrics" in markdown.value for markdown in app.markdown)
    assert any("Calculated context" in markdown.value for markdown in app.markdown)
    assert any("Insufficient evidence" in markdown.value for markdown in app.markdown)
    research_tables = _internal_tables(app, "Strategy")
    parsed = urlparse(_first_internal_url(research_tables[-1]))
    assert parse_qs(parsed.query)["return_route"] == ["Research"]
    assert any(button.label == "Create alert" for button in app.button)
    next(button for button in app.button if button.key == "compare_remove_pool-a").click().run()
    selected = next(multiselect for multiselect in app.multiselect if multiselect.label == "Selected pools")
    assert selected.value == ["pool-b"]


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


def test_pool_detail_labels_protocol_destination_as_external(monkeypatch) -> None:
    app = _authenticated_app(monkeypatch, FakeSavedPoolsClient(), page="Pool Detail")
    app.query_params["pool"] = "canonical-pool-1"
    app.run()

    assert 'st.link_button("Open on protocol ↗"' in Path("app.py").read_text(encoding="utf-8")
    assert any("External destination" in caption.value for caption in app.caption)
    stats = next(table.value for table in app.dataframe if {"Metric", "Value"} <= set(table.value.columns))
    values = dict(zip(stats["Metric"], stats["Value"], strict=True))
    assert values["Classification"] == "Insufficient evidence"
    assert values["7d APY change"] == "Insufficient evidence"
    assert values["7d TVL change"] == "Insufficient evidence"


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
