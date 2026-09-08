"""Parse every tracked Python file without importing application code."""

from __future__ import annotations

import ast
import subprocess
import tokenize
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    output = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "*.py"],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    tracked = [part.decode("utf-8") for part in output.split(b"\0") if part]

    failures: list[str] = []
    parsed_count = 0
    for relative in tracked:
        path = root / relative
        if not path.is_file():
            continue
        try:
            with tokenize.open(path) as source_file:
                ast.parse(source_file.read(), filename=relative)
                parsed_count += 1
        except (SyntaxError, UnicodeError) as exc:
            failures.append(f"{relative}: {exc}")

    if failures:
        print("Python syntax validation failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print(f"Parsed {parsed_count} tracked/non-ignored Python files successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
