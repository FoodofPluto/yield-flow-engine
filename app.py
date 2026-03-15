from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

APP_NAME = "FuruFlow"
APP_TAGLINE = "DeFi yield intelligence with scanner, signals, arbitrage, and watchlist workflows"
POOL_LIMIT = 350
TIMEOUT = 18
SIGNAL_SAMPLE = 14

st.set_page_config(
    page_title=f"{APP_NAME} v6",
    page_icon="🐸",
    layout="wide",
    initial_sidebar_state="expanded",
)

PROTOCOL_META = {
    "aave-v3": {"age": 96, "audit": 98, "brand": "A", "tier": "Core"},
    "aave": {"age": 96, "audit": 98, "brand": "A", "tier": "Core"},
    "uniswap-v3": {"age": 94, "audit": 95, "brand": "U", "tier": "Core"},
    "uniswap": {"age": 94, "audit": 95, "brand": "U", "tier": "Core"},
    "curve": {"age": 95, "audit": 94, "brand": "C", "tier": "Core"},
    "morpho": {"age": 72, "audit": 86, "brand": "M", "tier": "Prime"},
    "morpho-v1": {"age": 72, "audit": 86, "brand": "M", "tier": "Prime"},
    "pendle": {"age": 78, "audit": 90, "brand": "P", "tier": "Prime"},
    "camelot-v3": {"age": 68, "audit": 74, "brand": "C", "tier": "Growth"},
    "beefy": {"age": 83, "audit": 86, "brand": "B", "tier": "Prime"},
    "yearn": {"age": 90, "audit": 88, "brand": "Y", "tier": "Core"},
    "hyperliquid-vault": {"age": 40, "audit": 45, "brand": "H", "tier": "Spec"},
    "hyperliquid": {"age": 40, "audit": 45, "brand": "H", "tier": "Spec"},
    "ethena": {"age": 52, "audit": 70, "brand": "E", "tier": "Growth"},
    "gmx": {"age": 76, "audit": 82, "brand": "G", "tier": "Prime"},
    "silo": {"age": 64, "audit": 78, "brand": "S", "tier": "Growth"},
}


def inject_css() -> None:
    st.markdown(
        """
        <style>
            :root {
                --bg: #07111f;
                --bg-2: #0a1628;
                --panel: #0f1d33;
                --panel-2: #12243e;
                --panel-3: #162c49;
                --border: rgba(255,255,255,0.08);
                --text: #eef4ff;
                --muted: #a7b7d4;
                --muted-2: #8ea2c6;
                --accent: #7ce2ff;
                --accent-2: #5ec7ff;
                --good: #35d49a;
                --warn: #f3c15f;
                --bad: #ff7b86;
                --surface-light: #f4f8ff;
                --surface-light-2: #e8f0ff;
                --surface-dark-text: #07111f;
                --surface-dark-text-2: #22324d;
            }

            html, body, [class*="css"] {
                font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            }

            .stApp {
                color: var(--text);
                background:
                    radial-gradient(circle at top right, rgba(124,226,255,0.12), transparent 24%),
                    radial-gradient(circle at top left, rgba(50,120,255,0.08), transparent 28%),
                    linear-gradient(180deg, var(--bg) 0%, #081321 100%);
            }

            .block-container {
                max-width: 1650px;
                padding-top: 1rem;
                padding-bottom: 2rem;
                padding-left: 1.35rem;
                padding-right: 1.35rem;
            }

            h1, h2, h3, h4, h5, h6, p, span, label, div { color: var(--text); }

            .hero-shell {
                border: 1px solid var(--border);
                border-radius: 30px;
                overflow: hidden;
                background: linear-gradient(150deg, rgba(17,32,54,0.98), rgba(9,18,31,0.98));
                box-shadow: 0 30px 80px rgba(0,0,0,0.28);
                margin-bottom: 1rem;
            }
            .hero-inner {
                padding: 1.45rem 1.6rem 1.2rem 1.6rem;
                background:
                    radial-gradient(circle at 85% 0%, rgba(124,226,255,0.12), transparent 22%),
                    linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0));
            }
            .eyebrow {
                display: inline-flex; align-items: center; gap: 0.45rem;
                padding: 0.34rem 0.7rem; border-radius: 999px;
                background: rgba(255,255,255,0.05); border: 1px solid var(--border);
                color: var(--accent); font-size: 0.78rem; font-weight: 800;
                letter-spacing: 0.08em; text-transform: uppercase; margin-bottom: 0.8rem;
            }
            .hero-title { font-size: 2.6rem; line-height: 1; font-weight: 900; margin-bottom: 0.38rem; letter-spacing: -0.03em; }
            .hero-subtitle { max-width: 960px; font-size: 0.98rem; line-height: 1.6; color: var(--muted); }

            .top-band { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 0.85rem; margin-top: 1rem; }
            .stat-card {
                background: linear-gradient(180deg, rgba(18,36,61,0.98), rgba(11,21,37,0.98));
                border: 1px solid var(--border); border-radius: 22px; padding: 1rem; min-height: 116px;
                box-shadow: 0 12px 28px rgba(0,0,0,0.18);
            }
            .stat-label { color: var(--muted); font-size: 0.8rem; font-weight: 700; margin-bottom: 0.35rem; }
            .stat-value { color: var(--text); font-size: 1.65rem; font-weight: 900; line-height: 1.05; margin-bottom: 0.2rem; letter-spacing: -0.02em; }
            .stat-note { color: var(--muted); font-size: 0.82rem; line-height: 1.45; }

            .panel {
                background: linear-gradient(180deg, rgba(13,27,47,0.96), rgba(9,18,31,0.98));
                border: 1px solid var(--border); border-radius: 24px; padding: 1rem 1rem 1.05rem;
                box-shadow: 0 14px 34px rgba(0,0,0,0.16);
            }
            .section-kicker { color: var(--accent); font-size: 0.77rem; font-weight: 800; letter-spacing: 0.08em; text-transform: uppercase; margin-bottom: 0.22rem; }
            .section-title { color: var(--text); font-size: 1.12rem; font-weight: 800; margin-bottom: 0.18rem; }
            .section-copy { color: var(--muted); font-size: 0.88rem; line-height: 1.5; margin-bottom: 0.72rem; }
            .note { color: var(--muted); font-size: 0.82rem; line-height: 1.48; }

            [data-testid="stSidebar"] {
                background: linear-gradient(180deg, rgba(9,18,31,1), rgba(7,16,28,1));
                border-right: 1px solid var(--border);
            }
            [data-testid="stSidebar"] * { color: var(--text) !important; }
            [data-testid="stSidebar"] .stMarkdown p { color: var(--muted) !important; }
            [data-testid="stDataFrame"] { border: 1px solid var(--border); border-radius: 18px; overflow: hidden; }

            /* Fix all dropdown/select contrast, including opened menus */
            div[data-baseweb="select"] > div,
            .stSelectbox div[data-baseweb="select"] > div,
            .stMultiSelect div[data-baseweb="select"] > div,
            div[data-baseweb="input"] > div,
            div[data-baseweb="input"] input,
            div[data-baseweb="select"] input,
            div[data-baseweb="tag"],
            div[data-baseweb="tag"] span,
            div[data-baseweb="tag"] svg,
            .stNumberInput div[data-baseweb="input"] > div,
            .stTextInput div[data-baseweb="input"] > div,
            .stTextInput input,
            .stMultiSelect span,
            .stSelectbox span {
                background: var(--surface-light) !important;
                color: var(--surface-dark-text) !important;
                border-color: rgba(0,0,0,0.08) !important;
                font-weight: 700 !important;
            }
            div[data-baseweb="select"] * {
                color: var(--surface-dark-text) !important;
            }
            div[data-baseweb="popover"],
            div[data-baseweb="popover"] *,
            div[data-baseweb="menu"],
            div[data-baseweb="menu"] *,
            ul[role="listbox"],
            ul[role="listbox"] *,
            li[role="option"],
            div[role="option"] {
                background: #f7fbff !important;
                color: var(--surface-dark-text) !important;
                font-weight: 700 !important;
            }
            li[role="option"]:hover,
            div[role="option"]:hover,
            li[role="option"][aria-selected="true"],
            div[role="option"][aria-selected="true"] {
                background: #d8ebff !important;
                color: var(--surface-dark-text) !important;
            }
            .stMultiSelect label,
            .stSelectbox label,
            .stNumberInput label,
            .stSlider label,
            .stToggle label,
            .stRadio label,
            .stCheckbox label {
                color: var(--text) !important;
                font-weight: 700 !important;
            }

            .stSlider [data-baseweb="slider"] > div > div > div { background: var(--accent-2) !important; }
            .stSlider [role="slider"] {
                background: var(--surface-light) !important;
                border: 2px solid #c8f7ff !important;
                box-shadow: 0 0 0 4px rgba(124,226,255,0.15);
            }
            .stSlider [data-testid="stTickBarMin"],
            .stSlider [data-testid="stTickBarMax"],
            .stSlider [data-testid="stWidgetLabel"] + div,
            .stSlider span { color: var(--surface-dark-text-2) !important; }

            .stDownloadButton button,
            .stButton button,
            .stLinkButton a {
                background: linear-gradient(180deg, #9beeff, #6eddff) !important;
                border: 1px solid rgba(0,0,0,0.08) !important;
                border-radius: 12px !important;
                padding: 0.58rem 0.9rem !important;
                color: #07111f !important;
                font-weight: 800 !important;
                text-decoration: none !important;
                text-align: center !important;
                box-shadow: none !important;
            }
            .watch-wrap .stButton button {
                background: linear-gradient(180deg, #b8fff0, #6bf0c9) !important;
                color: #052018 !important;
            }
            .pool-wrap .stLinkButton a {
                background: linear-gradient(180deg, #ffe9a8, #ffd366) !important;
                color: #332100 !important;
            }

            .stTabs [data-baseweb="tab-list"] {
                gap: 0.45rem; background: rgba(255,255,255,0.02); padding: 0.3rem;
                border-radius: 16px; border: 1px solid var(--border);
            }
            .stTabs [data-baseweb="tab"] {
                height: 44px; border-radius: 12px; color: var(--muted) !important;
                font-weight: 800; padding-left: 1rem; padding-right: 1rem;
            }
            .stTabs [aria-selected="true"] {
                background: linear-gradient(180deg, rgba(124,226,255,0.18), rgba(124,226,255,0.08));
                color: var(--text) !important;
            }

            .badge-row { display: flex; flex-wrap: wrap; gap: 0.45rem; margin-top: 0.65rem; margin-bottom: 0.65rem; }
            .badge {
                display: inline-flex; align-items: center; gap: 0.35rem; border-radius: 999px; padding: 0.35rem 0.7rem;
                background: var(--surface-light-2); border: 1px solid rgba(0,0,0,0.05); color: #1c2a3d;
                font-size: 0.76rem; font-weight: 800;
            }
            .opp-card {
                border: 1px solid var(--border); border-radius: 22px; padding: 1rem;
                background: linear-gradient(180deg, rgba(17,34,57,0.98), rgba(9,18,31,0.98));
                box-shadow: 0 12px 28px rgba(0,0,0,0.16); min-height: 265px;
            }
            .opp-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 0.75rem; margin-bottom: 0.75rem; }
            .opp-name { font-size: 1.05rem; font-weight: 900; line-height: 1.15; }
            .opp-sub { color: var(--muted); font-size: 0.84rem; margin-top: 0.18rem; }
            .protocol-dot {
                width: 44px; height: 44px; border-radius: 14px; display: inline-flex; align-items: center; justify-content: center;
                background: linear-gradient(180deg, rgba(124,226,255,0.24), rgba(94,199,255,0.14));
                border: 1px solid rgba(124,226,255,0.16); font-weight: 900; color: white; font-size: 1rem;
            }
            .metric-strip { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0.65rem; margin-top: 0.75rem; }
            .metric-box {
                border-radius: 16px; padding: 0.72rem; background: #f7f9fd; border: 1px solid rgba(0,0,0,0.05);
            }
            .metric-mini-label { color: #66748b; font-size: 0.72rem; font-weight: 700; margin-bottom: 0.18rem; }
            .metric-mini-value { color: #1f2937; font-size: 1rem; font-weight: 900; }
            .watch-pill {
                display: inline-flex; align-items: center; gap: 0.35rem; border-radius: 999px; padding: 0.25rem 0.6rem;
                background: rgba(53,212,154,0.12); color: #caffec; font-size: 0.74rem; font-weight: 800;
                border: 1px solid rgba(53,212,154,0.18);
            }
            .signal-card, .watch-card {
                border-radius: 20px; border: 1px solid var(--border); background: rgba(255,255,255,0.03); padding: 0.9rem;
                margin-bottom: 0.7rem;
            }
            .signal-title { font-weight: 800; margin-bottom: 0.25rem; }
            .signal-copy { color: var(--muted); font-size: 0.84rem; line-height: 1.48; }
            .arb-pill { display: inline-flex; align-items: center; border-radius: 999px; padding: 0.22rem 0.55rem; font-size: 0.72rem; font-weight: 800; background: rgba(243,193,95,0.14); color: #ffe08f; border: 1px solid rgba(243,193,95,0.2); }
            .tiny { color: var(--muted); font-size: 0.76rem; }

            @media (max-width: 1180px) { .top-band { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
            @media (max-width: 760px) { .top-band { grid-template-columns: repeat(1, minmax(0, 1fr)); } .hero-title { font-size: 2.05rem; } }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data(ttl=900, show_spinner=False)
def fetch_pools() -> pd.DataFrame:
    urls = [
        "https://yields.llama.fi/pools",
        "https://stablecoins.llama.fi/yields/pools",
    ]
    errors: list[str] = []
    for url in urls:
        try:
            response = requests.get(url, timeout=TIMEOUT)
            response.raise_for_status()
            payload = response.json()
            rows = payload.get("data", payload)
            df = pd.DataFrame(rows)
            if not df.empty:
                return df
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    return sample_pool_data(errors)


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_pool_chart(pool_id: str) -> pd.DataFrame:
    urls = [
        f"https://yields.llama.fi/chart/{pool_id}",
        f"https://yields.llama.fi/chartLendBorrow/{pool_id}",
    ]
    for url in urls:
        try:
            response = requests.get(url, timeout=TIMEOUT)
            response.raise_for_status()
            payload = response.json()
            rows = payload.get("data", payload)
            chart = pd.DataFrame(rows)
            if chart.empty:
                continue
            if "timestamp" in chart.columns:
                chart["timestamp"] = pd.to_datetime(chart["timestamp"], errors="coerce", unit="s")
                if chart["timestamp"].isna().all():
                    chart["timestamp"] = pd.to_datetime(chart["timestamp"], errors="coerce")
            elif "date" in chart.columns:
                chart["timestamp"] = pd.to_datetime(chart["date"], errors="coerce")
            else:
                continue
            chart = chart.dropna(subset=["timestamp"]).sort_values("timestamp")
            for col in ["apy", "apyBase", "apyReward", "tvlUsd"]:
                if col not in chart.columns:
                    chart[col] = 0.0
                chart[col] = pd.to_numeric(chart[col], errors="coerce").fillna(0.0)
            return chart[["timestamp", "apy", "apyBase", "apyReward", "tvlUsd"]].copy()
        except Exception:
            continue
    return pd.DataFrame()


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_signal_snapshots(pool_ids: tuple[str, ...]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    pool_ids = tuple(str(p) for p in pool_ids[:SIGNAL_SAMPLE])
    if not pool_ids:
        return pd.DataFrame()

    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(fetch_pool_chart, pid): pid for pid in pool_ids}
        for future in as_completed(futures):
            pool_id = futures[future]
            try:
                chart = future.result()
            except Exception:
                chart = pd.DataFrame()
            if chart.empty:
                continue
            rows.append(derive_chart_signal(pool_id, chart))

    return pd.DataFrame(rows)


def derive_chart_signal(pool_id: str, chart: pd.DataFrame) -> dict[str, Any]:
    recent = chart.dropna(subset=["timestamp"]).sort_values("timestamp").tail(30).copy()
    if recent.empty:
        return {"pool": pool_id}
    recent["apy_change"] = recent["apy"].pct_change().replace([float("inf"), float("-inf")], 0).fillna(0)
    recent["tvl_change"] = recent["tvlUsd"].pct_change().replace([float("inf"), float("-inf")], 0).fillna(0)
    apy_last = float(recent["apy"].iloc[-1])
    apy_prev = float(recent["apy"].iloc[max(0, len(recent) - 8)])
    tvl_last = float(recent["tvlUsd"].iloc[-1])
    tvl_prev = float(recent["tvlUsd"].iloc[max(0, len(recent) - 8)])
    apy_delta = apy_last - apy_prev
    tvl_delta_pct = ((tvl_last - tvl_prev) / tvl_prev * 100) if tvl_prev > 0 else 0.0
    apy_vol = float(recent["apy_change"].std() * 100) if len(recent) > 3 else 0.0

    signal = "Steady"
    if apy_delta > 18:
        signal = "APY spike"
    elif tvl_delta_pct > 25 and apy_last > 8:
        signal = "Whale inflow"
    elif apy_delta > 8 and tvl_delta_pct > 10:
        signal = "Emerging pool"
    elif apy_delta < -12 and tvl_delta_pct < -10:
        signal = "Farm rotation"

    return {
        "pool": pool_id,
        "signal": signal,
        "apy_delta_7": round(apy_delta, 2),
        "tvl_delta_7_pct": round(tvl_delta_pct, 2),
        "apy_volatility": round(apy_vol, 2),
    }


@st.cache_data(show_spinner=False)
def enrich(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy()

    for column in ["apy", "apyBase", "apyReward", "tvlUsd", "volumeUsd1d", "volumeUsd7d"]:
        if column not in data.columns:
            data[column] = 0.0
        data[column] = pd.to_numeric(data[column], errors="coerce").fillna(0.0)

    for col in ["chain", "project", "symbol", "poolMeta", "exposure", "pool"]:
        if col not in data.columns:
            data[col] = "Unknown"
        data[col] = data[col].fillna("Unknown").astype(str)

    if "stablecoin" not in data.columns:
        data["stablecoin"] = data["symbol"].str.contains("USDC|USDT|DAI|FRAX|USD|USDe", case=False, na=False)
    data["stablecoin"] = data["stablecoin"].fillna(False)

    data["strategy_type"] = data["poolMeta"].replace({"Unknown": "General", "": "General"})
    data["project_key"] = data["project"].str.lower().str.strip()
    data["protocol_age_score"] = data["project_key"].apply(lambda x: protocol_meta(x, "age", 58))
    data["audit_score"] = data["project_key"].apply(lambda x: protocol_meta(x, "audit", 60))
    data["protocol_badge"] = data["project_key"].apply(lambda x: protocol_meta(x, "brand", badge_from_project(x)))
    data["protocol_tier"] = data["project_key"].apply(lambda x: protocol_meta(x, "tier", "Watch"))
    data["tvl_stability_score"] = data["tvlUsd"].apply(score_tvl_stability)
    data["pool_volatility_score"] = data.apply(score_pool_volatility, axis=1)
    data["risk_score"] = data.apply(score_pool, axis=1)
    data["risk_band"] = data["risk_score"].apply(label_risk)
    data["pool_url"] = data.apply(build_pool_url, axis=1)
    data["scorecard"] = data.apply(build_scorecard, axis=1)
    data["watch_label"] = data.apply(lambda row: f"{row['project']} • {row['symbol']} • {row['chain']} • {row['apy']:.2f}%", axis=1)
    data["rank_score"] = (
        data["apy"].clip(lower=0, upper=80) * 0.68
        + (data["tvlUsd"].clip(lower=0).rank(pct=True) * 18)
        + (data["audit_score"] * 0.06)
        + (data["protocol_age_score"] * 0.04)
        - (data["risk_score"] * 0.42)
    )
    data = data.sort_values(["rank_score", "apy", "tvlUsd"], ascending=[False, False, False])
    return data


def protocol_meta(project_key: str, field: str, default: Any) -> Any:
    if project_key in PROTOCOL_META:
        return PROTOCOL_META[project_key].get(field, default)
    for key, meta in PROTOCOL_META.items():
        if key in project_key:
            return meta.get(field, default)
    return default


def badge_from_project(project: str) -> str:
    parts = [p for p in str(project).replace("_", "-").split("-") if p]
    letters = "".join(part[0] for part in parts[:2]).upper()
    return letters[:2] if letters else "??"


def score_tvl_stability(tvl: float) -> int:
    tvl = float(tvl or 0)
    if tvl >= 1_000_000_000:
        return 95
    if tvl >= 250_000_000:
        return 86
    if tvl >= 100_000_000:
        return 78
    if tvl >= 25_000_000:
        return 65
    if tvl >= 10_000_000:
        return 54
    if tvl >= 1_000_000:
        return 38
    return 24


def score_pool_volatility(row: pd.Series) -> int:
    apy = float(row.get("apy", 0) or 0)
    rewards = float(row.get("apyReward", 0) or 0)
    stablecoin = bool(row.get("stablecoin", False))
    exposure = str(row.get("exposure", "")).lower()
    strategy = str(row.get("poolMeta", "")).lower()
    vol = 22
    if apy > 120:
        vol += 42
    elif apy > 60:
        vol += 28
    elif apy > 25:
        vol += 14
    if rewards > 10:
        vol += 10
    if not stablecoin:
        vol += 8
    if exposure in {"multi", "lp"}:
        vol += 6
    if any(word in strategy for word in ["farm", "loop", "lever", "dex", "vault"]):
        vol += 8
    return max(5, min(100, int(round(vol))))


def score_pool(row: pd.Series) -> int:
    apy = float(row.get("apy", 0) or 0)
    tvl_stability = int(row.get("tvl_stability_score", 50) or 50)
    audit = int(row.get("audit_score", 55) or 55)
    age = int(row.get("protocol_age_score", 55) or 55)
    volatility = int(row.get("pool_volatility_score", 45) or 45)
    stablecoin = bool(row.get("stablecoin", False))
    rewards = float(row.get("apyReward", 0) or 0)

    risk = 58
    risk += max(0, min(28, apy / 5))
    risk += max(0, min(12, rewards / 2))
    risk += (100 - tvl_stability) * 0.22
    risk += (100 - audit) * 0.18
    risk += (100 - age) * 0.10
    risk += volatility * 0.22
    if stablecoin:
        risk -= 8
    return max(1, min(100, int(round(risk))))


def label_risk(score: int) -> str:
    if score <= 28:
        return "Low"
    if score <= 45:
        return "Moderate"
    if score <= 65:
        return "High"
    return "Speculative"


def build_pool_url(row: pd.Series) -> str:
    pool = row.get("pool", "")
    if isinstance(pool, str) and pool and pool != "Unknown":
        return f"https://defillama.com/yields/pool/{pool}"
    return "https://defillama.com/yields"


def build_scorecard(row: pd.Series) -> str:
    parts = []
    parts.append("Stable" if row.get("stablecoin", False) else "Directional")
    parts.append("Deep TVL" if float(row.get("tvlUsd", 0) or 0) >= 100_000_000 else "Lighter TVL")
    parts.append(label_risk(int(row.get("risk_score", 50))))
    return " • ".join(parts)


def sample_pool_data(errors: list[str]) -> pd.DataFrame:
    demo = pd.DataFrame(
        [
            {"pool": "demo-1", "chain": "Ethereum", "project": "aave-v3", "symbol": "USDC", "tvlUsd": 1450000000, "apy": 4.18, "apyBase": 3.61, "apyReward": 0.57, "poolMeta": "Lending", "exposure": "single", "stablecoin": True, "volumeUsd1d": 25000000},
            {"pool": "demo-2", "chain": "Arbitrum", "project": "camelot-v3", "symbol": "ETH-USDC", "tvlUsd": 23800000, "apy": 22.40, "apyBase": 10.10, "apyReward": 12.30, "poolMeta": "LP", "exposure": "multi", "stablecoin": False, "volumeUsd1d": 8200000},
            {"pool": "demo-3", "chain": "Base", "project": "morpho-v1", "symbol": "USDC", "tvlUsd": 980000000, "apy": 7.02, "apyBase": 6.22, "apyReward": 0.80, "poolMeta": "Lending", "exposure": "single", "stablecoin": True, "volumeUsd1d": 17000000},
            {"pool": "demo-4", "chain": "Sonic", "project": "beefy", "symbol": "wS-ETH", "tvlUsd": 8600000, "apy": 29.8, "apyBase": 9.6, "apyReward": 20.2, "poolMeta": "Farm", "exposure": "multi", "stablecoin": False, "volumeUsd1d": 2100000},
            {"pool": "demo-5", "chain": "Base", "project": "hyperliquid-vault", "symbol": "USDC", "tvlUsd": 8440000, "apy": 263.86, "apyBase": 15.2, "apyReward": 248.6, "poolMeta": "Vault", "exposure": "single", "stablecoin": True, "volumeUsd1d": 930000},
        ]
    )
    demo.attrs["errors"] = errors
    return demo


def format_money(value: float) -> str:
    value = float(value or 0)
    abs_value = abs(value)
    if abs_value >= 1_000_000_000:
        return f"${value/1_000_000_000:,.2f}B"
    if abs_value >= 1_000_000:
        return f"${value/1_000_000:,.2f}M"
    if abs_value >= 1_000:
        return f"${value/1_000:,.1f}K"
    return f"${value:,.0f}"


def stat_card(label: str, value: str, note: str) -> None:
    st.markdown(f"<div class='stat-card'><div class='stat-label'>{label}</div><div class='stat-value'>{value}</div><div class='stat-note'>{note}</div></div>", unsafe_allow_html=True)


def section_header(kicker: str, title: str, copy: str) -> None:
    st.markdown(f"<div class='section-kicker'>{kicker}</div><div class='section-title'>{title}</div><div class='section-copy'>{copy}</div>", unsafe_allow_html=True)


def compact_table(df: pd.DataFrame) -> pd.DataFrame:
    table = df[[
        "project", "chain", "symbol", "strategy_type", "apy", "apyBase", "apyReward", "tvlUsd", "risk_score", "signal", "pool_url"
    ]].rename(columns={
        "project": "Protocol", "chain": "Chain", "symbol": "Asset", "strategy_type": "Strategy", "apy": "APY", "apyBase": "Base", "apyReward": "Rewards", "tvlUsd": "TVL (USD)", "risk_score": "Risk", "signal": "Signal", "pool_url": "Open"
    })
    return table


def make_download_df(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["project", "chain", "symbol", "strategy_type", "apy", "apyBase", "apyReward", "tvlUsd", "volumeUsd1d", "risk_score", "risk_band", "signal", "audit_score", "protocol_age_score", "tvl_stability_score", "pool_volatility_score", "pool_url"]
    return df[[c for c in cols if c in df.columns]].copy()


def plotly_theme(fig: go.Figure, height: int = 380) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=10, r=10, t=20, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#eef4ff", family="Inter, Segoe UI, sans-serif"),
        legend=dict(bgcolor="rgba(0,0,0,0)", orientation="h", yanchor="bottom", y=1.02, x=0),
        xaxis=dict(gridcolor="rgba(255,255,255,0.08)", zeroline=False),
        yaxis=dict(gridcolor="rgba(255,255,255,0.08)", zeroline=False),
    )
    return fig


def top_n_summary(df: pd.DataFrame, group_col: str, n: int = 10) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    return (
        df.groupby(group_col, as_index=False)
        .agg(total_tvl=("tvlUsd", "sum"), median_apy=("apy", "median"), pools=("pool", "count"), avg_risk=("risk_score", "mean"))
        .sort_values("total_tvl", ascending=False)
        .head(n)
    )


def find_arbitrage_candidates(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    clean = df.copy()
    clean["asset_key"] = clean["symbol"].str.upper().str.replace(" ", "", regex=False)
    grouped = clean.groupby("asset_key")
    rows = []
    for asset, sub in grouped:
        chains = sub["chain"].nunique()
        if chains < 2 or len(sub) < 2:
            continue
        top = sub.sort_values("apy", ascending=False).head(1).iloc[0]
        low = sub.sort_values("apy", ascending=True).head(1).iloc[0]
        diff = float(top["apy"] - low["apy"])
        if diff >= 3:
            rows.append({
                "Asset": asset,
                "Best chain": top["chain"],
                "Best protocol": top["project"],
                "Best APY": float(top["apy"]),
                "Cheaper chain": low["chain"],
                "Cheaper protocol": low["project"],
                "Lower APY": float(low["apy"]),
                "APY difference": diff,
            })
    return pd.DataFrame(rows).sort_values("APY difference", ascending=False).head(25) if rows else pd.DataFrame()


def render_opportunity_card(row: pd.Series, idx: int, watched: bool) -> None:
    signal = row.get("signal", "Steady")
    st.markdown(
        f"""
        <div class="opp-card">
            <div class="opp-top">
                <div>
                    <div class="opp-name">{row['project']}</div>
                    <div class="opp-sub">{row['symbol']} • {row['chain']}</div>
                </div>
                <div class="protocol-dot">{row['protocol_badge']}</div>
            </div>
            {'<span class="watch-pill">★ Watched</span>' if watched else ''}
            <div class="badge-row">
                <span class="badge">{row['strategy_type']}</span>
                <span class="badge">{row['risk_band']} risk</span>
                <span class="badge">{row['scorecard']}</span>
                <span class="badge">{signal}</span>
            </div>
            <div class="metric-strip">
                <div class="metric-box"><div class="metric-mini-label">APY</div><div class="metric-mini-value">{row['apy']:.2f}%</div></div>
                <div class="metric-box"><div class="metric-mini-label">TVL</div><div class="metric-mini-value">{format_money(row['tvlUsd'])}</div></div>
                <div class="metric-box"><div class="metric-mini-label">Risk</div><div class="metric-mini-value">{int(row['risk_score'])}/100</div></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("<div class='watch-wrap'>", unsafe_allow_html=True)
        label = "Remove" if watched else "Watch"
        if st.button(label, key=f"watch_{idx}", use_container_width=True):
            if watched:
                st.session_state.watchlist = [p for p in st.session_state.watchlist if p != row["pool"]]
            else:
                st.session_state.watchlist = list(dict.fromkeys(st.session_state.watchlist + [row["pool"]]))
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
    with c2:
        st.markdown("<div class='pool-wrap'>", unsafe_allow_html=True)
        st.link_button("Open Pool", row["pool_url"], use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)


inject_css()
raw_df = fetch_pools()
df = enrich(raw_df)

if "watchlist" not in st.session_state:
    st.session_state.watchlist = []

signal_source = filtered_signal_pool_ids = tuple(df.head(SIGNAL_SAMPLE)["pool"].tolist())
signal_df = fetch_signal_snapshots(filtered_signal_pool_ids)
if not signal_df.empty:
    df = df.merge(signal_df, on="pool", how="left")
for col, default in [("signal", "Steady"), ("apy_delta_7", 0.0), ("tvl_delta_7_pct", 0.0), ("apy_volatility", 0.0)]:
    if col not in df.columns:
        df[col] = default
    df[col] = df[col].fillna(default)

st.markdown(
    f"""
    <section class="hero-shell"><div class="hero-inner">
        <div class="eyebrow">DeFi yield workstation • v6</div>
        <div class="hero-title">{APP_NAME}</div>
        <div class="hero-subtitle">{APP_TAGLINE}. This build adds fully readable dropdowns and action buttons, cleaner pool bubbles, richer scanner cards, a stronger watchlist layer, same-asset cross-chain arbitrage detection, smarter risk scoring, and a first-pass signal engine for APY spikes, farm rotations, emerging pools, and whale inflows.</div>
    </div></section>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown(f"## {APP_NAME} v6")
    st.markdown("Shape the scanner, then inspect the signal and arbitrage layers.")

    chains = sorted(df["chain"].dropna().unique().tolist())
    projects = sorted(df["project"].dropna().unique().tolist())
    strategies = sorted(df["strategy_type"].dropna().unique().tolist())
    signals = sorted(df["signal"].dropna().unique().tolist())

    selected_chains = st.multiselect("Chains", chains, default=chains[: min(len(chains), 8)])
    selected_projects = st.multiselect("Protocols", projects)
    selected_strategies = st.multiselect("Strategy type", strategies)
    selected_signals = st.multiselect("Signal filter", signals)
    stable_only = st.toggle("Stablecoin pools only", value=False)
    min_tvl = st.slider("Minimum TVL", min_value=0, max_value=500_000_000, value=5_000_000, step=1_000_000)
    max_risk = st.slider("Maximum risk score", min_value=1, max_value=100, value=70)
    min_apy = st.slider("Minimum APY", min_value=0.0, max_value=250.0, value=0.0, step=0.5)
    sort_by = st.selectbox("Sort by", ["FuruFlow rank", "Highest APY", "Largest TVL", "Lowest risk", "Highest 24h volume", "Largest signal move"], index=0)
    st.markdown("<div class='note'>Risk score is heuristic. It blends protocol age, TVL stability, audit confidence, reward dependence, and inferred pool volatility. Signal labels come from recent pool-chart moves when chart data is available.</div>", unsafe_allow_html=True)

filtered = df.copy()
if selected_chains:
    filtered = filtered[filtered["chain"].isin(selected_chains)]
if selected_projects:
    filtered = filtered[filtered["project"].isin(selected_projects)]
if selected_strategies:
    filtered = filtered[filtered["strategy_type"].isin(selected_strategies)]
if selected_signals:
    filtered = filtered[filtered["signal"].isin(selected_signals)]
if stable_only:
    filtered = filtered[filtered["stablecoin"] == True]

filtered = filtered[(filtered["tvlUsd"] >= min_tvl) & (filtered["risk_score"] <= max_risk) & (filtered["apy"] >= min_apy)]

if sort_by == "Highest APY":
    filtered = filtered.sort_values(["apy", "tvlUsd"], ascending=[False, False])
elif sort_by == "Largest TVL":
    filtered = filtered.sort_values(["tvlUsd", "apy"], ascending=[False, False])
elif sort_by == "Lowest risk":
    filtered = filtered.sort_values(["risk_score", "apy", "tvlUsd"], ascending=[True, False, False])
elif sort_by == "Highest 24h volume":
    filtered = filtered.sort_values(["volumeUsd1d", "apy"], ascending=[False, False])
elif sort_by == "Largest signal move":
    filtered = filtered.sort_values(["apy_delta_7", "tvl_delta_7_pct"], ascending=[False, False])
else:
    filtered = filtered.sort_values(["rank_score", "apy", "tvlUsd"], ascending=[False, False, False])

filtered = filtered.head(POOL_LIMIT)
watchlist_df = df[df["pool"].isin(st.session_state.watchlist)].copy()

visible = len(filtered)
median_apy = filtered["apy"].median() if visible else 0.0
total_tvl = filtered["tvlUsd"].sum() if visible else 0.0
signal_share = (filtered["signal"].ne("Steady").mean() * 100) if visible else 0.0
arb_df = find_arbitrage_candidates(filtered)

metric_cols = st.columns(5)
with metric_cols[0]: stat_card("Visible opportunities", f"{visible:,}", "Pools left after your current filters")
with metric_cols[1]: stat_card("Median APY", f"{median_apy:,.2f}%", "A steadier center of the current market slice")
with metric_cols[2]: stat_card("Aggregate TVL", format_money(total_tvl), "Combined depth across visible pools")
with metric_cols[3]: stat_card("Signal density", f"{signal_share:,.0f}%", "Pools with non-steady signal labels")
with metric_cols[4]: stat_card("Watchlist", f"{len(watchlist_df):,}", "Pools you marked for repeat tracking")

main_tab, signal_tab, market_tab, drill_tab, watch_tab = st.tabs(["Scanner", "Signals", "Market map", "Pool drilldown", "Watchlist"])

with main_tab:
    left, right = st.columns([1.6, 1], gap="large")
    with left:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Scanner", "Custom scan view", "The scanner now behaves more like a product surface: richer cards up top, cleaner table below, and stronger controls that stay readable.")
        top_cards = filtered.head(6)
        for start in range(0, len(top_cards), 3):
            cols = st.columns(3, gap="medium")
            for i, (_, row) in enumerate(top_cards.iloc[start:start+3].iterrows()):
                with cols[i]:
                    render_opportunity_card(row, start + i, row["pool"] in st.session_state.watchlist)
        st.markdown("<div style='height:0.4rem;'></div>", unsafe_allow_html=True)
        table_df = compact_table(filtered)
        st.dataframe(
            table_df,
            use_container_width=True,
            hide_index=True,
            height=520,
            column_config={
                "APY": st.column_config.NumberColumn(format="%.2f%%", width="small"),
                "Base": st.column_config.NumberColumn(format="%.2f%%", width="small"),
                "Rewards": st.column_config.NumberColumn(format="%.2f%%", width="small"),
                "TVL (USD)": st.column_config.NumberColumn(format="$%.0f", width="medium"),
                "Risk": st.column_config.NumberColumn(width="small"),
                "Open": st.column_config.LinkColumn("Pool link", display_text="Open"),
            },
        )
        csv = make_download_df(filtered).to_csv(index=False).encode("utf-8")
        st.download_button("Download current table as CSV", csv, file_name="furuflow_scanner_v6.csv", mime="text/csv")
        st.markdown("</div>", unsafe_allow_html=True)

    with right:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Cross-chain edge", "Live arbitrage detection", "This compares the same asset across different chains and highlights APY spreads that may be worth routing into deeper research.")
        if arb_df.empty:
            st.info("No strong same-asset cross-chain APY spreads were found in the current filtered set.")
        else:
            st.dataframe(
                arb_df,
                use_container_width=True,
                hide_index=True,
                height=255,
                column_config={"Best APY": st.column_config.NumberColumn(format="%.2f%%"), "Lower APY": st.column_config.NumberColumn(format="%.2f%%"), "APY difference": st.column_config.NumberColumn(format="%.2f%%")},
            )
        signal_counts = filtered["signal"].value_counts().reset_index()
        signal_counts.columns = ["Signal", "Count"]
        if not signal_counts.empty:
            bar = px.bar(signal_counts, x="Signal", y="Count")
            st.plotly_chart(plotly_theme(bar, 250), use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

with signal_tab:
    left, right = st.columns([1.15, 1], gap="large")
    with left:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Signal engine", "Yield trend AI layer", "These labels are rules-based signals drawn from recent APY and TVL movement on the pool chart endpoint, meant to surface where to look next.")
        sig_view = filtered[["project", "chain", "symbol", "signal", "apy_delta_7", "tvl_delta_7_pct", "apy_volatility"]].copy().head(18)
        sig_view.columns = ["Protocol", "Chain", "Asset", "Signal", "7d APY Δ", "7d TVL Δ %", "APY volatility"]
        st.dataframe(sig_view, use_container_width=True, hide_index=True, height=520, column_config={"7d APY Δ": st.column_config.NumberColumn(format="%.2f"), "7d TVL Δ %": st.column_config.NumberColumn(format="%.2f"), "APY volatility": st.column_config.NumberColumn(format="%.2f")})
        st.markdown("</div>", unsafe_allow_html=True)
    with right:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("What the signal labels mean", "Operator guidance", "Use these labels as triage, not certainty.")
        guides = [
            ("APY spike", "Yield jumped quickly. Check whether rewards, temporary emissions, or incentive campaigns are driving the move."),
            ("Farm rotation", "Yield and TVL both rolled over. Capital may be rotating out after emissions decayed or a newer farm launched."),
            ("Emerging pool", "APY is rising and TVL is arriving. This can be the sweet spot before a pool becomes crowded."),
            ("Whale inflow", "TVL jumped sharply in a short period. Larger deposits may be validating the venue or crowding the trade."),
        ]
        for title, copy in guides:
            st.markdown(f"<div class='signal-card'><div class='signal-title'>{title}</div><div class='signal-copy'>{copy}</div></div>", unsafe_allow_html=True)
        if not filtered.empty:
            sig_plot_df = filtered.groupby("signal", as_index=False).agg(avg_apy=("apy", "mean"), avg_tvl=("tvlUsd", "mean"))
            fig = px.scatter(sig_plot_df, x="avg_tvl", y="avg_apy", size="avg_tvl", color="signal", hover_name="signal", size_max=42, log_x=True)
            fig.update_xaxes(title="Average TVL")
            fig.update_yaxes(title="Average APY %")
            st.plotly_chart(plotly_theme(fig, 290), use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

with market_tab:
    left, right = st.columns([1, 1], gap="large")
    with left:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Market map", "Risk vs yield field", "A compact view of where the current opportunity set sits across APY, risk, and capital depth.")
        if not filtered.empty:
            bubble = px.scatter(filtered.head(85), x="risk_score", y="apy", size="tvlUsd", color="chain", hover_name="project", hover_data={"symbol": True, "tvlUsd": ':$,.0f', "risk_score": True, "apy": ':.2f'}, size_max=34)
            bubble.update_traces(marker=dict(line=dict(width=1, color="rgba(255,255,255,0.22)"), opacity=0.8))
            bubble.update_xaxes(title="Risk score")
            bubble.update_yaxes(title="APY %")
            st.plotly_chart(plotly_theme(bubble, 390), use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with right:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Protocol map", "Badges and leaders", "A cleaner side view of protocol depth, median APY, and risk profile.")
        top_protocols = top_n_summary(filtered, "project", 10)
        if not top_protocols.empty:
            top_protocols = top_protocols.rename(columns={"project": "Protocol", "total_tvl": "TVL (USD)", "median_apy": "Median APY", "pools": "Pools", "avg_risk": "Avg Risk"})
            st.dataframe(top_protocols, use_container_width=True, hide_index=True, height=245, column_config={"TVL (USD)": st.column_config.NumberColumn(format="$%.0f"), "Median APY": st.column_config.NumberColumn(format="%.2f%%"), "Avg Risk": st.column_config.NumberColumn(format="%.0f")})
            chain_df = filtered.groupby("chain", as_index=False).agg(total_tvl=("tvlUsd", "sum"), median_apy=("apy", "median"), pools=("pool", "count"))
            sun = px.treemap(chain_df, path=[px.Constant("Chains"), "chain"], values="total_tvl", color="median_apy", hover_data={"pools": True, "median_apy": ':.2f'})
            st.plotly_chart(plotly_theme(sun, 290), use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

with drill_tab:
    st.markdown("<div class='panel'>", unsafe_allow_html=True)
    section_header("Pool drilldown", "Open a single venue", "Inspect chart shape, risk factors, and watchlist actions without leaving the app.")
    pool_options = filtered.copy()
    pool_options["pool_pick"] = pool_options.apply(lambda r: f"{r['project']} • {r['symbol']} • {r['chain']}", axis=1)
    if pool_options.empty:
        st.info("No pools match the current filter set.")
    else:
        chosen = st.selectbox("Choose a Pool", pool_options["pool_pick"].tolist(), index=0)
        row = pool_options.loc[pool_options["pool_pick"] == chosen].iloc[0]
        cols = st.columns([1.3, 1], gap="large")
        with cols[0]:
            chart = fetch_pool_chart(str(row["pool"]))
            if not chart.empty:
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=chart["timestamp"], y=chart["apy"], mode="lines", name="APY"))
                if chart["tvlUsd"].gt(0).any():
                    fig.add_trace(go.Scatter(x=chart["timestamp"], y=chart["tvlUsd"], mode="lines", name="TVL", yaxis="y2"))
                    fig.update_layout(yaxis2=dict(overlaying="y", side="right", showgrid=False, title="TVL"))
                fig.update_xaxes(title="Time")
                fig.update_yaxes(title="APY %")
                st.plotly_chart(plotly_theme(fig, 420), use_container_width=True)
            else:
                st.info("Chart history is unavailable for this pool right now.")
        with cols[1]:
            st.markdown(f"<div class='signal-card'><div class='signal-title'>{row['project']} • {row['symbol']}</div><div class='signal-copy'>{row['chain']} • {row['strategy_type']} • {row['signal']}</div></div>", unsafe_allow_html=True)
            stats = pd.DataFrame([
                ["APY", f"{row['apy']:.2f}%"],
                ["TVL", format_money(row['tvlUsd'])],
                ["Risk", f"{int(row['risk_score'])}/100 ({row['risk_band']})"],
                ["Audit confidence", f"{int(row['audit_score'])}/100"],
                ["Protocol age", f"{int(row['protocol_age_score'])}/100"],
                ["TVL stability", f"{int(row['tvl_stability_score'])}/100"],
                ["Pool volatility", f"{int(row['pool_volatility_score'])}/100"],
                ["7d APY change", f"{float(row['apy_delta_7']):.2f}"],
                ["7d TVL change", f"{float(row['tvl_delta_7_pct']):.2f}%"],
            ], columns=["Metric", "Value"])
            st.dataframe(stats, use_container_width=True, hide_index=True, height=350)
            c1, c2 = st.columns(2)
            with c1:
                watched = row["pool"] in st.session_state.watchlist
                st.markdown("<div class='watch-wrap'>", unsafe_allow_html=True)
                if st.button("Remove from watchlist" if watched else "Add to watchlist", key="drill_watch", use_container_width=True):
                    if watched:
                        st.session_state.watchlist = [p for p in st.session_state.watchlist if p != row["pool"]]
                    else:
                        st.session_state.watchlist = list(dict.fromkeys(st.session_state.watchlist + [row["pool"]]))
                    st.rerun()
                st.markdown("</div>", unsafe_allow_html=True)
            with c2:
                st.markdown("<div class='pool-wrap'>", unsafe_allow_html=True)
                st.link_button("Open Pool", row["pool_url"], use_container_width=True)
                st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

with watch_tab:
    left, right = st.columns([1.2, 1], gap="large")
    with left:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Watchlist", "Tracked pools", "This is your lightweight conviction layer inside the scanner.")
        if watchlist_df.empty:
            st.info("Your watchlist is empty. Use Watch on any scanner card or pool drilldown panel.")
        else:
            view = watchlist_df[["project", "chain", "symbol", "apy", "tvlUsd", "risk_score", "signal"]].copy()
            view.columns = ["Protocol", "Chain", "Asset", "APY", "TVL (USD)", "Risk", "Signal"]
            st.dataframe(view, use_container_width=True, hide_index=True, height=440, column_config={"APY": st.column_config.NumberColumn(format="%.2f%%"), "TVL (USD)": st.column_config.NumberColumn(format="$%.0f")})
        st.markdown("</div>", unsafe_allow_html=True)
    with right:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Watchlist chart", "Where attention is concentrated", "The watchlist stays simple for now, but it already supports quick visual comparison.")
        if not watchlist_df.empty:
            fig = px.bar(watchlist_df.sort_values("apy", ascending=False), x="project", y="apy", color="risk_band", hover_data={"chain": True, "symbol": True, "tvlUsd": ':$,.0f'})
            fig.update_xaxes(title="Protocol")
            fig.update_yaxes(title="APY %")
            st.plotly_chart(plotly_theme(fig, 300), use_container_width=True)
            sig_counts = watchlist_df["signal"].value_counts().reset_index()
            sig_counts.columns = ["Signal", "Count"]
            st.dataframe(sig_counts, use_container_width=True, hide_index=True, height=180)
        else:
            st.info("Add a few pools to see watchlist comparisons.")
        st.markdown("</div>", unsafe_allow_html=True)
