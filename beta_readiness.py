"""Safe, environment-driven controls and presentation for the closed beta."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Mapping
from urllib.parse import urlparse
from uuid import UUID


SAFE_BUILD_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SAFE_LABEL_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,31}$")
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


@dataclass(frozen=True)
class BetaConfig:
    enabled: bool
    label: str
    allowed_user_ids: frozenset[str]
    allow_signup: bool
    maintenance_message: str | None
    errors: tuple[str, ...]


@dataclass(frozen=True)
class BetaAccessDecision:
    allowed: bool
    reason: str


class FailureKind(str, Enum):
    NO_DATA = "no_data"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    STALE_DATA = "stale_data"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    RATE_LIMITED = "rate_limited"
    AUTHENTICATION_REQUIRED = "authentication_required"
    AUTHORIZATION_REQUIRED = "authorization_required"
    CONFIGURATION_UNAVAILABLE = "configuration_unavailable"


@dataclass(frozen=True)
class FailurePresentation:
    kind: FailureKind
    status_kind: str
    title: str
    message: str
    action: str


FAILURE_PRESENTATIONS = {
    FailureKind.NO_DATA: FailurePresentation(
        FailureKind.NO_DATA,
        "empty",
        "No data",
        "The provider returned no usable data for this request; missing values were not converted to zero.",
        "Return to Discover or retry after the provider has new data.",
    ),
    FailureKind.INSUFFICIENT_EVIDENCE: FailurePresentation(
        FailureKind.INSUFFICIENT_EVIDENCE,
        "warning",
        "Insufficient evidence",
        "Data exists, but it does not satisfy the evidence requirements for this analysis.",
        "Review the available observations or wait for additional history.",
    ),
    FailureKind.STALE_DATA: FailurePresentation(
        FailureKind.STALE_DATA,
        "stale",
        "Stale data",
        "The last successful observation is older than the accepted freshness threshold.",
        "Verify the visible timestamp and retry before relying on current conditions.",
    ),
    FailureKind.PROVIDER_UNAVAILABLE: FailurePresentation(
        FailureKind.PROVIDER_UNAVAILABLE,
        "error",
        "Provider unavailable",
        "The external data provider could not return a usable response. No current values were inferred.",
        "Retry later, return to Discover, or use an explicitly labelled stored view when available.",
    ),
    FailureKind.RATE_LIMITED: FailurePresentation(
        FailureKind.RATE_LIMITED,
        "warning",
        "Temporarily busy",
        "The data provider is rate limiting requests. FuruFlow stopped this refresh instead of retrying repeatedly.",
        "Wait a short time, then retry once. Previously displayed freshness labels remain authoritative.",
    ),
    FailureKind.AUTHENTICATION_REQUIRED: FailurePresentation(
        FailureKind.AUTHENTICATION_REQUIRED,
        "auth",
        "Authentication required",
        "This account workflow requires a verified sign-in.",
        "Open Account and sign in, or continue with public Discover workflows.",
    ),
    FailureKind.AUTHORIZATION_REQUIRED: FailurePresentation(
        FailureKind.AUTHORIZATION_REQUIRED,
        "restricted",
        "Authorization required",
        "Your verified account does not include this capability.",
        "Return to an available workflow or review the capability requirements.",
    ),
    FailureKind.CONFIGURATION_UNAVAILABLE: FailurePresentation(
        FailureKind.CONFIGURATION_UNAVAILABLE,
        "error",
        "Configuration unavailable",
        "This server-side feature is not configured for this release candidate.",
        "Use another available workflow or contact beta support.",
    ),
}


def _parse_boolean(source: Mapping[str, str], key: str, *, default: bool) -> tuple[bool, str | None]:
    raw = str(source.get(key) or "").strip().lower()
    if not raw:
        return default, None
    if raw in {"1", "true", "yes", "on"}:
        return True, None
    if raw in {"0", "false", "no", "off"}:
        return False, None
    return default, f"{key} must be true or false"


def _allowed_user_ids(value: str) -> tuple[frozenset[str], tuple[str, ...]]:
    allowed: set[str] = set()
    errors: list[str] = []
    for candidate in (part.strip() for part in value.split(",")):
        if not candidate:
            continue
        try:
            allowed.add(str(UUID(candidate)))
        except ValueError:
            errors.append("FURUFLOW_BETA_ALLOWED_USER_IDS contains an invalid UUID")
    return frozenset(allowed), tuple(errors)


def beta_config(source: Mapping[str, str]) -> BetaConfig:
    """Parse beta controls with fail-closed access and non-sensitive errors."""

    enabled, enabled_error = _parse_boolean(source, "FURUFLOW_BETA_ENABLED", default=False)
    allow_signup, signup_error = _parse_boolean(source, "FURUFLOW_BETA_ALLOW_SIGNUP", default=False)
    allowed_user_ids, id_errors = _allowed_user_ids(str(source.get("FURUFLOW_BETA_ALLOWED_USER_IDS") or ""))
    errors = tuple(error for error in (enabled_error, signup_error, *id_errors) if error)

    label_value = str(source.get("FURUFLOW_BETA_LABEL") or "Closed Beta").strip()
    label = label_value if SAFE_LABEL_VALUE.fullmatch(label_value) else "Closed Beta"

    maintenance_value = " ".join(str(source.get("FURUFLOW_MAINTENANCE_MESSAGE") or "").split())
    maintenance_message = maintenance_value[:240] if maintenance_value else None
    if enabled and not allowed_user_ids:
        errors += ("FURUFLOW_BETA_ALLOWED_USER_IDS must contain at least one UUID when beta access is enabled",)

    return BetaConfig(
        enabled=enabled,
        label=label,
        allowed_user_ids=allowed_user_ids,
        allow_signup=allow_signup,
        maintenance_message=maintenance_message,
        errors=errors,
    )


def beta_access(config: BetaConfig, user: Mapping[str, object] | None) -> BetaAccessDecision:
    """Keep beta participation separate from subscription capability grants."""

    if not config.enabled:
        return BetaAccessDecision(True, "beta_disabled")
    if config.errors:
        return BetaAccessDecision(False, "configuration_unavailable")
    if not user or not user.get("_identity_verified"):
        return BetaAccessDecision(False, "authentication_required")
    if user.get("_account_authority") == "supabase" and user.get("is_admin") is True:
        return BetaAccessDecision(True, "verified_admin")
    try:
        user_id = str(UUID(str(user.get("provider_user_id") or "")))
    except ValueError:
        return BetaAccessDecision(False, "beta_access_required")
    if user_id in config.allowed_user_ids:
        return BetaAccessDecision(True, "allowlisted")
    return BetaAccessDecision(False, "beta_access_required")


def failure_presentation(kind: FailureKind | str) -> FailurePresentation:
    try:
        canonical = FailureKind(kind)
    except ValueError:
        canonical = FailureKind.PROVIDER_UNAVAILABLE
    return FAILURE_PRESENTATIONS[canonical]


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
