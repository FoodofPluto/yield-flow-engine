"""Scan tracked text files for credential shapes without printing matched values."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


PATTERNS = {
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "Discord webhook": re.compile(r"https://(?:canary\.|ptb\.)?discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9._-]+"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    "JWT": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "SendGrid API key": re.compile(r"\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\b"),
    "Slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    "Stripe secret key": re.compile(r"\b[rs]k_(?:live|test)_[A-Za-z0-9]{16,}\b"),
    "Telegram bot token": re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b"),
}


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    output = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    tracked = [part.decode("utf-8") for part in output.split(b"\0") if part]
    findings: list[tuple[str, int, str]] = []

    for relative in tracked:
        path = root / relative
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for name, pattern in PATTERNS.items():
                if pattern.search(line):
                    findings.append((relative, line_number, name))

    if findings:
        print("Potential tracked credentials found (values intentionally suppressed):")
        for relative, line_number, name in findings:
            print(f"- {relative}:{line_number}: {name}")
        return 1

    print(f"Scanned {len(tracked)} tracked/non-ignored files; no credential patterns found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
