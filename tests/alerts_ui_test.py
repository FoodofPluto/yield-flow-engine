from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest
import streamlit as st

from saved_pools import SavedPool


@pytest.fixture(autouse=True)
def _clear_streamlit_cache_after_test():
    yield
    st.cache_data.clear()


class FakeNotificationClient:
    def __init__(self, *, alerts: list[dict[str, object]] | None = None, linked: bool = True) -> None:
        self.alerts = alerts or []
        self.linked = linked
        self.toggles: list[tuple[str, bool]] = []
        self.created: list[dict[str, object]] = []
        self.updated: list[dict[str, object]] = []
        self.deleted: list[str] = []

    def telegram_status(self) -> dict[str, object]:
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


class FakeMarketResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "data": [
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
        }


def _authenticated_alert_app(
    monkeypatch,
    client: FakeNotificationClient,
    *,
    page: str = "Alerts",
    pool_id: str | None = None,
    saved_pool_ids: tuple[str, ...] = (),
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
    monkeypatch.setattr(auth_service, "can_access_pro", lambda _user: False)
    monkeypatch.setattr(user_alerts, "current_user_notification_client", lambda: client)
    monkeypatch.setattr(saved_pools, "current_user_saved_pools_client", lambda: FakeSavedPoolsClient(saved_pool_ids))
    monkeypatch.setattr(requests, "get", lambda *_args, **_kwargs: FakeMarketResponse())
    monkeypatch.delenv("FURUFLOW_MARKET_SAMPLE_MODE", raising=False)
    st.cache_data.clear()
    app = AppTest.from_file("app.py", default_timeout=60)
    app.query_params["page"] = page
    if pool_id:
        app.query_params["pool"] = pool_id
    return app.run()


def _keyed_button(app: AppTest, key: str):
    return next(button for button in app.button if button.key == key)


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
