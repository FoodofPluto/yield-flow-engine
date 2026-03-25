from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import random
import time
from pathlib import Path
from typing import Dict, Iterable, List
from urllib.parse import quote

import requests
from dotenv import load_dotenv

load_dotenv()

from engine.recap import _read_rows, build_daily_recap, build_weekly_recap
from engine.x_format import format_x_recap_post, format_x_signal_post
from post_real_signals import get_real_furuflow_signals

X_POST_LOG = Path(os.getenv("FURUFLOW_X_POST_LOG", "x_posts_log.json"))
X_OUTBOX = Path(os.getenv("FURUFLOW_X_OUTBOX", "x_post_outbox.txt"))


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "y", "on"}


def _pct_encode(value: str) -> str:
    return quote(str(value), safe="~-._")


def _oauth_header(method: str, url: str) -> str:
    consumer_key = os.getenv("X_API_KEY", "")
    consumer_secret = os.getenv("X_API_SECRET", "")
    access_token = os.getenv("X_ACCESS_TOKEN", "")
    access_secret = os.getenv("X_ACCESS_TOKEN_SECRET", "")

    if not all([consumer_key, consumer_secret, access_token, access_secret]):
        raise RuntimeError(
            "Missing X OAuth credentials. Set X_API_KEY, X_API_SECRET, "
            "X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET."
        )

    oauth_params: Dict[str, str] = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": str(random.randint(10**8, 10**9 - 1)),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": access_token,
        "oauth_version": "1.0",
    }

    # For application/json POST requests, do not include JSON body fields in the signature
    param_str = "&".join(
        f"{_pct_encode(k)}={_pct_encode(v)}"
        for k, v in sorted(oauth_params.items())
    )

    base_str = "&".join([
        method.upper(),
        _pct_encode(url),
        _pct_encode(param_str),
    ])

    signing_key = f"{_pct_encode(consumer_secret)}&{_pct_encode(access_secret)}"
    signature = base64.b64encode(
        hmac.new(signing_key.encode(), base_str.encode(), hashlib.sha1).digest()
    ).decode()

    oauth_params["oauth_signature"] = signature

    return "OAuth " + ", ".join(
        f'{_pct_encode(k)}="{_pct_encode(v)}"'
        for k, v in oauth_params.items()
    )


def post_tweet(text: str) -> dict:
    url = "https://api.twitter.com/2/tweets"
    payload = json.dumps({"text": text}, ensure_ascii=False)
    headers = {
        "Authorization": _oauth_header("POST", url),
        "Content-Type": "application/json",
    }
    resp = requests.post(url, data=payload.encode("utf-8"), headers=headers, timeout=30)
    print(resp.status_code)
    print(resp.text)
    resp.raise_for_status()
    return resp.json()


def _write_outbox(posts: Iterable[str]) -> None:
    X_OUTBOX.write_text("\n\n---\n\n".join(posts), encoding="utf-8")


def build_signal_posts(limit: int = 2) -> List[str]:
    signals = [
        s for s in get_real_furuflow_signals()
        if str(s.get("tier") or "Free").lower() == "free"
    ]
    return [format_x_signal_post(signal, include_link=False) for signal in signals[:limit]]


def build_daily_post() -> str:
    rows = sorted(
        _read_rows(),
        key=lambda r: (r.get("timestamp") or "", int(float(r.get("strength_score") or 0))),
        reverse=True,
    )
    return format_x_recap_post("🔥 FuruFlow Daily Recap", rows, limit=3) if rows else build_daily_recap()


def build_weekly_post() -> str:
    rows = sorted(
        _read_rows(),
        key=lambda r: (int(float(r.get("strength_score") or 0)), float(r.get("apy") or 0.0)),
        reverse=True,
    )
    return format_x_recap_post("📈 FuruFlow Weekly Winners", rows, limit=5) if rows else build_weekly_recap()


def main() -> None:
    mode = (os.getenv("FURUFLOW_X_MODE", "signals") or "signals").strip().lower()
    post_live = _env_bool("FURUFLOW_X_POST_LIVE", False)

    if mode == "daily":
        posts: List[str] = [build_daily_post()]
    elif mode == "weekly":
        posts = [build_weekly_post()]
    else:
        posts = build_signal_posts(limit=int(os.getenv("FURUFLOW_X_MAX_POSTS", "2")))

    if not posts:
        print("No X posts generated.")
        return

    if not post_live:
        _write_outbox(posts)
        for i, post in enumerate(posts, start=1):
            print(f"--- X POST {i} ---")
            print(post)
        print(f"Saved X outbox to {X_OUTBOX}")
        return

    results = []
    for post in posts:
        results.append(post_tweet(post))

    X_POST_LOG.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Posted {len(results)} tweet(s) to X.")


if __name__ == "__main__":
    main()