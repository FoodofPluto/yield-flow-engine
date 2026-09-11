from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest
import streamlit as st

from automation.store import AutomationStoreError
from saved_pools import SavedPool
from ui_shell import alert_creation_state


@pytest.fixture(autouse=True)
def _clear_streamlit_cache_after_test():
    yield
    st.cache_data.clear()


class FakeNotificationClient:
    def __init__(
        self,
        *,
        alerts: list[dict[str, object]] | None = None,
        linked: bool = True,
        status_error: bool = False,
    ) -> None:
        self.alerts = alerts or []
        self.linked = linked
        self.status_error = status_error
        self.toggles: list[tuple[str, bool]] = []
        self.created: list[dict[str, object]] = []
        self.updated: list[dict[str, object]] = []
        self.deleted: list[str] = []

    def telegram_status(self) -> dict[str, object]:
        if self.status_error:
            raise AutomationStoreError("status unavailable")
        return {"available": self.linked, "status": "linked" if self.linked else "not_linked"}

    def list_alerts(self) -> list[dict[str, object]]:
        return self.alerts

    def set_alert_enabled(self, alert_id: str, enabled: bool) -> bool:
        self.toggles.append((alert_id, enabled))
        for alert in self.alerts:
            if alert["id"] == alert_id:
                alert["enabled"] = enabled
        return True

    def create_pool_alert(self, **values: object) -> dict[str, object]:
        self.created.append(values)
        alert = {
            "id": f"alert-{len(self.alerts) + 1}",
            "enabled": True,
            "condition_type": "signal_qualified",
            "timezone": values["timezone_name"],
            **values,
        }
        alert.pop("timezone_name")
        alert.pop("client_request_key")
        self.alerts.append(alert)
        return alert

    def update_pool_alert(self, **values: object) -> dict[str, object]:
        self.updated.append(values)
        alert = next(item for item in self.alerts if item["id"] == values["alert_id"])
        for key, value in values.items():
            if key != "alert_id":
                alert["timezone" if key == "timezone_name" else key] = value
        return alert

    def delete_alert(self, alert_id: str) -> bool:
        self.deleted.append(alert_id)
        self.alerts[:] = [item for item in self.alerts if item["id"] != alert_id]
        return True

    def request_test_delivery(self, alert_id: str) -> str:
        return f"test-{alert_id}"


class FakeSavedPoolsClient:
    def __init__(self, pool_ids: tuple[str, ...] = ()) -> None:
        self.pool_ids = set(pool_ids)

    def list_saved_pools(self) -> tuple[SavedPool, ...]:
        return tuple(SavedPool(pool_id, "2026-08-16T12:00:00+00:00") for pool_id in sorted(self.pool_ids))

    def save_pool(self, pool_id: str) -> SavedPool:
        self.pool_ids.add(pool_id)
        return SavedPool(pool_id)

    def remove_pool(self, pool_id: str) -> bool:
        existed = pool_id in self.pool_ids
        self.pool_ids.discard(pool_id)
        return existed


GENERAL_POOL_ID = "aa70268e-4b52-42bf-a116-608b370f9501"
PRIME_POOL_ID = "effcb4a4-4dcb-45e5-935d-f15542c13e6b"
DUPLICATE_POOL_ROWS = [
    {
        "pool": GENERAL_POOL_ID,
        "chain": "Ethereum",
        "project": "aave-v3",
        "symbol": "USDC",
        "poolMeta": "General",
        "exposure": "single",
        "apy": 11.02,
        "apyBase": 11.02,
        "apyReward": 0.0,
        "tvlUsd": 28_065_143,
        "stablecoin": True,
    },
    {
        "pool": PRIME_POOL_ID,
        "chain": "Ethereum",
        "project": "aave-v3",
        "symbol": "USDC",
        "poolMeta": "Prime Instance",
        "exposure": "single",
        "apy": 4.98,
        "apyBase": 4.98,
        "apyReward": 0.0,
        "tvlUsd": 56_660_000,
        "stablecoin": True,
    },
]


class FakeMarketResponse:
    def __init__(self, rows: list[dict[str, object]] | None = None) -> None:
        self.rows = rows or [
            {
                "pool": "canonical-pool-1",
                "chain": "Ethereum",
                "project": "aave-v3",
                "symbol": "USDC",
                "apy": 5.0,
                "apyBase": 5.0,
                "apyReward": 0.0,
                "tvlUsd": 1_000_000,
                "stablecoin": True,
            }
        ]

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {"data": self.rows}


def _authenticated_alert_app(
    monkeypatch,
    client: FakeNotificationClient,
    *,
    page: str = "Alerts",
    pool_id: str | None = None,
    saved_pool_ids: tuple[str, ...] = (),
    market_rows: list[dict[str, object]] | None = None,
) -> AppTest:
    import auth_service
    import user_alerts
    import requests
    import saved_pools

    user = {
        "id": "user-1",
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
    monkeypatch.setattr(auth_service, "can_access_pro", lambda _user: True)
    monkeypatch.setattr(user_alerts, "current_user_notification_client", lambda: client)
    monkeypatch.setattr(saved_pools, "current_user_saved_pools_client", lambda: FakeSavedPoolsClient(saved_pool_ids))
    monkeypatch.setattr(requests, "get", lambda *_args, **_kwargs: FakeMarketResponse(market_rows))
    monkeypatch.delenv("FURUFLOW_MARKET_SAMPLE_MODE", raising=False)
    st.cache_data.clear()
    app = AppTest.from_file("app.py", default_timeout=60)
    app.query_params["page"] = page
    if pool_id:
        app.query_params["pool"] = pool_id
    return app.run()


def _keyed_button(app: AppTest, key: str):
    return next(button for button in app.button if button.key == key)


def _create_form_submits(app: AppTest):
    return [
        button
        for button in app.button
        if button.label == "Create alert" and str(button.key).startswith("FormSubmitter:alert_form_create")
    ]


def _pool_selectbox(app: AppTest):
    return next(selectbox for selectbox in app.selectbox if selectbox.label == "Pool")


def test_authenticated_alerts_page_has_honest_empty_state(monkeypatch) -> None:
    app = _authenticated_alert_app(monkeypatch, FakeNotificationClient())

    assert not app.exception
    assert any(button.label == "Create alert" and not button.disabled for button in app.button)
    assert any("No alerts yet" in markdown.value for markdown in app.markdown)


def test_authenticated_alerts_page_explains_and_pauses_persistent_alert(monkeypatch) -> None:
    client = FakeNotificationClient(
        alerts=[
            {
                "id": "alert-1",
                "target_pool_id": "sample-eth-usdc",
                "enabled": True,
                "minimum_strength": 60,
                "signal_tier": "free",
                "delivery_mode": "immediate",
                "timezone": "UTC",
                "cooldown_minutes": 1440,
            }
        ]
    )
    app = _authenticated_alert_app(monkeypatch, client)

    assert not app.exception
    assert any("Free-tier FuruFlow signal" in markdown.value for markdown in app.markdown)
    pause = next(button for button in app.button if button.label == "Pause")
    pause.click().run()
    assert client.toggles == [("alert-1", False)]
    assert any(button.label == "Resume" for button in app.button)


def test_configured_alert_reopens_current_pool_with_alert_return_context(monkeypatch) -> None:
    client = FakeNotificationClient(
        alerts=[
            {
                "id": "alert-1",
                "target_pool_id": "canonical-pool-1",
                "enabled": True,
                "minimum_strength": 60,
                "signal_tier": "free",
                "delivery_mode": "immediate",
                "timezone": "UTC",
                "cooldown_minutes": 1440,
            }
        ]
    )
    app = _authenticated_alert_app(monkeypatch, client)

    _keyed_button(app, "alert_pool_alert-1").click().run()
    assert app.query_params["page"] == ["Pool Detail"]
    assert app.query_params["pool"] == ["canonical-pool-1"]
    assert any(button.label == "← Back to Alerts" for button in app.button)


def test_alert_create_edit_and_delete_survive_normal_reruns(monkeypatch) -> None:
    client = FakeNotificationClient()
    app = _authenticated_alert_app(monkeypatch, client)

    _keyed_button(app, "alerts_create").click().run()
    assert any(selectbox.label == "Pool" and selectbox.value == "canonical-pool-1" for selectbox in app.selectbox)
    next(button for button in app.button if button.label == "Create alert" and button.key != "alerts_create").click().run()
    assert len(client.created) == 1
    assert len(client.alerts) == 1
    app.run()
    assert any("Configured alerts" in markdown.value for markdown in app.markdown)

    _keyed_button(app, "alert_edit_alert-1").click().run()
    next(slider for slider in app.slider if slider.label == "Minimum signal strength").set_value(75)
    next(button for button in app.button if button.label == "Save changes").click().run()
    assert client.updated[-1]["minimum_strength"] == 75

    # Start a new normal browser run against the same persistent backend model;
    # this also avoids retaining stale form widget handles in AppTest itself.
    app = _authenticated_alert_app(monkeypatch, client)
    _keyed_button(app, "alert_delete_alert-1").click().run()
    _keyed_button(app, "alert_delete_confirm_alert-1").click().run()
    assert client.deleted == ["alert-1"]
    assert not client.alerts
    assert any("No alerts yet" in markdown.value for markdown in app.markdown)


@pytest.mark.parametrize("pool_id", [GENERAL_POOL_ID, PRIME_POOL_ID])
def test_duplicate_label_watchlist_create_persists_and_reopens_exact_pool(monkeypatch, pool_id: str) -> None:
    client = FakeNotificationClient()
    app = _authenticated_alert_app(
        monkeypatch,
        client,
        page="Watchlists",
        saved_pool_ids=(pool_id,),
        market_rows=DUPLICATE_POOL_ROWS,
    )

    next(button for button in app.button if button.label == "Create alert").click().run()
    pool_selectbox = _pool_selectbox(app)
    assert pool_selectbox.value == pool_id
    assert pool_selectbox.options == [
        "aave-v3 · USDC · Ethereum · General",
        "aave-v3 · USDC · Ethereum · Prime Instance",
    ]

    _create_form_submits(app)[0].click().run()
    assert client.created[-1]["target_pool_id"] == pool_id
    app.run()
    assert client.alerts[0]["target_pool_id"] == pool_id

    _keyed_button(app, "alert_pool_alert-1").click().run()
    assert app.query_params["page"] == ["Pool Detail"]
    assert app.query_params["pool"] == [pool_id]


@pytest.mark.parametrize("pool_id", [GENERAL_POOL_ID, PRIME_POOL_ID])
def test_duplicate_label_pool_detail_create_persists_and_reopens_exact_pool(monkeypatch, pool_id: str) -> None:
    client = FakeNotificationClient()
    app = _authenticated_alert_app(
        monkeypatch,
        client,
        page="Pool Detail",
        pool_id=pool_id,
        market_rows=DUPLICATE_POOL_ROWS,
    )

    next(button for button in app.button if button.label == "Create alert").click().run()
    assert app.session_state["alert_prefill_pool_id"] == pool_id

    # AppTest retains a stale Pool Detail sidebar widget after the route-changing
    # rerun. Start the Alerts render from the exact canonical transition state to
    # exercise the form submission without relying on that test-runner artifact.
    app = _authenticated_alert_app(monkeypatch, client, market_rows=DUPLICATE_POOL_ROWS)
    for key, value in alert_creation_state(pool_id).items():
        app.session_state[key] = value
    app.session_state["alert_create_request_key"] = f"pool-detail-{pool_id}"
    app.run()
    assert _pool_selectbox(app).value == pool_id
    _create_form_submits(app)[0].click().run()
    assert client.created[-1]["target_pool_id"] == pool_id

    _keyed_button(app, "alert_pool_alert-1").click().run()
    assert app.query_params["page"] == ["Pool Detail"]
    assert app.query_params["pool"] == [pool_id]


@pytest.mark.parametrize("pool_id", [GENERAL_POOL_ID, PRIME_POOL_ID])
def test_duplicate_label_manual_alert_selection_uses_canonical_option_value(monkeypatch, pool_id: str) -> None:
    client = FakeNotificationClient()
    app = _authenticated_alert_app(monkeypatch, client, market_rows=DUPLICATE_POOL_ROWS)

    _keyed_button(app, "alerts_create").click().run()
    pool_selectbox = _pool_selectbox(app)
    pool_selectbox.set_value(pool_id)
    _create_form_submits(app)[0].click().run()

    assert client.created[-1]["target_pool_id"] == pool_id
    assert client.created[-1]["target_pool_id"] != (
        PRIME_POOL_ID if pool_id == GENERAL_POOL_ID else GENERAL_POOL_ID
    )


def test_duplicate_label_alert_identity_survives_reload_edit_pause_resume_and_reopen(monkeypatch) -> None:
    client = FakeNotificationClient()
    app = _authenticated_alert_app(
        monkeypatch,
        client,
        page="Watchlists",
        saved_pool_ids=(GENERAL_POOL_ID,),
        market_rows=DUPLICATE_POOL_ROWS,
    )
    next(button for button in app.button if button.label == "Create alert").click().run()
    _create_form_submits(app)[0].click().run()
    assert client.alerts[0]["target_pool_id"] == GENERAL_POOL_ID

    app = _authenticated_alert_app(monkeypatch, client, market_rows=DUPLICATE_POOL_ROWS)
    assert client.alerts[0]["target_pool_id"] == GENERAL_POOL_ID
    _keyed_button(app, "alert_edit_alert-1").click().run()
    next(slider for slider in app.slider if slider.label == "Minimum signal strength").set_value(75)
    next(button for button in app.button if button.label == "Save changes").click().run()
    assert client.alerts[0]["target_pool_id"] == GENERAL_POOL_ID

    app = _authenticated_alert_app(monkeypatch, client, market_rows=DUPLICATE_POOL_ROWS)
    _keyed_button(app, "alert_toggle_alert-1").click().run()
    assert client.alerts[0]["target_pool_id"] == GENERAL_POOL_ID
    assert client.alerts[0]["enabled"] is False
    _keyed_button(app, "alert_toggle_alert-1").click().run()
    assert client.alerts[0]["target_pool_id"] == GENERAL_POOL_ID
    assert client.alerts[0]["enabled"] is True

    _keyed_button(app, "alert_pool_alert-1").click().run()
    assert app.query_params["pool"] == [GENERAL_POOL_ID]


def test_ambiguous_legacy_label_prefill_fails_closed_without_creation(monkeypatch) -> None:
    client = FakeNotificationClient()
    app = _authenticated_alert_app(monkeypatch, client, market_rows=DUPLICATE_POOL_ROWS)
    app.session_state["alert_form_mode"] = "create"
    app.session_state["alert_prefill_pool_id"] = "aave-v3 · USDC · Ethereum"
    app.session_state["alert_create_request_key"] = "legacy-label-request"

    app.run()

    assert not app.exception
    assert not _create_form_submits(app)
    assert "alert_form_mode" not in app.session_state.filtered_state
    assert "alert_prefill_pool_id" not in app.session_state.filtered_state
    assert "alert_create_request_key" not in app.session_state.filtered_state
    assert client.created == []
    assert any("Choose the exact pool again" in markdown.value for markdown in app.markdown)


def test_pool_detail_create_alert_preserves_canonical_context_without_pool_query(monkeypatch) -> None:
    app = _authenticated_alert_app(
        monkeypatch,
        FakeNotificationClient(),
        page="Pool Detail",
        pool_id="canonical-pool-1",
    )

    assert not app.exception
    next(button for button in app.button if button.label == "Create alert").click().run()
    assert app.query_params["page"] == ["Alerts"]
    assert "pool" not in app.query_params
    assert any(selectbox.label == "Pool" and selectbox.value == "canonical-pool-1" for selectbox in app.selectbox)


def test_watchlist_create_alert_fails_closed_while_telegram_is_unlinked(monkeypatch) -> None:
    client = FakeNotificationClient(linked=False)
    app = _authenticated_alert_app(
        monkeypatch,
        client,
        page="Watchlists",
        saved_pool_ids=("canonical-pool-1",),
    )

    next(button for button in app.button if button.label == "Create alert").click().run()
    assert not app.exception
    assert app.query_params["page"] == ["Alerts"]
    assert app.session_state["alert_prefill_pool_id"] == "canonical-pool-1"
    assert _keyed_button(app, "alerts_create").disabled
    assert not _create_form_submits(app)
    assert any("Telegram connection required" in markdown.value for markdown in app.markdown)
    assert client.created == []

    app.run()
    assert not _create_form_submits(app)
    assert client.created == []


def test_pool_detail_create_alert_fails_closed_without_corrupting_pool_identity(monkeypatch) -> None:
    client = FakeNotificationClient(linked=False)
    app = _authenticated_alert_app(
        monkeypatch,
        client,
        page="Pool Detail",
        pool_id="canonical-pool-1",
    )

    next(button for button in app.button if button.label == "Create alert").click().run()
    assert not app.exception
    assert app.query_params["page"] == ["Alerts"]
    assert "pool" not in app.query_params
    assert app.session_state["alert_prefill_pool_id"] == "canonical-pool-1"
    assert _keyed_button(app, "alerts_create").disabled
    assert not _create_form_submits(app)
    assert client.created == []


def test_stale_create_state_is_cleared_and_linkage_changes_fail_closed(monkeypatch) -> None:
    client = FakeNotificationClient(linked=False)
    app = _authenticated_alert_app(monkeypatch, client)
    app.session_state["alert_prefill_pool_id"] = "canonical-pool-1"
    app.session_state["alert_form_mode"] = "create"
    app.session_state["alert_create_request_key"] = "stale-request-key"

    app.run()
    assert not app.exception
    assert "alert_form_mode" not in app.session_state.filtered_state
    assert "alert_create_request_key" not in app.session_state.filtered_state
    assert not _create_form_submits(app)
    assert client.created == []

    app.run()
    assert not _create_form_submits(app)

    client.linked = True
    app.run()
    assert not _keyed_button(app, "alerts_create").disabled
    assert not _create_form_submits(app)

    _keyed_button(app, "alerts_create").click().run()
    create_submit = _create_form_submits(app)
    assert len(create_submit) == 1
    assert not create_submit[0].disabled
    assert any(
        selectbox.label == "Pool" and selectbox.value == "canonical-pool-1"
        for selectbox in app.selectbox
    )

    client.linked = False
    app.run()
    assert _keyed_button(app, "alerts_create").disabled
    assert not _create_form_submits(app)
    assert client.created == []


def test_telegram_status_failure_clears_stale_creation_without_mutation(monkeypatch) -> None:
    client = FakeNotificationClient(status_error=True)
    app = _authenticated_alert_app(monkeypatch, client)
    app.session_state["alert_form_mode"] = "create"
    app.session_state["alert_create_request_key"] = "stale-request-key"

    app.run()
    assert not app.exception
    assert "alert_form_mode" not in app.session_state.filtered_state
    assert "alert_create_request_key" not in app.session_state.filtered_state
    assert not _create_form_submits(app)
    assert any("temporarily unavailable" in markdown.value for markdown in app.markdown)
    assert client.created == []


def test_strategy_result_carries_canonical_pool_directly_into_alert_creation(monkeypatch) -> None:
    app = _authenticated_alert_app(monkeypatch, FakeNotificationClient(), page="Pro Tools")
    next(slider for slider in app.slider if slider.label == "Strategy minimum APY").set_value(0.0).run()
    next(slider for slider in app.slider if slider.label == "Strategy minimum TVL").set_value(0).run()
    next(slider for slider in app.slider if slider.label == "Strategy maximum risk").set_value(100).run()

    _keyed_button(app, "strategy_result_alert").click().run()
    assert not app.exception
    assert app.query_params["page"] == ["Alerts"]
    assert "pool" not in app.query_params
    assert any(selectbox.label == "Pool" and selectbox.value == "canonical-pool-1" for selectbox in app.selectbox)


@pytest.mark.parametrize("source_page", ["Discover", "Watchlists"])
def test_discover_and_watchlist_create_alert_preselect_canonical_pool(monkeypatch, source_page: str) -> None:
    app = _authenticated_alert_app(
        monkeypatch,
        FakeNotificationClient(),
        page=source_page,
        saved_pool_ids=("canonical-pool-1",) if source_page == "Watchlists" else (),
    )

    if source_page == "Discover":
        next(radio for radio in app.radio if radio.label == "Discover view").set_value("All Pools").run()
    next(button for button in app.button if button.label == "Create alert").click().run()
    assert not app.exception
    assert app.query_params["page"] == ["Alerts"]
    assert "pool" not in app.query_params
    assert any(selectbox.label == "Pool" and selectbox.value == "canonical-pool-1" for selectbox in app.selectbox)
