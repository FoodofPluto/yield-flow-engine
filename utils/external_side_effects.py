"""Shared opt-out guard for network operations that create external side effects.

Production behavior is unchanged unless ``FURUFLOW_DISABLE_EXTERNAL_SIDE_EFFECTS``
is explicitly enabled. Tests and smoke checks enable the flag before imports.
"""

from __future__ import annotations

import os


_TRUE_VALUES = {"1", "true", "yes", "on"}


class ExternalSideEffectBlocked(RuntimeError):
    """Raised when a side-effecting integration is disabled by the environment."""


def external_side_effects_disabled() -> bool:
    return os.getenv("FURUFLOW_DISABLE_EXTERNAL_SIDE_EFFECTS", "false").strip().lower() in _TRUE_VALUES


def require_external_side_effects_allowed(integration: str) -> None:
    if external_side_effects_disabled():
        raise ExternalSideEffectBlocked(
            f"External side effects are disabled; refusing {integration} request."
        )
