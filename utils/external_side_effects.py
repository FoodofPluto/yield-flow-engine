"""Shared opt-out guard for network operations that create external side effects.

Production behavior is unchanged unless ``FURUFLOW_DISABLE_EXTERNAL_SIDE_EFFECTS``
is explicitly enabled. Tests and smoke checks enable the flag before imports.
"""

from __future__ import annotations

import os
from contextvars import ContextVar


_TRUE_VALUES = {"1", "true", "yes", "on"}
_demo_session: ContextVar[bool] = ContextVar("furuflow_demo_session", default=False)


class ExternalSideEffectBlocked(RuntimeError):
    """Raised when a side-effecting integration is disabled by the environment."""


def external_side_effects_disabled() -> bool:
    return _demo_session.get() or os.getenv("FURUFLOW_DISABLE_EXTERNAL_SIDE_EFFECTS", "false").strip().lower() in _TRUE_VALUES


def set_demo_side_effect_block(is_demo: bool) -> None:
    """Bind side-effect denial to the current Streamlit request context."""

    _demo_session.set(bool(is_demo))


def require_external_side_effects_allowed(integration: str) -> None:
    if external_side_effects_disabled():
        raise ExternalSideEffectBlocked(
            f"External side effects are disabled; refusing {integration} request."
        )
