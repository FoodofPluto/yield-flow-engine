from __future__ import annotations

import html
from dataclasses import dataclass
from html import escape
from typing import Any, Mapping, MutableMapping
from urllib.parse import urlencode

import streamlit as st

from product_capabilities import Capability, ProductCapabilities


@dataclass(frozen=True)
class NavItem:
    route: str
    label: str
    section: str
    requires_auth: bool = False
    required_capability: Capability | None = None
    admin_only: bool = False


PUBLIC_NAV = (
    NavItem("Home", "Home", "Find"),
    NavItem("Discover", "Discover", "Find"),
    NavItem("Research", "Research", "Compare"),
    NavItem("Signals", "Signals", "Investigate"),
    NavItem("Methodology & Data Status", "Methodology & data", "Learn & account"),
    NavItem("Pricing", "Pricing", "Learn & account"),
)

AUTHENTICATED_NAV = (
    NavItem("Watchlists", "Watchlist", "Monitor", requires_auth=True, required_capability=Capability.WATCHLISTS),
    NavItem("Alerts", "Alerts", "Monitor", requires_auth=True, required_capability=Capability.ALERTS),
    NavItem("Pro Tools", "Pro tools", "Advanced", requires_auth=True, required_capability=Capability.PRO_TOOLS),
    NavItem("Account & Billing", "Account & billing", "Learn & account", requires_auth=True),
)

ADMIN_NAV = NavItem("Admin", "Admin", "Restricted", requires_auth=True, admin_only=True)

ALL_ROUTES = frozenset(item.route for item in (*PUBLIC_NAV, *AUTHENTICATED_NAV, ADMIN_NAV)) | {
    "Pool Detail",
    "Activity & Digests",
}

LEGACY_ROUTE_ALIASES = {
    "Scanner": ("Discover", "Opportunities"),
    "Signal Engine": ("Signals", None),
    "Market Map": ("Research", "Comparison"),
    "Pool Explorer": ("Discover", "Opportunities"),
    "Watchlist": ("Watchlists", None),
    "Recaps": ("Activity & Digests", None),
    "Protocol Dashboard": ("Research", "Comparison"),
    "Strategy Builder": ("Pro Tools", "Strategy Builder"),
    "Arbitrage": ("Pro Tools", "Yield Spreads"),
}

PAGE_CONTEXT = {
    "Home": ("Find → Understand → Compare → Monitor → Act", "Move from current provider reports to evidence, comparison, monitoring, and an informed external action."),
    "Discover": ("Discover", "Find investigation candidates or search the broader current pool universe."),
    "Research": ("Research", "Compare a deliberately selected set of pools, their reported metrics, evidence, and tradeoffs."),
    "Signals": ("Signals", "Investigate observed yield and liquidity movement without treating missing history as a weak signal."),
    "Pricing": ("Pricing", "Preview the planned Free, Core, Plus, and Pro capability ladder; new paid tiers are not yet purchasable."),
    "Methodology & Data Status": (
        "Methodology & data status",
        "See how FuruFlow frames yield, risk, freshness, and degraded source conditions.",
    ),
    "Watchlists": ("Watchlist", "Monitor the pools you deliberately saved and decide what deserves attention."),
    "Alerts": ("Alerts", "Create and manage persistent pool alerts delivered through verified Telegram routing."),
    "Activity & Digests": ("Activity & digests", "Review observed market activity and available recap history."),
    "Pro Tools": ("Pro tools", "Compose strategy slices and inspect cross-chain yield spreads."),
    "Account & Billing": ("Account & billing", "Review the server-authoritative account and entitlement state."),
    "Admin": ("Admin", "Restricted account administration guidance for verified administrators."),
    "Pool Detail": ("Pool detail", "Understand one pool and continue into monitoring, alerts, or focused research."),
}

DISCOVER_VIEWS = ("Opportunities", "All Pools")
RESEARCH_VIEWS = ("Comparison",)
PRO_TOOL_VIEWS = ("Strategy Builder", "Yield Spreads")
OPPORTUNITIES_TABLE_COLUMNS = (
    ("pool", "Pool"),
    ("symbol", "Asset"),
    ("chain", "Network"),
    ("project", "Protocol"),
    ("strategy_type", "Strategy"),
    ("apy", "APY"),
    ("tvlUsd", "TVL (USD)"),
    ("evidence_coverage", "Evidence"),
    ("confidence_level", "Confidence"),
    ("risk_score", "Risk"),
    ("data_freshness", "Freshness"),
)
SIGNAL_ENGINE_TABLE_COLUMNS = (
    ("pool", "Pool"),
    ("project", "Protocol"),
    ("chain", "Chain"),
    ("symbol", "Asset"),
    ("signal", "Signal"),
    ("signal_strength", "Strength"),
    ("evidence_coverage", "Evidence"),
    ("confidence_level", "Confidence"),
    ("risk_band", "Risk"),
    ("data_freshness", "Freshness"),
    ("apy_delta_7", "7d APY Δ"),
    ("tvl_delta_7_pct", "7d TVL Δ %"),
    ("apy_volatility", "APY volatility"),
)
STRATEGY_RESULTS_TABLE_COLUMNS = (
    ("pool", "Pool"),
    ("project", "Protocol"),
    ("chain", "Chain"),
    ("symbol", "Asset"),
    ("apy", "APY"),
    ("tvlUsd", "TVL (USD)"),
    ("risk_score", "Risk"),
    ("signal", "Signal"),
)

POOL_DETAIL_RETURN_VIEWS = {
    "Home": frozenset({"Home"}),
    "Discover": frozenset(DISCOVER_VIEWS),
    "Research": frozenset(RESEARCH_VIEWS),
    "Signals": frozenset({"Signals"}),
    "Pro Tools": frozenset(PRO_TOOL_VIEWS),
    "Watchlists": frozenset({"Opportunities"}),
    "Alerts": frozenset({"Alerts"}),
}


def pool_detail_url(
    pool_id: str,
    *,
    return_route: str,
    return_view: str,
    discover_state: Mapping[str, str] | None = None,
) -> str:
    """Build a same-origin Pool Detail URL with allowlisted return context."""

    allowed_views = POOL_DETAIL_RETURN_VIEWS.get(return_route)
    if allowed_views is None or return_view not in allowed_views:
        raise ValueError("Invalid Pool Detail return context.")
    query_values = {
        "page": "Pool Detail",
        "pool": str(pool_id),
        "return_route": return_route,
        "return_view": return_view,
    }
    if return_route == "Discover" and discover_state:
        from market_research import FILTER_QUERY_KEYS

        query_values.update(
            (key, str(value)) for key, value in discover_state.items() if key in FILTER_QUERY_KEYS and value not in {None, ""}
        )
    query = urlencode(query_values)
    return f"/?{query}"


def pool_detail_anchor(
    pool_id: str,
    *,
    return_route: str,
    return_view: str,
    label: str = "Open Pool",
    discover_state: Mapping[str, str] | None = None,
) -> str:
    """Render canonical internal navigation explicitly in the current tab."""

    url = pool_detail_url(
        pool_id,
        return_route=return_route,
        return_view=return_view,
        discover_state=discover_state,
    )
    return (
        f'<a class="ff-pool-detail-link" href="{html.escape(url, quote=True)}" '
        f'target="_self" data-ff-route="pool-detail">{html.escape(label)}</a>'
    )


def pool_detail_query_context(params: Mapping[str, Any]) -> dict[str, str]:
    """Return only valid, non-secret Pool Detail navigation context from a URL."""

    return_route = str(params.get("return_route") or "")
    return_view = str(params.get("return_view") or "")
    if return_view not in POOL_DETAIL_RETURN_VIEWS.get(return_route, frozenset()):
        return {}
    return {
        "pool_return_route": return_route,
        "pool_return_view": return_view,
    }


def visible_navigation(
    *, signed_in: bool, capabilities: ProductCapabilities, is_admin: bool
) -> tuple[NavItem, ...]:
    items = list(PUBLIC_NAV)
    if signed_in:
        for item in AUTHENTICATED_NAV:
            if item.required_capability is None or capabilities.allows(item.required_capability):
                items.append(item)
    if signed_in and is_admin:
        items.append(ADMIN_NAV)
    section_order = {
        "Find": 0,
        "Compare": 1,
        "Investigate": 2,
        "Monitor": 3,
        "Advanced": 4,
        "Learn & account": 5,
        "Restricted": 6,
    }
    route_order = {
        route: index
        for index, route in enumerate(
            (
                "Home",
                "Discover",
                "Research",
                "Signals",
                "Watchlists",
                "Alerts",
                "Pro Tools",
                "Methodology & Data Status",
                "Pricing",
                "Account & Billing",
                "Admin",
            )
        )
    }
    return tuple(sorted(items, key=lambda item: (section_order[item.section], route_order[item.route])))


def canonical_route(route: str | None) -> tuple[str, str | None]:
    requested = (route or "Home").strip()
    if requested in LEGACY_ROUTE_ALIASES:
        return LEGACY_ROUTE_ALIASES[requested]
    if requested in ALL_ROUTES:
        return requested, None
    return "Home", None


def route_access(
    route: str,
    *,
    signed_in: bool,
    capabilities: ProductCapabilities,
    is_admin: bool,
) -> tuple[bool, str | None]:
    if route == "Admin" and not is_admin:
        return False, "unauthorized"
    protected = {item.route for item in AUTHENTICATED_NAV} | {"Activity & Digests"}
    if route in protected and not signed_in:
        return False, "authentication_required"
    item = next((item for item in AUTHENTICATED_NAV if item.route == route), None)
    if item and item.required_capability and not capabilities.allows(item.required_capability):
        return False, "capability_required"
    if route == "Pool Detail":
        return True, None
    return route in ALL_ROUTES, None if route in ALL_ROUTES else "not_found"


def account_control_model(
    user: Mapping[str, Any] | None,
    *,
    capabilities: ProductCapabilities,
    is_admin: bool,
) -> dict[str, str]:
    if not user:
        return {
            "label": "Sign in",
            "email": "Public browsing",
            "plan": "Free",
            "status": "signed_out",
        }
    email = str(user.get("email") or "Signed-in account")
    plan = "Admin" if is_admin else capabilities.tier.value.title()
    return {
        "label": f"{email} · {plan}",
        "email": email,
        "plan": plan,
        "status": "signed_in",
    }


def pool_detail_state(pool_id: str, *, return_route: str = "Discover", return_view: str = "Opportunities") -> dict[str, str]:
    return {
        "current_route": "Pool Detail",
        "selected_pool_id": str(pool_id),
        "pool_return_route": return_route,
        "pool_return_view": return_view,
    }


def pool_detail_back_state(state: Mapping[str, Any]) -> dict[str, str]:
    return {
        "current_route": str(state.get("pool_return_route") or "Discover"),
        "current_view": str(state.get("pool_return_view") or "Opportunities"),
    }


def alert_creation_state(pool_id: str) -> dict[str, str]:
    return {
        "current_route": "Alerts",
        "alert_prefill_pool_id": str(pool_id),
        "alert_form_mode": "create",
    }


def research_selection_state(pool_id: str, selected: tuple[str, ...] = ()) -> dict[str, Any]:
    """Carry canonical pool context into bounded Research state without a URL secret."""

    pool_id = str(pool_id)
    values = list(dict.fromkeys(str(item) for item in selected if item))
    if pool_id not in values:
        values.append(pool_id)
    return {
        "current_route": "Research",
        "research_selection": values[-4:],
    }


def research_selection_state_many(pool_ids: tuple[str, ...], selected: tuple[str, ...] = ()) -> dict[str, Any]:
    """Carry one or more canonical pools into the bounded Research selection."""

    values = list(dict.fromkeys(str(item) for item in (*selected, *pool_ids) if item))
    return {"current_route": "Research", "research_selection": values[-4:]}


def update_route_state(
    state: MutableMapping[str, Any],
    route: str,
    *,
    view: str | None = None,
    pool_id: str | None = None,
) -> None:
    state["current_route"] = route
    if view:
        state["current_view"] = view
        if route == "Discover":
            state["discover_view"] = view
        elif route == "Research":
            state["research_view"] = view
        elif route == "Pro Tools":
            state["pro_tools_view"] = view
    if pool_id:
        state.update(pool_detail_state(pool_id, return_route=route, return_view=view or "Opportunities"))


def inject_shell_css() -> None:
    st.markdown(
        """
        <style>
            .block-container { max-width: 1440px; padding-top: 1.1rem; }
            .ff-brand { display:flex; align-items:center; gap:.7rem; padding:.3rem 0 1rem; }
            .ff-brand-mark { width:2rem; height:2rem; display:grid; place-items:center; border-radius:.7rem;
                background:linear-gradient(135deg,var(--ff-color-interactive),#6b86ff); color:#07131f !important; font-weight:950; }
            .ff-brand-name { color:var(--ff-color-text); font-size:1.05rem; font-weight:900; letter-spacing:-.02em; line-height:1.2; }
            .ff-brand-copy { color:var(--ff-color-text-muted); font-size:var(--ff-font-size-meta); line-height:1.35; }
            .ff-page-head { padding:.2rem 0 .85rem; border-bottom:1px solid var(--ff-color-border); margin-bottom:1rem; }
            .ff-breadcrumb { color:var(--ff-color-text-subtle); font-size:var(--ff-font-size-meta); font-weight:750; letter-spacing:.05em; text-transform:uppercase; }
            .ff-page-title { color:var(--ff-color-text); font-size:clamp(1.7rem,3vw,2.45rem); font-weight:900; letter-spacing:-.035em;
                line-height:1.08; margin:.3rem 0; }
            .ff-page-copy { color:var(--ff-color-text-muted); font-size:var(--ff-font-size-body); line-height:var(--ff-line-height-body); max-width:72ch; }
            .ff-status { display:grid; grid-template-columns:auto 1fr; gap:.7rem; align-items:start; padding:.8rem .9rem;
                margin:.55rem 0 1rem; border:1px solid var(--ff-color-border); border-radius:var(--ff-radius-md); background:var(--ff-color-surface); }
            .ff-status-icon { font-size:.95rem; line-height:1.3; }
            .ff-status-title { color:var(--ff-color-text); font-weight:850; font-size:.88rem; }
            .ff-status-copy { color:var(--ff-color-text-muted); font-size:var(--ff-font-size-supporting); line-height:1.45; margin-top:.12rem; }
            .ff-status--warning { border-color:rgba(247,207,101,.5); background:linear-gradient(90deg,rgba(247,207,101,.08),var(--ff-color-surface) 40%); }
            .ff-status--error { border-color:rgba(255,139,153,.55); background:linear-gradient(90deg,rgba(255,139,153,.08),var(--ff-color-surface) 40%); }
            .ff-status--success { border-color:rgba(67,214,161,.45); background:linear-gradient(90deg,rgba(67,214,161,.08),var(--ff-color-surface) 40%); }
            .ff-status--restricted, .ff-status--info, .ff-status--degraded { border-color:rgba(124,226,255,.42); background:linear-gradient(90deg,rgba(124,226,255,.08),var(--ff-color-surface) 40%); }
            .ff-state { max-width:760px; padding:1.2rem; border-radius:var(--ff-radius-lg); border:1px solid var(--ff-color-border);
                background:linear-gradient(180deg,var(--ff-color-surface-secondary),var(--ff-color-surface)); }
            .ff-state h2 { margin:0 0 .35rem; font-size:1.2rem; }
            .ff-state p { color:var(--ff-color-text-muted); margin:0; line-height:1.55; }
            [data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap:.48rem; }
            [data-testid="stSidebar"] .stButton button { justify-content:flex-start; min-height:2.55rem; border-radius:.72rem;
                padding:.55rem .75rem !important; font-size:var(--ff-font-size-control); font-weight:750 !important;
                line-height:1.3; text-align:left !important; white-space:normal; }
            [data-testid="stSidebar"] .stButton button p { color:inherit !important; font-size:inherit; line-height:inherit; }
            [data-testid="stSidebar"] .stButton button[kind="secondary"] {
                background:rgba(255,255,255,.025) !important; color:var(--ff-color-text) !important;
                border-color:var(--ff-color-border) !important;
            }
            [data-testid="stSidebar"] .stButton button[kind="secondary"]:hover {
                background:var(--ff-color-hover) !important; color:var(--ff-color-interactive-hover) !important;
                border-color:rgba(142,232,255,.4) !important;
            }
            [data-testid="stSidebar"] .stButton button[kind="primary"] {
                background:var(--ff-color-selected) !important; color:var(--ff-color-text) !important;
                border-color:rgba(142,232,255,.5) !important;
                box-shadow:inset 3px 0 0 var(--ff-color-interactive) !important;
            }
            [data-testid="stSidebar"] .ff-nav-section { color:var(--ff-color-text-subtle) !important; font-size:.7rem; font-weight:900;
                letter-spacing:.1em; text-transform:uppercase; margin:1rem 0 .25rem; }
            [data-testid="stSidebar"] details { border-radius:.8rem; }
            [data-testid="stHeader"], .stAppHeader {
                background:var(--ff-color-bg) !important; border-bottom:1px solid var(--ff-color-border);
            }
            [data-testid="stHeader"] button, .stAppHeader button { color:var(--ff-color-text) !important; }
            .panel:empty { display:none !important; }
            @media (max-width: 1100px) {
                .block-container { padding: .8rem .9rem 1.8rem; }
                .ff-page-head { padding-top:0; }
                .top-band { grid-template-columns:repeat(2,minmax(0,1fr)) !important; }
                div[data-testid="stHorizontalBlock"] { flex-wrap:wrap; }
                div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {
                    min-width:min(100%,19rem) !important;
                    flex:1 1 19rem !important;
                }
            }
            @media (max-width: 520px) {
                .block-container { padding-left:.7rem; padding-right:.7rem; }
                .ff-page-title { font-size:1.65rem; }
                .top-band { grid-template-columns:1fr !important; }
                .stat-card { min-height:auto !important; }
                [data-testid="stDataFrame"] { max-width:calc(100vw - 1.4rem); overflow:auto; }
                .ff-status { padding:.72rem; }
                .stButton button, .stDownloadButton button, .stFormSubmitButton button { min-height:2.65rem; }
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_brand() -> None:
    st.markdown(
        """
        <div class="ff-brand">
          <div class="ff-brand-mark" aria-hidden="true">F</div>
          <div><div class="ff-brand-name">FuruFlow</div><div class="ff-brand-copy">DeFi yield intelligence</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_navigation(
    *, current_route: str, signed_in: bool, capabilities: ProductCapabilities, is_admin: bool
) -> str:
    selected = current_route
    previous_section = ""
    for item in visible_navigation(signed_in=signed_in, capabilities=capabilities, is_admin=is_admin):
        if item.section != previous_section:
            st.markdown(f'<div class="ff-nav-section">{item.section}</div>', unsafe_allow_html=True)
            previous_section = item.section
        if st.button(
            item.label,
            key=f"nav_{item.route}",
            type="primary" if current_route == item.route else "secondary",
            width="stretch",
        ):
            selected = item.route
    return selected


def render_page_heading(
    route: str,
    *,
    view: str | None = None,
    detail_label: str | None = None,
    parent_route: str | None = None,
) -> None:
    title, copy = PAGE_CONTEXT.get(route, PAGE_CONTEXT["Home"])
    if route == "Pool Detail" and detail_label:
        title = detail_label
    parent = parent_route or ("Discover" if route == "Pool Detail" else route)
    breadcrumb = f"FuruFlow / {parent}"
    if view:
        breadcrumb += f" / {view}"
    safe_breadcrumb = escape(breadcrumb)
    safe_title = escape(title)
    safe_copy = escape(copy)
    st.markdown(
        f"""
        <header class="ff-page-head">
          <div class="ff-breadcrumb">{safe_breadcrumb}</div>
          <h1 class="ff-page-title">{safe_title}</h1>
          <div class="ff-page-copy">{safe_copy}</div>
        </header>
        """,
        unsafe_allow_html=True,
    )


def render_status(kind: str, title: str, message: str) -> None:
    icons = {
        "loading": "↻",
        "refreshing": "↻",
        "empty": "○",
        "error": "!",
        "warning": "!",
        "stale": "◷",
        "degraded": "△",
        "auth": "◇",
        "pro": "◆",
        "unauthorized": "⊘",
        "success": "✓",
        "info": "i",
        "restricted": "◇",
    }
    css_kind = "restricted" if kind in {"auth", "pro", "unauthorized"} else kind
    safe_title = escape(title)
    safe_message = escape(message)
    st.markdown(
        f"""
        <div class="ff-status ff-status--{css_kind}" role="status">
          <div class="ff-status-icon" aria-hidden="true">{icons.get(kind, 'i')}</div>
          <div><div class="ff-status-title">{safe_title}</div><div class="ff-status-copy">{safe_message}</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_state(title: str, message: str) -> None:
    st.markdown(
        f'<section class="ff-state"><h2>{escape(title)}</h2><p>{escape(message)}</p></section>',
        unsafe_allow_html=True,
    )


def market_filters_apply(route: str) -> bool:
    return route in {"Home", "Discover", "Pool Detail"}
