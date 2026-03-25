import json
import os
import subprocess
import time
from typing import Any, Dict

import requests
from requests.exceptions import (
    ConnectTimeout,
    ReadTimeout,
    RequestException,
    SSLError,
)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TELEGRAM_CONNECT_TIMEOUT = float(os.getenv("TELEGRAM_CONNECT_TIMEOUT", "10"))
TELEGRAM_READ_TIMEOUT = float(os.getenv("TELEGRAM_READ_TIMEOUT", "45"))
TELEGRAM_RETRY_COUNT = max(int(os.getenv("TELEGRAM_RETRY_COUNT", "3")), 1)
TELEGRAM_RETRY_SLEEP_SECONDS = float(os.getenv("TELEGRAM_RETRY_SLEEP_SECONDS", "5"))
TELEGRAM_DISABLE_SSL_VERIFY = os.getenv("TELEGRAM_DISABLE_SSL_VERIFY", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
TELEGRAM_ENABLE_POWERSHELL_FALLBACK = os.getenv(
    "TELEGRAM_ENABLE_POWERSHELL_FALLBACK", "true"
).strip().lower() in {"1", "true", "yes", "on"}


def _build_url(token: str) -> str:
    return f"https://api.telegram.org/bot{token}/sendMessage"


def _build_payload(text: str) -> Dict[str, Any]:
    return {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }


def _send_with_requests(url: str, payload: Dict[str, Any], verify: bool = True) -> dict:
    response = requests.post(
        url,
        json=payload,
        timeout=(TELEGRAM_CONNECT_TIMEOUT, TELEGRAM_READ_TIMEOUT),
        verify=verify,
    )
    response.raise_for_status()
    return response.json()


def _send_with_powershell(payload: Dict[str, Any]) -> dict:
    if os.name != "nt":
        raise RuntimeError("PowerShell fallback is only available on Windows.")

    token = TELEGRAM_BOT_TOKEN or ""
    payload_json = json.dumps(payload, ensure_ascii=False)
    ps_script = rf'''
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$body = @'
{payload_json}
'@
Invoke-RestMethod -Uri "https://api.telegram.org/bot{token}/sendMessage" -Method Post -ContentType "application/json" -Body $body | ConvertTo-Json -Depth 8 -Compress
'''.strip()

    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            ps_script,
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        raise RuntimeError(
            "PowerShell Telegram fallback failed"
            + (f": {stderr}" if stderr else (f": {stdout}" if stdout else ""))
        )

    raw = (completed.stdout or "").strip()
    if not raw:
        raise RuntimeError("PowerShell Telegram fallback returned no output.")

    return json.loads(raw)


def send_telegram_message(text: str) -> dict:
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("Missing TELEGRAM_BOT_TOKEN environment variable")
    if not TELEGRAM_CHAT_ID:
        raise ValueError("Missing TELEGRAM_CHAT_ID environment variable")

    url = _build_url(TELEGRAM_BOT_TOKEN)
    payload = _build_payload(text)
    last_error: Exception | None = None
    saw_ssl_error = False

    for attempt in range(1, TELEGRAM_RETRY_COUNT + 1):
        try:
            print(f"[telegram] HTTPS send attempt {attempt}/{TELEGRAM_RETRY_COUNT}")
            return _send_with_requests(
                url,
                payload,
                verify=not TELEGRAM_DISABLE_SSL_VERIFY,
            )
        except SSLError as e:
            last_error = e
            saw_ssl_error = True
            print(f"[telegram] SSL error on attempt {attempt}/{TELEGRAM_RETRY_COUNT}: {e}")
        except (ReadTimeout, ConnectTimeout) as e:
            last_error = e
            print(f"[telegram] Timeout on attempt {attempt}/{TELEGRAM_RETRY_COUNT}: {e}")
        except RequestException as e:
            last_error = e
            print(f"[telegram] Request failed on attempt {attempt}/{TELEGRAM_RETRY_COUNT}: {e}")

        if attempt < TELEGRAM_RETRY_COUNT:
            time.sleep(TELEGRAM_RETRY_SLEEP_SECONDS)

    if saw_ssl_error and TELEGRAM_ENABLE_POWERSHELL_FALLBACK:
        print("[telegram] Falling back to PowerShell Invoke-RestMethod after HTTPS SSL failure.")
        try:
            return _send_with_powershell(payload)
        except Exception as e:
            last_error = e
            print(f"[telegram] PowerShell fallback failed: {e}")

    raise RuntimeError(f"Telegram send failed after retries: {last_error}")
