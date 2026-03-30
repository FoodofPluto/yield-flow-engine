from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

from engine.alerts import send_strong_alerts
from engine.history import append_signal_history
from engine.links import build_signal_links
from engine.scanner import list_market_snapshot, rank_top_yields
from engine.scoring import public_risk_label, score_signal, strength_label
from engine.tier import signal_tier, split_signal_tiers
from history_store import save_snapshot
from signal_formatter import format_multiple_signals
from signal_intelligence import enrich_signals
from telegram_utils import send_telegram_message

DEFAULT_CHAINS = {"base", "arbitrum", "optimism", "polygon", "ethereum"}
POSTED_FILE = Path(os.getenv("FURUFLOW_POSTED_SIGNALS_FILE", "posted_signals.json"))

import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be a number, got: {raw!r}") from exc


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be an integer, got: {raw!r}") from exc


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "y", "on"}


def _env_chain_set() -> set[str]:
    raw = os.getenv("FURUFLOW_SIGNAL_CHAINS", "").strip()
    if not raw:
        return set(DEFAULT_CHAINS)
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def load_posted_signals() -> Dict[str, str]:
    if not POSTED_FILE.exists():
        return {}
    try:
        data = json.loads(POSTED_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            now = datetime.now(timezone.utc).isoformat()
            return {str(x): now for x in data}
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except Exception:
        pass
    return {}


def save_posted_signals(posted: Dict[str, str]) -> None:
    POSTED_FILE.write_text(json.dumps(posted, indent=2, sort_keys=True), encoding="utf-8")


def signal_id(signal: Dict[str, Any]) -> str:
    pool_id = str(signal.get("pool_id") or "").strip()
    if pool_id:
        return pool_id
    return "|".join([
        str(signal.get("name") or "").strip().lower(),
        str(signal.get("chain") or "").strip().lower(),
        str(signal.get("category") or "").strip().lower(),
    ])


def _capture_market_history(source: str) -> None:
    try:
        market_items = list_market_snapshot(source)
        rows: List[Dict[str, Any]] = []
        for item in market_items:
            meta = item.meta or {}
            rows.append({
                "pool": meta.get("pool_id") or "",
                "apy": float(meta.get("apy") or item.apy or 0.0),
                "apyBase": float(meta.get("apyBase") or 0.0),
                "apyReward": float(meta.get("apyReward") or 0.0),
                "tvlUsd": float(meta.get("tvlUsd") or 0.0),
            })
        if rows:
            import pandas as pd
            save_snapshot(pd.DataFrame(rows))
    except Exception as exc:
        print(f"History snapshot skipped: {exc}")


def _attach_phase_two_fields(signals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for signal in signals:
        s = dict(signal)
        s.update(build_signal_links(s))
        s["strength_score"] = score_signal(s)
        s["strength_label"] = strength_label(int(s["strength_score"]))
        s["risk_label"] = public_risk_label(s, int(s["strength_score"]))
        s["tier"] = signal_tier(s)
        out.append(s)
    return out


def get_real_furuflow_signals() -> List[Dict[str, Any]]:
    source = os.getenv("FURUFLOW_SIGNAL_SOURCE", "defillama").strip() or "defillama"
    min_tvl = _env_float("FURUFLOW_SIGNAL_MIN_TVL", 1_000_000)
    min_apy = _env_float("FURUFLOW_SIGNAL_MIN_APY", 8.0)
    max_apy = _env_float("FURUFLOW_SIGNAL_MAX_APY", 200.0)
    min_risk = _env_float("FURUFLOW_SIGNAL_MIN_RISK", 0.0)
    max_risk = _env_float("FURUFLOW_SIGNAL_MAX_RISK", 100.0)
    min_strength = _env_float("FURUFLOW_SIGNAL_MIN_STRENGTH", 0.0)
    max_strength = _env_float("FURUFLOW_SIGNAL_MAX_STRENGTH", 100.0)
    top_n = _env_int("FURUFLOW_SIGNAL_TOP_N", 5)
    stablecoin_only = _env_bool("FURUFLOW_SIGNAL_STABLECOIN_ONLY", False)
    requested_chains = _env_chain_set()

    _capture_market_history(source)

    candidates = rank_top_yields(
        top=max(top_n * 8, 40),
        source=source,
        min_tvl=min_tvl,
        max_apy=max_apy,
        stablecoin_only=stablecoin_only,
        chains=list(requested_chains) if requested_chains else None,
    )

    signals: List[Dict[str, Any]] = []
    for item in candidates:
        meta = item.meta or {}
        apy = float(meta.get("apy") or item.apy or 0.0)
        tvl = float(meta.get("tvlUsd") or 0.0)
        chain = str(meta.get("chain") or "").strip()
        chain_norm = chain.lower()
        if apy < min_apy or apy > max_apy or tvl < min_tvl:
            continue
        if requested_chains and chain_norm not in requested_chains:
            continue
        signals.append({
            "name": item.name,
            "chain": chain,
            "apy": round(apy, 2),
            "tvl": tvl,
            "category": meta.get("category") or "Unknown",
            "source": str(item.source).title(),
            "project": meta.get("project") or "",
            "symbol": meta.get("symbol") or "",
            "pool_id": meta.get("pool_id") or "",
            "stablecoin": bool(meta.get("stablecoin") or False),
            "risk_score": int(meta.get("risk_score") or 0),
            "risk_label": meta.get("risk_label") or "",
            "risk_reasons": meta.get("risk_reasons") or "",
            "protocol_url": meta.get("protocol_url") or "",
            "llama_pool_url": meta.get("llama_pool_url") or "",
        })

    signals = enrich_signals(signals)
    signals = _attach_phase_two_fields(signals)

    filtered_signals: List[Dict[str, Any]] = []
    for signal in signals:
        risk_score = float(signal.get("risk_score") or 0.0)
        strength_score = float(signal.get("strength_score") or 0.0)
        if risk_score < min_risk or risk_score > max_risk:
            continue
        if strength_score < min_strength or strength_score > max_strength:
            continue
        filtered_signals.append(signal)

    return filtered_signals[:top_n]


def get_new_signals(signals: List[Dict[str, Any]], dedupe_hours: int) -> List[Dict[str, Any]]:
    posted = load_posted_signals()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(dedupe_hours, 0))
    fresh: List[Dict[str, Any]] = []
    for signal in signals:
        sid = signal_id(signal)
        seen_at = posted.get(sid)
        if not seen_at:
            fresh.append(signal)
            continue
        try:
            seen_dt = datetime.fromisoformat(seen_at.replace("Z", "+00:00"))
            if seen_dt.tzinfo is None:
                seen_dt = seen_dt.replace(tzinfo=timezone.utc)
        except Exception:
            fresh.append(signal)
            continue
        if seen_dt <= cutoff:
            fresh.append(signal)
    return fresh


def remember_signals(signals: List[Dict[str, Any]]) -> None:
    posted = load_posted_signals()
    now = datetime.now(timezone.utc).isoformat()
    for signal in signals:
        posted[signal_id(signal)] = now
    save_posted_signals(posted)


def main() -> None:
    dry_run = _env_bool("FURUFLOW_SIGNAL_DRY_RUN", False)
    allow_reposts = _env_bool("FURUFLOW_SIGNAL_ALLOW_REPOSTS", False)
    dedupe_hours = _env_int("FURUFLOW_SIGNAL_DEDUPE_HOURS", 24)
    max_posts = _env_int("FURUFLOW_SIGNAL_MAX_POSTS", 3)

    post_free = _env_bool("FURUFLOW_POST_FREE_SIGNALS", True)
    post_pro = _env_bool("FURUFLOW_POST_PRO_SIGNALS", False)

    signals = get_real_furuflow_signals()
    if not signals:
        print("No qualifying signals found.")
        return

    append_signal_history(signals)

    free_signals, pro_signals = split_signal_tiers(signals)

    telegram_candidates = []
    if post_free:
        telegram_candidates.extend(free_signals)
    if post_pro:
        telegram_candidates.extend(pro_signals)

    if not telegram_candidates:
        print("No Telegram-eligible signals found for the current tier settings.")
        return

    fresh_signals = telegram_candidates if allow_reposts else get_new_signals(
        telegram_candidates,
        dedupe_hours=dedupe_hours,
    )

    if max_posts > 0:
        fresh_signals = fresh_signals[:max_posts]

    if not fresh_signals:
        print("No new Telegram-eligible signals to post.")
        if pro_signals:
            print(f"{len(pro_signals)} Pro-tier signal(s) captured.")
        return

    message = format_multiple_signals(fresh_signals)
    if dry_run:
        print(message)
        return

    result = send_telegram_message(message)
    alerts_sent = send_strong_alerts(fresh_signals)
    remember_signals(fresh_signals)

    print(f"Posted {len(fresh_signals)} signal(s) to Telegram.")
    print(f"Strong alerts sent: {len(alerts_sent)}")
    print(result)


if __name__ == "__main__":
    main()
