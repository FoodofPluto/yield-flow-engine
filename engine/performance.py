from __future__ import annotations

import csv
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List

import pandas as pd

from engine.history import SIGNAL_HISTORY_FILE


def load_signal_history(path: Path | str = SIGNAL_HISTORY_FILE) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()
    with path.open('r', encoding='utf-8', newline='') as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    for col in ['apy', 'tvl', 'strength_score', 'risk_score', 'trend_score']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce', utc=True)
    return df


def latest_signal_history(limit: int = 12) -> pd.DataFrame:
    df = load_signal_history()
    if df.empty:
        return df
    return df.sort_values(['timestamp', 'strength_score', 'apy'], ascending=[False, False, False]).head(limit).copy()


def trend_summary_df(limit: int = 10) -> pd.DataFrame:
    df = load_signal_history()
    if df.empty:
        return df
    grouped = df.sort_values('timestamp').groupby('pool_id', dropna=False)
    rows: List[Dict[str, object]] = []
    for pool_id, g in grouped:
        g = g.dropna(subset=['timestamp'])
        if g.empty:
            continue
        latest = g.iloc[-1]
        first = g.iloc[0]
        rows.append({
            'Pool': latest.get('name', 'Unknown'),
            'Chain': latest.get('chain', 'Unknown'),
            'APY': float(latest.get('apy', 0.0)),
            'TVL (USD)': float(latest.get('tvl', 0.0)),
            'Score': int(latest.get('strength_score', 0)),
            'Tier': latest.get('tier', 'Free'),
            'Seen': len(g),
            'APY Δ': float(latest.get('apy', 0.0)) - float(first.get('apy', 0.0)),
            'Last seen': latest.get('timestamp'),
        })
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(['Score', 'Seen', 'APY'], ascending=[False, False, False]).head(limit)


def alert_snapshot() -> Dict[str, object]:
    df = load_signal_history()
    if df.empty:
        return {'signals_24h': 0, 'pro_24h': 0, 'best_chain': 'None'}
    cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    recent = df[df['timestamp'] >= cutoff].copy() if 'timestamp' in df.columns else df.copy()
    if recent.empty:
        return {'signals_24h': 0, 'pro_24h': 0, 'best_chain': 'None'}
    chains = Counter(recent['chain'].fillna('Unknown').astype(str).tolist())
    return {
        'signals_24h': int(len(recent)),
        'pro_24h': int((recent['tier'].astype(str).str.lower() == 'pro').sum()) if 'tier' in recent.columns else 0,
        'best_chain': chains.most_common(1)[0][0] if chains else 'None',
    }
