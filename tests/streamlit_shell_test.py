from __future__ import annotations

from streamlit.testing.v1 import AppTest


def _button(app: AppTest, label: str):
    return next(button for button in app.button if button.label == label)


def test_signed_out_shell_navigation_and_pool_detail_round_trip() -> None:
    app = AppTest.from_file("app.py", default_timeout=60).run()
    assert not app.exception

    labels = [button.label for button in app.button]
    expected_navigation = ["Home", "Discover", "Research", "Signals", "Methodology & data", "Pricing"]
    assert [label for label in labels if label in expected_navigation] == expected_navigation
    assert "Admin" not in labels
    assert "Watchlist" not in labels

    _button(app, "Discover").click().run()
    assert not app.exception
    assert app.radio[0].label == "Discover view"
    assert app.radio[0].options == ["Opportunities", "All Pools"]

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


def test_pricing_truthfully_previews_four_tiers_without_new_purchase_paths() -> None:
    app = AppTest.from_file("app.py", default_timeout=60)
    app.query_params["page"] = "Pricing"
    app.run()

    assert not app.exception
    rendered = "\n".join(markdown.value for markdown in app.markdown)
    for value in ("Free", "$0", "Core", "$9.99/month", "Plus", "$14.99/month", "Pro", "$24.99/month"):
        assert value in rendered
    assert "not yet purchasable" in rendered
    assert "existing $20 Pro checkout" in rendered
