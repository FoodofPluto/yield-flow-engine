from __future__ import annotations

from pathlib import Path

from ui_theme import UI_THEME_CSS


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
