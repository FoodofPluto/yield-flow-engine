"""Safe, environment-driven presentation metadata for controlled beta support."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlparse


SAFE_BUILD_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
ENVIRONMENT_LABELS = {
    "development": "Development",
    "preview": "Preview",
    "staging": "Staging",
    "production": "Production",
    "test": "Test",
}


@dataclass(frozen=True)
class BetaDiagnostics:
    environment: str
    app_version: str
    build_id: str | None
    support_url: str | None


def _safe_build_id(source: Mapping[str, str]) -> str | None:
    for key in ("FURUFLOW_BUILD_ID", "RENDER_GIT_COMMIT"):
        value = str(source.get(key) or "").strip()
        if SAFE_BUILD_VALUE.fullmatch(value):
            return value[:12] if key == "RENDER_GIT_COMMIT" else value
    return None


def _safe_support_url(source: Mapping[str, str]) -> str | None:
    value = str(source.get("FURUFLOW_SUPPORT_URL") or "").strip()
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        return None
    return value


def beta_diagnostics(source: Mapping[str, str], *, app_version: str) -> BetaDiagnostics:
    """Resolve non-sensitive runtime identity without inventing deployment facts."""

    raw_environment = str(source.get("ENVIRONMENT") or "development").strip().lower()
    environment = ENVIRONMENT_LABELS.get(raw_environment, "Unspecified")
    return BetaDiagnostics(
        environment=environment,
        app_version=str(app_version),
        build_id=_safe_build_id(source),
        support_url=_safe_support_url(source),
    )
