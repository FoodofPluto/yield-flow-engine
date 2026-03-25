from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List

from telegram_utils import send_telegram_message


def should_alert(signal: Dict[str, Any]) -> bool:
    score = int(signal.get("strength_score") or 0)
    apy = float(signal.get("apy") or 0.0)
    tvl = float(signal.get("tvl") or 0.0)
    trend_score = float(signal.get("trend_score") or 0.0)
    return (
        score >= int(os.getenv("FURUFLOW_ALERT_MIN_SCORE", "70"))
        or (apy >= float(os.getenv("FURUFLOW_ALERT_MIN_APY", "25")) and tvl >= float(os.getenv("FURUFLOW_ALERT_MIN_TVL", "1000000")))
        or trend_score >= float(os.getenv("FURUFLOW_ALERT_MIN_TREND", "20"))
    )


def build_alert_message(signal: Dict[str, Any]) -> str:
    link = str(signal.get("pool_url") or signal.get("llama_pool_url") or signal.get("protocol_url") or "").strip()
    parts = [
        "🚨 Strong FuruFlow Alert",
        "",
        f"Pool: {signal.get('name', 'Unknown')}",
        f"Chain: {signal.get('chain', 'Unknown')}",
        f"APY: {float(signal.get('apy') or 0.0):.2f}%",
        f"TVL: ${float(signal.get('tvl') or 0.0):,.0f}",
        f"Strength: {int(signal.get('strength_score') or 0)}/100",
        f"Risk: {signal.get('risk_label', 'Unknown')}",
        f"Signal: {signal.get('signal', 'Steady')}",
        "",
        f"Why: {signal.get('reason', 'High-conviction setup')}",
    ]
    if link:
        parts += ["", link]
    parts += ["", "#FuruFlow #YieldAlerts"]
    return "\n".join(parts)


def send_strong_alerts(signals: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sent: List[Dict[str, Any]] = []
    if os.getenv("FURUFLOW_ENABLE_ALERTS", "true").strip().lower() not in {"1", "true", "yes", "on"}:
        return sent
    for signal in signals:
        if should_alert(signal):
            send_telegram_message(build_alert_message(signal))
            sent.append(signal)
    return sent
