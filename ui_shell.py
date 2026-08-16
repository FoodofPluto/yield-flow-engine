from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Any, Mapping, MutableMapping

import streamlit as st


@dataclass(frozen=True)
class NavItem:
    route: str
    label: str
    section: str
    requires_auth: bool = False
    pro_context: bool = False
    admin_only: bool = False


PUBLIC_NAV = (
    NavItem("Home", "Home", "Explore"),
    NavItem("Discover", "Discover", "Explore"),
    NavItem("Research", "Research", "Explore"),
    NavItem("Pricing", "Pricing", "Explore"),
    NavItem("Methodology & Data Status", "Methodology & data", "Explore"),
)

AUTHENTICATED_NAV = (
    NavItem("Watchlists", "Watchlists", "Your workspace", requires_auth=True),
    NavItem("Alerts", "Alerts", "Your workspace", requires_auth=True),
    NavItem("Activity & Digests", "Activity & digests", "Your workspace", requires_auth=True),
    NavItem("Pro Tools", "Pro tools", "Your workspace", requires_auth=True, pro_context=True),
    NavItem("Account & Billing", "Account & billing", "Your workspace", requires_auth=True),
)

ADMIN_NAV = NavItem("Admin", "Admin", "Restricted", requires_auth=True, admin_only=True)

ALL_ROUTES = frozenset(item.route for item in (*PUBLIC_NAV, *AUTHENTICATED_NAV, ADMIN_NAV)) | {"Pool Detail"}

LEGACY_ROUTE_ALIASES = {
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

PAGE_CONTEXT = {
    "Home": ("Market briefing", "A concise view of yield conditions, tracked opportunities, and recent activity."),
    "Discover": ("Discover", "Explore opportunities, compare visible pools, and inspect Pro signals in one workflow."),
    "Research": ("Research", "Understand market structure through chain, protocol, risk, and capital-depth views."),
    "Pricing": ("Pricing", "Understand what is available in Free and Pro before choosing an account plan."),
    "Methodology & Data Status": (
        "Methodology & data status",
        "See how FuruFlow frames yield, risk, freshness, and degraded source conditions.",
    ),
    "Watchlists": ("Watchlists", "Return to opportunities you have chosen to track."),
    "Alerts": ("Alerts", "Create and manage persistent pool alerts delivered through verified Telegram routing."),
    "Activity & Digests": ("Activity & digests", "Review observed market activity and available recap history."),
    "Pro Tools": ("Pro tools", "Compose strategy slices and inspect cross-chain yield spreads."),
    "Account & Billing": ("Account & billing", "Review the server-authoritative account and entitlement state."),
    "Admin": ("Admin", "Restricted account administration guidance for verified administrators."),
    "Pool Detail": ("Pool detail", "Inspect the selected opportunity without losing the results context."),
}

DISCOVER_VIEWS = ("Opportunities", "Signals", "Compare")
RESEARCH_VIEWS = ("Market Map", "Protocols")
PRO_TOOL_VIEWS = ("Strategy Builder", "Yield Spreads")


def visible_navigation(*, signed_in: bool, is_pro: bool, is_admin: bool) -> tuple[NavItem, ...]:
    items = list(PUBLIC_NAV)
    if signed_in:
        for item in AUTHENTICATED_NAV:
            if item.pro_context and not is_pro:
                items.append(NavItem(item.route, f"{item.label} · Pro", item.section, True, True, False))
            else:
                items.append(item)
    if signed_in and is_admin:
        items.append(ADMIN_NAV)
    return tuple(items)


def canonical_route(route: str | None) -> tuple[str, str | None]:
    requested = (route or "Home").strip()
    if requested in LEGACY_ROUTE_ALIASES:
        return LEGACY_ROUTE_ALIASES[requested]
    if requested in ALL_ROUTES:
        return requested, None
    return "Home", None


def route_access(route: str, *, signed_in: bool, is_admin: bool) -> tuple[bool, str | None]:
    if route == "Admin" and not is_admin:
        return False, "unauthorized"
    if route in {item.route for item in AUTHENTICATED_NAV} and not signed_in:
        return False, "authentication_required"
    if route == "Pool Detail":
        return True, None
    return route in ALL_ROUTES, None if route in ALL_ROUTES else "not_found"


def account_control_model(user: Mapping[str, Any] | None, *, is_pro: bool, is_admin: bool) -> dict[str, str]:
    if not user:
        return {
            "label": "Sign in",
            "email": "Public browsing",
            "plan": "Free",
            "status": "signed_out",
        }
    email = str(user.get("email") or "Signed-in account")
    plan = "Admin" if is_admin else "Pro" if is_pro else "Free"
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
            :root {
                --ff-space-1: .25rem;
                --ff-space-2: .5rem;
                --ff-space-3: .75rem;
                --ff-space-4: 1rem;
                --ff-space-6: 1.5rem;
                --ff-radius-sm: .65rem;
                --ff-radius-md: 1rem;
                --ff-radius-lg: 1.4rem;
                --ff-focus: #f7cf65;
                --ff-info: #7ce2ff;
                --ff-success: #43d6a1;
                --ff-warning: #f7cf65;
                --ff-danger: #ff8b99;
            }
            .block-container { max-width: 1440px; padding-top: 1.1rem; }
            .ff-brand { display:flex; align-items:center; gap:.7rem; padding:.3rem 0 1rem; }
            .ff-brand-mark { width:2rem; height:2rem; display:grid; place-items:center; border-radius:.7rem;
                background:linear-gradient(135deg,#7ce2ff,#6b86ff); color:#07131f !important; font-weight:950; }
            .ff-brand-name { color:#fff; font-size:1.05rem; font-weight:900; letter-spacing:-.02em; }
            .ff-brand-copy { color:#aab8d4; font-size:.72rem; }
            .ff-page-head { padding:.2rem 0 .85rem; border-bottom:1px solid rgba(255,255,255,.08); margin-bottom:1rem; }
            .ff-breadcrumb { color:#8fa2c1; font-size:.76rem; font-weight:700; letter-spacing:.04em; text-transform:uppercase; }
            .ff-page-title { color:#f6f9ff; font-size:clamp(1.7rem,3vw,2.45rem); font-weight:900; letter-spacing:-.035em;
                line-height:1.08; margin:.3rem 0; }
            .ff-page-copy { color:#aab8d4; font-size:.95rem; line-height:1.55; max-width:72ch; }
            .ff-status { display:grid; grid-template-columns:auto 1fr; gap:.7rem; align-items:start; padding:.8rem .9rem;
                margin:.55rem 0 1rem; border:1px solid rgba(255,255,255,.11); border-radius:var(--ff-radius-md); background:rgba(12,26,45,.92); }
            .ff-status-icon { font-size:.95rem; line-height:1.3; }
            .ff-status-title { color:#f6f9ff; font-weight:850; font-size:.88rem; }
            .ff-status-copy { color:#b7c4da; font-size:.82rem; line-height:1.45; margin-top:.12rem; }
            .ff-status--warning { border-color:rgba(247,207,101,.42); }
            .ff-status--error { border-color:rgba(255,139,153,.48); }
            .ff-status--success { border-color:rgba(67,214,161,.36); }
            .ff-status--restricted { border-color:rgba(124,226,255,.38); }
            .ff-state { max-width:760px; padding:1.2rem; border-radius:var(--ff-radius-lg); border:1px solid rgba(255,255,255,.1);
                background:linear-gradient(180deg,rgba(18,36,61,.92),rgba(10,20,36,.96)); }
            .ff-state h2 { margin:0 0 .35rem; font-size:1.2rem; }
            .ff-state p { color:#aab8d4; margin:0; line-height:1.55; }
            button:focus-visible, a:focus-visible, input:focus-visible, [role="button"]:focus-visible {
                outline:3px solid var(--ff-focus) !important; outline-offset:3px !important;
            }
            [data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap:.48rem; }
            [data-testid="stSidebar"] .stButton button { justify-content:flex-start; min-height:2.45rem; border-radius:.72rem; }
            [data-testid="stSidebar"] .stButton button[kind="secondary"] {
                background:rgba(255,255,255,.025) !important;
                color:#dce7f8 !important;
                border-color:transparent !important;
            }
            [data-testid="stSidebar"] .stButton button[kind="primary"] {
                background:linear-gradient(180deg,#9beeff,#6eddff) !important;
                color:#07131f !important;
                border-color:rgba(124,226,255,.65) !important;
            }
            [data-testid="stSidebar"] .ff-nav-section { color:#8296b8 !important; font-size:.69rem; font-weight:900;
                letter-spacing:.1em; text-transform:uppercase; margin:1rem 0 .25rem; }
            [data-testid="stSidebar"] details { border-radius:.8rem; }
            [data-testid="stSidebar"] summary:focus-visible { outline:3px solid var(--ff-focus); outline-offset:2px; }
            [data-testid="stHeader"], .stAppHeader {
                background:#071321 !important;
                border-bottom:1px solid rgba(255,255,255,.07);
            }
            [data-testid="stHeader"] button, .stAppHeader button { color:#eef4ff !important; }
            .panel:empty { display:none !important; }
            @media (max-width: 1200px) {
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
            }
            @media (prefers-reduced-motion: reduce) {
                *, *::before, *::after { scroll-behavior:auto !important; transition:none !important; animation:none !important; }
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


def render_navigation(*, current_route: str, signed_in: bool, is_pro: bool, is_admin: bool) -> str:
    selected = current_route
    previous_section = ""
    for item in visible_navigation(signed_in=signed_in, is_pro=is_pro, is_admin=is_admin):
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


def render_page_heading(route: str, *, view: str | None = None, detail_label: str | None = None) -> None:
    title, copy = PAGE_CONTEXT.get(route, PAGE_CONTEXT["Home"])
    if route == "Pool Detail" and detail_label:
        title = detail_label
    parent = "Discover" if route == "Pool Detail" else route
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
    return route in {"Home", "Discover", "Research", "Pool Detail", "Watchlists", "Pro Tools"}
