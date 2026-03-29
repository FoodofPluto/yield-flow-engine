from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st
from streamlit.components.v1 import html as st_html

from auth import get_current_user, login_form, logout_button
from db import claim_session, clear_session, get_user_by_email, init_db, search_users, set_admin, set_lifetime_access, set_pro_active, touch_session, upsert_user
from entitlements import can_access_pro
from stripe_stub import render_checkout_section
from history_store import load_history, save_snapshot
from engine.performance import alert_snapshot, latest_signal_history, trend_summary_df
from engine.recap import build_daily_recap, build_weekly_recap

APP_NAME = "FuruFlow"
APP_VERSION = "v8.1"
APP_TAGLINE = "Find the smartest yields. Avoid the dumb ones."
POOL_LIMIT = 400
FREE_POOL_LIMIT = 10
FREE_SORT_OPTIONS = ["Highest APY", "Largest TVL"]
PRO_SORT_OPTIONS = ["FuruFlow rank", "Lowest risk", "Highest 24h volume", "Largest signal move"]
PAGE_OPTIONS = [
    "Home",
    "Scanner",
    "Signals",
    "Market Map",
    "Pool Explorer",
    "Watchlist",
    "Recaps",
    "Protocol Dashboard",
    "Strategy Builder",
    "Arbitrage",
]
PAGE_LABELS = {
    "Home": "🏠 Home",
    "Scanner": "🔎 Scanner",
    "Signals": "📡 Signals",
    "Market Map": "🗺️ Market Map",
    "Pool Explorer": "🧪 Pool Explorer",
    "Watchlist": "⭐ Watchlist",
    "Recaps": "📝 Recaps",
    "Protocol Dashboard": "🏛️ Protocol Dashboard",
    "Strategy Builder": "🧱 Strategy Builder",
    "Arbitrage": "⚡ Arbitrage",
}
TIMEOUT = 18
SIGNAL_SAMPLE = 16
WATCHLIST_FILE = Path(__file__).with_name("watchlist.json")
FURUFLOW_STRIPE_LINK = os.getenv("FURUFLOW_STRIPE_LINK", "https://buy.stripe.com/bJefZgcgmbYecju4ztd3i00")
AFFILIATE_LINKS = {
    "aave": "https://app.aave.com/?ref=furuflow",
    "aave-v3": "https://app.aave.com/?ref=furuflow",
    "pendle": "https://app.pendle.finance/trade/markets?ref=furuflow",
    "gmx": "https://app.gmx.io/#/?ref=furuflow",
    "curve": "https://curve.fi/#/ethereum/pools?ref=furuflow",
    "beefy": "https://app.beefy.com/?ref=furuflow",
    "yearn": "https://yearn.fi/?ref=furuflow",
    "morpho": "https://app.morpho.org/?ref=furuflow",
    "morpho-v1": "https://app.morpho.org/?ref=furuflow",
    "uniswap": "https://app.uniswap.org/?ref=furuflow",
    "uniswap-v3": "https://app.uniswap.org/?ref=furuflow",
}

UNISWAP_CHAIN_IDS = {
    "ethereum": 1,
    "polygon": 137,
    "optimism": 10,
    "arbitrum": 42161,
    "base": 8453,
    "avalanche": 43114,
}

GENERIC_DEX_URLS = {
    "https://app.uniswap.org",
    "https://app.uniswap.org/",
    "https://app.uniswap.org/?ref=furuflow",
    "https://uniswap.org",
    "https://uniswap.org/",
    "https://aerodrome.finance",
    "https://aerodrome.finance/",
    "https://app.merkl.xyz",
    "https://app.merkl.xyz/",
    "https://merkl.xyz",
    "https://merkl.xyz/",
}


def clean_value(value: Any) -> str:
    if value is None:
        return ""
    if pd.isna(value):
        return ""
    return str(value).strip()


def parse_pair_symbols(row: pd.Series) -> tuple[str, str]:
    for field in ("symbol", "underlyingTokens", "symbols"):
        raw = row.get(field)
        if isinstance(raw, list) and len(raw) >= 2:
            items = [clean_value(v) for v in raw if clean_value(v)]
            if len(items) >= 2:
                return items[0], items[1]

    symbol = clean_value(row.get("symbol"))
    if not symbol:
        return "", ""

    normalized = symbol.replace("-", "/").replace("_", "/").replace(":", "/")
    parts = [part.strip() for part in normalized.split("/") if part.strip()]
    if len(parts) >= 2:
        return parts[0], parts[1]
    return "", ""


def is_specific_url(url: str) -> bool:
    url = clean_value(url)
    if not (url.startswith("http://") or url.startswith("https://")):
        return False
    lower = url.lower().rstrip("/")
    return lower not in {u.rstrip("/") for u in GENERIC_DEX_URLS}


def build_protocol_deeplink(row: pd.Series) -> str:
    project_key = clean_value(row.get("project_key", row.get("project", ""))).lower()
    chain = clean_value(row.get("chain")).lower()
    token_a = clean_value(row.get("token0") or row.get("tokenA"))
    token_b = clean_value(row.get("token1") or row.get("tokenB"))

    if not token_a or not token_b:
        token_a, token_b = parse_pair_symbols(row)

    if "uniswap" in project_key:
        chain_id = UNISWAP_CHAIN_IDS.get(chain)
        if chain_id and token_a and token_b:
            return (
                "https://app.uniswap.org/positions/create/v3"
                f"?chain={chain_id}&currencyA={quote(token_a)}&currencyB={quote(token_b)}&ref=furuflow"
            )

    if "aerodrome" in project_key:
        pool_address = clean_value(row.get("poolMeta"))
        if pool_address and pool_address != "Unknown":
            return f"https://aerodrome.finance/liquidity?pool={quote(pool_address)}"
        return "https://aerodrome.finance/liquidity"

    if "merkl" in project_key:
        opportunity_id = clean_value(row.get("campaignId") or row.get("opportunityId"))
        if opportunity_id:
            return f"https://app.merkl.xyz/opportunities/{quote(opportunity_id)}"
        return "https://app.merkl.xyz/opportunities"

    return ""


def build_defillama_pool_url(row: pd.Series) -> str:
    for field in ("pool", "pool_id", "defillama_pool_id"):
        pool_value = clean_value(row.get(field))
        if pool_value and pool_value != "Unknown":
            return f"https://defillama.com/yields/pool/{quote(pool_value)}"
    return ""

st.set_page_config(
    page_title=APP_NAME,
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
                --bg: #06101d;
                --bg-2: #0a1527;
                --panel: rgba(13, 26, 45, 0.96);
                --panel-2: rgba(15, 30, 50, 0.98);
                --border: rgba(255,255,255,0.08);
                --text: #eef4ff;
                --muted: #aab8d4;
                --accent: #7ce2ff;
                --accent-2: #66d5ff;
                --good: #35d49a;
                --warn: #f1c96a;
                --bad: #ff7f8e;
                --surface-light: #f5f8ff;
                --surface-light-2: #e7f0ff;
                --surface-dark-text: #0d1a2b;
                --surface-dark-text-2: #23344a;
            }

            html, body, [class*="css"] {
                font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            }
            .stApp {
                color: var(--text);
                background:
                    radial-gradient(circle at 10% 0%, rgba(124,226,255,0.08), transparent 22%),
                    radial-gradient(circle at 90% 5%, rgba(78,137,255,0.08), transparent 24%),
                    linear-gradient(180deg, var(--bg) 0%, var(--bg-2) 100%);
            }
            .block-container {
                max-width: 1680px;
                padding-top: 1rem;
                padding-bottom: 2.2rem;
                padding-left: 1.35rem;
                padding-right: 1.35rem;
            }
            h1, h2, h3, h4, h5, h6, p, span, label, div {
                color: var(--text);
            }
            .hero-shell {
                border: 1px solid var(--border);
                border-radius: 30px;
                overflow: hidden;
                background: linear-gradient(150deg, rgba(17,32,54,0.98), rgba(8,15,26,0.98));
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
            .hero-title { font-size: 2.65rem; line-height: 1; font-weight: 900; margin-bottom: 0.38rem; letter-spacing: -0.03em; }
            .hero-subtitle { max-width: 1060px; font-size: 0.98rem; line-height: 1.6; color: var(--muted); }

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
            [data-testid="stSidebar"] [data-testid="stExpander"] {
                background: linear-gradient(180deg, rgba(255,255,255,0.035), rgba(255,255,255,0.02));
                border: 1px solid rgba(255,255,255,0.07);
                border-radius: 18px;
                overflow: hidden;
                margin-bottom: 0.75rem;
                box-shadow: inset 0 1px 0 rgba(255,255,255,0.025);
            }
            [data-testid="stSidebar"] [data-testid="stExpander"] details {
                background: transparent;
            }
            [data-testid="stSidebar"] [data-testid="stExpander"] summary {
                padding-top: 0.2rem;
                padding-bottom: 0.2rem;
            }
            [data-testid="stSidebar"] .sidebar-group-title {
                font-size: 0.73rem;
                font-weight: 900;
                letter-spacing: 0.11em;
                text-transform: uppercase;
                color: var(--accent) !important;
                margin-bottom: 0.28rem;
            }
            [data-testid="stSidebar"] .sidebar-group-copy {
                font-size: 0.8rem;
                line-height: 1.45;
                color: var(--muted) !important;
                margin-bottom: 0.45rem;
            }
            [data-testid="stSidebar"] .sidebar-mini-note {
                font-size: 0.74rem;
                line-height: 1.45;
                color: var(--muted) !important;
                margin-top: 0.38rem;
            }
            [data-testid="stSidebar"] .sidebar-plan {
                border: 1px solid rgba(255,255,255,0.07);
                border-radius: 18px;
                padding: 0.9rem 0.95rem;
                background: linear-gradient(180deg, rgba(255,255,255,0.04), rgba(255,255,255,0.02));
                margin-top: 0.25rem;
            }
            [data-testid="stSidebar"] .stSelectbox > label,
            [data-testid="stSidebar"] .stMultiSelect > label,
            [data-testid="stSidebar"] .stSlider > label,
            [data-testid="stSidebar"] .stToggle > label {
                color: #f2f7ff !important;
                font-weight: 800 !important;
                font-size: 0.92rem !important;
            }
            [data-testid="stSidebar"] .stSlider p,
            [data-testid="stSidebar"] .stSlider span,
            [data-testid="stSidebar"] .stSlider div[data-testid="stTickBarMin"],
            [data-testid="stSidebar"] .stSlider div[data-testid="stTickBarMax"] {
                color: #d9e6fb !important;
                opacity: 1 !important;
            }
            [data-testid="stSidebar"] .stSlider [data-baseweb="slider"] {
                padding-top: 0.35rem;
                padding-bottom: 0.15rem;
            }
            [data-testid="stSidebar"] .stMultiSelect [data-baseweb="tag"] {
                border-radius: 999px !important;
                padding-left: 0.25rem !important;
                padding-right: 0.25rem !important;
            }
            [data-testid="stDataFrame"] { border: 1px solid var(--border); border-radius: 18px; overflow: hidden; }

            /* Fix all title boxes / dropdowns / tags */
            label, .stSelectbox label, .stMultiSelect label, .stSlider label, .stRadio label, .stCheckbox label, .stToggle label {
                color: var(--text) !important;
                font-weight: 800 !important;
            }
            div[data-baseweb="select"] > div,
            .stSelectbox div[data-baseweb="select"] > div,
            .stMultiSelect div[data-baseweb="select"] > div,
            .stSelectbox [data-baseweb="select"] div,
            .stMultiSelect [data-baseweb="select"] div,
            div[data-baseweb="input"] > div,
            div[data-baseweb="input"] input,
            div[data-baseweb="select"] input,
            div[data-baseweb="tag"],
            div[data-baseweb="tag"] span,
            .stNumberInput div[data-baseweb="input"] > div,
            .stTextInput div[data-baseweb="input"] > div,
            .stTextInput input,
            .stMultiSelect span,
            .stSelectbox span,
            .stMultiSelect p,
            .stSelectbox p,
            [data-baseweb="select"] svg {
                background: var(--surface-light) !important;
                color: var(--surface-dark-text) !important;
                fill: var(--surface-dark-text) !important;
                border-color: rgba(0,0,0,0.08) !important;
                font-weight: 800 !important;
            }
            div[data-baseweb="select"] *,
            div[data-baseweb="tag"] *,
            .stMultiSelect [data-baseweb="tag"] *,
            .stSelectbox [data-baseweb="select"] * {
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
                font-weight: 800 !important;
            }
            li[role="option"]:hover,
            div[role="option"]:hover,
            li[role="option"][aria-selected="true"],
            div[role="option"][aria-selected="true"] {
                background: #d8ebff !important;
                color: var(--surface-dark-text) !important;
            }

            .stSlider [data-baseweb="slider"] > div > div > div { background: var(--accent-2) !important; }
            .stSlider [role="slider"] {
                background: var(--surface-light) !important;
                border: 2px solid #c8f7ff !important;
                box-shadow: 0 0 0 4px rgba(124,226,255,0.15);
            }
            .stSlider span, .stSlider p { color: var(--surface-dark-text-2) !important; }

            .stDownloadButton button,
            .stButton button,
            .stLinkButton a {
                background: linear-gradient(180deg, #9beeff, #6eddff) !important;
                border: 1px solid rgba(0,0,0,0.08) !important;
                border-radius: 12px !important;
                padding: 0.58rem 0.9rem !important;
                color: #07111f !important;
                font-weight: 900 !important;
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
            .danger-wrap .stButton button {
                background: linear-gradient(180deg, #ffd6dc, #ff9aa8) !important;
                color: #3c0d16 !important;
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
                box-shadow: 0 12px 28px rgba(0,0,0,0.16); min-height: 295px;
            }
            .opp-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 0.75rem; margin-bottom: 0.75rem; }
            .opp-name { font-size: 1.05rem; font-weight: 900; line-height: 1.15; }
            .opp-sub { color: var(--muted); font-size: 0.84rem; margin-top: 0.18rem; }
            .protocol-dot {
                width: 46px; height: 46px; border-radius: 14px; display: inline-flex; align-items: center; justify-content: center;
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
            .signal-card, .watch-card, .mini-card {
                border-radius: 20px; border: 1px solid var(--border); background: rgba(255,255,255,0.03); padding: 0.9rem;
                margin-bottom: 0.7rem;
            }
            .signal-title { font-weight: 800; margin-bottom: 0.25rem; }
            .signal-copy { color: var(--muted); font-size: 0.84rem; line-height: 1.48; }
            .arb-pill { display: inline-flex; align-items: center; border-radius: 999px; padding: 0.22rem 0.55rem; font-size: 0.72rem; font-weight: 800; background: rgba(243,193,95,0.14); color: #ffe08f; border: 1px solid rgba(243,193,95,0.2); }
            .tiny { color: var(--muted); font-size: 0.76rem; }
            .divider { height: 1px; background: var(--border); margin: 0.8rem 0; }

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


@st.cache_data(ttl=1800, show_spinner=False)
def synthesize_pool_chart(pool_id: str, apy: float, apy_base: float, apy_reward: float, tvl: float) -> pd.DataFrame:
    periods = 14
    end = pd.Timestamp.utcnow().floor("D")
    dates = pd.date_range(end=end, periods=periods, freq="D")
    drift = max(apy * 0.03, 0.25)
    apy_points = [max(0.0, round(apy - drift * (periods - i - 1), 2)) for i in range(periods)]
    base_points = [max(0.0, round(apy_base - drift * 0.55 * (periods - i - 1), 2)) for i in range(periods)]
    reward_points = [max(0.0, round(a - b, 2)) for a, b in zip(apy_points, base_points)]
    tvl_floor = tvl * 0.9
    tvl_points = [round(tvl_floor + ((i + 1) / periods) * max(tvl - tvl_floor, 0.0), 2) for i in range(periods)]
    return pd.DataFrame({
        "timestamp": dates,
        "apy": apy_points,
        "apyBase": base_points,
        "apyReward": reward_points,
        "tvlUsd": tvl_points,
    })


def get_pool_chart_with_fallback(row: pd.Series) -> tuple[pd.DataFrame, str]:
    pool_id = str(row["pool"])
    chart = fetch_pool_chart(pool_id)
    if not chart.empty:
        return chart, "live"

    stored = load_history(pool_id)
    if not stored.empty:
        return stored, "stored"

    apy = float(row.get("apy", 0.0) or 0.0)
    apy_base = float(row.get("apyBase", apy * 0.7) or 0.0)
    apy_reward = float(row.get("apyReward", max(apy - apy_base, 0.0)) or 0.0)
    tvl = float(row.get("tvlUsd", 0.0) or 0.0)
    return synthesize_pool_chart(pool_id, apy, apy_base, apy_reward, tvl), "fallback"


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
    existing_candidates = [
        row.get("pool_url"),
        row.get("url"),
        row.get("link"),
        row.get("urlMain"),
    ]
    for candidate in existing_candidates:
        candidate_url = clean_value(candidate)
        if is_specific_url(candidate_url):
            return candidate_url

    protocol_deeplink = build_protocol_deeplink(row)
    if protocol_deeplink:
        return protocol_deeplink

    defillama_url = build_defillama_pool_url(row)
    if defillama_url:
        return defillama_url

    project_key = clean_value(row.get("project_key", row.get("project", ""))).lower()
    for key, link in AFFILIATE_LINKS.items():
        if key in project_key:
            return link

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


def get_checkout_link(current_email: str = "") -> str:
    base = FURUFLOW_STRIPE_LINK.strip()
    if not current_email:
        return base
    sep = "&" if "?" in base else "?"
    safe_email = quote(current_email)
    safe_ref = quote(f"furuflow:{current_email}")
    return f"{base}{sep}prefilled_email={safe_email}&client_reference_id={safe_ref}"


def render_link_table(source_df: pd.DataFrame, title: str, description: str, *, limit: int = 8, sort_cols: list[str] | None = None) -> None:
    st.markdown("<div class='panel'>", unsafe_allow_html=True)
    section_header(title, "Pool links", description)
    if source_df.empty:
        st.info("No pool links are available for the current filter set.")
    else:
        view = source_df.copy()
        if sort_cols:
            ascending = [False] * len(sort_cols)
            view = view.sort_values(sort_cols, ascending=ascending)
        cols = ["project", "chain", "symbol", "apy", "tvlUsd", "risk_score", "signal", "pool_url"]
        cols = [c for c in cols if c in view.columns]
        link_view = view[cols].head(limit).copy()
        link_view = link_view.rename(columns={
            "project": "Protocol",
            "chain": "Chain",
            "symbol": "Asset",
            "apy": "APY",
            "tvlUsd": "TVL (USD)",
            "risk_score": "Risk",
            "signal": "Signal",
            "pool_url": "Open",
        })
        st.dataframe(
            link_view,
            use_container_width=True,
            hide_index=True,
            height=min(120 + 42 * len(link_view), 420),
            column_config={
                "APY": st.column_config.NumberColumn(format="%.2f%%"),
                "TVL (USD)": st.column_config.NumberColumn(format="$%.0f"),
                "Risk": st.column_config.NumberColumn(format="%.0f"),
                "Open": st.column_config.LinkColumn("Pool link", display_text="Open"),
            },
        )
    st.markdown("</div>", unsafe_allow_html=True)


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


def sidebar_group(title: str, copy: str) -> None:
    st.markdown(f"<div class='sidebar-group-title'>{title}</div><div class='sidebar-group-copy'>{copy}</div>", unsafe_allow_html=True)


def page_selectbox(default_page: str = "Home") -> str:
    label_to_page = {PAGE_LABELS[p]: p for p in PAGE_OPTIONS}
    labels = [PAGE_LABELS[p] for p in PAGE_OPTIONS]
    default_label = PAGE_LABELS.get(default_page, labels[0])
    selected_label = st.selectbox(
        "Workspace",
        labels,
        index=labels.index(default_label),
        key="sidebar_page_select",
    )
    return label_to_page[selected_label]


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
    rows = []
    for asset, sub in clean.groupby("asset_key"):
        if sub["chain"].nunique() < 2 or len(sub) < 2:
            continue
        top = sub.sort_values("apy", ascending=False).iloc[0]
        low = sub.sort_values("apy", ascending=True).iloc[0]
        diff = float(top["apy"] - low["apy"])
        if diff >= 3:
            rows.append({
                "Asset": asset,
                "Best chain": top["chain"],
                "Best protocol": top["project"],
                "Best APY": float(top["apy"]),
                "Best link": top["pool_url"],
                "Lower chain": low["chain"],
                "Lower protocol": low["project"],
                "Lower APY": float(low["apy"]),
                "Lower link": low["pool_url"],
                "APY difference": diff,
            })
    return pd.DataFrame(rows).sort_values("APY difference", ascending=False).head(30) if rows else pd.DataFrame()


def save_watchlist(items: list[str]) -> None:
    try:
        WATCHLIST_FILE.write_text(json.dumps(items, indent=2), encoding="utf-8")
    except Exception:
        pass


def load_watchlist() -> list[str]:
    try:
        if WATCHLIST_FILE.exists():
            data = json.loads(WATCHLIST_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [str(x) for x in data]
    except Exception:
        pass
    return []


def set_watchlist(items: list[str]) -> None:
    deduped = list(dict.fromkeys([str(i) for i in items]))
    st.session_state.watchlist = deduped
    save_watchlist(deduped)


def watch_toggle(pool_id: str) -> None:
    current = list(st.session_state.watchlist)
    if pool_id in current:
        current = [p for p in current if p != pool_id]
    else:
        current.append(pool_id)
    set_watchlist(current)


def strategy_builder_filter(df: pd.DataFrame, stable_only: bool, min_apy: float, min_tvl: float, max_risk: int, signal_pref: str) -> pd.DataFrame:
    out = df.copy()
    if stable_only:
        out = out[out["stablecoin"] == True]
    out = out[(out["apy"] >= min_apy) & (out["tvlUsd"] >= min_tvl) & (out["risk_score"] <= max_risk)]
    if signal_pref != "Any":
        out = out[out["signal"] == signal_pref]
    return out.sort_values(["rank_score", "apy", "tvlUsd"], ascending=[False, False, False]).head(25)


def require_pro(feature_name: str, preview_df: pd.DataFrame | None = None, preview_note: str | None = None) -> None:
    st.markdown("<div class='panel'>", unsafe_allow_html=True)
    section_header("FuruFlow Pro", f"Unlock {feature_name}", "The public product stays useful on purpose. Pro adds the signal layer, ranked workflows, and faster decision support.")
    st.markdown(
        """
<div class='signal-card'>
  <div class='signal-title'>🚫 You're seeing limited signal data</div>
  <div class='signal-copy'>
    Free users can scan pools.<br><br>
    <b>Pro users get:</b><br>
    • Full signal rankings<br>
    • Real APY + TVL movement detection<br>
    • Early-stage opportunity identification<br>
    • Whale-flow and farm-rotation context<br>
    • Full dataset access instead of the public top slice
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )
    st.warning(f"⚡ Most profitable {feature_name.lower()} move fast. Pro users see the full board first.")
    if preview_note:
        st.caption(preview_note)
    if preview_df is not None and not preview_df.empty:
        st.markdown("### Preview")
        st.dataframe(preview_df.head(3), use_container_width=True, hide_index=True, height=180)
    st.markdown(
        """
**FuruFlow Pro includes:**
- Arbitrage signals
- Whale-flow and signal engine views
- Advanced ranking and sorting
- Full scanner depth and CSV export
- Future signal-based alerts
"""
    )
    st.caption("Pro is $20/month.")
    if st.session_state.get("auth_email"):
        st.caption(f"Signed in as {st.session_state.get('auth_email')}")
    else:
        st.info("Keep browsing in free mode, or sign in when you're ready to unlock Pro.")
    render_checkout_section(current_email=st.session_state.get("auth_email", ""))
    st.link_button("Upgrade to FuruFlow Pro — $20/month", get_checkout_link(st.session_state.get("auth_email", "")))
    st.markdown("</div>", unsafe_allow_html=True)
    st.stop()




def render_admin_access_panel(current_user: dict) -> None:
    st.markdown("<div class='panel'>", unsafe_allow_html=True)
    section_header(
        "Admin access controls",
        "Grant or remove account access",
        "Manage lifetime access, recurring Pro, and admin status for any account.",
    )

    query = st.text_input(
        "Find account by email",
        value="",
        placeholder="name@example.com",
        key="admin_user_search",
    )
    users = search_users(query=query, limit=50)

    target_emails = [u["email"] for u in users]
    if current_user["email"] not in target_emails:
        target_emails.insert(0, current_user["email"])

    selected_email = st.selectbox(
        "Select account",
        options=target_emails if target_emails else [current_user["email"]],
        key="admin_target_email",
    )

    target_user = get_user_by_email(selected_email)
    if not target_user:
        upsert_user(selected_email, is_admin=False)
        target_user = get_user_by_email(selected_email)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Admin", "Yes" if target_user["is_admin"] else "No")
    with col2:
        st.metric("Lifetime", "Yes" if target_user["lifetime_access"] else "No")
    with col3:
        st.metric("Pro active", "Yes" if target_user["pro_active"] else "No")

    a1, a2, a3 = st.columns(3)
    with a1:
        if target_user["lifetime_access"]:
            if st.button("Remove lifetime access", key=f"remove_lifetime_{selected_email}"):
                set_lifetime_access(selected_email, False)
                st.success(f"Removed lifetime access from {selected_email}.")
                st.rerun()
        else:
            if st.button("Grant lifetime access", key=f"grant_lifetime_{selected_email}"):
                set_lifetime_access(selected_email, True)
                st.success(f"Granted lifetime access to {selected_email}.")
                st.rerun()

    with a2:
        if target_user["pro_active"]:
            if st.button("Deactivate Pro", key=f"deactivate_pro_{selected_email}"):
                set_pro_active(selected_email, False)
                st.success(f"Deactivated Pro for {selected_email}.")
                st.rerun()
        else:
            if st.button("Activate Pro", key=f"activate_pro_{selected_email}"):
                set_pro_active(selected_email, True)
                st.success(f"Activated Pro for {selected_email}.")
                st.rerun()

    with a3:
        can_edit_admin = selected_email != current_user["email"]
        if target_user["is_admin"]:
            if st.button("Remove admin", key=f"remove_admin_{selected_email}", disabled=not can_edit_admin):
                set_admin(selected_email, False)
                st.success(f"Removed admin from {selected_email}.")
                st.rerun()
        else:
            if st.button("Make admin", key=f"make_admin_{selected_email}"):
                set_admin(selected_email, True)
                st.success(f"Made {selected_email} an admin.")
                st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)

def render_opportunity_card(row: pd.Series, idx: int, watched: bool) -> None:
    signal = row.get("signal", "Steady")
    card_html = f"""
    <style>
        .ff-card-wrap {{
            background: linear-gradient(180deg, rgba(14,29,49,0.98), rgba(10,21,39,0.98));
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 18px;
            padding: 16px;
            color: #eef4ff;
            font-family: Inter, 'Segoe UI', sans-serif;
            box-shadow: 0 14px 34px rgba(0,0,0,0.22);
        }}
        .ff-opp-top {{ display:flex; justify-content:space-between; gap:12px; align-items:flex-start; }}
        .ff-opp-name {{ font-size: 1.02rem; font-weight: 700; color:#ffffff; line-height:1.15; }}
        .ff-opp-sub {{ color:#aab8d4; font-size:0.85rem; margin-top:0.25rem; }}
        .ff-protocol-dot {{ min-width:34px; height:34px; border-radius:999px; display:flex; align-items:center; justify-content:center; background: linear-gradient(135deg, #7ce2ff, #66d5ff); color:#072030; font-weight:800; }}
        .ff-watch-pill {{ display:inline-flex; margin-top:10px; background:rgba(124,226,255,0.14); color:#7ce2ff; border:1px solid rgba(124,226,255,0.28); padding:5px 9px; border-radius:999px; font-size:0.78rem; font-weight:700; }}
        .ff-badge-row {{ display:flex; flex-wrap:wrap; gap:7px; margin-top:12px; margin-bottom:12px; align-items:flex-start; }}
        .ff-badge {{ display:inline-flex; align-items:center; background:#eef4ff; color:#17283d; border:1px solid #d7e4fb; border-radius:999px; padding:4px 9px; font-size:0.75rem; font-weight:700; white-space:normal; overflow-wrap:anywhere; line-height:1.25; max-width:100%; }}
        .ff-metric-strip {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; margin-top:6px; }}
        .ff-metric-box {{ background:#f7faff; border:1px solid #d9e7fb; border-radius:12px; padding:10px 8px; text-align:center; }}
        .ff-metric-mini-label {{ font-size:0.70rem; font-weight:700; color:#617287; text-transform:uppercase; letter-spacing:0.05em; }}
        .ff-metric-mini-value {{ font-size:1rem; font-weight:800; color:#122235; margin-top:2px; }}
    </style>
    <div class="ff-card-wrap">
        <div class="ff-opp-top">
            <div>
                <div class="ff-opp-name">{row['project']}</div>
                <div class="ff-opp-sub">{row['symbol']} • {row['chain']} • {row['protocol_tier']}</div>
            </div>
            <div class="ff-protocol-dot">{row['protocol_badge']}</div>
        </div>
        {'<span class="ff-watch-pill">★ Watched</span>' if watched else ''}
        <div class="ff-badge-row">
            <span class="ff-badge">{row['strategy_type']}</span>
            <span class="ff-badge">{row['risk_band']} risk</span>
            <span class="ff-badge">{row['scorecard']}</span>
            <span class="ff-badge">{signal}</span>
        </div>
        <div class="ff-metric-strip">
            <div class="ff-metric-box"><div class="ff-metric-mini-label">APY</div><div class="ff-metric-mini-value">{row['apy']:.2f}%</div></div>
            <div class="ff-metric-box"><div class="ff-metric-mini-label">TVL</div><div class="ff-metric-mini-value">{format_money(row['tvlUsd'])}</div></div>
            <div class="ff-metric-box"><div class="ff-metric-mini-label">Risk</div><div class="ff-metric-mini-value">{int(row['risk_score'])}/100</div></div>
        </div>
    </div>
    """
    st_html(card_html, height=300)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("<div class='watch-wrap'>", unsafe_allow_html=True)
        label = "Remove" if watched else "Watch"
        if st.button(label, key=f"watch_{idx}", use_container_width=True):
            watch_toggle(str(row["pool"]))
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
    with c2:
        st.markdown("<div class='pool-wrap'>", unsafe_allow_html=True)
        st.link_button("Open Pool", row["pool_url"], use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)


def render_protocol_dashboard(df: pd.DataFrame) -> None:
    st.markdown("<div class='panel'>", unsafe_allow_html=True)
    section_header("Protocol dashboard", "Depth by venue", "Compare the strongest visible protocols by capital depth, median yield, and average risk.")
    if df.empty:
        st.info("No protocol data available for the current filters.")
        st.markdown("</div>", unsafe_allow_html=True)
        return
    top_protocols = top_n_summary(df, "project", 12)
    top_protocols = top_protocols.rename(columns={"project": "Protocol", "total_tvl": "TVL (USD)", "median_apy": "Median APY", "pools": "Pools", "avg_risk": "Avg Risk"})
    left, right = st.columns([1.15, 1], gap="large")
    with left:
        st.dataframe(top_protocols, use_container_width=True, hide_index=True, height=420, column_config={"TVL (USD)": st.column_config.NumberColumn(format="$%.0f"), "Median APY": st.column_config.NumberColumn(format="%.2f%%"), "Avg Risk": st.column_config.NumberColumn(format="%.0f")})
    with right:
        bar = px.bar(top_protocols.head(10), x="Protocol", y="TVL (USD)", color="Median APY", hover_data={"Pools": True, "Avg Risk": ':.1f'})
        bar.update_xaxes(title="Protocol")
        bar.update_yaxes(title="TVL")
        st.plotly_chart(plotly_theme(bar, 420), use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)


def render_home_page(filtered: pd.DataFrame, full_filtered: pd.DataFrame, watchlist_df: pd.DataFrame, alert_stats: dict[str, Any], history_latest_df: pd.DataFrame, history_trend_df: pd.DataFrame, is_pro: bool) -> None:
    visible = len(filtered)
    median_apy = filtered["apy"].median() if visible else 0.0
    total_tvl = filtered["tvlUsd"].sum() if visible else 0.0
    signal_share = (filtered["signal"].ne("Steady").mean() * 100) if visible else 0.0

    st.markdown("<div class='panel'>", unsafe_allow_html=True)
    section_header("Home", "Your fastest read on the market", "Start here to see the current opportunity set, understand what is moving, and decide where to drill in next.")
    top_left, top_right = st.columns([1.25, 0.9], gap="large")
    with top_left:
        stat_cols = st.columns(4)
        with stat_cols[0]:
            stat_card("Visible opportunities", f"{visible:,}", "Pools left after your current filters")
        with stat_cols[1]:
            stat_card("Median APY", f"{median_apy:,.2f}%", "A steadier center of the current market slice")
        with stat_cols[2]:
            stat_card("Aggregate TVL", format_money(total_tvl), "Combined depth across visible pools")
        with stat_cols[3]:
            stat_card("Signal density", f"{signal_share:,.0f}%", "Pools with non-steady signal labels")

        st.markdown("<div style='height:0.75rem;'></div>", unsafe_allow_html=True)
        section_header("Best opportunities now", "Start with the strongest visible pools", "Use this shortlist for fast triage, then move into Signals or Pool Explorer for more conviction.")
        top_today = full_filtered[["project", "chain", "symbol", "apy", "tvlUsd", "risk_band", "pool_url"]].head(8).copy()
        if top_today.empty:
            st.info("No opportunities match the current filters.")
        else:
            top_today.columns = ["Protocol", "Chain", "Asset", "APY", "TVL (USD)", "Risk", "Open"]
            st.dataframe(top_today, use_container_width=True, hide_index=True, height=320, column_config={"APY": st.column_config.NumberColumn(format="%.2f%%"), "TVL (USD)": st.column_config.NumberColumn(format="$%.0f"), "Open": st.column_config.LinkColumn("Pool link", display_text="Open")})
    with top_right:
        st.markdown("<div class='signal-card'><div class='signal-title'>What to do next</div><div class='signal-copy'>Use Home for a quick market read, Signals for ranked conviction, Watchlist for your shortlist, and Recaps for the memory layer behind alerts and trend persistence.</div></div>", unsafe_allow_html=True)
        st.markdown("<div style='height:0.65rem;'></div>", unsafe_allow_html=True)
        stat_card("Signals logged (24h)", f"{alert_stats['signals_24h']:,}", "Captured for recap and alert workflows")
        stat_card("Best chain (24h)", str(alert_stats['best_chain']), "Chain with the most qualifying signals today")
        stat_card("Watchlist", f"{len(watchlist_df):,}", "Pools saved to your persistent tracker")
        if not is_pro:
            st.markdown("<div style='height:0.65rem;'></div>", unsafe_allow_html=True)
            st.markdown("<div class='signal-card'><div class='signal-title'>FuruFlow Pro</div><div class='signal-copy'>Unlock the full signals view, deeper scanner access, advanced ranking, arbitrage, and strategy workflows.</div></div>", unsafe_allow_html=True)
            if len(full_filtered) > len(filtered):
                st.caption(f"Free mode currently shows the top {len(filtered):,} of {len(full_filtered):,} matching pools.")
            st.link_button("Upgrade to FuruFlow Pro — $20/month", get_checkout_link(st.session_state.get("auth_email", "")))
    st.markdown("</div>", unsafe_allow_html=True)

    bottom_left, bottom_mid, bottom_right = st.columns(3, gap="large")
    with bottom_left:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Biggest yield changes", "What moved recently", "Big APY moves can signal opportunity, crowding, or emissions changes.")
        movers = full_filtered.sort_values(["apy_delta_7", "tvl_delta_7_pct"], ascending=[False, False])[["project", "symbol", "apy_delta_7", "tvl_delta_7_pct", "signal"]].head(5).copy()
        if movers.empty:
            st.info("No yield changes available yet.")
        else:
            movers.columns = ["Protocol", "Asset", "7d APY Δ", "7d TVL Δ %", "Signal"]
            st.dataframe(movers, use_container_width=True, hide_index=True, height=220, column_config={"7d APY Δ": st.column_config.NumberColumn(format="%.2f"), "7d TVL Δ %": st.column_config.NumberColumn(format="%.2f")})
        st.markdown("</div>", unsafe_allow_html=True)
    with bottom_mid:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Safer high APY", "Yield with stronger footing", "Pools above 10% APY with deeper TVL and lower modeled risk.")
        safest = full_filtered[(full_filtered["apy"] >= 10) & (full_filtered["tvlUsd"] >= 1_000_000) & (full_filtered["risk_score"] <= 45)].sort_values(["risk_score", "apy", "tvlUsd"], ascending=[True, False, False])[["project", "symbol", "apy", "tvlUsd", "risk_score"]].head(5).copy()
        if safest.empty:
            st.info("No safer high-APY pools match the current filters.")
        else:
            safest.columns = ["Protocol", "Asset", "APY", "TVL (USD)", "Risk"]
            st.dataframe(safest, use_container_width=True, hide_index=True, height=220, column_config={"APY": st.column_config.NumberColumn(format="%.2f%%"), "TVL (USD)": st.column_config.NumberColumn(format="$%.0f")})
        st.markdown("</div>", unsafe_allow_html=True)
    with bottom_right:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Engine intelligence", "Why FuruFlow gets better over time", "History and recap layers turn one-off scans into a memory system.")
        if history_trend_df.empty:
            st.info("Trend blocks appear once multiple signals have been logged.")
        else:
            st.dataframe(history_trend_df.head(5), use_container_width=True, hide_index=True, height=220, column_config={"APY": st.column_config.NumberColumn(format="%.2f%%"), "TVL (USD)": st.column_config.NumberColumn(format="$%.0f"), "APY Δ": st.column_config.NumberColumn(format="%.2f")})
        st.markdown("</div>", unsafe_allow_html=True)


def render_recaps_page(alert_stats: dict[str, Any], history_latest_df: pd.DataFrame, history_trend_df: pd.DataFrame, is_pro: bool) -> None:
    st.markdown("<div class='panel'>", unsafe_allow_html=True)
    section_header("Recaps", "The memory layer behind the signal engine", "Use recaps to review what the engine saw, what kept repeating, and where durable opportunities may be forming.")
    summary_cols = st.columns(3)
    with summary_cols[0]:
        stat_card("Signals logged (24h)", f"{alert_stats['signals_24h']:,}", "Captured into the local signal history")
    with summary_cols[1]:
        stat_card("Pro signals (24h)", f"{alert_stats['pro_24h']:,}", "Premium-only signals captured for faster workflows")
    with summary_cols[2]:
        stat_card("Best chain (24h)", str(alert_stats['best_chain']), "Chain with the most logged qualifying signals today")
    st.markdown("</div>", unsafe_allow_html=True)

    recap_left, recap_right = st.columns(2, gap="large")
    with recap_left:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Daily recap preview", "What the engine saw today", "A compact public summary of the current signal picture.")
        st.code(build_daily_recap(), language="text")
        st.markdown("</div>", unsafe_allow_html=True)
    with recap_right:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Weekly recap preview", "Recurring winners and momentum", "A higher-level summary for repeat behavior and stronger conviction.")
        st.code(build_weekly_recap(), language="text")
        st.markdown("</div>", unsafe_allow_html=True)

    history_left, history_right = st.columns([1.1, 1], gap="large")
    with history_left:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Latest signal history", "Recent logged signals", "Review what the engine actually saw instead of relying on memory.")
        if history_latest_df.empty:
            st.info("Run post_real_signals.py once to begin populating signal history.")
        else:
            latest_view = history_latest_df[["name", "chain", "apy", "tvl", "strength_score", "tier"]].copy()
            latest_view.columns = ["Pool", "Chain", "APY", "TVL (USD)", "Score", "Tier"]
            st.dataframe(latest_view, use_container_width=True, hide_index=True, height=320, column_config={"APY": st.column_config.NumberColumn(format="%.2f%%"), "TVL (USD)": st.column_config.NumberColumn(format="$%.0f")})
        st.markdown("</div>", unsafe_allow_html=True)
    with history_right:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Trend snapshot", "Recurring opportunities", "Pools that keep appearing can matter more than one-off spikes.")
        if history_trend_df.empty:
            st.info("Trend blocks appear once multiple signals have been logged.")
        else:
            st.dataframe(history_trend_df, use_container_width=True, hide_index=True, height=320, column_config={"APY": st.column_config.NumberColumn(format="%.2f%%"), "TVL (USD)": st.column_config.NumberColumn(format="$%.0f"), "APY Δ": st.column_config.NumberColumn(format="%.2f")})
        if not is_pro:
            st.markdown("<div class='note'>Free mode can see the recap layer. Pro is where you get the full signal engine, stronger alerts, and faster decision workflows.</div>", unsafe_allow_html=True)
            st.link_button("Upgrade to FuruFlow Pro — $20/month", get_checkout_link(st.session_state.get("auth_email", "")))
        st.markdown("</div>", unsafe_allow_html=True)


inject_css()
init_db()

ADMIN_EMAILS = {
    email.strip().lower()
    for email in os.getenv("ADMIN_EMAILS", "d.arvelop93@gmail.com").split(",")
    if email.strip()
}

with st.sidebar:
    st.markdown("## Account")
    if st.session_state.get("auth_email"):
        st.caption("Signed in for saved access and Pro features.")
    else:
        st.caption("Public mode is live. Sign in only for saved account features or Pro.")
    login_form()

user = get_current_user()
guest_mode = user is None

if guest_mode:
    db_user = {
        "email": "Guest",
        "is_admin": False,
        "lifetime_access": False,
        "pro_active": False,
    }
    is_pro = False
else:
    email = user["email"].lower()
    db_user = get_user_by_email(email)
    if not db_user:
        db_user = upsert_user(email=email, is_admin=(email in ADMIN_EMAILS))
    elif email in ADMIN_EMAILS and not db_user.get("is_admin", False):
        db_user = upsert_user(email=email, is_admin=True)

    session_id = st.session_state.get("auth_session_id")
    if not session_id:
        session_id = os.urandom(16).hex()
        st.session_state["auth_session_id"] = session_id
        st.session_state["auth_session_claimed"] = False

    if not st.session_state.get("auth_session_claimed", False):
        claim_session(email, session_id)
        st.session_state["auth_session_claimed"] = True
    else:
        db_user = get_user_by_email(email)
        active_session_id = db_user.get("current_session_id") if db_user else None
        if active_session_id and active_session_id != session_id:
            st.session_state.pop("auth_email", None)
            st.session_state.pop("auth_session_id", None)
            st.session_state.pop("auth_session_claimed", None)
            st.session_state.pop("access_granted", None)
            st.warning("This account was opened in another browser session, so this session was signed out to keep FuruFlow to one active login at a time.")
            st.stop()
        touch_session(email, session_id)

    db_user = get_user_by_email(email)
    is_pro = can_access_pro(db_user)

st.session_state["access_granted"] = is_pro

with st.sidebar:
    st.write(f"Session: **{db_user['email']}**")
    st.write(f"Plan: **{'Pro' if is_pro else 'Free'}**")
    if not guest_mode:
        st.write(f"Admin: **{'Yes' if db_user['is_admin'] else 'No'}**")
        st.write(f"Lifetime access: **{'Yes' if db_user['lifetime_access'] else 'No'}**")
        st.write(f"Pro active: **{'Yes' if db_user['pro_active'] else 'No'}**")
        st.caption("Single-active-session lock is on for email-only sign-in.")
        if st.button("Log out", key="logout_button"):
            clear_session(db_user["email"], st.session_state.get("auth_session_id"))
            st.session_state.pop("auth_email", None)
            st.session_state.pop("auth_session_id", None)
            st.session_state.pop("auth_session_claimed", None)
            st.session_state.pop("access_granted", None)
            st.rerun()

if db_user.get('is_admin'):
    render_admin_access_panel(db_user)

raw_df = fetch_pools()
df = enrich(raw_df)

if "watchlist" not in st.session_state:
    st.session_state.watchlist = load_watchlist()

signal_source = tuple(df.head(SIGNAL_SAMPLE)["pool"].tolist())
signal_df = fetch_signal_snapshots(signal_source)
if not signal_df.empty:
    df = df.merge(signal_df, on="pool", how="left")
for col, default in [("signal", "Steady"), ("apy_delta_7", 0.0), ("tvl_delta_7_pct", 0.0), ("apy_volatility", 0.0)]:
    if col not in df.columns:
        df[col] = default
    df[col] = df[col].fillna(default)

df["signal_strength"] = (
    df["apy_delta_7"].abs() * 0.6
    + df["tvl_delta_7_pct"].abs() * 0.3
    + df["apy_volatility"] * 0.1
).round(1)

watchlist_df = df[df["pool"].isin(st.session_state.watchlist)].copy()
save_snapshot(df)

history_latest_df = latest_signal_history(limit=12)
history_trend_df = trend_summary_df(limit=10)
alert_stats = alert_snapshot()

st.markdown(
    f"""
    <section class="hero-shell"><div class="hero-inner">
        <div class="eyebrow">DeFi yield intelligence</div>
        <div class="hero-title">{APP_NAME}</div>
        <div class="hero-subtitle">{APP_TAGLINE}</div>
    </div></section>
    """,
    unsafe_allow_html=True,
)

if guest_mode:
    st.info("🌐 Free mode is open immediately. Explore core pools, the market map, protocol dashboard, and pool explorer without creating an account.")
elif is_pro:
    st.info("🔥 Pro is active. You have access to ranked signals, advanced workflows, and full scanner depth.")
else:
    st.info("✅ Free account active. Upgrade to Pro for signals, arbitrage, advanced ranking, and the full opportunity set.")

with st.sidebar:
    st.markdown(f"## {APP_NAME}")
    st.markdown(APP_TAGLINE)

    chains = sorted(df["chain"].dropna().unique().tolist())
    projects = sorted(df["project"].dropna().unique().tolist())
    strategies = sorted(df["strategy_type"].dropna().unique().tolist())
    signals = sorted(df["signal"].dropna().unique().tolist())

    default_chains = chains[: min(len(chains), 8)] if chains else []

    with st.expander("🧭 Navigation", expanded=True):
        sidebar_group("Workspace", "All pages stay available, but the navigation now lives in a cleaner dropdown instead of one long list.")
        page = page_selectbox(st.session_state.get("current_page", "Home"))
        st.session_state["current_page"] = page
        st.markdown("<div class='sidebar-mini-note'>Tip: Home is the fastest overview, Signals is the premium intelligence layer, and Pool Explorer is best for single-pool inspection.</div>", unsafe_allow_html=True)

    with st.expander("🧰 Market Filters", expanded=True):
        sidebar_group("Universe", "Choose the chains, protocols, and market slices you want in view.")
        selected_chains = st.multiselect("Chains", chains, default=default_chains)
        selected_projects = st.multiselect("Protocols", projects, placeholder="Choose protocols")
        selected_strategies = st.multiselect("Strategy Type", strategies, placeholder="Choose strategy types")
        selected_signals = st.multiselect("Signal Filter", signals, placeholder="Choose signals")
        stable_only = st.toggle("Stablecoin pools only", value=False)

    with st.expander("🎚️ Risk & Yield", expanded=True):
        sidebar_group("Thresholds", "Tighten the opportunity set with TVL, APY, and risk controls.")
        min_tvl = st.slider("Minimum TVL", min_value=0, max_value=500_000_000, value=5_000_000, step=1_000_000)
        max_risk = st.slider("Maximum risk score", min_value=1, max_value=100, value=70)
        min_apy = st.slider("Minimum APY", min_value=0.0, max_value=250.0, value=0.0, step=0.5)
        st.markdown("<div class='sidebar-mini-note'>Risk score is heuristic. It blends protocol age, TVL stability, audit confidence, reward dependence, and inferred pool volatility. Signals come from recent chart movement when chart data is available.</div>", unsafe_allow_html=True)

    with st.expander("📊 Sorting", expanded=False):
        sidebar_group("Ranking", "Change how results are ordered without changing the underlying filter set.")
        sort_options = FREE_SORT_OPTIONS + PRO_SORT_OPTIONS if is_pro else FREE_SORT_OPTIONS
        sort_by = st.selectbox("Sort by", sort_options, index=0)

    st.markdown("<div class='sidebar-plan'>", unsafe_allow_html=True)
    sidebar_group("Plan overview", "Free mode stays useful on purpose. Pro adds the intelligence layer and deeper workflows.")
    if is_pro:
        st.success("Pro is active for this account.")
        st.markdown("""- Full signal engine
- Advanced ranking and deeper scanner depth
- Arbitrage and strategy workflows
- Faster decision support with recaps and history
""")
    else:
        st.info("Free mode stays useful on purpose. Pro adds the intelligence layer.")
        st.markdown("""**Free includes**
- Scanner, market map, pool explorer, protocol dashboard
- Basic sorting and top opportunities
- Watchlist and recap previews

**Pro adds**
- Full signals view and deeper scanner depth
- Advanced ranking, arbitrage, and strategy builder
- Stronger recap workflows and future alerts
""")
        st.link_button("Upgrade to FuruFlow Pro — $20/month", get_checkout_link(st.session_state.get("auth_email", "")))
    st.markdown("<div class='sidebar-mini-note'>Use Home for the fastest read on the market, Signals for ranked conviction, and Recaps for the memory layer.</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

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
full_filtered = filtered.copy()
if not is_pro:
    filtered = filtered.head(FREE_POOL_LIMIT)
watchlist_df = df[df["pool"].isin(st.session_state.watchlist)].copy()
arb_df = find_arbitrage_candidates(full_filtered if is_pro else filtered)

if page == "Home":
    render_home_page(filtered, full_filtered, watchlist_df, alert_stats, history_latest_df, history_trend_df, is_pro)

elif page == "Scanner":
    left, right = st.columns([1.6, 1], gap="large")
    with left:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Scanner", "Custom scan view", "A more product-like scanner surface with richer cards, cleaner table layout, and strong control readability.")
        top_cards = filtered.head(6)
        for start in range(0, len(top_cards), 3):
            cols = st.columns(3, gap="medium")
            for i, (_, row) in enumerate(top_cards.iloc[start : start + 3].iterrows()):
                with cols[i]:
                    render_opportunity_card(row, start + i, row["pool"] in st.session_state.watchlist)
        st.markdown("<div style='height:0.5rem;'></div>", unsafe_allow_html=True)
        table_df = compact_table(filtered)
        st.dataframe(
            table_df,
            use_container_width=True,
            hide_index=True,
            height=540,
            column_config={
                "APY": st.column_config.NumberColumn(format="%.2f%%", width="small"),
                "Base": st.column_config.NumberColumn(format="%.2f%%", width="small"),
                "Rewards": st.column_config.NumberColumn(format="%.2f%%", width="small"),
                "TVL (USD)": st.column_config.NumberColumn(format="$%.0f", width="medium"),
                "Risk": st.column_config.NumberColumn(width="small"),
                "Open": st.column_config.LinkColumn("Pool link", display_text="Open"),
            },
        )
        if is_pro:
            csv = make_download_df(filtered).to_csv(index=False).encode("utf-8")
            st.download_button("Download current table as CSV", csv, file_name="furuflow_scanner.csv", mime="text/csv")
        else:
            st.markdown("<div class='signal-card'><div class='signal-title'>CSV export is Pro</div><div class='signal-copy'>Keep the scanner open to everyone, then charge for export workflows and deeper decision tools.</div></div>", unsafe_allow_html=True)
            st.link_button("Unlock CSV export", get_checkout_link(st.session_state.get("auth_email", "")), use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with right:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Scanner guidance", "How to read the cards", "The card layer helps you triage quickly before you dig into individual pool detail.")
        bullets = [
            ("Risk", "Heuristic score from protocol age, audit confidence, TVL stability, reward dependence, and pool volatility."),
            ("Signal", "Labels such as APY spike, Emerging pool, Farm rotation, and Whale inflow come from recent chart movement."),
            ("Watchlist", "Click Watch to persist a pool to your tracked list inside this project zip."),
        ]
        for title, copy in bullets:
            st.markdown(f"<div class='signal-card'><div class='signal-title'>{title}</div><div class='signal-copy'>{copy}</div></div>", unsafe_allow_html=True)
        mini = filtered.head(12).groupby("risk_band", as_index=False).agg(pools=("pool", "count")) if not filtered.empty else pd.DataFrame()
        if not mini.empty:
            pie = px.pie(mini, values="pools", names="risk_band", hole=0.45)
            st.plotly_chart(plotly_theme(pie, 260), use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

elif page == "Signals":
    st.markdown(
        """
        <section class="hero-shell"><div class="hero-inner">
            <div class="eyebrow">FuruFlow Intelligence</div>
            <div class="hero-title">Signals Engine</div>
            <div class="hero-subtitle">Ranked conviction across DeFi. Detect APY shifts, capital flows, and emerging opportunities before they get crowded.</div>
        </div></section>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("<div class='panel'>", unsafe_allow_html=True)
    section_header("Signals", "Ranked conviction with context", "This is the flagship intelligence view: signal labels, APY and TVL change, volatility context, and direct pool access for the strongest movers.")
    st.markdown("<div class='note'>Use signals to separate raw APY from actual setup quality. Rising APY with stable or improving TVL is usually more interesting than isolated spikes.</div>", unsafe_allow_html=True)
    metric_source = full_filtered if not full_filtered.empty else filtered
    metric_cols = st.columns(3)
    with metric_cols[0]:
        stat_card("Active signals", f"{len(metric_source):,}", "Pools currently visible in the signal universe")
    with metric_cols[1]:
        high_strength = int((metric_source["signal_strength"] >= 12).sum()) if not metric_source.empty else 0
        stat_card("High-strength setups", f"{high_strength:,}", "Signals with stronger combined movement and volatility")
    with metric_cols[2]:
        avg_strength = metric_source["signal_strength"].mean() if not metric_source.empty else 0.0
        stat_card("Avg signal strength", f"{avg_strength:,.1f}", "A quick pulse on overall opportunity intensity")
    st.markdown("</div>", unsafe_allow_html=True)

    top_signal_source = full_filtered.sort_values(["signal_strength", "apy_delta_7", "tvl_delta_7_pct"], ascending=[False, False, False]).head(3)
    if not top_signal_source.empty:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Top signals right now", "The fastest shortlist", "These are the strongest visible setups by combined signal strength, APY movement, and TVL follow-through.")
        cols = st.columns(3, gap="medium")
        for idx, (_, row) in enumerate(top_signal_source.iterrows()):
            with cols[idx]:
                render_opportunity_card(row, 700 + idx, row["pool"] in st.session_state.watchlist)
                st.caption(f"Signal strength: {row['signal_strength']:.1f} • 7d APY Δ: {row['apy_delta_7']:.2f} • 7d TVL Δ: {row['tvl_delta_7_pct']:.2f}%")
        st.markdown("</div>", unsafe_allow_html=True)

    if not is_pro:
        preview = full_filtered[["project", "chain", "symbol", "signal", "signal_strength", "apy_delta_7", "tvl_delta_7_pct"]].copy().head(5)
        preview.columns = ["Protocol", "Chain", "Asset", "Signal", "Strength", "7d APY Δ", "7d TVL Δ %"]
        require_pro("Signals", preview_df=preview, preview_note="Free users can scan pools, but the full signal engine is reserved for Pro.")

    left, right = st.columns([1.2, 1], gap="large")
    with left:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Signal engine", "Yield trend AI layer", "Rules-based labels surface APY spikes, farm rotations, emerging pools, and whale inflows from recent pool chart movement.")
        sig_view = filtered[["project", "chain", "symbol", "signal", "signal_strength", "apy_delta_7", "tvl_delta_7_pct", "apy_volatility", "pool_url"]].copy().head(20)
        sig_view.columns = ["Protocol", "Chain", "Asset", "Signal", "Strength", "7d APY Δ", "7d TVL Δ %", "APY volatility", "Open"]
        st.dataframe(sig_view, use_container_width=True, hide_index=True, height=560, column_config={"Strength": st.column_config.NumberColumn(format="%.1f"), "7d APY Δ": st.column_config.NumberColumn(format="%.2f"), "7d TVL Δ %": st.column_config.NumberColumn(format="%.2f"), "APY volatility": st.column_config.NumberColumn(format="%.2f"), "Open": st.column_config.LinkColumn("Pool link", display_text="Open")})
        st.markdown("</div>", unsafe_allow_html=True)
    with right:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Interpretation", "Operator notes", "These are decision-support signals, not guarantees.")
        guides = [
            ("APY spike", "Yield jumped quickly. Check whether emissions, rewards, or a short-term campaign are driving the move."),
            ("Farm rotation", "Yield and TVL rolled over together. Capital may be leaving after incentives decayed or a newer farm launched."),
            ("Emerging pool", "APY is climbing while TVL is arriving. This can be the sweet spot before a pool becomes crowded."),
            ("Whale inflow", "TVL jumped sharply in a short period. Larger deposits may be validating the venue or crowding the trade."),
        ]
        for title, copy in guides:
            st.markdown(f"<div class='signal-card'><div class='signal-title'>{title}</div><div class='signal-copy'>{copy}</div></div>", unsafe_allow_html=True)
        if not filtered.empty:
            sig_plot_df = filtered.groupby("signal", as_index=False).agg(avg_apy=("apy", "mean"), avg_tvl=("tvlUsd", "mean"), avg_strength=("signal_strength", "mean"))
            fig = px.scatter(sig_plot_df, x="avg_tvl", y="avg_apy", size="avg_strength", color="signal", hover_name="signal", size_max=42, log_x=True)
            fig.update_xaxes(title="Average TVL")
            fig.update_yaxes(title="Average APY %")
            st.plotly_chart(plotly_theme(fig, 320), use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)
    render_link_table(filtered.sort_values(["signal_strength", "apy_delta_7", "tvl_delta_7_pct"], ascending=[False, False, False]), "Signals", "Open the strongest recent signal movers directly from the signal view.", limit=10)

elif page == "Arbitrage":
    if not is_pro:
        require_pro("Arbitrage scanner")
    left, right = st.columns([1.15, 1], gap="large")
    with left:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Arbitrage", "Same asset, different chain", "This view hunts for APY gaps across chains for the same displayed asset symbol.")
        if arb_df.empty:
            st.info("No meaningful cross-chain APY gaps are visible for the current filters.")
        else:
            st.dataframe(arb_df, use_container_width=True, hide_index=True, height=560, column_config={"Best APY": st.column_config.NumberColumn(format="%.2f%%"), "Lower APY": st.column_config.NumberColumn(format="%.2f%%"), "APY difference": st.column_config.NumberColumn(format="%.2f"), "Best link": st.column_config.LinkColumn("Best pool", display_text="Open"), "Lower link": st.column_config.LinkColumn("Lower pool", display_text="Open")})
        st.markdown("</div>", unsafe_allow_html=True)
    with right:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Arb triage", "What to check next", "A spread is only interesting if the execution path and risk justify it.")
        checks = [
            ("Bridge friction", "Estimate the cost and time to move capital between the chains involved."),
            ("Protocol risk mismatch", "Higher APY often comes with lower audit confidence or a weaker TVL base."),
            ("Signal support", "A Whale inflow or Emerging pool label can mean a spread is being discovered by others."),
        ]
        for title, copy in checks:
            st.markdown(f"<div class='signal-card'><div class='signal-title'>{title}</div><div class='signal-copy'>{copy}</div></div>", unsafe_allow_html=True)
        if not arb_df.empty:
            fig = px.bar(arb_df.head(12), x="Asset", y="APY difference", color="Best chain", hover_data={"Best protocol": True, "Lower chain": True, "Lower protocol": True})
            fig.update_yaxes(title="APY difference")
            st.plotly_chart(plotly_theme(fig, 330), use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)
    if not filtered.empty:
        arb_focus = filtered.sort_values(["apy", "tvlUsd"], ascending=[False, False]).head(10)
        render_link_table(arb_focus, "Arbitrage", "Open candidate pools from the arb universe without leaving this screen.", limit=10)

elif page == "Market Map":
    left, right = st.columns([1, 1], gap="large")
    with left:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Market map", "Risk vs yield field", "A compact look at where the visible opportunity set sits across APY, risk, and capital depth.")
        if not filtered.empty:
            bubble = px.scatter(filtered.head(90), x="risk_score", y="apy", size="tvlUsd", color="chain", hover_name="project", hover_data={"symbol": True, "tvlUsd": ':$,.0f', "risk_score": True, "apy": ':.2f'}, size_max=34)
            bubble.update_traces(marker=dict(line=dict(width=1, color="rgba(255,255,255,0.22)"), opacity=0.8))
            bubble.update_xaxes(title="Risk score")
            bubble.update_yaxes(title="APY %")
            st.plotly_chart(plotly_theme(bubble, 420), use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with right:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Chain map", "Capital and yield concentration", "Treemap sizing is based on aggregate TVL across the currently visible pools.")
        if not filtered.empty:
            chain_df = filtered.groupby("chain", as_index=False).agg(total_tvl=("tvlUsd", "sum"), median_apy=("apy", "median"), pools=("pool", "count"))
            sun = px.treemap(chain_df, path=[px.Constant("Chains"), "chain"], values="total_tvl", color="median_apy", hover_data={"pools": True, "median_apy": ':.2f'})
            st.plotly_chart(plotly_theme(sun, 420), use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)
    render_link_table(filtered, "Market map", "Open the pools you are seeing in the current market field view.", limit=10, sort_cols=["rank_score", "apy", "tvlUsd"])

elif page == "Pool Explorer":
    st.markdown("<div class='panel'>", unsafe_allow_html=True)
    section_header("Pool explorer", "Open a single venue", "Inspect chart shape, risk factors, and watchlist actions without leaving the app.")
    pool_options = filtered.copy()
    pool_options["pool_pick"] = pool_options.apply(lambda r: f"{r['project']} • {r['symbol']} • {r['chain']}", axis=1)
    if pool_options.empty:
        st.info("No pools match the current filter set.")
    else:
        chosen = st.selectbox("Choose a Pool", pool_options["pool_pick"].tolist(), index=0)
        row = pool_options.loc[pool_options["pool_pick"] == chosen].iloc[0]
        cols = st.columns([1.3, 1], gap="large")
        with cols[0]:
            chart, chart_mode = get_pool_chart_with_fallback(row)
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=chart["timestamp"], y=chart["apy"], mode="lines", name="APY"))
            if chart["tvlUsd"].gt(0).any():
                fig.add_trace(go.Scatter(x=chart["timestamp"], y=chart["tvlUsd"], mode="lines", name="TVL", yaxis="y2"))
                fig.update_layout(yaxis2=dict(overlaying="y", side="right", showgrid=False, title="TVL"))
            fig.update_xaxes(title="Time")
            fig.update_yaxes(title="APY %")
            st.plotly_chart(plotly_theme(fig, 430), use_container_width=True)
            if chart_mode == "fallback":
                st.caption("Live history was unavailable, so FuruFlow generated a preview trend from the current pool snapshot to avoid an empty chart state.")
            elif chart_mode == "stored":
                st.caption("Live history was unavailable, so FuruFlow loaded stored snapshots collected by the app to render a real local chart history.")
            else:
                st.caption("Live chart history loaded from the upstream pool endpoint.")
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
            st.dataframe(stats, use_container_width=True, hide_index=True, height=360)
            c1, c2 = st.columns(2)
            with c1:
                watched = row["pool"] in st.session_state.watchlist
                st.markdown("<div class='watch-wrap'>", unsafe_allow_html=True)
                if st.button("Remove from watchlist" if watched else "Add to watchlist", key="drill_watch", use_container_width=True):
                    watch_toggle(str(row["pool"]))
                    st.rerun()
                st.markdown("</div>", unsafe_allow_html=True)
            with c2:
                st.markdown("<div class='pool-wrap'>", unsafe_allow_html=True)
                st.link_button("Open Pool", row["pool_url"], use_container_width=True)
                st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

elif page == "Protocol Dashboard":
    render_protocol_dashboard(filtered)
    top_protocol_pools = filtered.sort_values(["tvlUsd", "apy"], ascending=[False, False]).head(10)
    render_link_table(top_protocol_pools, "Protocol dashboard", "Jump from protocol summary into high-TVL pools without switching sections.", limit=10)

elif page == "Strategy Builder":
    if not is_pro:
        preview = strategy_builder_filter(df, True, 8.0, 10_000_000.0, 40, "Any")[["project", "chain", "symbol", "apy", "risk_score", "signal"]].copy().head(8)
        preview.columns = ["Protocol", "Chain", "Asset", "APY", "Risk", "Signal"]
        require_pro("Strategy Builder", preview_df=preview, preview_note="Build reusable high-conviction slices in Pro.")
    left, right = st.columns([1, 1.1], gap="large")
    with left:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Strategy builder", "Compose a target slice", "Build a reusable market slice like 'stablecoin pools, TVL above 10M, risk below 40, APY above 8'.")
        builder_stable = st.toggle("Stablecoin only strategy", value=True, key="builder_stable")
        builder_min_apy = st.slider("Strategy minimum APY", min_value=0.0, max_value=80.0, value=8.0, step=0.5)
        builder_min_tvl = st.slider("Strategy minimum TVL", min_value=0, max_value=250_000_000, value=10_000_000, step=1_000_000)
        builder_max_risk = st.slider("Strategy maximum risk", min_value=1, max_value=100, value=40)
        signal_pref = st.selectbox("Preferred signal", ["Any"] + signals, index=0 if "Any" else 0)
        strategy_df = strategy_builder_filter(df, builder_stable, builder_min_apy, float(builder_min_tvl), builder_max_risk, signal_pref)
        summary_text = f"{len(strategy_df)} pools match this strategy slice."
        st.markdown(f"<div class='signal-card'><div class='signal-title'>Builder summary</div><div class='signal-copy'>{summary_text}</div></div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with right:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Strategy results", "Top matching pools", "Use this as a shortlist generator, then move candidates to the watchlist or pool explorer.")
        if strategy_df.empty:
            st.info("No pools match the current strategy builder settings.")
        else:
            view = strategy_df[["project", "chain", "symbol", "apy", "tvlUsd", "risk_score", "signal", "pool_url"]].copy()
            view.columns = ["Protocol", "Chain", "Asset", "APY", "TVL (USD)", "Risk", "Signal", "Open"]
            st.dataframe(view, use_container_width=True, hide_index=True, height=520, column_config={"APY": st.column_config.NumberColumn(format="%.2f%%"), "TVL (USD)": st.column_config.NumberColumn(format="$%.0f"), "Open": st.column_config.LinkColumn("Pool link", display_text="Open")})
        st.markdown("</div>", unsafe_allow_html=True)

elif page == "Recaps":
    render_recaps_page(alert_stats, history_latest_df, history_trend_df, is_pro)

elif page == "Watchlist":
    left, right = st.columns([1.2, 1], gap="large")
    with left:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Watchlist", "Tracked pools", "This is your lightweight conviction layer. Items persist in watchlist.json inside the project folder.")
        if watchlist_df.empty:
            st.info("Your watchlist is empty. Use Watch on any scanner card or pool explorer panel.")
        else:
            view = watchlist_df[["project", "chain", "symbol", "apy", "tvlUsd", "risk_score", "signal", "pool_url"]].copy()
            view.columns = ["Protocol", "Chain", "Asset", "APY", "TVL (USD)", "Risk", "Signal", "Open"]
            st.dataframe(view, use_container_width=True, hide_index=True, height=440, column_config={"APY": st.column_config.NumberColumn(format="%.2f%%"), "TVL (USD)": st.column_config.NumberColumn(format="$%.0f"), "Open": st.column_config.LinkColumn("Pool link", display_text="Open")})
            st.markdown("<div class='danger-wrap'>", unsafe_allow_html=True)
            if st.button("Clear watchlist", use_container_width=True):
                set_watchlist([])
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with right:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Watchlist chart", "Where your attention sits", "Quick visual comparison of tracked yield and signal distribution.")
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
