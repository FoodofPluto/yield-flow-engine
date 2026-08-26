from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_methodology_page_starts_with_derived_live_status_and_coverage() -> None:
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    page = source[source.index('elif content_page == "Methodology & Data Status"') : source.index('elif content_page == "Alerts"')]

    assert "market_status_summary(df)" in page
    assert 'metric("Current availability"' in page
    assert 'metric("Freshness"' in page
    assert 'metric("Pools represented"' in page
    assert 'metric("Networks represented"' in page
    assert 'metric("Protocols represented"' in page
    assert 'metric("Assets represented"' in page
    assert '"Latest retrieval"' in page
    assert "metric.available" in page and "metric.total" in page
    assert "missing values are not counted as zero" in page


def test_data_status_uses_existing_provider_truth_and_honest_unavailable_states() -> None:
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    page = source[source.index('elif content_page == "Methodology & Data Status"') : source.index('elif content_page == "Alerts"')]

    assert "market_data_status.availability" in page
    assert "market_data_status.retrieved_at" in page
    assert "market_freshness" in page
    assert "Provider unavailable" in page
    assert "Sample only" in page
    assert "Not reported" in page
    assert "uptime" in page.lower()
    assert "SLA" in page


def test_internal_pool_detail_tables_do_not_use_new_tab_link_columns() -> None:
    app_source = (ROOT / "app.py").read_text(encoding="utf-8")
    shell_source = (ROOT / "ui_shell.py").read_text(encoding="utf-8")

    assert "st.column_config.LinkColumn" not in app_source
    assert 'target="_self"' in shell_source
    assert "_blank" not in shell_source
    assert 'st.link_button("Open Pool", row["pool_url"]' in app_source
