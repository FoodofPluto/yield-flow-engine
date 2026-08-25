from __future__ import annotations

import streamlit as st


# Prompt 10 presentation contract. Keep semantic roles here so shell and page
# components share one palette, spacing scale, typography, and interaction model.
UI_THEME_CSS = """
<style>
    :root {
        color-scheme: dark;
        --ff-color-bg: #06101d;
        --ff-color-bg-secondary: #0a1527;
        --ff-color-surface: #0d1b2f;
        --ff-color-surface-secondary: #102139;
        --ff-color-surface-elevated: #142944;
        --ff-color-surface-control: #111f33;
        --ff-color-border: rgba(223, 234, 255, .14);
        --ff-color-border-strong: rgba(223, 234, 255, .25);
        --ff-color-text: #f4f7ff;
        --ff-color-text-muted: #b6c3d8;
        --ff-color-text-subtle: #94a8c7;
        --ff-color-interactive: #8ee8ff;
        --ff-color-interactive-hover: #b9f2ff;
        --ff-color-hover: rgba(142, 232, 255, .09);
        --ff-color-selected: rgba(142, 232, 255, .17);
        --ff-color-focus: #ffd76a;
        --ff-color-success: #43d6a1;
        --ff-color-warning: #f7cf65;
        --ff-color-danger: #ff8b99;
        --ff-color-info: #7ce2ff;

        --ff-font-body: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        --ff-font-size-meta: .75rem;
        --ff-font-size-supporting: .84rem;
        --ff-font-size-body: .94rem;
        --ff-font-size-control: .9rem;
        --ff-line-height-tight: 1.2;
        --ff-line-height-body: 1.55;

        --ff-space-1: .25rem;
        --ff-space-2: .5rem;
        --ff-space-3: .75rem;
        --ff-space-4: 1rem;
        --ff-space-5: 1.25rem;
        --ff-space-6: 1.5rem;
        --ff-space-8: 2rem;

        --ff-radius-sm: .65rem;
        --ff-radius-md: 1rem;
        --ff-radius-lg: 1.35rem;
        --ff-shadow-card: 0 14px 34px rgba(0, 0, 0, .18);

        /* Compatibility aliases for established page components. */
        --bg: var(--ff-color-bg);
        --bg-2: var(--ff-color-bg-secondary);
        --panel: rgba(13, 27, 47, .96);
        --panel-2: rgba(16, 33, 57, .98);
        --border: var(--ff-color-border);
        --text: var(--ff-color-text);
        --muted: var(--ff-color-text-muted);
        --accent: var(--ff-color-interactive);
        --accent-2: #66d5ff;
        --good: var(--ff-color-success);
        --warn: var(--ff-color-warning);
        --bad: var(--ff-color-danger);
    }

    html, body, button, input, textarea, select, [class*="css"] {
        font-family: var(--ff-font-body);
    }

    button:focus-visible,
    a:focus-visible,
    input:focus-visible,
    textarea:focus-visible,
    select:focus-visible,
    summary:focus-visible,
    [role="button"]:focus-visible,
    [role="tab"]:focus-visible,
    [role="radio"]:focus-visible,
    [role="slider"]:focus-visible,
    [role="switch"]:focus-visible {
        outline: 3px solid var(--ff-color-focus) !important;
        outline-offset: 3px !important;
        box-shadow: none !important;
    }

    [data-testid="stSidebar"] [data-testid="stExpander"] details > summary {
        min-height: 2.75rem;
        padding: .55rem .72rem !important;
        border: 1px solid var(--ff-color-border);
        border-radius: var(--ff-radius-sm);
        background: var(--ff-color-surface-control) !important;
        color: var(--ff-color-text) !important;
        font-size: var(--ff-font-size-control);
        font-weight: 800;
        line-height: var(--ff-line-height-tight);
    }
    [data-testid="stSidebar"] [data-testid="stExpander"] details > summary * {
        background: transparent !important;
        color: inherit !important;
        fill: currentColor !important;
    }
    [data-testid="stSidebar"] [data-testid="stExpander"] details > summary:hover {
        background: var(--ff-color-hover) !important;
        border-color: var(--ff-color-border-strong);
    }
    [data-testid="stSidebar"] [data-testid="stExpander"] details[open] > summary {
        background: var(--ff-color-selected) !important;
        border-color: rgba(142, 232, 255, .4);
    }

    .stButton button[kind="secondary"],
    .stDownloadButton button[kind="secondary"],
    .stFormSubmitButton button[kind="secondary"] {
        background: var(--ff-color-surface-control) !important;
        border: 1px solid var(--ff-color-border) !important;
        color: var(--ff-color-text) !important;
    }
    .stButton button[kind="secondary"]:hover,
    .stDownloadButton button[kind="secondary"]:hover,
    .stFormSubmitButton button[kind="secondary"]:hover {
        background: var(--ff-color-hover) !important;
        border-color: rgba(142, 232, 255, .45) !important;
        color: var(--ff-color-interactive-hover) !important;
    }
    .stButton button[kind="tertiary"] {
        min-height: 2.15rem;
        padding: .36rem .7rem !important;
        border: 1px solid rgba(142, 232, 255, .3) !important;
        border-radius: 999px !important;
        background: rgba(142, 232, 255, .1) !important;
        color: var(--ff-color-interactive-hover) !important;
        font-size: var(--ff-font-size-supporting);
    }
    .stButton button[kind="tertiary"]:hover {
        background: var(--ff-color-selected) !important;
        border-color: rgba(142, 232, 255, .5) !important;
    }
    .stButton button:disabled,
    .stDownloadButton button:disabled,
    .stFormSubmitButton button:disabled {
        opacity: .62 !important;
        border-style: dashed !important;
        cursor: not-allowed !important;
    }

    /* Streamlit 1.60 renders selectboxes with React Aria rather than BaseWeb. */
    [data-testid="stSelectbox"] [role="group"] {
        background: var(--ff-color-surface-control) !important;
        border-color: var(--ff-color-border-strong) !important;
        color: var(--ff-color-text) !important;
    }
    [data-testid="stSelectbox"] [role="combobox"],
    [data-testid="stSelectbox"] [role="group"] button,
    [data-testid="stSelectbox"] [role="group"] svg {
        background: transparent !important;
        color: var(--ff-color-text) !important;
        fill: currentColor !important;
    }
    [data-testid="stSelectbox"] [role="group"]:hover {
        background: var(--ff-color-hover) !important;
        border-color: rgba(142, 232, 255, .45) !important;
    }
    [data-testid="stSelectbox"] [role="group"]:focus-within {
        border-color: var(--ff-color-focus) !important;
        box-shadow: 0 0 0 2px rgba(255, 215, 106, .28) !important;
    }
    [role="listbox"] {
        background: var(--ff-color-surface-elevated) !important;
        color: var(--ff-color-text) !important;
    }
    /* React Aria portals the menu to body and publishes its viewport-safe
       height on this overlay. Keep the virtualized listbox inside that bound
       so longer Pro sort menus scroll instead of being clipped by the overlay. */
    [data-testid="stSelectboxVirtualDropdown"] [role="listbox"] {
        max-height: inherit !important;
        overflow-y: auto !important;
        overscroll-behavior: contain;
    }
    /* Sort lives low in the sidebar even at desktop widths. Keep its portal
       inside the viewport so every option is pointer- and keyboard-reachable. */
    [data-testid="stSelectboxVirtualDropdown"]:has([role="listbox"][aria-label="Sort by"]) {
        inset: auto auto .75rem .75rem !important;
        transform: none !important;
        width: min(var(--trigger-width), calc(100vw - 1.5rem)) !important;
        max-width: calc(100vw - 1.5rem) !important;
        max-height: min(300px, calc(100dvh - 1.5rem)) !important;
    }
    @media (max-width: 1100px) {
        /* Streamlit 1.60 can mark a sidebar menu for top placement while its
           generated transform still sends it below the mobile viewport. This
           fallback is deliberately limited to the Discover Sort by menu. */
        [data-testid="stSelectboxVirtualDropdown"]:has([role="listbox"][aria-label="Sort by"]) {
            inset: auto auto .75rem .75rem !important;
            transform: none !important;
            width: min(var(--trigger-width), calc(100vw - 1.5rem)) !important;
            max-width: calc(100vw - 1.5rem) !important;
            max-height: min(300px, calc(100dvh - 1.5rem)) !important;
        }
    }
    [role="option"] {
        background: var(--ff-color-surface-elevated) !important;
        color: var(--ff-color-text) !important;
    }
    [role="option"]:hover,
    [role="option"][data-focused="true"] {
        background: var(--ff-color-hover) !important;
        color: var(--ff-color-interactive-hover) !important;
    }
    [role="option"][aria-selected="true"] {
        background: var(--ff-color-selected) !important;
        color: var(--ff-color-text) !important;
    }

    /* Streamlit renders help text in a body-level light tooltip by default.
       Keep that portal aligned with the dark shell so inherited paragraph
       text remains readable on hover and keyboard focus. */
    [data-testid="stTooltipContent"] {
        background: var(--ff-color-surface-elevated) !important;
        border: 1px solid var(--ff-color-border-strong) !important;
        color: var(--ff-color-text) !important;
        box-shadow: var(--ff-shadow-card) !important;
    }
    [data-testid="stTooltipContent"] * {
        color: inherit !important;
    }

    /* The account container scopes authentication submit-button states. */
    .st-key-account_auth_controls button[data-testid^="stBaseButton-"],
    .st-key-account_auth_controls [data-testid="stFormSubmitButton"] button {
        background: var(--ff-color-surface-control) !important;
        border: 1px solid var(--ff-color-border-strong) !important;
        color: var(--ff-color-text) !important;
    }
    .st-key-account_auth_controls button[data-testid^="stBaseButton-"] *,
    .st-key-account_auth_controls [data-testid="stFormSubmitButton"] button * {
        background: transparent !important;
        color: inherit !important;
    }
    .st-key-account_auth_controls button[data-testid^="stBaseButton-"]:hover,
    .st-key-account_auth_controls [data-testid="stFormSubmitButton"] button:hover {
        background: var(--ff-color-hover) !important;
        border-color: rgba(142, 232, 255, .45) !important;
        color: var(--ff-color-interactive-hover) !important;
    }
    .st-key-account_auth_controls button[data-testid^="stBaseButton-"]:active,
    .st-key-account_auth_controls [data-testid="stFormSubmitButton"] button:active {
        background: var(--ff-color-selected) !important;
        color: var(--ff-color-text) !important;
    }
    .st-key-account_auth_controls button[data-testid^="stBaseButton-"]:disabled,
    .st-key-account_auth_controls [data-testid="stFormSubmitButton"] button:disabled {
        background: var(--ff-color-surface-secondary) !important;
        border-style: dashed !important;
        color: var(--ff-color-text-muted) !important;
        opacity: .68 !important;
    }

    .ff-card-wrap {
        min-width: 0;
        padding: var(--ff-space-4);
        border: 1px solid var(--ff-color-border);
        border-radius: var(--ff-radius-lg);
        background: linear-gradient(180deg, rgba(18, 38, 64, .98), rgba(10, 21, 39, .98));
        box-shadow: var(--ff-shadow-card);
        color: var(--ff-color-text);
    }
    .ff-opp-top { display: flex; justify-content: space-between; gap: var(--ff-space-3); align-items: flex-start; }
    .ff-opp-name { color: var(--ff-color-text); font-size: 1.02rem; font-weight: 800; line-height: 1.2; overflow-wrap: anywhere; }
    .ff-opp-sub { color: var(--ff-color-text-muted); font-size: var(--ff-font-size-supporting); margin-top: var(--ff-space-1); }
    .ff-protocol-dot { min-width: 2.2rem; height: 2.2rem; display: grid; place-items: center; border-radius: 999px;
        background: linear-gradient(135deg, var(--ff-color-interactive), #66d5ff); color: #072030; font-weight: 900; }
    .ff-watch-pill, .ff-state-pill { display: inline-flex; align-items: center; gap: .3rem; margin-top: var(--ff-space-2);
        padding: .28rem .58rem; border: 1px solid rgba(67, 214, 161, .35); border-radius: 999px;
        background: rgba(67, 214, 161, .12); color: #baffdf; font-size: var(--ff-font-size-meta); font-weight: 800; }
    .ff-state-pill--paused { border-color: rgba(247, 207, 101, .4); background: rgba(247, 207, 101, .12); color: #ffe59b; }
    .ff-badge-row { display: flex; flex-wrap: wrap; gap: .42rem; margin: var(--ff-space-3) 0; align-items: flex-start; }
    .ff-badge { display: inline-flex; max-width: 100%; padding: .28rem .58rem; border: 1px solid var(--ff-color-border);
        border-radius: 999px; background: rgba(255, 255, 255, .045); color: var(--ff-color-text-muted);
        font-size: var(--ff-font-size-meta); font-weight: 750; line-height: 1.25; overflow-wrap: anywhere; }
    .ff-metric-strip { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--ff-space-2); margin-top: var(--ff-space-2); }
    .ff-metric-box { min-width: 0; padding: .68rem .45rem; border: 1px solid var(--ff-color-border);
        border-radius: var(--ff-radius-sm); background: rgba(6, 16, 29, .58); text-align: center; }
    .ff-metric-mini-label { color: var(--ff-color-text-subtle); font-size: .68rem; font-weight: 800; letter-spacing: .06em; text-transform: uppercase; }
    .ff-metric-mini-value { color: var(--ff-color-text); font-size: .96rem; font-weight: 850; margin-top: .15rem; overflow-wrap: anywhere; }

    .ff-billing-action button {
        width: 100%; min-height: 2.7rem; cursor: pointer; padding: .6rem .9rem;
        border: 1px solid rgba(142, 232, 255, .65); border-radius: var(--ff-radius-sm);
        background: linear-gradient(180deg, #9beeff, #6eddff); color: #07111f;
        font: 900 var(--ff-font-size-control)/1.2 var(--ff-font-body);
    }

    @media (max-width: 760px) {
        .ff-metric-strip { grid-template-columns: 1fr; }
        .ff-card-wrap { padding: var(--ff-space-3); }
        .ff-badge { white-space: normal; }
    }

    @media (prefers-reduced-motion: reduce) {
        *, *::before, *::after { scroll-behavior: auto !important; transition: none !important; animation: none !important; }
    }
</style>
"""


def inject_theme_css() -> None:
    st.markdown(UI_THEME_CSS, unsafe_allow_html=True)
