"""Test-wide containment for credentials and outbound network activity."""

from __future__ import annotations

import os
import socket
from typing import Any

import pytest


_PRODUCTION_CREDENTIALS = (
    "DISCORD_WEBHOOK",
    "DISCORD_WEBHOOK_URL",
    "SENDGRID_API_KEY",
    "SMTP_PASSWORD",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "SUPABASE_ANON_KEY",
    "SUPABASE_JWKS_URL",
    "SUPABASE_JWT_SECRET",
    "SUPABASE_REDIRECT_URL_DEVELOPMENT",
    "SUPABASE_REDIRECT_URL_PREVIEW",
    "SUPABASE_REDIRECT_URL_PRODUCTION",
    "SUPABASE_REDIRECT_URL_TEST",
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "FURUFLOW_SESSION_ENCRYPTION_KEY",
    "FURUFLOW_SESSION_BRIDGE_KEY",
    "FURUFLOW_SESSION_BROKER_INTERNAL_URL",
    "FURUFLOW_SESSION_BROKER_PUBLIC_ORIGIN",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "TWITTER_ACCESS_TOKEN",
    "TWITTER_ACCESS_TOKEN_SECRET",
    "TWITTER_API_KEY",
    "TWITTER_API_SECRET",
    "X_ACCESS_TOKEN",
    "X_ACCESS_TOKEN_SECRET",
    "X_API_KEY",
    "X_API_SECRET",
)


def pytest_configure() -> None:
    os.environ["ENVIRONMENT"] = "test"
    os.environ["DEV_MODE"] = "false"
    os.environ["FURUFLOW_DISABLE_EXTERNAL_SIDE_EFFECTS"] = "true"
    # Streamlit workflow tests use an explicit, clearly labelled development
    # fixture. Production leaves this unset and never substitutes sample pools.
    os.environ["FURUFLOW_MARKET_SAMPLE_MODE"] = "true"
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    for name in _PRODUCTION_CREDENTIALS:
        os.environ.pop(name, None)


@pytest.fixture(autouse=True)
def block_outbound_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail every socket connection, including indirect SDK and HTTP-client calls."""

    def blocked(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("Outbound network access is disabled during tests.")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
