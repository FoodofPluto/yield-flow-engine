from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _function_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def test_linkdebug_is_a_reduced_app_copy_with_known_canonical_shell_features_missing() -> None:
    app_functions = _function_names(ROOT / "app.py")
    linkdebug_functions = _function_names(ROOT / "app_linkdebug.py")

    assert app_functions - linkdebug_functions == {
        "_alert_form",
        "_internal_table_value",
        "build_signal_card_assets",
        "clear_discover_query_state",
        "fetch_enriched_pools",
        "go_to_route",
        "open_research",
        "open_research_many",
        "open_pool_detail",
        "render_alerts_page",
        "render_internal_pool_table",
        "return_from_pool_detail",
        "start_alert_creation",
    }
    assert linkdebug_functions - app_functions == {
        "load_watchlist",
        "make_download_df",
        "page_selectbox",
        "render_protocol_dashboard",
        "save_watchlist",
        "set_watchlist",
        "synthesize_pool_chart",
        "top_n_summary",
    }

    app_source = (ROOT / "app.py").read_text(encoding="utf-8")
    linkdebug_source = (ROOT / "app_linkdebug.py").read_text(encoding="utf-8")
    assert "Generate Card" in app_source
    assert "Generate Card" not in linkdebug_source
    assert 'key="drill_watch"' not in app_source
    assert 'key="drill_watch"' in linkdebug_source


def test_exact_legacy_script_duplicates_are_characterized() -> None:
    assert (ROOT / "scan-watch-adaptive.ps1").read_bytes() == (
        ROOT / "scan-watch-adaptive.patched.ps1"
    ).read_bytes()
    assert (ROOT / "parse-engine.fixed.ps1").read_bytes() == (
        ROOT / "scripts" / "parse-engine.ps1"
    ).read_bytes()
    assert (ROOT / "parse-engine.fixed.ps1").read_bytes() == (
        ROOT / "scripts" / "parse-engine.backup.ps1"
    ).read_bytes()


def test_github_telegram_workflow_is_manual_only_and_uses_durable_worker() -> None:
    workflow = (ROOT / ".github" / "workflows" / "post-telegram-signals.yml").read_text(encoding="utf-8")
    assert "python ./telegram_worker.py run" in workflow
    assert "schedule:" not in workflow
    assert "run_furuflow" not in workflow
