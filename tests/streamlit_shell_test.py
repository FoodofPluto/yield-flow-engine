from __future__ import annotations

from streamlit.testing.v1 import AppTest


def _button(app: AppTest, label: str):
    return next(button for button in app.button if button.label == label)


def test_signed_out_shell_navigation_and_pool_detail_round_trip() -> None:
    app = AppTest.from_file("app.py", default_timeout=60).run()
    assert not app.exception

    labels = [button.label for button in app.button]
    assert labels[:5] == ["Home", "Discover", "Research", "Pricing", "Methodology & data"]
    assert "Admin" not in labels
    assert "Watchlists" not in labels

    _button(app, "Discover").click().run()
    assert not app.exception
    assert app.radio[0].label == "Discover view"
    assert app.radio[0].options == ["Opportunities", "Signals", "Compare"]

    _button(app, "View details").click().run()
    assert not app.exception
    assert app.query_params["page"] == ["Pool Detail"]
    assert app.query_params.get("pool")
    assert any(button.label == "← Back to opportunities" for button in app.button)

    _button(app, "← Back to opportunities").click().run()
    assert not app.exception
    assert app.query_params["page"] == ["Discover"]


def test_direct_admin_route_is_denied_to_signed_out_user() -> None:
    app = AppTest.from_file("app.py", default_timeout=60)
    app.query_params["page"] = "Admin"
    app.run()
    assert not app.exception
    assert any("Unauthorized" in warning.value for warning in app.markdown)


def test_direct_alerts_route_requires_authentication() -> None:
    app = AppTest.from_file("app.py", default_timeout=60)
    app.query_params["page"] = "Alerts"
    app.run()
    assert not app.exception
    assert any("Authentication required" in markdown.value for markdown in app.markdown)
