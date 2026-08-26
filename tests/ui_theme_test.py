from __future__ import annotations

from pathlib import Path

from ui_theme import UI_THEME_CSS
from ui_shell import (
    OPPORTUNITIES_TABLE_COLUMNS,
    SIGNAL_ENGINE_TABLE_COLUMNS,
    STRATEGY_RESULTS_TABLE_COLUMNS,
    market_filters_apply,
)


ROOT = Path(__file__).parents[1]


def test_theme_defines_semantic_color_typography_spacing_and_radius_roles() -> None:
    required_tokens = {
        "--ff-color-bg",
        "--ff-color-surface",
        "--ff-color-surface-elevated",
        "--ff-color-border",
        "--ff-color-text",
        "--ff-color-text-muted",
        "--ff-color-interactive",
        "--ff-color-hover",
        "--ff-color-selected",
        "--ff-color-focus",
        "--ff-color-success",
        "--ff-color-warning",
        "--ff-color-danger",
        "--ff-color-info",
        "--ff-font-size-body",
        "--ff-space-4",
        "--ff-radius-md",
    }

    assert required_tokens <= {line.split(":", 1)[0].strip() for line in UI_THEME_CSS.splitlines() if ":" in line}


def test_theme_keeps_filter_expanders_readable_without_hover_and_focus_visible() -> None:
    assert 'details > summary {' in UI_THEME_CSS
    assert "background: var(--ff-color-surface-control) !important" in UI_THEME_CSS
    assert "color: var(--ff-color-text) !important" in UI_THEME_CSS
    assert "summary:focus-visible" in UI_THEME_CSS
    assert "outline: 3px solid var(--ff-color-focus) !important" in UI_THEME_CSS


def test_account_auth_controls_are_scoped_and_readable_in_every_button_state() -> None:
    account_theme = UI_THEME_CSS[UI_THEME_CSS.index(".st-key-account_auth_controls") :]

    assert 'button[data-testid^="stBaseButton-"]' in account_theme
    assert "background: var(--ff-color-surface-control) !important" in account_theme
    assert "color: var(--ff-color-text) !important" in account_theme
    for state in (":hover", ":active", ":disabled"):
        assert state in account_theme
    assert "button:focus-visible" in UI_THEME_CSS


def test_react_aria_selectbox_is_readable_closed_open_focused_and_selected() -> None:
    assert '[data-testid="stSelectbox"] [role="group"]' in UI_THEME_CSS
    assert '[data-testid="stSelectbox"] [role="combobox"]' in UI_THEME_CSS
    assert '[data-testid="stSelectbox"] [role="group"]:focus-within' in UI_THEME_CSS
    assert '[role="listbox"]' in UI_THEME_CSS
    assert '[role="option"][aria-selected="true"]' in UI_THEME_CSS
    assert "background: var(--ff-color-surface-control) !important" in UI_THEME_CSS
    assert "color: var(--ff-color-text) !important" in UI_THEME_CSS


def test_react_aria_selectbox_listbox_respects_the_portal_viewport_boundary() -> None:
    dropdown_start = UI_THEME_CSS.index('[data-testid="stSelectboxVirtualDropdown"] [role="listbox"]')
    dropdown_css = UI_THEME_CSS[dropdown_start:]

    assert "max-height: inherit !important" in dropdown_css
    assert "overflow-y: auto !important" in dropdown_css
    assert "overscroll-behavior: contain" in dropdown_css
    sort_portal = '[data-testid="stSelectboxVirtualDropdown"]:has([role="listbox"][aria-label="Sort by"])'
    assert sort_portal in dropdown_css
    assert dropdown_css.index(sort_portal) < dropdown_css.index("@media (max-width: 1100px)")
    assert "@media (max-width: 1100px)" in dropdown_css
    assert "inset: auto auto .75rem .75rem !important" in dropdown_css
    assert "transform: none !important" in dropdown_css
    assert "max-height: min(300px, calc(100dvh - 1.5rem)) !important" in dropdown_css


def test_theme_keeps_portalled_tooltips_readable_on_dark_surfaces() -> None:
    assert '[data-testid="stTooltipContent"]' in UI_THEME_CSS
    assert "background: var(--ff-color-surface-elevated) !important" in UI_THEME_CSS
    assert '[data-testid="stTooltipContent"] *' in UI_THEME_CSS
    assert "color: inherit !important" in UI_THEME_CSS


def test_page_uses_shared_card_styles_and_explicit_action_hierarchy() -> None:
    app_source = (ROOT / "app.py").read_text(encoding="utf-8")

    assert 'st.expander("Discover Filters"' in app_source
    assert 'st.expander("Advanced filters & sorting"' in app_source
    assert 'type="tertiary"' in app_source
    assert 'class="ff-billing-action"' in app_source
    assert '[data-testid="stTextInputRootElement"]' in app_source
    assert "<style>\n        .ff-card-wrap" not in app_source
    assert "background:#f7faff" not in app_source
    assert "background:#eef4ff" not in app_source


def test_shell_distinguishes_default_active_hover_and_disabled_controls() -> None:
    shell_source = (ROOT / "ui_shell.py").read_text(encoding="utf-8")

    assert 'button[kind="secondary"]' in shell_source
    assert 'button[kind="secondary"]:hover' in shell_source
    assert 'button[kind="primary"]' in shell_source
    assert "box-shadow:inset 3px 0 0 var(--ff-color-interactive)" in shell_source
    assert ".stButton button:disabled" in UI_THEME_CSS


def test_alert_state_is_textual_and_does_not_render_a_raw_chat_identifier() -> None:
    app_source = (ROOT / "app.py").read_text(encoding="utf-8")
    rendered_alerts = app_source[app_source.index("def render_alerts_page") : app_source.index("inject_theme_css()")]

    assert 'state_label = "Active" if alert.enabled else "Paused"' in rendered_alerts
    assert "ff-state-pill--paused" in rendered_alerts
    assert "chat_id" not in rendered_alerts.lower()


def test_signal_and_strategy_tables_put_pool_navigation_first() -> None:
    assert OPPORTUNITIES_TABLE_COLUMNS[0] == ("pool", "Pool")
    assert SIGNAL_ENGINE_TABLE_COLUMNS[0] == ("pool", "Pool")
    assert STRATEGY_RESULTS_TABLE_COLUMNS[0] == ("pool", "Pool")


def test_session_recovery_controls_have_scoped_readable_states() -> None:
    recovery_css = UI_THEME_CSS[UI_THEME_CSS.index(".st-key-session_recovery_actions") :]

    assert 'button[data-testid="stBaseButton-primary"]' in recovery_css
    assert "color: #07111f !important" in recovery_css
    assert "background: linear-gradient(180deg, #9beeff, #6eddff) !important" in recovery_css
    for state in (":hover", ":focus-visible", ":active", ":disabled"):
        assert state in recovery_css
    assert "session_recovery_actions" in (ROOT / "app.py").read_text(encoding="utf-8")


def test_discover_controls_are_not_duplicated_on_pro_tools() -> None:
    assert market_filters_apply("Discover")
    assert market_filters_apply("Pool Detail")
    assert not market_filters_apply("Pro Tools")


def test_pool_detail_open_pool_has_scoped_readable_interaction_states() -> None:
    action_css = UI_THEME_CSS[UI_THEME_CSS.index(".st-key-pool_detail_open_pool") :]

    assert ".stLinkButton a:visited" in action_css
    assert ".stLinkButton a p" in action_css
    assert "color: #332100 !important" in action_css
    for state in (":hover", ":focus-visible", ":active", '[aria-disabled="true"]'):
        assert state in action_css


def test_strategy_results_expose_complete_workflow_and_activity_leaves_primary_navigation() -> None:
    app_source = (ROOT / "app.py").read_text(encoding="utf-8")
    strategy_source = app_source[app_source.index('elif content_page == "Strategy Builder"') : app_source.index('elif content_page == "Activity & Digests"')]
    shell_source = (ROOT / "ui_shell.py").read_text(encoding="utf-8")
    primary_navigation = shell_source[shell_source.index("AUTHENTICATED_NAV") : shell_source.index("ADMIN_NAV")]

    assert '"Save to Watchlist"' in strategy_source
    assert '"Open Pool"' in strategy_source
    assert '"Compare / Research"' in strategy_source
    assert '"Create Alert"' in strategy_source
    assert 'return_route="Pro Tools"' in strategy_source
    assert "Activity & Digests" not in primary_navigation
    assert "post_real_signals.py" not in app_source
    assert "No signal history yet." in app_source
