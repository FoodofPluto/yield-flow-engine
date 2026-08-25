from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from ui_shell import (
    AUTHENTICATED_NAV,
    PUBLIC_NAV,
    account_control_model,
    alert_creation_state,
    canonical_route,
    pool_detail_back_state,
    pool_detail_query_context,
    pool_detail_state,
    pool_detail_url,
    research_selection_state,
    route_access,
    update_route_state,
    visible_navigation,
    market_filters_apply,
)


def _routes(*, signed_in: bool, is_pro: bool = False, is_admin: bool = False) -> list[str]:
    return [item.route for item in visible_navigation(signed_in=signed_in, is_pro=is_pro, is_admin=is_admin)]


def test_signed_out_navigation_contains_only_public_routes() -> None:
    assert _routes(signed_in=False) == [item.route for item in PUBLIC_NAV]
    assert "Admin" not in _routes(signed_in=False)
    assert "Watchlists" not in _routes(signed_in=False)


def test_authenticated_navigation_adds_workspace_without_admin() -> None:
    routes = _routes(signed_in=True)
    assert routes == [
        "Home",
        "Discover",
        "Research",
        "Watchlists",
        "Alerts",
        "Activity & Digests",
        "Signals",
        "Pro Tools",
        "Methodology & Data Status",
        "Pricing",
        "Account & Billing",
    ]
    assert "Admin" not in routes


def test_verified_admin_is_the_only_navigation_model_that_exposes_admin() -> None:
    assert _routes(signed_in=True, is_admin=True)[-1] == "Admin"
    assert "Admin" not in _routes(signed_in=True, is_admin=False)
    assert "Admin" not in _routes(signed_in=False, is_admin=True)


def test_admin_and_authenticated_routes_deny_direct_unauthorized_access() -> None:
    assert route_access("Admin", signed_in=True, is_admin=False) == (False, "unauthorized")
    assert route_access("Admin", signed_in=False, is_admin=False) == (False, "unauthorized")
    assert route_access("Watchlists", signed_in=False, is_admin=False) == (False, "authentication_required")
    assert route_access("Admin", signed_in=True, is_admin=True) == (True, None)


def test_pro_navigation_marks_locked_context_without_hiding_it_from_free_accounts() -> None:
    free_items = visible_navigation(signed_in=True, is_pro=False, is_admin=False)
    pro_items = visible_navigation(signed_in=True, is_pro=True, is_admin=False)
    assert next(item.label for item in free_items if item.route == "Pro Tools").endswith("· Pro")
    assert next(item.label for item in pro_items if item.route == "Pro Tools") == "Pro tools"


def test_primary_navigation_routes_are_canonical_and_unknown_routes_fail_safe() -> None:
    for item in (*PUBLIC_NAV, *AUTHENTICATED_NAV):
        assert canonical_route(item.route) == (item.route, None)
    assert canonical_route("not-a-route") == ("Home", None)


def test_pool_detail_open_and_back_preserve_results_context() -> None:
    opened = pool_detail_state("pool-123", return_route="Discover", return_view="Signals")
    assert opened["current_route"] == "Pool Detail"
    assert opened["selected_pool_id"] == "pool-123"
    assert pool_detail_back_state(opened) == {"current_route": "Discover", "current_view": "Signals"}

    state: dict[str, object] = {}
    update_route_state(state, "Discover", view="Opportunities", pool_id="pool-456")
    assert state["current_route"] == "Pool Detail"
    assert state["pool_return_route"] == "Discover"
    assert state["pool_return_view"] == "Opportunities"

    compared = pool_detail_state("pool-789", return_route="Research", return_view="Comparison")
    assert pool_detail_back_state(compared) == {"current_route": "Research", "current_view": "Comparison"}


def test_pool_detail_context_can_return_to_the_existing_watchlists_route() -> None:
    opened = pool_detail_state("canonical-pool-123", return_route="Watchlists")

    assert pool_detail_back_state(opened) == {"current_route": "Watchlists", "current_view": "Opportunities"}


def test_table_pool_link_uses_canonical_contextual_pool_detail_url() -> None:
    url = pool_detail_url(
        "canonical-pool-123",
        public_origin="https://furuflow-staging.onrender.com/",
        return_route="Signals",
        return_view="Signals",
    )
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert f"{parsed.scheme}://{parsed.netloc}" == "https://furuflow-staging.onrender.com"
    assert query == {
        "page": ["Pool Detail"],
        "pool": ["canonical-pool-123"],
        "return_route": ["Signals"],
        "return_view": ["Signals"],
    }
    assert pool_detail_query_context({key: values[0] for key, values in query.items()}) == {
        "pool_return_route": "Signals",
        "pool_return_view": "Signals",
    }


def test_pool_detail_url_rejects_unrecognized_return_context() -> None:
    assert pool_detail_query_context({"return_route": "Admin", "return_view": "Secrets"}) == {}
    with pytest.raises(ValueError, match="return context"):
        pool_detail_url(
            "canonical-pool-123",
            public_origin="https://furuflow-staging.onrender.com",
            return_route="Admin",
            return_view="Secrets",
        )


def test_pool_detail_alert_action_uses_session_state_without_a_pool_url() -> None:
    assert alert_creation_state("canonical-pool-123") == {
        "current_route": "Alerts",
        "alert_prefill_pool_id": "canonical-pool-123",
        "alert_form_mode": "create",
    }


def test_pool_context_can_enter_bounded_research_without_url_session_state() -> None:
    assert research_selection_state("pool-c", ("pool-a", "pool-b")) == {
        "current_route": "Research",
        "research_selection": ["pool-a", "pool-b", "pool-c"],
    }
    state = research_selection_state("pool-e", ("pool-a", "pool-b", "pool-c", "pool-d"))
    assert state["research_selection"] == ["pool-b", "pool-c", "pool-d", "pool-e"]
    assert all(key not in state for key in ("access_token", "refresh_token", "session"))


def test_renamed_and_reorganized_pages_map_to_the_new_sitemap() -> None:
    expected = {
        "Scanner": ("Discover", "Opportunities"),
        "Signals": ("Signals", None),
        "Signal Engine": ("Signals", None),
        "Market Map": ("Research", "Comparison"),
        "Pool Explorer": ("Discover", "Opportunities"),
        "Watchlist": ("Watchlists", None),
        "Recaps": ("Activity & Digests", None),
        "Protocol Dashboard": ("Research", "Comparison"),
        "Strategy Builder": ("Pro Tools", "Strategy Builder"),
        "Arbitrage": ("Pro Tools", "Yield Spreads"),
    }
    assert {name: canonical_route(name) for name in expected} == expected


def test_account_control_model_is_compact_and_uses_server_derived_roles() -> None:
    assert account_control_model(None, is_pro=False, is_admin=False) == {
        "label": "Sign in",
        "email": "Public browsing",
        "plan": "Free",
        "status": "signed_out",
    }
    user = {"email": "member@example.com"}
    assert account_control_model(user, is_pro=False, is_admin=False)["plan"] == "Free"
    assert account_control_model(user, is_pro=True, is_admin=False)["plan"] == "Pro"
    assert account_control_model(user, is_pro=True, is_admin=True)["plan"] == "Admin"


def test_discover_filter_controls_do_not_render_as_a_second_pro_tools_workflow() -> None:
    assert market_filters_apply("Discover") is True
    assert market_filters_apply("Research") is False
    assert market_filters_apply("Pro Tools") is False
