from __future__ import annotations

import socket
from unittest.mock import patch

import pytest
import requests

import telegram_utils
from engine.postprocess import post_to_discord
from post_to_x import post_tweet
from utils.external_side_effects import ExternalSideEffectBlocked, set_demo_side_effect_block


def test_test_runner_blocks_direct_network_requests() -> None:
    with pytest.raises(RuntimeError, match="Outbound network access is disabled"):
        requests.get("https://example.invalid", timeout=1)

    with pytest.raises(RuntimeError, match="Outbound network access is disabled"):
        socket.create_connection(("example.invalid", 443), timeout=1)


def test_message_integrations_stop_before_transport() -> None:
    with patch.object(telegram_utils.requests, "post") as telegram_post:
        with pytest.raises(ExternalSideEffectBlocked, match="Telegram"):
            telegram_utils.send_telegram_message("test")
        telegram_post.assert_not_called()

    with patch("engine.postprocess.requests.post") as discord_post:
        with pytest.raises(ExternalSideEffectBlocked, match="Discord"):
            post_to_discord("https://example.invalid/webhook", "test")
        discord_post.assert_not_called()

    with patch("post_to_x.requests.post") as x_post:
        with pytest.raises(ExternalSideEffectBlocked, match="X"):
            post_tweet("test")
        x_post.assert_not_called()


def test_demo_context_blocks_delivery_even_when_global_guard_is_off() -> None:
    with patch.dict("os.environ", {"FURUFLOW_DISABLE_EXTERNAL_SIDE_EFFECTS": "false"}, clear=False):
        set_demo_side_effect_block(True)
        try:
            with patch.object(telegram_utils.requests, "post") as telegram_post:
                with pytest.raises(ExternalSideEffectBlocked, match="Telegram"):
                    telegram_utils.send_telegram_message("demo")
                telegram_post.assert_not_called()
        finally:
            set_demo_side_effect_block(False)
