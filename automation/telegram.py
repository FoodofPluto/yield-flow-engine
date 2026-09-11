from __future__ import annotations

import os
from typing import Any

import requests

from automation.models import TelegramDeliveryError, TelegramReceipt
from utils.external_side_effects import require_external_side_effects_allowed


class TelegramClient:
    """Single-attempt Telegram transport; durable retries belong to the worker."""

    def __init__(
        self,
        *,
        token: str | None = None,
        session: Any | None = None,
        connect_timeout: float | None = None,
        read_timeout: float | None = None,
    ) -> None:
        self._token = (token or os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
        if not self._token:
            raise ValueError("Missing TELEGRAM_BOT_TOKEN environment variable")
        self._session = session or requests
        self._connect_timeout = connect_timeout or float(os.getenv("TELEGRAM_CONNECT_TIMEOUT", "10"))
        self._read_timeout = read_timeout or float(os.getenv("TELEGRAM_READ_TIMEOUT", "45"))

    def send(self, *, chat_id: str, text: str) -> TelegramReceipt:
        require_external_side_effects_allowed("Telegram")
        if not chat_id.strip():
            raise TelegramDeliveryError("missing_chat_id", retryable=False)
        try:
            response = self._session.post(
                f"https://api.telegram.org/bot{self._token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
                timeout=(self._connect_timeout, self._read_timeout),
            )
        except (requests.ConnectTimeout, requests.ReadTimeout) as exc:
            raise TelegramDeliveryError("telegram_timeout_unknown_outcome", retryable=False, ambiguous=True) from exc
        except requests.RequestException as exc:
            raise TelegramDeliveryError("telegram_network_unknown_outcome", retryable=False, ambiguous=True) from exc

        status = int(response.status_code)
        if status < 200 or status >= 300:
            retry_after = None
            if status == 429:
                try:
                    retry_after = int(response.json().get("parameters", {}).get("retry_after"))
                except (TypeError, ValueError, AttributeError):
                    retry_after = None
            if status in {400, 401, 403, 404}:
                raise TelegramDeliveryError(f"telegram_http_{status}", retryable=False)
            raise TelegramDeliveryError(
                f"telegram_http_{status}",
                retryable=True,
                retry_after_seconds=retry_after,
            )
        try:
            payload = response.json()
            result = payload["result"]
            message_id = str(result["message_id"])
            provider_chat_id = str(result.get("chat", {}).get("id") or "") or None
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise TelegramDeliveryError("telegram_invalid_success_response", retryable=False, ambiguous=True) from exc
        return TelegramReceipt(message_id=message_id, provider_chat_id=provider_chat_id)
