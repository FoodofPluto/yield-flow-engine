from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _function_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def test_linkdebug_is_a_reduced_app_copy_with_one_known_missing_feature() -> None:
    app_functions = _function_names(ROOT / "app.py")
    linkdebug_functions = _function_names(ROOT / "app_linkdebug.py")

    assert app_functions - linkdebug_functions == {"build_signal_card_assets"}
    assert linkdebug_functions - app_functions == set()

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


def test_active_telegram_workflow_uses_the_canonical_poster() -> None:
    workflow = (ROOT / ".github" / "workflows" / "post-telegram-signals.yml").read_text(encoding="utf-8")
    assert "python ./post_real_signals.py" in workflow
    assert "run_furuflow" not in workflow
