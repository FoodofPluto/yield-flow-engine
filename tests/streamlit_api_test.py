from pathlib import Path


def test_streamlit_apps_do_not_use_deprecated_container_width_argument() -> None:
    root = Path(__file__).resolve().parents[1]
    for name in ("app.py", "app_linkdebug.py"):
        source = (root / name).read_text(encoding="utf-8")
        assert "use_container_width=" not in source
