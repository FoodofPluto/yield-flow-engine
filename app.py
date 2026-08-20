from __future__ import annotations
from signal_card import build_signal_card
from inspect import signature
import tempfile
import uuid

import json
import html
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st


from auth import login_form
from auth_session import render_pending_session_activation
from automation.store import AutomationStoreError
from auth_service import can_access_pro, claim_session, get_current_user, is_admin, logout, validate_session
from utils.external_side_effects import set_demo_side_effect_block
from history_store import load_history, save_snapshot
from engine.performance import SignalHistoryReadError, alert_snapshot, latest_signal_history, trend_summary_df
from engine.recap import build_daily_recap, build_weekly_recap
from engine.scoring import (
    label_pool_risk as label_risk,
    score_pool,
    score_pool_volatility,
    score_signal_movement,
    score_tvl_stability,
)
from market_research import (
    COMPARISON_LIMIT,
    DEFAULT_FILTERS,
    DiscoveryFilters,
    active_filters,
    apply_discovery_filters,
    comparison_rows,
    data_status_from_attrs,
    filter_query,
    freshness,
    parse_filter_query,
    remove_filter,
    risk_explanation,
    track_research_event,
    yield_explanation,
    yield_spreads,
)
from market_data import provider_pool_frame
from saved_pools import (
    SavedPool,
    SavedPoolStoreError,
    UserSavedPoolsClient,
    current_user_saved_pools_client,
)
from ui_shell import (
    DISCOVER_VIEWS,
    OPPORTUNITIES_TABLE_COLUMNS,
    PRO_TOOL_VIEWS,
    SIGNAL_ENGINE_TABLE_COLUMNS,
    STRATEGY_RESULTS_TABLE_COLUMNS,
    RESEARCH_VIEWS,
    account_control_model,
    alert_creation_state,
    canonical_route,
    inject_shell_css,
    market_filters_apply,
    pool_detail_back_state,
    pool_detail_query_context,
    pool_detail_state,
    pool_detail_url,
    render_brand,
    render_navigation,
    render_page_heading,
    render_state,
    render_status,
    route_access,
)
from ui_theme import inject_theme_css
from user_alerts import (
    UserAlert,
    alert_explanation,
    current_user_notification_client,
    format_alert_time,
    pool_label_mapping,
    safe_pool_label,
)

APP_NAME = "FuruFlow"
APP_VERSION = "v8.1"
APP_TAGLINE = "Find the smartest yields. Avoid the dumb ones."
LINK_RESOLVER_VERSION = "2026-03-28-linkfix-2"
POOL_LIMIT = 400
FREE_POOL_LIMIT = 10
FREE_SORT_OPTIONS = ["Highest APY", "Largest TVL"]
PRO_SORT_OPTIONS = ["FuruFlow rank", "Lowest risk", "Highest 24h volume", "Largest signal move"]
TIMEOUT = 18
SIGNAL_SAMPLE = 16
AFFILIATE_LINKS = {
    "aave": "https://app.aave.com/?ref=furuflow",
    "aave-v3": "https://app.aave.com/?ref=furuflow",

    "gmx": "https://app.gmx.io/#/?ref=furuflow",
    "curve": "https://curve.fi/#/ethereum/pools?ref=furuflow",
    "beefy": "https://app.beefy.com/?ref=furuflow",
    "yearn": "https://yearn.fi/?ref=furuflow",
    "morpho": "https://app.morpho.org/?ref=furuflow",
    "morpho-v1": "https://app.morpho.org/?ref=furuflow",


}

st.set_page_config(
    page_title=APP_NAME,
    page_icon="🐸",
    layout="wide",
    initial_sidebar_state="auto",
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
            html, body, [class*="css"] {
                font-family: var(--ff-font-body);
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

            /* Keep form controls dark and readable without painting every nested label. */
            label, .stSelectbox label, .stMultiSelect label, .stSlider label, .stRadio label, .stCheckbox label, .stToggle label {
                color: var(--text) !important;
                font-weight: 800 !important;
            }
            div[data-baseweb="select"] > div,
            div[data-baseweb="input"] > div,
            .stNumberInput div[data-baseweb="input"] > div,
            .stTextInput div[data-baseweb="input"] > div,
            [data-testid="stTextInputRootElement"],
            [data-testid="stNumberInputContainer"] {
                background: var(--ff-color-surface-control) !important;
                border-color: var(--ff-color-border-strong) !important;
                color: var(--ff-color-text) !important;
            }
            div[data-baseweb="select"] input,
            div[data-baseweb="input"] input,
            .stSelectbox [data-baseweb="select"] span,
            .stMultiSelect [data-baseweb="select"] span,
            [data-baseweb="select"] svg {
                background: transparent !important;
                color: var(--ff-color-text) !important;
                fill: currentColor !important;
            }
            [data-testid="stTextInputRootElement"] input,
            [data-testid="stNumberInputContainer"] input {
                background: transparent !important;
                color: var(--ff-color-text) !important;
                caret-color: var(--ff-color-interactive) !important;
            }
            [data-testid="stTextInputRootElement"] input::placeholder,
            [data-testid="stNumberInputContainer"] input::placeholder {
                color: var(--ff-color-text-subtle) !important;
                opacity: 1 !important;
            }
            div[data-baseweb="tag"] {
                background: var(--ff-color-selected) !important;
                border: 1px solid rgba(142,232,255,.28) !important;
            }
            div[data-baseweb="tag"], div[data-baseweb="tag"] * {
                color: var(--ff-color-text) !important;
            }
            div[data-baseweb="popover"],
            div[data-baseweb="popover"] *,
            div[data-baseweb="menu"],
            div[data-baseweb="menu"] *,
            ul[role="listbox"],
            ul[role="listbox"] *,
            li[role="option"],
            div[role="option"] {
                background: var(--ff-color-surface-elevated) !important;
                color: var(--ff-color-text) !important;
                font-weight: 800 !important;
            }
            li[role="option"]:hover,
            div[role="option"]:hover,
            li[role="option"][aria-selected="true"],
            div[role="option"][aria-selected="true"] {
                background: var(--ff-color-selected) !important;
                color: var(--ff-color-text) !important;
            }

            .stSlider [data-baseweb="slider"] > div > div > div { background: var(--accent-2) !important; }
            .stSlider [role="slider"] {
                background: var(--ff-color-surface-control) !important;
                border: 2px solid #c8f7ff !important;
                box-shadow: 0 0 0 4px rgba(124,226,255,0.15);
            }
            .stSlider span, .stSlider p { color: var(--ff-color-text-muted) !important; }

            .stDownloadButton button[kind="primary"],
            .stButton button[kind="primary"],
            .stFormSubmitButton button[kind="primary"] {
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
            .stLinkButton a {
                border-radius: 12px !important;
                padding: 0.58rem 0.9rem !important;
                text-decoration: none !important;
                text-align: center !important;
                font-weight: 900 !important;
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
                background: rgba(255,255,255,.045); border: 1px solid var(--ff-color-border); color: var(--ff-color-text-muted);
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
                border-radius: 16px; padding: 0.72rem; background: rgba(6,16,29,.58); border: 1px solid var(--ff-color-border);
            }
            .metric-mini-label { color: var(--ff-color-text-subtle); font-size: 0.72rem; font-weight: 700; margin-bottom: 0.18rem; }
            .metric-mini-value { color: var(--ff-color-text); font-size: 1rem; font-weight: 900; }
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


def fetch_pools() -> pd.DataFrame:
    if os.getenv("FURUFLOW_MARKET_SAMPLE_MODE", "").strip().lower() in {"1", "true", "yes"}:
        return sample_pool_data(["Explicit FURUFLOW_MARKET_SAMPLE_MODE development fixture"])
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
            df = provider_pool_frame(rows)
            if not df.empty:
                required_identity = {"pool", "chain", "project", "symbol"}
                if not required_identity.issubset(df.columns):
                    errors.append(f"{url}: malformed response missing pool identity fields")
                    continue
                usable = df[list(required_identity)].notna().all(axis=1)
                dropped = int((~usable).sum())
                df = df[usable].copy()
                if df.empty:
                    errors.append(f"{url}: response contained no usable pool identities")
                    continue
                value_fields_missing = any(column not in df.columns for column in ("apy", "tvlUsd"))
                df.attrs["source_status"] = "partial" if dropped or value_fields_missing else "live"
                df.attrs["source_label"] = "DeFiLlama Yields"
                df.attrs["retrieved_at"] = datetime.now(timezone.utc).isoformat()
                df.attrs["cache_seconds"] = 900
                if dropped:
                    df.attrs["errors"] = [f"Dropped {dropped} rows without complete pool identity"]
                return df
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    unavailable = pd.DataFrame()
    unavailable.attrs["errors"] = errors
    unavailable.attrs["source_status"] = "unavailable"
    unavailable.attrs["source_label"] = "DeFiLlama Yields"
    unavailable.attrs["retrieved_at"] = None
    unavailable.attrs["cache_seconds"] = 900
    return unavailable


@st.cache_data(ttl=3600, max_entries=64, show_spinner=False)
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


@st.cache_data(ttl=1800, max_entries=4, show_spinner=False)
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


def get_pool_chart_with_fallback(row: pd.Series) -> tuple[pd.DataFrame, str]:
    pool_id = str(row["pool"])
    sample_mode = os.getenv("FURUFLOW_MARKET_SAMPLE_MODE", "").strip().lower() in {"1", "true", "yes"}
    chart = pd.DataFrame() if sample_mode else fetch_pool_chart(pool_id)
    if not chart.empty:
        return chart, "live"

    if sample_mode:
        return pd.DataFrame(columns=["timestamp", "apy", "apyBase", "apyReward", "tvlUsd"]), "unavailable"

    stored = load_history(pool_id)
    if not stored.empty:
        return stored, "stored"

    return pd.DataFrame(columns=["timestamp", "apy", "apyBase", "apyReward", "tvlUsd"]), "unavailable"


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


def enrich(df: pd.DataFrame, resolver_version: str = LINK_RESOLVER_VERSION) -> pd.DataFrame:
    data = df.copy()

    for column in ["apy", "apyBase", "apyReward", "tvlUsd", "volumeUsd1d", "volumeUsd7d"]:
        if column not in data.columns:
            data[column] = pd.NA
        availability_name = {
            "apy": "apy_available",
            "apyBase": "apy_base_available",
            "apyReward": "apy_reward_available",
            "tvlUsd": "tvl_available",
            "volumeUsd1d": "volume_1d_available",
            "volumeUsd7d": "volume_7d_available",
        }[column]
        data[availability_name] = pd.to_numeric(data[column], errors="coerce").notna()
        data[column] = pd.to_numeric(data[column], errors="coerce").fillna(0.0)

    for col in ["chain", "project", "symbol", "poolMeta", "exposure", "pool"]:
        if col not in data.columns:
            data[col] = "Unknown"
        data[col] = data[col].fillna("Unknown").astype(str)

    if "stablecoin" not in data.columns:
        data["stablecoin"] = data["symbol"].str.contains("USDC|USDT|DAI|FRAX|USD|USDe", case=False, na=False)
    data["stablecoin"] = data["stablecoin"].fillna(False)

    if data.empty:
        text_columns = ["strategy_type", "project_key", "protocol_badge", "protocol_tier", "risk_band", "pool_url", "scorecard", "watch_label"]
        numeric_columns = ["protocol_age_score", "audit_score", "tvl_stability_score", "pool_volatility_score", "risk_score", "rank_score"]
        for column in text_columns:
            data[column] = pd.Series(dtype="object")
        for column in numeric_columns:
            data[column] = pd.Series(dtype="float64")
        return data

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


@st.cache_data(ttl=900, max_entries=1, show_spinner=False)
def fetch_enriched_pools(resolver_version: str = LINK_RESOLVER_VERSION) -> pd.DataFrame:
    """Return one bounded public snapshot without hashing a DataFrame argument."""

    return enrich(fetch_pools(), resolver_version=resolver_version)


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


def build_pool_url(row: pd.Series) -> str:
    upstream_url_fields = [
        "url",
        "poolUrl",
        "pool_url",
        "projectUrl",
        "project_url",
        "link",
    ]

    generic_urls = {
        "https://defillama.com/yields",
        "https://app.pendle.finance/trade/markets?ref=furuflow",
        "https://app.uniswap.org/?ref=furuflow",
        "https://app.aave.com/?ref=furuflow",
        "https://curve.fi/#/ethereum/pools?ref=furuflow",
        "https://app.beefy.com/?ref=furuflow",
        "https://yearn.fi/?ref=furuflow",
        "https://app.morpho.org/?ref=furuflow",
        "https://app.gmx.io/#/?ref=furuflow",
    }

    for field in upstream_url_fields:
        value = row.get(field, "")
        if isinstance(value, str):
            value = value.strip()
            if value.startswith("http://") or value.startswith("https://"):
                if value not in generic_urls:
                    return value

    pool = str(row.get("pool", "")).strip()
    if pool and pool != "Unknown":
        return f"https://defillama.com/yields/pool/{pool}"

    project_key = str(row.get("project_key", row.get("project", ""))).lower().strip()
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
    demo.attrs["source_status"] = "sample"
    demo.attrs["source_label"] = "Local development market fixture"
    demo.attrs["retrieved_at"] = datetime.now(timezone.utc).isoformat()
    demo.attrs["cache_seconds"] = 900
    return demo


def build_signal_card_assets(*, pool_name: str, chain: str, apy: str, tvl: str, strength: str, risk: str, signal: str, why_text: str, cta: str, sparkline_values: list[float], preview_path: str, export_path: str) -> dict[str, str]:
    common_kwargs = {
        "pool_name": pool_name,
        "chain": chain,
        "apy": apy,
        "tvl": tvl,
        "strength": strength,
        "risk": risk,
        "signal": signal,
        "why_text": why_text,
        "cta": cta,
        "sparkline_values": sparkline_values,
    }

    sig = signature(build_signal_card)
    supports_mode = "mode" in sig.parameters

    if supports_mode:
        build_signal_card(**common_kwargs, mode="preview", out_path=preview_path)
        build_signal_card(**common_kwargs, mode="export", out_path=export_path)
    else:
        build_signal_card(**common_kwargs, out_path=export_path)
        build_signal_card(**common_kwargs, out_path=preview_path)

    return {"preview_path": preview_path, "export_path": export_path}


def render_billing_action(
    current_user: dict[str, Any] | None,
    *,
    label: str,
    portal: bool = False,
) -> None:
    """Render a fixed POST action; no account or provider identifier reaches the browser."""

    eligible = bool(
        current_user
        and current_user.get("_identity_verified")
        and current_user.get("_account_authority") == "supabase"
        and not current_user.get("demo_active")
    )
    if not eligible:
        st.caption("Sign in with a verified non-demo account to use billing.")
        return
    action = "/billing/portal" if portal else "/billing/checkout"
    safe_label = html.escape(label)
    st.markdown(
        f'<form class="ff-billing-action" method="post" action="{action}" target="_top">'
        f'<button type="submit">{safe_label}</button>'
        "</form>",
        unsafe_allow_html=True,
    )


def billing_access_source(user: dict[str, Any] | None) -> str:
    user = user or {}
    if user.get("is_admin"):
        return "Administrator access"
    if user.get("lifetime_access"):
        return "Lifetime access"
    if user.get("pro_active"):
        return "Account grant"
    if user.get("subscription_pro_active"):
        return "Active subscription"
    if user.get("demo_active"):
        return "Time-limited demo"
    return "Free plan"


def subscription_summary(user: dict[str, Any] | None) -> str | None:
    user = user or {}
    status = user.get("subscription_status")
    if not isinstance(status, str):
        return None
    labels = {
        "active": "Active",
        "trialing": "Trialing — access pending",
        "past_due": "Payment needs attention — Pro access is paused",
        "unpaid": "Unpaid — Pro access is paused",
        "canceled": "Ended",
        "incomplete": "Setup incomplete",
        "incomplete_expired": "Setup expired",
        "paused": "Paused",
        "inactive": "No active subscription",
    }
    summary = labels.get(status, "Not active")
    period_end = user.get("subscription_period_end")
    if isinstance(period_end, str):
        try:
            date_label = datetime.fromisoformat(period_end.replace("Z", "+00:00")).strftime("%b %d, %Y")
            if status == "active" and user.get("subscription_cancel_at_period_end"):
                return f"Active until {date_label}; cancellation is scheduled"
            if status == "active":
                return f"Active; renews {date_label}"
            if status in {"canceled", "unpaid", "paused"}:
                return f"{summary}; access ended {date_label}"
        except ValueError:
            pass
    return summary


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
            width="stretch",
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


def compact_table(df: pd.DataFrame) -> pd.DataFrame:
    source = df.copy()
    for value_col, available_col in (
        ("apy", "apy_available"),
        ("apyBase", "apy_base_available"),
        ("apyReward", "apy_reward_available"),
        ("tvlUsd", "tvl_available"),
    ):
        if available_col in source:
            source.loc[~source[available_col].astype(bool), value_col] = pd.NA
    source["pool_detail_url"] = source["pool"].map(
        lambda pool_id: pool_detail_url(
            str(pool_id),
            public_origin=os.getenv("FURUFLOW_SESSION_BROKER_PUBLIC_ORIGIN", "http://localhost:8501"),
            return_route="Discover",
            return_view="Opportunities",
        )
    )
    table = source[[column for column, _ in OPPORTUNITIES_TABLE_COLUMNS]].copy()
    table.columns = [label for _, label in OPPORTUNITIES_TABLE_COLUMNS]
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


def watch_toggle(
    pool_id: str,
    *,
    watched: bool,
    client: UserSavedPoolsClient | None,
) -> bool:
    if client is None:
        st.error("Saved pools are temporarily unavailable. Your Watchlist was not changed.")
        return False
    try:
        if watched:
            client.remove_pool(pool_id)
        else:
            client.save_pool(pool_id)
    except SavedPoolStoreError as exc:
        st.error(str(exc))
        return False
    return True


def open_pool_detail(pool_id: str, *, return_route: str = "Discover", return_view: str = "Opportunities") -> None:
    st.session_state.update(pool_detail_state(pool_id, return_route=return_route, return_view=return_view))
    st.query_params["page"] = "Pool Detail"
    st.query_params["pool"] = str(pool_id)


def return_from_pool_detail() -> None:
    destination = pool_detail_back_state(st.session_state)
    route = destination["current_route"]
    st.session_state["current_route"] = route
    if route == "Discover":
        st.session_state["discover_view"] = destination["current_view"]
    elif route == "Pro Tools":
        st.session_state["pro_tools_view"] = destination["current_view"]
    st.query_params["page"] = route
    if "pool" in st.query_params:
        del st.query_params["pool"]


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
        st.dataframe(preview_df.head(3), width="stretch", hide_index=True, height=180)
    st.markdown(
        """
**FuruFlow Pro includes:**
- Yield-spread signals
- Whale-flow and signal engine views
- Advanced ranking and sorting
- Full Discover depth and CSV export
- Future signal-based alerts
"""
    )
    st.caption("Pro is $20/month.")
    if st.session_state.get("auth_email"):
        st.caption(f"Signed in as {st.session_state.get('auth_email')}")
    else:
        st.info("Keep browsing in free mode, or sign in when you're ready to unlock Pro.")
    render_billing_action(get_current_user(), label="Upgrade to FuruFlow Pro — $20/month")
    st.markdown("</div>", unsafe_allow_html=True)
    st.stop()




def render_admin_access_panel(current_user: dict) -> None:
    st.markdown("<div class='panel'>", unsafe_allow_html=True)
    section_header(
        "Admin access controls",
        "Trusted account administration",
        "Role and entitlement changes run through the audited service-role CLI, outside Streamlit.",
    )
    st.info("Use `python scripts/manage_accounts.py` from a trusted shell. Target accounts by verified Supabase user ID.")
    st.caption("The service-role credential is intentionally unavailable to this Streamlit process and browser UI.")

    st.markdown("</div>", unsafe_allow_html=True)

def render_opportunity_card(
    row: pd.Series,
    idx: int,
    watched: bool,
    *,
    authenticated: bool,
    watchlist_client: UserSavedPoolsClient | None,
    freshness_label: str,
    return_route: str = "Discover",
    return_view: str = "Opportunities",
    key_prefix: str = "discover",
) -> None:
    signal = row.get("signal", "Steady")
    apy_text = f"{row['apy']:.2f}%" if bool(row.get("apy_available", True)) else "Unavailable"
    tvl_text = format_money(row["tvlUsd"]) if bool(row.get("tvl_available", True)) else "Unavailable"
    card_html = f"""
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
            <span class="ff-badge">Data: {freshness_label}</span>
        </div>
        <div class="ff-metric-strip">
            <div class="ff-metric-box"><div class="ff-metric-mini-label">APY</div><div class="ff-metric-mini-value">{apy_text}</div></div>
            <div class="ff-metric-box"><div class="ff-metric-mini-label">TVL</div><div class="ff-metric-mini-value">{tvl_text}</div></div>
            <div class="ff-metric-box"><div class="ff-metric-mini-label">Risk</div><div class="ff-metric-mini-value">{int(row['risk_score'])}/100</div></div>
        </div>
    </div>
    """
    st.html(card_html)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("<div class='watch-wrap'>", unsafe_allow_html=True)
        label = "Remove" if watched else "Watch" if authenticated else "Sign in to save"
        if st.button(
            label if watchlist_client is not None or not authenticated else "Watchlist unavailable",
            key=f"{key_prefix}_watch_{idx}",
            width="stretch",
            disabled=not authenticated or watchlist_client is None,
        ):
            track_research_event("watchlist_action_initiated", {"pool": str(row["pool"]), "action": label})
            if watch_toggle(str(row["pool"]), watched=watched, client=watchlist_client):
                st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
    with c2:
        st.markdown("<div class='pool-wrap'>", unsafe_allow_html=True)
        if st.button(
            "View details",
            key=f"{key_prefix}_detail_{idx}_{row['pool']}",
            type="primary",
            width="stretch",
        ):
            track_research_event("pool_detail_opened", {"pool": str(row["pool"]), "view": return_view})
            open_pool_detail(str(row["pool"]), return_route=return_route, return_view=return_view)
            st.rerun()
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
        st.dataframe(top_protocols, width="stretch", hide_index=True, height=420, column_config={"TVL (USD)": st.column_config.NumberColumn(format="$%.0f"), "Median APY": st.column_config.NumberColumn(format="%.2f%%"), "Avg Risk": st.column_config.NumberColumn(format="%.0f")})
    with right:
        bar = px.bar(top_protocols.head(10), x="Protocol", y="TVL (USD)", color="Median APY", hover_data={"Pools": True, "Avg Risk": ':.1f'})
        bar.update_xaxes(title="Protocol")
        bar.update_yaxes(title="TVL")
        st.plotly_chart(plotly_theme(bar, 420), width="stretch")
    st.markdown("</div>", unsafe_allow_html=True)


def render_home_page(filtered: pd.DataFrame, full_filtered: pd.DataFrame, watchlist_df: pd.DataFrame, watchlist_count: int, alert_stats: dict[str, Any], history_latest_df: pd.DataFrame, history_trend_df: pd.DataFrame, is_pro: bool) -> None:
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
        section_header("Best opportunities now", "Start with the strongest visible pools", "Use this shortlist for fast triage, then open Discover signals or contextual Pool Detail for more conviction.")
        top_today = full_filtered[["project", "chain", "symbol", "apy", "tvlUsd", "risk_band", "pool_url"]].head(8).copy()
        if top_today.empty:
            st.info("No opportunities match the current filters.")
        else:
            top_today.columns = ["Protocol", "Chain", "Asset", "APY", "TVL (USD)", "Risk", "Open"]
            st.dataframe(top_today, width="stretch", hide_index=True, height=320, column_config={"APY": st.column_config.NumberColumn(format="%.2f%%"), "TVL (USD)": st.column_config.NumberColumn(format="$%.0f"), "Open": st.column_config.LinkColumn("Pool link", display_text="Open")})
    with top_right:
        st.markdown("<div class='signal-card'><div class='signal-title'>What to do next</div><div class='signal-copy'>Use Discover for opportunities and signals, Watchlists for your shortlist, and Activity & Digests for the memory layer behind alerts and trend persistence.</div></div>", unsafe_allow_html=True)
        st.markdown("<div style='height:0.65rem;'></div>", unsafe_allow_html=True)
        stat_card("Signals logged (24h)", f"{alert_stats['signals_24h']:,}", "Captured for recap and alert workflows")
        stat_card("Best chain (24h)", str(alert_stats['best_chain']), "Chain with the most qualifying signals today")
        stat_card("Watchlists", f"{watchlist_count:,}", "Pools saved to your persistent tracker")
        if not is_pro:
            st.markdown("<div style='height:0.65rem;'></div>", unsafe_allow_html=True)
            st.markdown("<div class='signal-card'><div class='signal-title'>FuruFlow Pro</div><div class='signal-copy'>Unlock the full Signals view, deeper Discover access, advanced ranking, Yield Spreads, and strategy workflows.</div></div>", unsafe_allow_html=True)
            if len(full_filtered) > len(filtered):
                st.caption(f"Free mode currently shows the top {len(filtered):,} of {len(full_filtered):,} matching pools.")
            render_billing_action(db_user, label="Upgrade to FuruFlow Pro — $20/month")
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
            st.dataframe(movers, width="stretch", hide_index=True, height=220, column_config={"7d APY Δ": st.column_config.NumberColumn(format="%.2f"), "7d TVL Δ %": st.column_config.NumberColumn(format="%.2f")})
        st.markdown("</div>", unsafe_allow_html=True)
    with bottom_mid:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Safer high APY", "Yield with stronger footing", "Pools above 10% APY with deeper TVL and lower modeled risk.")
        safest = full_filtered[(full_filtered["apy"] >= 10) & (full_filtered["tvlUsd"] >= 1_000_000) & (full_filtered["risk_score"] <= 45)].sort_values(["risk_score", "apy", "tvlUsd"], ascending=[True, False, False])[["project", "symbol", "apy", "tvlUsd", "risk_score"]].head(5).copy()
        if safest.empty:
            st.info("No safer high-APY pools match the current filters.")
        else:
            safest.columns = ["Protocol", "Asset", "APY", "TVL (USD)", "Risk"]
            st.dataframe(safest, width="stretch", hide_index=True, height=220, column_config={"APY": st.column_config.NumberColumn(format="%.2f%%"), "TVL (USD)": st.column_config.NumberColumn(format="$%.0f")})
        st.markdown("</div>", unsafe_allow_html=True)
    with bottom_right:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Engine intelligence", "Why FuruFlow gets better over time", "History and recap layers turn one-off scans into a memory system.")
        if history_trend_df.empty:
            st.info("Trend blocks appear once multiple signals have been logged.")
        else:
            st.dataframe(history_trend_df.head(5), width="stretch", hide_index=True, height=220, column_config={"APY": st.column_config.NumberColumn(format="%.2f%%"), "TVL (USD)": st.column_config.NumberColumn(format="$%.0f"), "APY Δ": st.column_config.NumberColumn(format="%.2f")})
        st.markdown("</div>", unsafe_allow_html=True)


def render_recaps_page(
    alert_stats: dict[str, Any],
    history_latest_df: pd.DataFrame,
    history_trend_df: pd.DataFrame,
    is_pro: bool,
    *,
    history_load_error: bool = False,
) -> None:
    st.markdown("<div class='panel'>", unsafe_allow_html=True)
    section_header("Activity & digests", "The memory layer behind the signal engine", "Review what the engine saw, what kept repeating, and where durable opportunities may be forming.")
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
        if history_load_error:
            render_status(
                "error",
                "Signal history unavailable",
                "Signal activity could not be loaded. Try again later; this is not an empty-history state.",
            )
        elif history_latest_df.empty:
            st.info("No signal history yet. Signal activity will appear here once qualifying yield movements are detected.")
        else:
            latest_view = history_latest_df[["name", "chain", "apy", "tvl", "strength_score", "tier"]].copy()
            latest_view.columns = ["Pool", "Chain", "APY", "TVL (USD)", "Score", "Tier"]
            st.dataframe(latest_view, width="stretch", hide_index=True, height=320, column_config={"APY": st.column_config.NumberColumn(format="%.2f%%"), "TVL (USD)": st.column_config.NumberColumn(format="$%.0f")})
        st.markdown("</div>", unsafe_allow_html=True)
    with history_right:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Trend snapshot", "Recurring opportunities", "Pools that keep appearing can matter more than one-off spikes.")
        if history_trend_df.empty:
            st.info("Trend blocks appear once multiple signals have been logged.")
        else:
            st.dataframe(history_trend_df, width="stretch", hide_index=True, height=320, column_config={"APY": st.column_config.NumberColumn(format="%.2f%%"), "TVL (USD)": st.column_config.NumberColumn(format="$%.0f"), "APY Δ": st.column_config.NumberColumn(format="%.2f")})
        if not is_pro:
            st.markdown("<div class='note'>Free mode can see the recap layer. Pro is where you get the full signal engine, stronger alerts, and faster decision workflows.</div>", unsafe_allow_html=True)
            render_billing_action(db_user, label="Upgrade to FuruFlow Pro — $20/month")
        st.markdown("</div>", unsafe_allow_html=True)


ALERT_TIMEZONES = (
    "UTC",
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "Europe/London",
)


def _alert_form(
    client: Any,
    *,
    pool_labels: dict[str, str],
    is_pro: bool,
    account_timezone: str,
    existing: UserAlert | None = None,
) -> None:
    if not pool_labels and existing is None:
        render_state(
            "No current pool targets",
            "Live pool identity is unavailable, so FuruFlow will not create an alert against guessed or sample data.",
        )
        return

    options = list(pool_labels)
    prefill = str(st.session_state.get("alert_prefill_pool_id") or "")
    if existing and existing.target_pool_id not in options:
        options.insert(0, existing.target_pool_id)
    selected_default = existing.target_pool_id if existing else prefill if prefill in options else options[0]
    tier_options = ["all", "free"]
    if is_pro or (existing and existing.signal_tier == "pro"):
        tier_options.append("pro")
    timezone_options = list(ALERT_TIMEZONES)
    if account_timezone and account_timezone not in timezone_options:
        timezone_options.append(account_timezone)
    selected_timezone = existing.timezone_name if existing else account_timezone or "UTC"
    if selected_timezone not in timezone_options:
        selected_timezone = "UTC"

    form_key = f"alert_form_{existing.id if existing else 'create'}"
    with st.form(form_key):
        st.markdown(f"#### {'Edit pool alert' if existing else 'Create pool alert'}")
        target_pool_id = st.selectbox(
            "Pool",
            options,
            index=options.index(selected_default),
            format_func=lambda pool_id: safe_pool_label(pool_id, pool_labels),
            disabled=existing is not None,
        )
        minimum_strength = st.slider(
            "Minimum signal strength",
            min_value=0,
            max_value=100,
            value=existing.minimum_strength if existing else 60,
            help="The alert matches only after this pool qualifies in the existing FuruFlow signal pipeline.",
        )
        signal_tier = st.selectbox(
            "Signal tier",
            tier_options,
            index=tier_options.index(existing.signal_tier if existing else "all"),
            format_func=lambda value: {"all": "Any eligible tier", "free": "Free tier", "pro": "Pro tier"}[value],
        )
        delivery_mode = st.selectbox(
            "Delivery timing",
            ["immediate", "digest"],
            index=["immediate", "digest"].index(existing.delivery_mode if existing else "immediate"),
            format_func=lambda value: "Immediate" if value == "immediate" else "Daily 09:00 digest window",
        )
        has_quiet_hours = st.toggle(
            "Use quiet hours",
            value=bool(existing and existing.quiet_hours_start and existing.quiet_hours_end),
        )
        quiet_start = quiet_end = None
        if has_quiet_hours:
            quiet_cols = st.columns(2)
            with quiet_cols[0]:
                quiet_start = st.time_input(
                    "Quiet hours start",
                    value=time.fromisoformat(existing.quiet_hours_start) if existing and existing.quiet_hours_start else time(22, 0),
                )
            with quiet_cols[1]:
                quiet_end = st.time_input(
                    "Quiet hours end",
                    value=time.fromisoformat(existing.quiet_hours_end) if existing and existing.quiet_hours_end else time(7, 0),
                )
        timezone_name = st.selectbox(
            "Timezone", timezone_options, index=timezone_options.index(selected_timezone)
        )
        cooldown_options = [60, 360, 1440, 10080]
        existing_cooldown = existing.cooldown_minutes if existing else 1440
        if existing_cooldown not in cooldown_options:
            cooldown_options.append(existing_cooldown)
            cooldown_options.sort()
        cooldown_minutes = st.selectbox(
            "Repeat cooldown",
            cooldown_options,
            index=cooldown_options.index(existing_cooldown),
            format_func=lambda value: {
                60: "1 hour",
                360: "6 hours",
                1440: "24 hours",
                10080: "7 days",
            }.get(value, f"{value} minutes"),
        )
        st.caption(
            "Condition: the selected canonical pool must appear in a fresh successful FuruFlow scan, qualify as the chosen tier, and meet the strength threshold."
        )
        submitted = st.form_submit_button(
            "Save changes" if existing else "Create alert",
            type="primary",
            width="stretch",
        )

    if not submitted:
        return
    start_value = quiet_start.strftime("%H:%M:%S") if quiet_start else None
    end_value = quiet_end.strftime("%H:%M:%S") if quiet_end else None
    try:
        if existing:
            client.update_pool_alert(
                alert_id=existing.id,
                minimum_strength=minimum_strength,
                signal_tier=signal_tier,
                delivery_mode=delivery_mode,
                quiet_hours_start=start_value,
                quiet_hours_end=end_value,
                timezone_name=timezone_name,
                cooldown_minutes=cooldown_minutes,
            )
        else:
            request_key = str(st.session_state.get("alert_create_request_key") or uuid.uuid4().hex)
            st.session_state["alert_create_request_key"] = request_key
            client.create_pool_alert(
                target_pool_id=target_pool_id,
                minimum_strength=minimum_strength,
                signal_tier=signal_tier,
                delivery_mode=delivery_mode,
                quiet_hours_start=start_value,
                quiet_hours_end=end_value,
                timezone_name=timezone_name,
                cooldown_minutes=cooldown_minutes,
                client_request_key=request_key,
            )
    except AutomationStoreError as exc:
        st.error(str(exc))
        return
    for key in ("alert_form_mode", "alert_edit_id", "alert_prefill_pool_id", "alert_create_request_key"):
        st.session_state.pop(key, None)
    st.success("Alert saved.")
    st.rerun()


def render_alerts_page(df: pd.DataFrame, *, is_pro: bool, account_timezone: str) -> None:
    pool_labels = pool_label_mapping(df[["pool", "project", "symbol", "chain"]].to_dict("records")) if not df.empty else {}
    try:
        client = current_user_notification_client()
        telegram_status = client.telegram_status()
        alerts = [UserAlert.from_row(row) for row in client.list_alerts()]
    except AutomationStoreError:
        render_status(
            "degraded",
            "Alert controls temporarily unavailable",
            "The authenticated alert service could not be reached. Market research remains available, and no alert state was guessed.",
        )
        return

    linked = bool(telegram_status.get("available"))
    status_kind = "success" if linked else "warning"
    status_title = "Telegram connected" if linked else "Telegram connection required"
    status_copy = (
        "Notifications use your verified Telegram connection. Routing identifiers and bot credentials are never shown here."
        if linked
        else "A trusted operator must verify and link your Telegram destination before an alert can be created or resumed."
    )
    render_status(status_kind, status_title, status_copy)

    action_cols = st.columns([1, 2])
    with action_cols[0]:
        if st.button(
            "Create alert",
            key="alerts_create",
            type="primary",
            width="stretch",
            disabled=not linked,
        ):
            st.session_state["alert_form_mode"] = "create"
            st.session_state["alert_create_request_key"] = uuid.uuid4().hex
            st.rerun()
    with action_cols[1]:
        st.caption("Delivery channel: Telegram · one verified account connection · no browser-provided routing IDs")

    if st.session_state.get("alert_form_mode") == "create":
        _alert_form(
            client,
            pool_labels=pool_labels,
            is_pro=is_pro,
            account_timezone=account_timezone,
        )

    if not alerts:
        render_state(
            "No alerts yet",
            "Create a pool alert to be notified when that exact pool qualifies in the existing FuruFlow signal pipeline.",
        )
        return

    st.markdown("### Configured alerts")
    for alert in alerts:
        with st.container(border=True):
            state_label = "Active" if alert.enabled else "Paused"
            st.markdown(f"#### {safe_pool_label(alert.target_pool_id, pool_labels)}")
            state_icon = "✓" if alert.enabled else "Ⅱ"
            state_class = "" if alert.enabled else " ff-state-pill--paused"
            st.markdown(
                f'<span class="ff-state-pill{state_class}">{state_icon} {state_label}</span>',
                unsafe_allow_html=True,
            )
            st.caption(f"{state_label} · Telegram · {alert.delivery_mode.title()} delivery")
            st.markdown(alert_explanation(alert))
            metadata = st.columns(3)
            metadata[0].metric("Last evaluated", format_alert_time(alert.last_evaluated_at))
            metadata[1].metric("Last triggered", format_alert_time(alert.last_triggered_at))
            delivery_label = alert.last_delivery_state.replace("_", " ").title() if alert.last_delivery_state else "No delivery yet"
            metadata[2].metric("Latest delivery", delivery_label)

            controls = st.columns(4)
            if controls[0].button("Edit", key=f"alert_edit_{alert.id}", width="stretch"):
                st.session_state["alert_edit_id"] = alert.id
                st.rerun()
            if controls[1].button(
                "Pause" if alert.enabled else "Resume",
                key=f"alert_toggle_{alert.id}",
                width="stretch",
                disabled=not linked and not alert.enabled,
            ):
                try:
                    client.set_alert_enabled(alert.id, not alert.enabled)
                except AutomationStoreError as exc:
                    st.error(str(exc))
                else:
                    st.rerun()
            if controls[2].button("Send test", key=f"alert_test_{alert.id}", width="stretch", disabled=not alert.enabled):
                try:
                    client.request_test_delivery(alert.id)
                except AutomationStoreError as exc:
                    st.error(str(exc))
                else:
                    st.success("Test queued through the durable Telegram delivery pipeline.")
            if controls[3].button("Delete", key=f"alert_delete_{alert.id}", width="stretch"):
                st.session_state["alert_delete_confirm"] = alert.id
                st.rerun()

            if st.session_state.get("alert_delete_confirm") == alert.id:
                st.warning("Delete this alert? Delivery audit records remain retained by the operational system.")
                confirm_cols = st.columns(2)
                if confirm_cols[0].button("Confirm delete", key=f"alert_delete_confirm_{alert.id}", width="stretch"):
                    try:
                        client.delete_alert(alert.id)
                    except AutomationStoreError as exc:
                        st.error(str(exc))
                    else:
                        st.session_state.pop("alert_delete_confirm", None)
                        st.rerun()
                if confirm_cols[1].button("Cancel", key=f"alert_delete_cancel_{alert.id}", width="stretch"):
                    st.session_state.pop("alert_delete_confirm", None)
                    st.rerun()

            if st.session_state.get("alert_edit_id") == alert.id:
                _alert_form(
                    client,
                    pool_labels=pool_labels,
                    is_pro=is_pro,
                    account_timezone=account_timezone,
                    existing=alert,
                )
inject_theme_css()
inject_css()
inject_shell_css()
render_pending_session_activation()

requested_route = str(st.query_params.get("page") or st.session_state.get("current_route") or "Home")
page, legacy_view = canonical_route(requested_route)
if legacy_view:
    if page == "Discover":
        st.session_state["discover_view"] = legacy_view
    elif page == "Research":
        st.session_state["research_view"] = legacy_view
    elif page == "Pro Tools":
        st.session_state["pro_tools_view"] = legacy_view
st.session_state["current_route"] = page
if st.query_params.get("pool"):
    st.session_state["selected_pool_id"] = str(st.query_params["pool"])
if page == "Pool Detail":
    st.session_state.update(pool_detail_query_context(st.query_params))

with st.sidebar:
    render_brand()
    navigation_slot = st.empty()
    with st.expander("Account", expanded=False):
        account_summary_slot = st.empty()
        with st.container(key="account_auth_controls"):
            login_form()

account_user = get_current_user()
signed_in = bool(account_user and account_user.get("_identity_verified"))

if signed_in:
    claim_session()
    if not validate_session():
        render_status(
            "warning",
            "Session expired",
            "This account was opened in another browser session, so this session was signed out to preserve the active-session boundary.",
        )
        st.stop()
    account_user = get_current_user()
    is_pro = can_access_pro(account_user)
    db_user = account_user or {}
else:
    is_pro = False
    db_user = {
        "email": "Guest",
        "is_admin": False,
        "lifetime_access": False,
        "pro_active": False,
        "email_verified": False,
    }

admin_user = is_admin(db_user)
guest_mode = not signed_in
st.session_state["access_granted"] = is_pro
st.session_state["furuflow_demo_active"] = bool(db_user.get("demo_active"))
set_demo_side_effect_block(st.session_state["furuflow_demo_active"])

with navigation_slot.container():
    selected_route = render_navigation(
        current_route=page,
        signed_in=signed_in,
        is_pro=is_pro,
        is_admin=admin_user,
    )
if selected_route != page:
    st.session_state["current_route"] = selected_route
    st.query_params["page"] = selected_route
    if "pool" in st.query_params:
        del st.query_params["pool"]
    st.rerun()

account_model = account_control_model(account_user if signed_in else None, is_pro=is_pro, is_admin=admin_user)
with account_summary_slot.container():
    st.markdown(f"**{account_model['email']}**")
    st.caption(f"{account_model['plan']} plan · server-authoritative access")
    if signed_in:
        if st.button("Log out", key="logout_button", width="stretch"):
            logout()
            st.rerun()
    else:
        st.caption("Sign in for saved account features. Public research remains available.")

allowed, denial_reason = route_access(page, signed_in=signed_in, is_admin=admin_user)
if not allowed:
    render_page_heading(page)
    if denial_reason == "authentication_required":
        render_status("auth", "Authentication required", "Open Account in the navigation drawer to sign in securely.")
    else:
        render_status("unauthorized", "Unauthorized", "This route is restricted to verified administrators.")
    st.stop()

with st.spinner("Refreshing market data…"):
    df = fetch_enriched_pools(resolver_version=LINK_RESOLVER_VERSION)
market_source_status = str(df.attrs.get("source_status", "live"))
market_source_label = str(df.attrs.get("source_label", "DeFiLlama Yields"))
market_data_status = data_status_from_attrs(df.attrs)
market_freshness = freshness(market_data_status)

watchlist_client: UserSavedPoolsClient | None = None
saved_pool_entries: tuple[SavedPool, ...] = ()
watchlist_load_error: str | None = None
if signed_in:
    try:
        watchlist_client = current_user_saved_pools_client()
        saved_pool_entries = watchlist_client.list_saved_pools()
    except SavedPoolStoreError as exc:
        watchlist_load_error = str(exc)
    except Exception:
        watchlist_load_error = "Saved pools are temporarily unavailable."
st.session_state.watchlist = [entry.pool_id for entry in saved_pool_entries]
saved_pool_ids = frozenset(st.session_state.watchlist)

signal_source = tuple(df.head(SIGNAL_SAMPLE)["pool"].tolist()) if market_source_status == "live" else ()
signal_df = fetch_signal_snapshots(signal_source)
if not signal_df.empty:
    df = df.merge(signal_df, on="pool", how="left")
for col, default in [("signal", "Steady"), ("apy_delta_7", 0.0), ("tvl_delta_7_pct", 0.0), ("apy_volatility", 0.0)]:
    if col not in df.columns:
        df[col] = default
    df[col] = df[col].fillna(default)

if df.empty:
    df["signal_strength"] = pd.Series(dtype="float64")
else:
    df["signal_strength"] = df.apply(
        lambda row: score_signal_movement(
            row["apy_delta_7"],
            row["tvl_delta_7_pct"],
            row["apy_volatility"],
        ),
        axis=1,
    )

watchlist_df = df[df["pool"].isin(saved_pool_ids)].copy()
if market_source_status == "live":
    save_snapshot(df)

signal_history_load_error = False
try:
    history_latest_df = latest_signal_history(limit=12)
    history_trend_df = trend_summary_df(limit=10)
    alert_stats = alert_snapshot()
except SignalHistoryReadError:
    signal_history_load_error = True
    history_latest_df = pd.DataFrame()
    history_trend_df = pd.DataFrame()
    alert_stats = {"signals_24h": 0, "pro_24h": 0, "best_chain": "Unavailable"}

with st.sidebar:
    chains = sorted(df["chain"].dropna().unique().tolist())
    projects = sorted(df["project"].dropna().unique().tolist())
    strategies = sorted(df["strategy_type"].dropna().unique().tolist())
    signals = sorted(df["signal"].dropna().unique().tolist())
    query_filter_model = parse_filter_query(st.query_params) if page in {"Discover", "Pool Detail"} else DEFAULT_FILTERS
    filter_defaults = {
        "market_search": query_filter_model.search,
        "market_chains": [value for value in query_filter_model.chains if value in chains],
        "market_protocols": [value for value in query_filter_model.protocols if value in projects],
        "market_strategies": [value for value in query_filter_model.strategies if value in strategies],
        "market_signals": [value for value in query_filter_model.signals if value in signals],
        "market_stable": query_filter_model.stablecoin_only,
        "market_min_tvl": int(query_filter_model.min_tvl),
        "market_max_risk": query_filter_model.max_risk,
        "market_min_apy": query_filter_model.min_apy,
        "market_sort": query_filter_model.sort_by,
    }
    sort_options = FREE_SORT_OPTIONS + PRO_SORT_OPTIONS if is_pro else FREE_SORT_OPTIONS
    if filter_defaults["market_sort"] not in sort_options:
        filter_defaults["market_sort"] = DEFAULT_FILTERS.sort_by
    for filter_key, filter_value in filter_defaults.items():
        if filter_key not in st.session_state:
            st.session_state[filter_key] = filter_value

    if market_filters_apply(page):
        with st.expander("Discover Filters", expanded=page == "Discover"):
            sidebar_group("Primary controls", "Search the market, narrow the chain universe, or focus on stablecoin-labelled pools.")
            search_text = st.text_input("Search protocol, pool, asset, or chain", key="market_search")
            selected_chains = st.multiselect("Chains", chains, key="market_chains", placeholder="All chains")
            stable_only = st.toggle("Stablecoin pools only", key="market_stable")

        with st.expander("Advanced filters & sorting", expanded=False):
            sidebar_group("Advanced controls", "Refine protocol, strategy, signal, liquidity, yield, and risk.")
            selected_projects = st.multiselect("Protocols", projects, key="market_protocols", placeholder="All protocols")
            selected_strategies = st.multiselect("Strategy type", strategies, key="market_strategies", placeholder="All strategies")
            selected_signals = st.multiselect("Signal", signals, key="market_signals", placeholder="All signals")
            min_tvl = st.slider("Minimum TVL", min_value=0, max_value=500_000_000, step=1_000_000, key="market_min_tvl")
            max_risk = st.slider("Maximum risk score", min_value=1, max_value=100, key="market_max_risk")
            min_apy = st.slider("Minimum APY", min_value=0.0, max_value=250.0, step=0.5, key="market_min_apy")
            sort_by = st.selectbox("Sort by", sort_options, key="market_sort")
            if st.button(
                "Clear all filters",
                key="market_clear_all",
                width="stretch",
                on_click=st.session_state.update,
                args=(
                    {
                        "market_search": DEFAULT_FILTERS.search,
                        "market_chains": [],
                        "market_protocols": [],
                        "market_strategies": [],
                        "market_signals": [],
                        "market_stable": DEFAULT_FILTERS.stablecoin_only,
                        "market_min_tvl": int(DEFAULT_FILTERS.min_tvl),
                        "market_max_risk": DEFAULT_FILTERS.max_risk,
                        "market_min_apy": DEFAULT_FILTERS.min_apy,
                        "market_sort": DEFAULT_FILTERS.sort_by,
                    },
                ),
            ):
                track_research_event("filters_reset", {"action": "clear_all", "view": page})
    else:
        search_text = DEFAULT_FILTERS.search
        selected_chains = []
        selected_projects = []
        selected_strategies = []
        selected_signals = []
        stable_only = DEFAULT_FILTERS.stablecoin_only
        min_tvl = DEFAULT_FILTERS.min_tvl
        max_risk = DEFAULT_FILTERS.max_risk
        min_apy = DEFAULT_FILTERS.min_apy
        sort_by = DEFAULT_FILTERS.sort_by

current_filters = DiscoveryFilters(
    search=search_text,
    chains=tuple(selected_chains),
    protocols=tuple(selected_projects),
    strategies=tuple(selected_strategies),
    signals=tuple(selected_signals),
    stablecoin_only=stable_only,
    min_tvl=float(min_tvl),
    max_risk=int(max_risk),
    min_apy=float(min_apy),
    sort_by=sort_by,
)

if page in {"Discover", "Pool Detail"}:
    encoded_filters = filter_query(current_filters)
    for query_key in ("q", "chains", "protocols", "strategies", "signals", "stable", "min_tvl", "max_risk", "min_apy", "sort"):
        if query_key in encoded_filters:
            if str(st.query_params.get(query_key) or "") != encoded_filters[query_key]:
                st.query_params[query_key] = encoded_filters[query_key]
        elif query_key in st.query_params:
            del st.query_params[query_key]

filtered = apply_discovery_filters(df, current_filters)

filtered = filtered.head(POOL_LIMIT)
full_filtered = filtered.copy()
if not is_pro:
    filtered = filtered.head(FREE_POOL_LIMIT)
watchlist_df = df[df["pool"].isin(saved_pool_ids)].copy()
arb_df = yield_spreads(full_filtered if is_pro else filtered)

content_page = page
active_view: str | None = None
if page == "Discover":
    render_page_heading(page)
    track_research_event("discover_viewed", {"view": str(st.session_state.get("discover_view") or "Opportunities")})
    active_view = st.radio(
        "Discover view",
        DISCOVER_VIEWS,
        horizontal=True,
        label_visibility="collapsed",
        key="discover_view",
    )
    content_page = {"Opportunities": "Scanner", "Signals": "Signals", "Compare": "Compare"}[active_view]
    applied_filter_models = active_filters(current_filters)
    if applied_filter_models:
        track_research_event("filters_applied", {"count": len(applied_filter_models), "view": "Discover"})
        st.caption(f"Active filters ({len(applied_filter_models)}). Activate a chip to remove that filter.")
        with st.container(horizontal=True):
            for filter_id, filter_label in applied_filter_models:
                removed_filters = remove_filter(current_filters, filter_id)
                removed_state = {
                    "market_search": removed_filters.search,
                    "market_chains": list(removed_filters.chains),
                    "market_protocols": list(removed_filters.protocols),
                    "market_strategies": list(removed_filters.strategies),
                    "market_signals": list(removed_filters.signals),
                    "market_stable": removed_filters.stablecoin_only,
                    "market_min_tvl": int(removed_filters.min_tvl),
                    "market_max_risk": removed_filters.max_risk,
                    "market_min_apy": removed_filters.min_apy,
                    "market_sort": removed_filters.sort_by,
                }
                st.button(
                    f"Remove {filter_label}",
                    key=f"remove_filter_{filter_id}",
                    type="tertiary",
                    on_click=st.session_state.update,
                    args=(removed_state,),
                )
    else:
        st.caption("No filters are active. The deterministic default market view is shown.")
elif page == "Research":
    render_page_heading(page)
    active_view = st.radio(
        "Research view",
        RESEARCH_VIEWS,
        horizontal=True,
        label_visibility="collapsed",
        key="research_view",
    )
    content_page = {"Market Map": "Market Map", "Protocols": "Protocol Dashboard"}[active_view]
elif page == "Pro Tools":
    render_page_heading(page)
    active_view = st.radio(
        "Pro tools view",
        PRO_TOOL_VIEWS,
        horizontal=True,
        label_visibility="collapsed",
        key="pro_tools_view",
    )
    content_page = {"Strategy Builder": "Strategy Builder", "Yield Spreads": "Arbitrage"}[active_view]
elif page != "Pool Detail":
    render_page_heading(page)

if market_data_status.availability == "unavailable" and market_filters_apply(page) and page != "Pool Detail":
    render_status(
        "error",
        "Market provider unavailable",
        f"{market_source_label} did not return usable market data. This is not a zero-results state, and no sample values were substituted.",
    )
elif market_data_status.availability == "sample" and market_filters_apply(page) and page != "Pool Detail":
    render_status("degraded", "Development sample mode", f"{market_source_label} is not live market data.")
elif market_data_status.availability == "partial" and market_filters_apply(page) and page != "Pool Detail":
    render_status("degraded", "Partial market data", f"{market_source_label} returned a usable but incomplete response.")
elif market_filters_apply(page) and page != "Pool Detail":
    render_status(
        market_freshness["kind"],
        f"{market_source_label} · {market_freshness['label']}",
        f"{market_freshness['age']}. Market requests use a 15-minute cache.",
    )

if content_page == "Home":
    render_home_page(filtered, full_filtered, watchlist_df, len(saved_pool_entries), alert_stats, history_latest_df, history_trend_df, is_pro)

elif content_page == "Scanner":
    left, right = st.columns([1.6, 1], gap="large")
    with left:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Opportunities", "Visible opportunity set", "Triage the current market slice, then open a contextual Pool Detail view for deeper inspection.")
        top_cards = filtered.head(6)
        if filtered.empty and market_data_status.availability != "unavailable":
            render_status(
                "empty",
                "No pools match the active filters",
                "Remove an active filter or use Clear all filters. The market provider loaded successfully; this is a genuine zero-match result.",
            )
        for start in range(0, len(top_cards), 2):
            cols = st.columns(2, gap="medium")
            for i, (_, row) in enumerate(top_cards.iloc[start : start + 2].iterrows()):
                with cols[i]:
                    render_opportunity_card(
                        row,
                        start + i,
                        row["pool"] in saved_pool_ids,
                        authenticated=signed_in,
                        watchlist_client=watchlist_client,
                        freshness_label=market_freshness["label"],
                        return_view="Opportunities",
                    )
        st.markdown("<div style='height:0.5rem;'></div>", unsafe_allow_html=True)
        table_df = compact_table(filtered)
        if not table_df.empty:
            st.dataframe(
                table_df,
                width="stretch",
                hide_index=True,
                height=540,
                column_config={
                    "APY": st.column_config.NumberColumn(format="%.2f%%", width="small"),
                    "Base": st.column_config.NumberColumn(format="%.2f%%", width="small"),
                    "Rewards": st.column_config.NumberColumn(format="%.2f%%", width="small"),
                    "TVL (USD)": st.column_config.NumberColumn(format="$%.0f", width="medium"),
                    "Risk": st.column_config.NumberColumn(width="small"),
                    "Pool": st.column_config.LinkColumn("Pool", display_text="Open"),
                },
            )
        if is_pro:
            csv = make_download_df(filtered).to_csv(index=False).encode("utf-8")
            st.download_button("Download current table as CSV", csv, file_name="furuflow_scanner.csv", mime="text/csv")
        else:
            st.markdown("<div class='signal-card'><div class='signal-title'>CSV export is Pro</div><div class='signal-copy'>Discover stays open to everyone; export and deeper decision workflows are part of Pro.</div></div>", unsafe_allow_html=True)
            render_billing_action(db_user, label="Unlock CSV export")
        st.markdown("</div>", unsafe_allow_html=True)
    with right:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Discovery guidance", "How to read the cards", "The card layer helps you triage quickly before you open individual pool detail.")
        bullets = [
            ("Risk", "Heuristic score from protocol age, audit confidence, TVL stability, reward dependence, and pool volatility."),
            ("Signal", "Labels such as APY spike, Emerging pool, Farm rotation, and Whale inflow come from recent chart movement."),
            ("Watchlists", "Sign in to use the existing Watch action and tracked-list persistence."),
        ]
        for title, copy in bullets:
            st.markdown(f"<div class='signal-card'><div class='signal-title'>{title}</div><div class='signal-copy'>{copy}</div></div>", unsafe_allow_html=True)
        mini = filtered.head(12).groupby("risk_band", as_index=False).agg(pools=("pool", "count")) if not filtered.empty else pd.DataFrame()
        if not mini.empty:
            pie = px.pie(mini, values="pools", names="risk_band", hole=0.45)
            st.plotly_chart(plotly_theme(pie, 260), width="stretch")
        st.markdown("</div>", unsafe_allow_html=True)

elif content_page == "Compare":
    st.markdown("<div class='panel'>", unsafe_allow_html=True)
    section_header(
        "Discover",
        "Compare selected opportunities",
        f"Select up to {COMPARISON_LIMIT} pools for a bounded comparison of reported yield, liquidity, risk factors, signal context, and missing values.",
    )
    if filtered.empty:
        render_status("empty", "Nothing to compare", "Adjust the market filters to restore at least one visible opportunity.")
    else:
        compare_options = filtered["pool"].astype(str).tolist()
        compare_query = str(st.query_params.get("compare") or "")
        if "compare_selection" not in st.session_state:
            st.session_state["compare_selection"] = [item for item in compare_query.split(",") if item in compare_options][
                :COMPARISON_LIMIT
            ]
        else:
            st.session_state["compare_selection"] = [
                item for item in st.session_state["compare_selection"] if item in compare_options
            ][:COMPARISON_LIMIT]
        label_by_pool = {
            str(row["pool"]): f"{row['project']} · {row['symbol']} · {row['chain']}"
            for _, row in filtered.iterrows()
        }
        selected_compare = st.multiselect(
            "Pools to compare",
            compare_options,
            key="compare_selection",
            max_selections=COMPARISON_LIMIT,
            format_func=lambda pool_id: label_by_pool.get(pool_id, pool_id),
            placeholder="Choose two to four pools",
        )
        if selected_compare:
            st.query_params["compare"] = ",".join(selected_compare)
        elif "compare" in st.query_params:
            del st.query_params["compare"]
        st.caption(f"{len(selected_compare)} of {COMPARISON_LIMIT} comparison slots used. Missing values remain unavailable, never zero-filled.")
        if st.button(
            "Clear comparison",
            key="clear_comparison",
            disabled=not selected_compare,
            on_click=st.session_state.update,
            args=({"compare_selection": []},),
        ):
            track_research_event("comparison_cleared", {"count": len(selected_compare)})
        compared_rows = comparison_rows(df, selected_compare)
        if not compared_rows:
            render_status("empty", "Choose pools to compare", "Select a small set above. The four-pool limit keeps phone and desktop review usable.")
        else:
            track_research_event("comparison_opened", {"count": len(compared_rows), "view": "Compare"})
            matrix_source = pd.DataFrame(compared_rows)
            matrix_source["Opportunity"] = (
                matrix_source["Protocol"] + " · " + matrix_source["Pool / assets"] + " · " + matrix_source["Chain"]
            )
            matrix = matrix_source.set_index("Opportunity").drop(columns=["pool", "Pool / assets"]).T
            st.dataframe(matrix, width="stretch", height=min(420, 120 + 38 * len(matrix.index)))
            st.caption("On narrow screens, the comparison grid scrolls inside its bounded region; the pool summaries below stack vertically.")
            for compared in compared_rows:
                pool_id = compared["pool"]
                with st.expander(f"{compared['Protocol']} · {compared['Pool / assets']} · {compared['Chain']}"):
                    total_compare = f"{compared['APY']:.2f}%" if compared["APY"] is not None else "Unavailable"
                    base_compare = f"{compared['Base APY']:.2f}%" if compared["Base APY"] is not None else "Unavailable"
                    reward_compare = f"{compared['Reward APY']:.2f}%" if compared["Reward APY"] is not None else "Unavailable"
                    st.markdown(
                        f"**Yield:** {total_compare} total · {base_compare} base · {reward_compare} rewards"
                    )
                    st.markdown(f"**Risk:** {compared['Risk']} · **Signal:** {compared['Signal']}")
                    action_cols = st.columns(2)
                    with action_cols[0]:
                        if st.button("View details", key=f"compare_detail_{pool_id}", width="stretch"):
                            track_research_event("pool_detail_opened", {"pool": pool_id, "view": "Compare"})
                            open_pool_detail(pool_id, return_view="Compare")
                            st.rerun()
                    with action_cols[1]:
                        watched = pool_id in saved_pool_ids
                        watch_label = "Remove" if watched else "Watch" if signed_in else "Sign in to save"
                        if st.button(
                            watch_label if watchlist_client is not None or not signed_in else "Watchlist unavailable",
                            key=f"compare_watch_{pool_id}",
                            width="stretch",
                            disabled=not signed_in or watchlist_client is None,
                        ):
                            track_research_event("watchlist_action_initiated", {"pool": pool_id, "action": watch_label})
                            if watch_toggle(pool_id, watched=watched, client=watchlist_client):
                                st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

elif content_page == "Signals":
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
                render_opportunity_card(
                    row,
                    700 + idx,
                    row["pool"] in saved_pool_ids,
                    authenticated=signed_in,
                    watchlist_client=watchlist_client,
                    freshness_label=market_freshness["label"],
                    return_view="Signals",
                )
                st.caption(f"Signal strength: {row['signal_strength']:.1f} • 7d APY Δ: {row['apy_delta_7']:.2f} • 7d TVL Δ: {row['tvl_delta_7_pct']:.2f}%")
        st.markdown("</div>", unsafe_allow_html=True)

    if not is_pro:
        preview = full_filtered[["project", "chain", "symbol", "signal", "signal_strength", "apy_delta_7", "tvl_delta_7_pct"]].copy().head(5)
        preview.columns = ["Protocol", "Chain", "Asset", "Signal", "Strength", "7d APY Δ", "7d TVL Δ %"]
        require_pro("Signals", preview_df=preview, preview_note="Free users can scan pools, but the full signal engine is reserved for Pro.")

    left, right = st.columns([1.2, 1], gap="large")
    with left:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Signal engine", "Rules-based yield movement", "Existing deterministic labels surface APY spikes, farm rotations, emerging pools, and whale inflows from recent pool chart movement.")
        signal_table_source = filtered.copy()
        signal_table_source["pool_detail_url"] = signal_table_source["pool"].map(
            lambda pool_id: pool_detail_url(
                str(pool_id),
                public_origin=os.getenv("FURUFLOW_SESSION_BROKER_PUBLIC_ORIGIN", "http://localhost:8501"),
                return_route="Discover",
                return_view="Signals",
            )
        )
        sig_view = signal_table_source[[column for column, _ in SIGNAL_ENGINE_TABLE_COLUMNS]].copy().head(20)
        sig_view.columns = [label for _, label in SIGNAL_ENGINE_TABLE_COLUMNS]
        st.dataframe(sig_view, width="stretch", hide_index=True, height=560, column_config={"Strength": st.column_config.NumberColumn(format="%.1f"), "7d APY Δ": st.column_config.NumberColumn(format="%.2f"), "7d TVL Δ %": st.column_config.NumberColumn(format="%.2f"), "APY volatility": st.column_config.NumberColumn(format="%.2f"), "Pool": st.column_config.LinkColumn("Pool", display_text="Open")})
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
            st.plotly_chart(plotly_theme(fig, 320), width="stretch")
        st.markdown("</div>", unsafe_allow_html=True)
    render_link_table(filtered.sort_values(["signal_strength", "apy_delta_7", "tvl_delta_7_pct"], ascending=[False, False, False]), "Signals", "Open the strongest recent signal movers directly from the signal view.", limit=10)

elif content_page == "Arbitrage":
    if not is_pro:
        require_pro("Yield Spreads")
    track_research_event("yield_spreads_viewed", {"count": len(arb_df), "view": "Yield Spreads"})
    left, right = st.columns([1.15, 1], gap="large")
    with left:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Yield spreads", "Same asset, different chain", "This view identifies APY gaps across chains for the same displayed asset symbol; it does not label them risk-free arbitrage.")
        if arb_df.empty:
            st.info("No meaningful cross-chain APY gaps are visible for the current filters.")
        else:
            spread_view = arb_df.drop(columns=["Higher pool ID", "Lower pool ID"])
            st.dataframe(spread_view, width="stretch", hide_index=True, height=560, column_config={"Higher APY": st.column_config.NumberColumn(format="%.2f%%"), "Lower APY": st.column_config.NumberColumn(format="%.2f%%"), "APY difference": st.column_config.NumberColumn(format="%.2f"), "Higher link": st.column_config.LinkColumn("Higher-yield pool", display_text="Open"), "Lower link": st.column_config.LinkColumn("Lower-yield pool", display_text="Open")})
            st.caption(f"Both sides use {market_source_label} · {market_freshness['label']} ({market_freshness['age'].lower()}).")
        st.markdown("</div>", unsafe_allow_html=True)
    with right:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Spread triage", "What to check next", "A reported yield difference is not guaranteed profit and does not represent an executable trade.")
        checks = [
            ("Costs not modeled", "Gas, bridging, slippage, lockups, taxes, and execution timing are unavailable here; FuruFlow does not assume they are zero."),
            ("Protocol risk mismatch", "Higher APY often comes with lower audit confidence or a weaker TVL base."),
            ("Reward-token dependence", "Compare reported base and reward APY. Incentive yield can decay or carry token-price exposure."),
        ]
        for title, copy in checks:
            st.markdown(f"<div class='signal-card'><div class='signal-title'>{title}</div><div class='signal-copy'>{copy}</div></div>", unsafe_allow_html=True)
        if not arb_df.empty:
            fig = px.bar(arb_df.head(12), x="Asset", y="APY difference", color="Higher chain", hover_data={"Higher protocol": True, "Lower chain": True, "Lower protocol": True})
            fig.update_yaxes(title="APY difference")
            st.plotly_chart(plotly_theme(fig, 330), width="stretch")
        st.markdown("</div>", unsafe_allow_html=True)
    if not filtered.empty:
        arb_focus = filtered.sort_values(["apy", "tvlUsd"], ascending=[False, False]).head(10)
        render_link_table(arb_focus, "Yield spreads", "Open candidate pools from the visible spread universe without leaving this screen.", limit=10)

elif content_page == "Market Map":
    left, right = st.columns([1, 1], gap="large")
    with left:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Market map", "Risk vs yield field", "A compact look at where the visible opportunity set sits across APY, risk, and capital depth.")
        if not filtered.empty:
            bubble = px.scatter(filtered.head(90), x="risk_score", y="apy", size="tvlUsd", color="chain", hover_name="project", hover_data={"symbol": True, "tvlUsd": ':$,.0f', "risk_score": True, "apy": ':.2f'}, size_max=34)
            bubble.update_traces(marker=dict(line=dict(width=1, color="rgba(255,255,255,0.22)"), opacity=0.8))
            bubble.update_xaxes(title="Risk score")
            bubble.update_yaxes(title="APY %")
            st.plotly_chart(plotly_theme(bubble, 420), width="stretch")
        st.markdown("</div>", unsafe_allow_html=True)
    with right:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Chain map", "Capital and yield concentration", "Treemap sizing is based on aggregate TVL across the currently visible pools.")
        if not filtered.empty:
            chain_df = filtered.groupby("chain", as_index=False).agg(total_tvl=("tvlUsd", "sum"), median_apy=("apy", "median"), pools=("pool", "count"))
            sun = px.treemap(chain_df, path=[px.Constant("Chains"), "chain"], values="total_tvl", color="median_apy", hover_data={"pools": True, "median_apy": ':.2f'})
            st.plotly_chart(plotly_theme(sun, 420), width="stretch")
        st.markdown("</div>", unsafe_allow_html=True)
    render_link_table(filtered, "Market map", "Open the pools you are seeing in the current market field view.", limit=10, sort_cols=["rank_score", "apy", "tvlUsd"])

elif content_page == "Pool Detail":
    selected_pool_id = str(st.session_state.get("selected_pool_id") or st.query_params.get("pool") or "")
    detail_return_route = str(st.session_state.get("pool_return_route") or "Discover")
    detail_return_view = str(st.session_state.get("pool_return_view") or "Opportunities")
    if detail_return_route == "Watchlists":
        detail_back_label = "← Back to Watchlist"
    elif detail_return_route == "Pro Tools":
        detail_back_label = "← Back to Strategy Results"
    elif detail_return_view == "Signals":
        detail_back_label = "← Back to Signals"
    else:
        detail_back_label = "← Back to opportunities"
    pool_options = df[df["pool"].astype(str) == selected_pool_id].copy()
    if pool_options.empty:
        render_page_heading("Pool Detail")
        if selected_pool_id in saved_pool_ids:
            render_status(
                "degraded",
                "Saved pool temporarily unavailable",
                "The canonical saved-pool record is intact, but the current market provider did not return this pool. No APY, TVL, or risk values are inferred.",
            )
            st.code(selected_pool_id, language=None)
            if st.button(
                "Remove from Watchlist",
                key="pool_detail_unavailable_remove",
                disabled=watchlist_client is None,
                width="stretch",
            ):
                if watch_toggle(selected_pool_id, watched=True, client=watchlist_client):
                    return_from_pool_detail()
                    st.rerun()
        else:
            render_status("empty", "Opportunity not available", "Choose an opportunity from Discover to open its contextual detail view.")
        if st.button(detail_back_label, key="pool_detail_empty_back"):
            return_from_pool_detail()
            st.rerun()
    else:
        row = pool_options.iloc[0]
        current_pool_id = str(row["pool"])
        card_state_key = f"pool_card_assets_{current_pool_id}"
        render_page_heading("Pool Detail", detail_label=f"{row['project']} · {row['symbol']}")
        track_research_event("pool_detail_opened", {"pool": current_pool_id, "view": "Pool Detail"})
        if market_data_status.availability == "sample":
            render_status("degraded", "Development sample mode", f"{market_source_label} is not live market data.")
        else:
            render_status(
                market_freshness["kind"],
                f"{market_source_label} · {market_freshness['label']}",
                f"{market_freshness['age']}. Retrieval time is shown because the provider does not supply a pool observation timestamp.",
            )
        if st.button(detail_back_label, key="pool_detail_back"):
            return_from_pool_detail()
            st.rerun()
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Opportunity context", "Pool research", "Inspect identity, reported yield, liquidity, risk factors, provenance, and actions without losing the Discover context.")
        st.markdown(
            f"**Pool / assets:** {row['symbol']}  \n**Protocol:** {row['project']}  \n"
            f"**Chain:** {row['chain']}  \n**Provider pool ID:** `{current_pool_id}`  \n"
            f"**Strategy metadata:** {row['strategy_type']} · **Exposure:** {row['exposure']}"
        )

        cols = st.columns([1.3, 1], gap="large")
        with cols[0]:
            chart, chart_mode = get_pool_chart_with_fallback(row)
            if chart.empty:
                render_status(
                    "empty",
                    "Historical series unavailable",
                    "No live or legitimately stored history exists for this pool. FuruFlow does not generate a trend from a single snapshot.",
                )
            else:
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=chart["timestamp"], y=chart["apy"], mode="lines", name="APY"))
                if chart["tvlUsd"].gt(0).any():
                    fig.add_trace(go.Scatter(x=chart["timestamp"], y=chart["tvlUsd"], mode="lines", name="TVL", yaxis="y2"))
                    fig.update_layout(yaxis2=dict(overlaying="y", side="right", showgrid=False, title="TVL"))
                fig.update_xaxes(title="Time")
                fig.update_yaxes(title="APY %")
                st.plotly_chart(plotly_theme(fig, 430), width="stretch")
                if chart_mode == "stored":
                    st.caption("The provider history endpoint was unavailable; this chart uses real snapshots previously stored by FuruFlow and may be stale.")
                else:
                    st.caption("Reported pool history loaded from the DeFiLlama history endpoint.")

        with cols[1]:
            st.markdown(
                f"<div class='signal-card'><div class='signal-title'>{row['project']} • {row['symbol']}</div><div class='signal-copy'>{row['chain']} • {row['strategy_type']} • {row['signal']}</div></div>",
                unsafe_allow_html=True,
            )

            pool_yield = yield_explanation(row)
            pool_risk = risk_explanation(row)
            stats = pd.DataFrame([
                ["Total APY · reported", f"{pool_yield['total']:.2f}%" if pool_yield["total"] is not None else "Unavailable"],
                ["Base APY · reported", f"{pool_yield['base']:.2f}%" if pool_yield["base"] is not None else "Unavailable"],
                ["Reward APY · reported", f"{pool_yield['reward']:.2f}%" if pool_yield["reward"] is not None else "Unavailable"],
                ["TVL · reported", format_money(row['tvlUsd']) if bool(row.get("tvl_available", True)) else "Unavailable"],
                ["Risk", f"{pool_risk['score']}/100 ({pool_risk['label']})" if pool_risk["score"] is not None else "Unknown · inputs missing"],
                ["Audit confidence", f"{int(row['audit_score'])}/100"],
                ["Protocol age", f"{int(row['protocol_age_score'])}/100"],
                ["TVL stability", f"{int(row['tvl_stability_score'])}/100"],
                ["Pool volatility", f"{int(row['pool_volatility_score'])}/100"],
                ["7d APY change", f"{float(row['apy_delta_7']):.2f}"],
                ["7d TVL change", f"{float(row['tvl_delta_7_pct']):.2f}%"],
            ], columns=["Metric", "Value"])

            st.dataframe(stats, width="stretch", hide_index=True, height=360)
            if pool_yield["mode"] == "aggregate_only":
                st.caption("The provider reports only aggregate APY for this pool; no yield decomposition is implied.")
            elif pool_yield["reconciles"] is False:
                st.warning(
                    f"Reported base plus reward APY differs from reported total APY by {pool_yield['discrepancy']:.2f} percentage points. Values are shown without forcing reconciliation."
                )

            st.markdown("#### Explainable risk factors")
            st.dataframe(pd.DataFrame(pool_risk["factors"]), width="stretch", hide_index=True, height=260)
            st.caption(pool_risk["method"])

            st.markdown("#### Data provenance")
            st.markdown(
                f"**Source:** {market_data_status.source}  \n**Availability:** {market_data_status.availability.title()}  \n"
                f"**Freshness:** {market_freshness['label']} · {market_freshness['age']}  \n"
                "**Value origin:** APY and TVL are provider-reported; FuruFlow risk, rank, and signal labels are derived."
            )

            if admin_user:
                st.markdown("### 📸 Shareable Signal Card")
                st.caption("Admin-only feature.")

                if st.button("Generate Card", key=f"generate_pool_card_{current_pool_id}", width="stretch"):
                    temp_dir = Path(tempfile.gettempdir())
                    preview_path = temp_dir / f"card_preview_{current_pool_id}.png"
                    export_path = temp_dir / f"card_export_{current_pool_id}.png"

                    card_assets = build_signal_card_assets(
                        pool_name=f"{row['project']} — {row['symbol']}",
                        chain=row["chain"],
                        apy=f"{row['apy']:.2f}%",
                        tvl=format_money(row["tvlUsd"]),
                        strength=f"{int(row['signal_strength'])}/100",
                        risk=row["risk_band"],
                        signal=row["signal"],
                        why_text=f"{row['signal']} • {row['scorecard']}",
                        cta="Farm or fade?",
                        sparkline_values=[20, 22, 21, 23, 24, 26, 25, 27],
                        preview_path=str(preview_path),
                        export_path=str(export_path),
                    )

                    st.session_state[card_state_key] = {
                        "pool_id": current_pool_id,
                        **card_assets,
                    }

                card_assets = st.session_state.get(card_state_key)
                if card_assets and card_assets.get("pool_id") == current_pool_id:
                    preview_path = Path(card_assets["preview_path"])
                    export_path = Path(card_assets["export_path"])
                    if preview_path.exists() and export_path.exists():
                        with st.container():
                            st.markdown(
                                "<div style='margin-top:0.35rem; padding:12px; background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); border-radius:16px;'>",
                                unsafe_allow_html=True,
                            )
                            st.image(str(preview_path), width="stretch")
                            st.markdown("</div>", unsafe_allow_html=True)

                        with open(export_path, "rb") as f:
                            st.download_button(
                                "Download Full-Size Card",
                                data=f.read(),
                                file_name="furuflow_signal.png",
                                mime="image/png",
                                width="stretch",
                                key=f"download_pool_card_{current_pool_id}",
                            )

            c1, c2, c3 = st.columns(3)
            with c1:
                watched = row["pool"] in saved_pool_ids
                st.markdown("<div class='watch-wrap'>", unsafe_allow_html=True)
                if st.button(
                    (
                        "Remove from Watchlist"
                        if watched
                        else "Add to Watchlist"
                        if signed_in and watchlist_client is not None
                        else "Watchlist unavailable"
                        if signed_in
                        else "Sign in to save"
                    ),
                    key=f"drill_watch_{current_pool_id}",
                    width="stretch",
                    disabled=not signed_in or watchlist_client is None,
                ):
                    track_research_event("watchlist_action_initiated", {"pool": current_pool_id, "action": "toggle"})
                    if watch_toggle(str(row["pool"]), watched=watched, client=watchlist_client):
                        st.rerun()
                st.markdown("</div>", unsafe_allow_html=True)
            with c2:
                if st.button(
                    "Create alert" if signed_in else "Sign in for alerts",
                    key=f"pool_alert_{current_pool_id}",
                    width="stretch",
                    disabled=not signed_in or market_source_status == "sample",
                    help="Sample-mode pools cannot become persistent alerts." if market_source_status == "sample" else None,
                ):
                    st.session_state.update(alert_creation_state(current_pool_id))
                    st.query_params["page"] = "Alerts"
                    if "pool" in st.query_params:
                        del st.query_params["pool"]
                    st.rerun()
            with c3:
                st.markdown("<div class='pool-wrap'>", unsafe_allow_html=True)
                st.link_button("Open Pool", row["pool_url"], width="stretch")
                st.markdown("</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

elif content_page == "Protocol Dashboard":
    render_protocol_dashboard(filtered)
    top_protocol_pools = filtered.sort_values(["tvlUsd", "apy"], ascending=[False, False]).head(10)
    render_link_table(top_protocol_pools, "Protocol dashboard", "Jump from protocol summary into high-TVL pools without switching sections.", limit=10)

elif content_page == "Strategy Builder":
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
        section_header("Strategy results", "Top matching pools", "Use the selected-pool actions below to save a candidate to Watchlist or open contextual Pool Detail.")
        if strategy_df.empty:
            st.info("No pools match the current strategy builder settings.")
        else:
            strategy_table_source = strategy_df.copy()
            strategy_table_source["pool_detail_url"] = strategy_table_source["pool"].map(
                lambda pool_id: pool_detail_url(
                    str(pool_id),
                    public_origin=os.getenv("FURUFLOW_SESSION_BROKER_PUBLIC_ORIGIN", "http://localhost:8501"),
                    return_route="Pro Tools",
                    return_view="Strategy Builder",
                )
            )
            view = strategy_table_source[[column for column, _ in STRATEGY_RESULTS_TABLE_COLUMNS]].copy()
            view.columns = [label for _, label in STRATEGY_RESULTS_TABLE_COLUMNS]
            st.dataframe(view, width="stretch", hide_index=True, height=520, column_config={"APY": st.column_config.NumberColumn(format="%.2f%%"), "TVL (USD)": st.column_config.NumberColumn(format="$%.0f"), "Pool": st.column_config.LinkColumn("Pool", display_text="Open")})
            strategy_rows = {str(row["pool"]): row for _, row in strategy_df.iterrows()}
            selected_strategy_pool = st.selectbox(
                "Strategy result pool",
                tuple(strategy_rows),
                format_func=lambda pool_id: (
                    f"{strategy_rows[pool_id]['project']} · {strategy_rows[pool_id]['symbol']} · "
                    f"{strategy_rows[pool_id]['chain']}"
                ),
                key="strategy_result_pool",
            )
            selected_is_saved = selected_strategy_pool in saved_pool_ids
            action_left, action_right = st.columns(2)
            with action_left:
                watch_label = "Remove from Watchlist" if selected_is_saved else "Save to Watchlist"
                if st.button(
                    watch_label,
                    key="strategy_result_watch",
                    width="stretch",
                    disabled=watchlist_client is None,
                ):
                    if watch_toggle(selected_strategy_pool, watched=selected_is_saved, client=watchlist_client):
                        st.rerun()
            with action_right:
                if st.button("Open Pool Detail", key="strategy_result_detail", type="primary", width="stretch"):
                    track_research_event("pool_detail_opened", {"pool": selected_strategy_pool, "view": "Strategy Builder"})
                    open_pool_detail(selected_strategy_pool, return_route="Pro Tools", return_view="Strategy Builder")
                    st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

elif content_page == "Activity & Digests":
    render_recaps_page(
        alert_stats,
        history_latest_df,
        history_trend_df,
        is_pro,
        history_load_error=signal_history_load_error,
    )

elif content_page == "Watchlists":
    left, right = st.columns([1.2, 1], gap="large")
    with left:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header(
            "Watchlist",
            "Saved pools",
            "Your durable shortlist, ordered by most recently saved and then canonical pool ID. Current values come from the market provider.",
        )
        if watchlist_load_error:
            render_status("error", "Watchlist unavailable", watchlist_load_error)
        elif not saved_pool_entries:
            render_status("empty", "Your watchlist is empty", "Use Watch on an opportunity card, then return here to review it.")
        else:
            market_rows_by_pool = {str(row["pool"]): row for _, row in df.iterrows()}
            for idx, entry in enumerate(saved_pool_entries):
                current_row = market_rows_by_pool.get(entry.pool_id)
                if current_row is not None:
                    render_opportunity_card(
                        current_row,
                        idx,
                        True,
                        authenticated=True,
                        watchlist_client=watchlist_client,
                        freshness_label=market_freshness["label"],
                        return_route="Watchlists",
                        key_prefix="watchlist",
                    )
                else:
                    st.markdown("#### Saved pool · current data unavailable")
                    st.code(entry.pool_id, language=None)
                    st.caption(
                        "The provider did not return this canonical pool in the current response. "
                        "The saved record remains intact; APY, TVL, risk, and provenance are unavailable."
                    )
                    if entry.created_at:
                        st.caption(f"Saved at {entry.created_at}")
                    if st.button(
                        "Remove from Watchlist",
                        key=f"watchlist_unavailable_remove_{idx}",
                        width="stretch",
                        disabled=watchlist_client is None,
                    ):
                        if watch_toggle(entry.pool_id, watched=True, client=watchlist_client):
                            st.rerun()
                    st.divider()
            st.caption("Saving or removing a pool does not create, change, disable, or delete Alerts.")
        st.markdown("</div>", unsafe_allow_html=True)
    with right:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Watchlist overview", "Where your attention sits", "Quick visual comparison of saved pools that have current market observations.")
        if not watchlist_df.empty:
            chart_watchlist = watchlist_df.sort_values(["apy", "pool"], ascending=[False, True], kind="mergesort")
            fig = px.bar(chart_watchlist, x="project", y="apy", color="risk_band", hover_data={"chain": True, "symbol": True, "tvlUsd": ':$,.0f'})
            fig.update_xaxes(title="Protocol")
            fig.update_yaxes(title="APY %")
            st.plotly_chart(plotly_theme(fig, 300), width="stretch")
            sig_counts = watchlist_df["signal"].value_counts().reset_index()
            sig_counts.columns = ["Signal", "Count"]
            st.dataframe(sig_counts, width="stretch", hide_index=True, height=180)
        else:
            st.info("Current market observations are unavailable for the saved pools.")
        st.markdown("</div>", unsafe_allow_html=True)

elif content_page == "Pricing":
    free_col, pro_col = st.columns(2, gap="large")
    with free_col:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Free", "Explore the market", "Public research remains useful without requiring an account.")
        st.markdown("- Home market briefing\n- Discover opportunities and comparison\n- Research views\n- Public methodology and data status")
        st.markdown("</div>", unsafe_allow_html=True)
    with pro_col:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Pro · $20/month", "Add the intelligence layer", "Existing Pro entitlements unlock signals, deeper ranking, export, and Pro Tools.")
        st.markdown("- Full Signals view\n- Advanced ranking and deeper result depth\n- Strategy Builder and Yield Spreads\n- CSV export")
        if is_pro:
            st.success(f"Pro is active through {billing_access_source(db_user).lower()}.")
        else:
            render_billing_action(db_user, label="Upgrade to FuruFlow Pro")
        st.caption("Paid access appears only after Stripe fulfillment is verified by FuruFlow.")
        st.markdown("</div>", unsafe_allow_html=True)

elif content_page == "Methodology & Data Status":
    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Methodology", "Decision support, not a guarantee", "The current scoring and calculations are preserved in this release.")
        st.markdown(
            "Risk is a heuristic blend of existing protocol-age, audit-confidence, TVL-stability, reward-dependence, and pool-volatility inputs. "
            "APY, signal, ranking, and risk formulas were not changed as part of the shell redesign."
        )
        st.markdown("</div>", unsafe_allow_html=True)
    with right:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Data status", "Source and fallback conventions", "FuruFlow distinguishes current, aging, stale, partial, sample, stored, and unavailable states.")
        if market_data_status.availability == "unavailable":
            render_status("error", "Provider unavailable", f"{market_source_label} returned no usable rows; no sample opportunities were substituted.")
        elif market_data_status.availability == "sample":
            render_status("degraded", "Development sample mode", f"{market_source_label}; values must not be interpreted as live.")
        else:
            render_status(market_freshness["kind"], f"{market_source_label} · {market_freshness['label']}", market_freshness["age"] + ".")
        st.markdown("Market snapshots use a 15-minute cache. Current means ≤20 minutes, Aging means >20–60 minutes, and Stale means >60 minutes. Pool charts identify reported live history or stored observations; a missing series is left unavailable.")
        st.markdown("</div>", unsafe_allow_html=True)

elif content_page == "Alerts":
    alert_target_df = df if market_source_status in {"live", "partial"} else df.iloc[0:0]
    render_alerts_page(alert_target_df, is_pro=is_pro, account_timezone=str(db_user.get("timezone") or "UTC"))

elif content_page == "Account & Billing":
    st.markdown("<div class='panel'>", unsafe_allow_html=True)
    section_header("Account & Billing", str(db_user.get("email") or "Signed-in account"), "Your plan comes from verified FuruFlow account state.")
    current_plan = "Pro" if is_pro else "Free"
    render_status(
        "success" if is_pro else "info",
        f"{current_plan} plan",
        f"Access source: {billing_access_source(db_user)}. Entitlement is reconstructed from trusted account state.",
    )
    billing_status = subscription_summary(db_user)
    if billing_status:
        st.markdown(f"**Subscription:** {billing_status}")
    if st.query_params.get("billing") == "return":
        st.info("Billing returned successfully. Any plan change appears here only after secure provider confirmation.")
    elif st.query_params.get("billing") == "cancelled":
        st.info("Checkout was closed. Your current plan has not been changed by this return page.")
    if not is_pro and not db_user.get("demo_active"):
        render_billing_action(db_user, label="Upgrade to FuruFlow Pro")
    if db_user.get("subscription_status") not in {None, "inactive", "incomplete_expired"}:
        render_billing_action(db_user, label="Manage billing", portal=True)
    st.caption("Account access remains available if Stripe is temporarily unavailable; billing actions may be retried later.")
    st.markdown("</div>", unsafe_allow_html=True)

elif content_page == "Admin":
    if not admin_user:
        render_status("unauthorized", "Unauthorized", "Verified administrator access is required.")
        st.stop()
    render_admin_access_panel(db_user)
    with st.expander("Link resolver diagnostic", expanded=False):
        pendle_debug = df[
            (df["project"].astype(str).str.lower() == "pendle")
            & (df["chain"].astype(str) == "Arbitrum")
            & (df["symbol"].astype(str) == "SUSDAI")
        ][["pool", "project", "chain", "symbol", "pool_url"]].head(10)
        st.dataframe(pendle_debug, width="stretch", hide_index=True)
