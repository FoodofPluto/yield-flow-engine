from __future__ import annotations

from ui_shell import (
    AUTHENTICATED_NAV,
    PUBLIC_NAV,
    account_control_model,
    alert_creation_state,
    canonical_route,
    pool_detail_back_state,
    pool_detail_state,
    route_access,
    update_route_state,
    visible_navigation,
)


def _routes(*, signed_in: bool, is_pro: bool = False, is_admin: bool = False) -> list[str]:
    return [item.route for item in visible_navigation(signed_in=signed_in, is_pro=is_pro, is_admin=is_admin)]


def test_signed_out_navigation_contains_only_public_routes() -> None:
    assert _routes(signed_in=False) == [item.route for item in PUBLIC_NAV]
    assert "Admin" not in _routes(signed_in=False)
    assert "Watchlists" not in _routes(signed_in=False)


def test_authenticated_navigation_adds_workspace_without_admin() -> None:
    routes = _routes(signed_in=True)
    assert routes == [item.route for item in (*PUBLIC_NAV, *AUTHENTICATED_NAV)]
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

    compared = pool_detail_state("pool-789", return_route="Discover", return_view="Compare")
    assert pool_detail_back_state(compared) == {"current_route": "Discover", "current_view": "Compare"}


def test_pool_detail_context_can_return_to_the_existing_watchlists_route() -> None:
    opened = pool_detail_state("canonical-pool-123", return_route="Watchlists")

    assert pool_detail_back_state(opened) == {"current_route": "Watchlists", "current_view": "Opportunities"}


def test_pool_detail_alert_action_uses_session_state_without_a_pool_url() -> None:
    assert alert_creation_state("canonical-pool-123") == {
        "current_route": "Alerts",
        "alert_prefill_pool_id": "canonical-pool-123",
        "alert_form_mode": "create",
    }


def test_renamed_and_reorganized_pages_map_to_the_new_sitemap() -> None:
    expected = {
        "Scanner": ("Discover", "Opportunities"),
        "Signals": ("Discover", "Signals"),
        "Market Map": ("Research", "Market Map"),
        "Pool Explorer": ("Discover", "Opportunities"),
        "Watchlist": ("Watchlists", None),
        "Recaps": ("Activity & Digests", None),
        "Protocol Dashboard": ("Research", "Protocols"),
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
