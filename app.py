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
from beta_readiness import beta_diagnostics
from auth_session import render_pending_session_activation
from automation.store import AutomationStoreError
from auth_service import can_access_pro, claim_session, get_current_user, is_admin, logout, validate_session
from utils.external_side_effects import set_demo_side_effect_block
from history_store import load_history, save_snapshot
from evidence_confidence import (
    assess_confidence,
    evidence_from_mapping,
    historical_evidence,
    serialize_evidence,
)
from engine.performance import SignalHistoryReadError, alert_snapshot, latest_signal_history, trend_summary_df
from engine.recap import build_daily_recap, build_weekly_recap
from engine.scoring import (
    label_pool_risk as label_risk,
    score_pool,
    score_pool_volatility,
    score_signal_movement,
    score_tvl_stability,
)
from csv_export import CSV_UPGRADE_MESSAGE, prepare_csv_export
from market_research import (
    COMPARISON_LIMIT,
    COMPARISON_SCENARIOS,
    DEFAULT_FILTERS,
    FILTER_QUERY_KEYS,
    NON_STEADY_CLASSIFICATIONS_LABEL,
    OBSERVED_SIGNAL_EVIDENCE_LABEL,
    POOLS_EVALUATED_LABEL,
    ComparisonWeights,
    DiscoveryFilters,
    active_filters,
    all_pools_filters,
    apply_discovery_filters,
    comparison_rows,
    comparison_analysis,
    data_status_from_attrs,
    filter_query,
    freshness,
    market_status_summary,
    parse_filter_query,
    pool_universe,
    remove_filter,
    risk_explanation,
    sensitive_query_keys,
    strategy_match_explanation,
    track_research_event,
    update_comparison,
    yield_explanation,
    yield_spreads,
)
from market_data import normalize_provider_numbers, provider_pool_frame
from product_capabilities import (
    Capability,
    PLANNED_TIERS,
    ProductCapabilities,
    can_export_csv,
    can_use_advanced_sorting,
    can_use_alerts,
    can_use_full_signals,
    can_use_pro_tools,
    can_use_research_modeling,
    can_use_watchlists,
    capability_presentation,
    capabilities_from_current_entitlement,
    required_tier_name,
)
from saved_pools import (
    SavedPool,
    SavedPoolStoreError,
    UserSavedPoolsClient,
    current_user_saved_pools_client,
)
from signal_visualization import build_signal_scatter
from ui_shell import (
    DISCOVER_VIEWS,
    OPPORTUNITIES_TABLE_COLUMNS,
    PRO_TOOL_VIEWS,
    SIGNAL_ENGINE_TABLE_COLUMNS,
    STRATEGY_RESULTS_TABLE_COLUMNS,
    account_control_model,
    alert_creation_state,
    canonical_route,
    inject_shell_css,
    market_filters_apply,
    pool_detail_back_state,
    pool_detail_anchor,
    pool_detail_query_context,
    pool_detail_state,
    research_selection_state,
    research_selection_state_many,
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
    alert_creation_prerequisites_met,
    alert_explanation,
    current_user_notification_client,
    deterministic_pool_options,
    format_alert_time,
    pool_label_mapping,
    safe_pool_label,
)

APP_NAME = "FuruFlow"
APP_VERSION = "v8.1"
APP_TAGLINE = "Research DeFi yields with clearer context."
LINK_RESOLVER_VERSION = "2026-03-28-linkfix-2"
POOL_LIMIT = 400
FREE_POOL_LIMIT = 10
FREE_SORT_OPTIONS = ["Investigation priority", "Highest APY", "Largest TVL"]
PRO_SORT_OPTIONS = ["FuruFlow rank", "Lowest risk", "Highest 24h volume", "Largest signal move"]
TIMEOUT = 18
SIGNAL_SAMPLE = 16
BETA_DIAGNOSTICS = beta_diagnostics(os.environ, app_version=APP_VERSION)
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
                    chart[col] = pd.NA
                chart[col] = pd.to_numeric(chart[col], errors="coerce")
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
            observed = derive_chart_signal(pool_id, chart)
            if "signal" in observed:
                rows.append(observed)

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
    required = {"timestamp", "apy", "tvlUsd"}
    if not required.issubset(chart.columns):
        return {"pool": pool_id}
    recent = chart.dropna(subset=["timestamp", "apy", "tvlUsd"]).sort_values("timestamp").tail(30).copy()
    if len(recent) < 2:
        return {"pool": pool_id}
    recent["apy_change"] = recent["apy"].pct_change(fill_method=None).replace([float("inf"), float("-inf")], pd.NA)
    recent["tvl_change"] = recent["tvlUsd"].pct_change(fill_method=None).replace([float("inf"), float("-inf")], pd.NA)
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
        **serialize_evidence(historical_evidence(recent, signal_history_available=True)),
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
        data[column], data[availability_name] = normalize_provider_numbers(data[column])

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


def render_link_table(
    source_df: pd.DataFrame,
    title: str,
    description: str,
    *,
    limit: int = 8,
    sort_cols: list[str] | None = None,
    return_route: str = "Discover",
    return_view: str = "Opportunities",
) -> None:
    st.markdown("<div class='panel'>", unsafe_allow_html=True)
    section_header(title, "Pool links", description)
    if source_df.empty:
        st.info("No pool links are available for the current filter set.")
    else:
        view = source_df.copy()
        if sort_cols:
            ascending = [False] * len(sort_cols)
            view = view.sort_values(sort_cols, ascending=ascending)
        cols = [
            "pool",
            "project",
            "chain",
            "symbol",
            "apy",
            "evidence_coverage",
            "confidence_level",
            "risk_band",
            "data_freshness",
        ]
        cols = [c for c in cols if c in view.columns]
        link_view = view[cols].head(limit).copy()
        labels = {
            "pool": "Pool",
            "project": "Protocol",
            "chain": "Chain",
            "symbol": "Asset",
            "apy": "APY",
            "evidence_coverage": "Evidence",
            "confidence_level": "Confidence",
            "risk_band": "Risk",
            "data_freshness": "Freshness",
        }
        render_internal_pool_table(
            link_view,
            tuple((column, labels[column]) for column in cols),
            return_route=return_route,
            return_view=return_view,
            formats={"apy": "percent"},
            max_height=min(120 + 42 * len(link_view), 420),
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


def compact_table(
    df: pd.DataFrame,
    *,
    return_route: str = "Discover",
    return_view: str = "Opportunities",
) -> pd.DataFrame:
    source = df.copy()
    for value_col, available_col in (
        ("apy", "apy_available"),
        ("apyBase", "apy_base_available"),
        ("apyReward", "apy_reward_available"),
        ("tvlUsd", "tvl_available"),
    ):
        if available_col in source:
            source.loc[~source[available_col].astype(bool), value_col] = pd.NA
    if "signal_available" in source and "signal" in source:
        source.loc[~source["signal_available"].astype(bool), "signal"] = "Insufficient evidence"
    table = source[[column for column, _ in OPPORTUNITIES_TABLE_COLUMNS]].copy()
    table.columns = [label for _, label in OPPORTUNITIES_TABLE_COLUMNS]
    return table


def _internal_table_value(value: Any, value_format: str) -> str:
    try:
        missing = bool(pd.isna(value))
    except (TypeError, ValueError):
        missing = value is None
    if missing:
        return "Unavailable"
    if value_format == "percent":
        return f"{float(value):.2f}%"
    if value_format == "money":
        return f"${float(value):,.0f}"
    if value_format == "number":
        return f"{float(value):,.1f}"
    return str(value)


def _internal_pool_link_label(row: pd.Series, fallback: str) -> str:
    """Prefer recognizable pool identity over an opaque or generic link label."""

    protocol = row.get("project", row.get("Protocol"))
    asset = row.get("symbol", row.get("Asset"))
    if protocol is not None and asset is not None and not pd.isna(protocol) and not pd.isna(asset):
        return f"{protocol} · {asset}"
    return fallback


def render_internal_pool_table(
    source_df: pd.DataFrame,
    columns: tuple[tuple[str, str], ...],
    *,
    return_route: str,
    return_view: str,
    link_columns: dict[str, str] | None = None,
    formats: dict[str, str] | None = None,
    discover_state: dict[str, str] | None = None,
    max_height: int = 560,
) -> None:
    """Render bounded, same-tab internal links without Streamlit LinkColumn."""

    link_columns = link_columns or {"pool": "Open"}
    formats = formats or {}
    origin = os.getenv("FURUFLOW_SESSION_BROKER_PUBLIC_ORIGIN", "http://localhost:8501")
    headers = "".join(f"<th>{html.escape(label)}</th>" for _, label in columns)
    body: list[str] = []
    for _, row in source_df.iterrows():
        cells: list[str] = []
        for column, _ in columns:
            if column in link_columns:
                value = row.get(column)
                link_label = _internal_pool_link_label(row, link_columns[column])
                cell = (
                    "Unavailable"
                    if value is None or (not isinstance(value, str) and pd.isna(value))
                    else pool_detail_anchor(
                        str(value),
                        public_origin=origin,
                        return_route=return_route,
                        return_view=return_view,
                        label=link_label,
                        discover_state=discover_state,
                    )
                )
            else:
                cell = html.escape(_internal_table_value(row.get(column), formats.get(column, "text")))
            cells.append(f"<td>{cell}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    st.markdown(
        f'<div class="ff-responsive-table" style="max-height:{max_height}px"><table class="ff-pool-table">'
        f"<thead><tr>{headers}</tr></thead><tbody>{''.join(body)}</tbody></table></div>",
        unsafe_allow_html=True,
    )


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
    if return_route != "Discover":
        clear_discover_query_state()
    st.query_params["page"] = "Pool Detail"
    st.query_params["pool"] = str(pool_id)


def clear_discover_query_state() -> None:
    for key in FILTER_QUERY_KEYS:
        if key in st.query_params:
            del st.query_params[key]


DISCOVER_NAVIGATION_STATE_KEY = "_discover_navigation_state"


def persist_discover_navigation_state(filters: DiscoveryFilters, view: str) -> None:
    """Keep public Discover controls across same-session internal navigation."""

    if view not in DISCOVER_VIEWS:
        return
    st.session_state[DISCOVER_NAVIGATION_STATE_KEY] = {
        "filters": filter_query(filters),
        "view": view,
    }


def restore_discover_navigation_state(*, view: str | None = None) -> None:
    """Restore only allowlisted Discover state when an internal route returns."""

    persisted = st.session_state.get(DISCOVER_NAVIGATION_STATE_KEY)
    persisted_filters = persisted.get("filters") if isinstance(persisted, dict) else None
    if isinstance(persisted_filters, dict):
        clear_discover_query_state()
        for key, value in persisted_filters.items():
            if key in FILTER_QUERY_KEYS and isinstance(value, str) and value:
                st.query_params[key] = value
    persisted_view = str(persisted.get("view") or "") if isinstance(persisted, dict) else ""
    restored_view = view or persisted_view
    if restored_view in DISCOVER_VIEWS:
        st.session_state["discover_view"] = restored_view


def reset_discover_filters() -> None:
    """Restore the canonical Discover defaults from any actionable empty state."""

    st.session_state.update(
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
        }
    )
    clear_discover_query_state()


def refresh_market_data() -> None:
    """Clear only bounded public market caches before a user-requested retry."""

    fetch_enriched_pools.clear()
    fetch_pool_chart.clear()
    fetch_signal_snapshots.clear()


def start_alert_creation(pool_id: str) -> None:
    st.session_state.update(alert_creation_state(pool_id))
    st.session_state["alert_create_request_key"] = uuid.uuid4().hex
    clear_discover_query_state()
    st.query_params["page"] = "Alerts"
    if "pool" in st.query_params:
        del st.query_params["pool"]


def open_research(pool_id: str) -> None:
    selected = tuple(st.session_state.get("research_selection") or ())
    st.session_state.update(research_selection_state(pool_id, selected))
    clear_discover_query_state()
    st.query_params["page"] = "Research"
    if "pool" in st.query_params:
        del st.query_params["pool"]


def open_research_many(pool_ids: tuple[str, ...]) -> None:
    selected = tuple(st.session_state.get("research_selection") or ())
    st.session_state.update(research_selection_state_many(pool_ids, selected))
    clear_discover_query_state()
    st.query_params["page"] = "Research"
    if "pool" in st.query_params:
        del st.query_params["pool"]


def remove_research_pool(pool_id: str) -> None:
    """Remove a canonical pool through a widget callback-safe state update."""

    selected = tuple(st.session_state.get("research_selection") or ())
    st.session_state["research_selection"] = list(
        update_comparison(selected, str(pool_id), selected_state=False)
    )


def add_research_pool_from_picker() -> None:
    """Add the picker value to canonical Research state by immutable pool ID."""

    pool_id = str(st.session_state.get("research_pool_addition") or "")
    if not pool_id:
        return
    selected = tuple(st.session_state.get("research_selection") or ())
    st.session_state["research_selection"] = list(
        update_comparison(selected, pool_id, selected_state=True)
    )


def go_to_route(route: str, *, view: str | None = None) -> None:
    st.session_state["current_route"] = route
    if route == "Discover":
        restore_discover_navigation_state(view=view)
    st.query_params["page"] = route
    for key in ("pool", "return_route", "return_view"):
        if key in st.query_params:
            del st.query_params[key]
    if route != "Discover":
        clear_discover_query_state()


def return_from_pool_detail() -> None:
    destination = pool_detail_back_state(st.session_state)
    route = destination["current_route"]
    st.session_state["current_route"] = route
    if route == "Discover":
        st.session_state["discover_view"] = destination["current_view"]
    elif route == "Pro Tools":
        st.session_state["pro_tools_view"] = destination["current_view"]
    st.query_params["page"] = route
    for key in ("pool", "return_route", "return_view"):
        if key in st.query_params:
            del st.query_params[key]
    if route != "Discover":
        clear_discover_query_state()


def strategy_builder_filter(df: pd.DataFrame, stable_only: bool, min_apy: float, min_tvl: float, max_risk: int, signal_pref: str) -> pd.DataFrame:
    out = df.copy()
    if stable_only:
        out = out[out["stablecoin"] == True]
    out = out[(out["apy"] >= min_apy) & (out["tvlUsd"] >= min_tvl) & (out["risk_score"] <= max_risk)]
    if signal_pref != "Any":
        out = out[out["signal"] == signal_pref]
    return out.sort_values(["rank_score", "apy", "tvlUsd"], ascending=[False, False, False]).head(25)


def require_pro(feature_name: str, preview_df: pd.DataFrame | None = None, preview_note: str | None = None) -> None:
    planned_pro = next(tier for tier in PLANNED_TIERS if tier.name == "Pro")
    st.markdown("<div class='panel'>", unsafe_allow_html=True)
    section_header(
        f"{planned_pro.name} · {planned_pro.monthly_price}",
        f"Unlock {feature_name}",
        "Free discovery and Pool Detail remain available. This advanced workflow belongs to the canonical top-tier capability set.",
    )
    st.markdown(
        """
<div class='signal-card'>
  <div class='signal-title'>Limited advanced analysis</div>
  <div class='signal-copy'>
    Free users can discover pools, inspect Pool Detail, and review basic signal evidence.<br><br>
    <b>The planned Pro capability set adds:</b><br>
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
    st.warning(f"Material {feature_name.lower()} conditions can change quickly. The advanced view is decision support, not a prediction.")
    if preview_note:
        st.caption(preview_note)
    if preview_df is not None and not preview_df.empty:
        st.markdown("### Preview")
        st.dataframe(preview_df.head(3), width="stretch", hide_index=True, height=180)
    st.markdown(
        """
**The planned Pro capability set includes:**
- Yield-spread signals
- Whale-flow and signal engine views
- Advanced ranking and sorting
- Full Discover depth and CSV export
- Advanced research and Pro Tools
"""
    )
    st.caption(f"Planned {planned_pro.name} pricing is {planned_pro.monthly_price}. The new four-tier checkout is not enabled yet.")
    if st.session_state.get("auth_email"):
        st.caption(f"Signed in as {st.session_state.get('auth_email')}")
    else:
        st.info("Keep browsing in free mode, or sign in when you're ready to unlock Pro.")
    render_billing_action(get_current_user(), label="Current Pro compatibility checkout — $20/month")
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
    watch_allowed: bool,
    alert_allowed: bool,
    research_allowed: bool,
    watchlist_client: UserSavedPoolsClient | None,
    freshness_label: str,
    return_route: str = "Discover",
    return_view: str = "Opportunities",
    key_prefix: str = "discover",
    alerts_available: bool = True,
) -> None:
    signal = row.get("signal", "Steady") if bool(row.get("signal_available", False)) else "Insufficient evidence"
    apy_text = f"{row['apy']:.2f}%" if bool(row.get("apy_available", True)) else "Unavailable"
    tvl_text = format_money(row["tvlUsd"]) if bool(row.get("tvl_available", True)) else "Unavailable"
    evidence_text = str(row.get("evidence_coverage") or "No evidence")
    confidence_text = str(row.get("confidence_level") or "Unavailable")
    risk_text = f"{row.get('risk_band', 'Unknown')} · {int(row['risk_score'])}/100"
    safe_project = html.escape(str(row.get("project") or "Unknown"))
    safe_symbol = html.escape(str(row.get("symbol") or "Unknown"))
    safe_chain = html.escape(str(row.get("chain") or "Unknown"))
    safe_protocol_tier = html.escape(str(row.get("protocol_tier") or "Unknown"))
    safe_protocol_badge = html.escape(str(row.get("protocol_badge") or "?"))
    safe_strategy = html.escape(str(row.get("strategy_type") or "Unknown"))
    safe_signal = html.escape(signal)
    safe_freshness = html.escape(freshness_label)
    card_html = f"""
    <div class="ff-card-wrap">
        <div class="ff-opp-top">
            <div>
                <div class="ff-opp-name">{safe_project}</div>
                <div class="ff-opp-sub">{safe_symbol} • {safe_chain} • {safe_protocol_tier}</div>
            </div>
            <div class="ff-protocol-dot">{safe_protocol_badge}</div>
        </div>
        {'<span class="ff-watch-pill">★ Watched</span>' if watched else ''}
        <div class="ff-badge-row">
            <span class="ff-badge">TVL: {html.escape(tvl_text)}</span>
            <span class="ff-badge">{safe_strategy}</span>
            <span class="ff-badge">Signal: {safe_signal}</span>
            <span class="ff-badge">Data: {safe_freshness}</span>
        </div>
        <div class="ff-metric-strip">
            <div class="ff-metric-box"><div class="ff-metric-mini-label">Reported APY</div><div class="ff-metric-mini-value">{html.escape(apy_text)}</div></div>
            <div class="ff-metric-box"><div class="ff-metric-mini-label">Evidence</div><div class="ff-metric-mini-value">{html.escape(evidence_text)}</div></div>
            <div class="ff-metric-box"><div class="ff-metric-mini-label">Confidence</div><div class="ff-metric-mini-value">{html.escape(confidence_text)}</div></div>
            <div class="ff-metric-box"><div class="ff-metric-mini-label">Risk</div><div class="ff-metric-mini-value">{html.escape(risk_text)}</div></div>
        </div>
    </div>
    """
    st.html(card_html)
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown("<div class='watch-wrap'>", unsafe_allow_html=True)
        label = (
            "Sign in to save"
            if not authenticated
            else f"Watchlists · {required_tier_name(Capability.WATCHLISTS)}"
            if not watch_allowed
            else "Remove"
            if watched
            else "Watch"
        )
        if st.button(
            label if watchlist_client is not None or not watch_allowed else "Watchlist unavailable",
            key=f"{key_prefix}_watch_{idx}",
            width="stretch",
            disabled=not authenticated or not watch_allowed or watchlist_client is None,
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
    with c3:
        if st.button(
            "Sign in for alerts"
            if not authenticated
            else f"Alerts · {required_tier_name(Capability.ALERTS)}"
            if not alert_allowed
            else "Create alert",
            key=f"{key_prefix}_alert_{idx}_{row['pool']}",
            width="stretch",
            disabled=not authenticated or not alert_allowed or not alerts_available,
            help="Sample-mode pools cannot become persistent alerts." if not alerts_available else None,
        ):
            start_alert_creation(str(row["pool"]))
            st.rerun()
    with c4:
        if st.button(
            "Research" if research_allowed else f"Research · {required_tier_name(Capability.RESEARCH_MODELING)}",
            key=f"{key_prefix}_research_{idx}_{row['pool']}",
            width="stretch",
            disabled=not research_allowed,
        ):
            open_research(str(row["pool"]))
            st.rerun()


def render_home_page(
    market_df: pd.DataFrame,
    opportunity_df: pd.DataFrame,
    *,
    watchlist_count: int,
    capabilities: ProductCapabilities,
    signed_in: bool,
    source_label: str,
    freshness_label: str,
) -> None:
    indexed_count = len(pool_universe(market_df))
    opportunity_count = len(opportunity_df)
    non_steady_classification_count = (
        int(opportunity_df.loc[opportunity_df["signal_available"].astype(bool), "signal"].ne("Steady").sum())
        if opportunity_count
        else 0
    )

    st.markdown(
        """
        <section class="hero-shell"><div class="hero-inner">
          <div class="eyebrow">DeFi yield decision support</div>
          <div class="hero-title">Find → Understand → Compare → Monitor → Act</div>
          <div class="hero-subtitle">Investigate what providers report now, test it against observed evidence and risk context, then keep the same pool identity through comparison and monitoring. FuruFlow does not forecast profit or recommend an investment.</div>
        </div></section>
        """,
        unsafe_allow_html=True,
    )
    plan = capability_presentation(capabilities)
    render_status(
        "info",
        "Keep the decision signals separate",
        "Opportunity is not confidence, confidence is not safety, and none of them is expected profit. Open Pool Detail before acting on an external protocol.",
    )

    section_header(
        "Market overview",
        "What the current snapshot can support",
        f"Provider: {source_label} · {freshness_label}. These are current market facts and observed classifications, not forecasts.",
    )
    stat_columns = st.columns(4)
    with stat_columns[0]:
        stat_card("Indexed pools", f"{indexed_count:,}", "Canonical pools in the current provider response")
    with stat_columns[1]:
        stat_card("Current opportunities", f"{opportunity_count:,}", "Pools matching the current opportunity filters")
    with stat_columns[2]:
        stat_card(
            NON_STEADY_CLASSIFICATIONS_LABEL,
            f"{non_steady_classification_count:,}",
            "Visible opportunity pools whose current rules-based classification is not Steady",
        )
    with stat_columns[3]:
        watch_enabled = signed_in and can_use_watchlists(capabilities)
        if watch_enabled:
            stat_card("Watched pools", f"{watchlist_count:,}", "Durable saved pools for this account")
        else:
            stat_card("Current plan", str(plan["plan"]), "Review included and unavailable capabilities in Account")

    st.markdown("<div class='panel'>", unsafe_allow_html=True)
    section_header(
        "Opportunities to investigate",
        "Open one pool and understand the evidence",
        "Candidates meet the current opportunity criteria and ordering. Inclusion is a research starting point, not an expected-profit claim.",
    )
    if opportunity_df.empty:
        render_status("empty", "No current opportunities", "Adjust Discover filters or browse All Pools; no placeholder rows were substituted.")
    else:
        home_source = opportunity_df.head(8).copy()
        render_internal_pool_table(
            home_source,
            (
                ("pool", "Pool"),
                ("symbol", "Asset"),
                ("chain", "Network"),
                ("project", "Protocol"),
                ("apy", "APY"),
                ("tvlUsd", "TVL (USD)"),
                ("evidence_coverage", "Evidence"),
                ("confidence_level", "Confidence"),
                ("risk_band", "Risk"),
                ("data_freshness", "Freshness"),
            ),
            return_route="Home",
            return_view="Home",
            link_columns={"pool": "Open Pool"},
            formats={"apy": "percent", "tvlUsd": "money"},
            max_height=320,
        )
    st.markdown("</div>", unsafe_allow_html=True)

    section_header(
        "Your monitoring",
        "Return to what you chose to track",
        "Watchlists preserve your chosen canonical pools. Alerts remain separate durable rules and require their accepted account and Telegram prerequisites.",
    )
    monitor_summary = st.columns(2)
    with monitor_summary[0]:
        stat_card(
            "Watched pools" if watch_enabled else "Watchlists",
            f"{watchlist_count:,}" if watch_enabled else f"{required_tier_name(Capability.WATCHLISTS)} tier",
            "Saved for this account" if watch_enabled else "Durable monitoring is not included in the current capability set",
        )
    alerts_enabled_for_user = signed_in and can_use_alerts(capabilities)
    with monitor_summary[1]:
        stat_card(
            "Alert workflow",
            "Available" if alerts_enabled_for_user else f"{required_tier_name(Capability.ALERTS)} tier",
            "Open Alerts to verify Telegram readiness and rule state" if alerts_enabled_for_user else "Alert rules remain gated without exposing protected data",
        )

    section_header(
        "Next actions",
        "Continue the investigation",
        f"Current plan: {plan['plan']}. Available controls route to the existing workflows; gated controls name the required tier.",
    )
    action_columns = st.columns(3)
    if action_columns[0].button("Discover Pools", key="home_browse_all", type="primary", width="stretch"):
        go_to_route("Discover", view="All Pools")
        st.rerun()
    if action_columns[1].button("View Signals", key="home_signals", width="stretch"):
        go_to_route("Signals")
        st.rerun()
    research_enabled = can_use_research_modeling(capabilities)
    research_tier = required_tier_name(Capability.RESEARCH_MODELING)
    if action_columns[2].button(
        "Compare Pools" if research_enabled else f"Comparison · {research_tier}",
        key="home_research",
        width="stretch",
        disabled=not research_enabled,
        help=None if research_enabled else f"The planned {research_tier} capability adds full comparison modeling.",
    ):
        go_to_route("Research")
        st.rerun()
    watchlist_tier = required_tier_name(Capability.WATCHLISTS)
    monitor_columns = st.columns(2)
    if monitor_columns[0].button(
        "Open Watchlist" if watch_enabled else f"Watchlists · {watchlist_tier}",
        key="home_watchlist",
        width="stretch",
        disabled=not watch_enabled,
        help=None if watch_enabled else f"The planned {watchlist_tier} capability adds durable Watchlists.",
    ):
        go_to_route("Watchlists")
        st.rerun()
    alerts_tier = required_tier_name(Capability.ALERTS)
    if monitor_columns[1].button(
        "Open Alerts" if alerts_enabled_for_user else f"Alerts · {alerts_tier}",
        key="home_alerts",
        width="stretch",
        disabled=not alerts_enabled_for_user,
        help=None if alerts_enabled_for_user else f"The planned {alerts_tier} capability adds Telegram monitoring rules.",
    ):
        go_to_route("Alerts")
        st.rerun()


def render_recaps_page(
    alert_stats: dict[str, Any],
    history_latest_df: pd.DataFrame,
    history_trend_df: pd.DataFrame,
    full_signal_access: bool,
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
        section_header("Weekly recap preview", "Recurring patterns and momentum", "A higher-level summary of repeated observations and movement context.")
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
        if not full_signal_access:
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
    full_signal_access: bool,
    account_timezone: str,
    creation_allowed: bool,
    existing: UserAlert | None = None,
) -> None:
    if not pool_labels and existing is None:
        render_state(
            "No current pool targets",
            "Live pool identity is unavailable, so FuruFlow will not create an alert against guessed or sample data.",
        )
        return

    options = list(deterministic_pool_options(pool_labels))
    prefill = str(st.session_state.get("alert_prefill_pool_id") or "")
    if existing and existing.target_pool_id not in options:
        options.insert(0, existing.target_pool_id)
    if existing:
        selected_default = existing.target_pool_id
    elif prefill and prefill not in options:
        for key in ("alert_form_mode", "alert_prefill_pool_id", "alert_create_request_key"):
            st.session_state.pop(key, None)
        render_state(
            "Choose the exact pool again",
            "The carried alert target is not a current canonical pool ID. Start a new alert and choose the exact pool; FuruFlow will not guess from a display label.",
        )
        return
    else:
        selected_default = prefill or options[0]
    tier_options = ["all", "free"]
    if full_signal_access or (existing and existing.signal_tier == "pro"):
        tier_options.append("pro")
    timezone_options = list(ALERT_TIMEZONES)
    if account_timezone and account_timezone not in timezone_options:
        timezone_options.append(account_timezone)
    selected_timezone = existing.timezone_name if existing else account_timezone or "UTC"
    if selected_timezone not in timezone_options:
        selected_timezone = "UTC"

    if existing:
        form_key = f"alert_form_{existing.id}"
    else:
        request_key = str(st.session_state.get("alert_create_request_key") or uuid.uuid4().hex)
        st.session_state["alert_create_request_key"] = request_key
        form_key = f"alert_form_create_{request_key}"
    with st.form(form_key):
        st.markdown(f"#### {'Edit pool alert' if existing else 'Create pool alert'}")
        target_pool_id = st.selectbox(
            "Pool",
            options,
            index=options.index(selected_default),
            format_func=lambda pool_id: safe_pool_label(pool_id, pool_labels),
            disabled=existing is not None,
            help="Type to search meaningful protocol, asset, and network labels. Targets are ordered deterministically.",
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
            disabled=existing is None and not creation_allowed,
        )

    if not submitted:
        return
    if existing is None and not creation_allowed:
        st.error("A verified Telegram connection is required before an alert can be created.")
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


def _clear_alert_creation_intent() -> None:
    if st.session_state.get("alert_form_mode") == "create":
        st.session_state.pop("alert_form_mode", None)
    st.session_state.pop("alert_create_request_key", None)


def render_alerts_page(
    df: pd.DataFrame,
    *,
    alerts_entitled: bool,
    full_signal_access: bool,
    account_timezone: str,
) -> None:
    pool_labels = (
        pool_label_mapping(
            df[["pool", "project", "symbol", "chain", "strategy_type", "exposure"]].to_dict("records")
        )
        if not df.empty
        else {}
    )
    try:
        client = current_user_notification_client()
        telegram_status = client.telegram_status()
        alerts = [UserAlert.from_row(row) for row in client.list_alerts()]
    except AutomationStoreError:
        _clear_alert_creation_intent()
        render_status(
            "degraded",
            "Alert controls temporarily unavailable",
            "The authenticated alert service could not be reached. Market research remains available, and no alert state was guessed.",
        )
        return

    linked = telegram_status.get("available") is True
    can_create_alert = alert_creation_prerequisites_met(
        alerts_entitled=alerts_entitled,
        telegram_status=telegram_status,
    )
    if not can_create_alert:
        _clear_alert_creation_intent()
    status_kind = "success" if linked else "warning"
    status_title = "Telegram connected" if linked else "Telegram connection required"
    status_copy = (
        "Notifications use your verified Telegram connection. Routing identifiers and bot credentials are never shown here."
        if linked
        else "A trusted operator must verify and link your Telegram destination before an alert can be created or resumed."
    )
    render_status(status_kind, status_title, status_copy)
    st.caption(
        "Alerts are durable notification rules. Saving a pool to Watchlist does not create an alert, "
        "and pausing an alert does not remove the pool from Watchlist."
    )

    action_cols = st.columns([1, 2])
    with action_cols[0]:
        if st.button(
            "Create alert",
            key="alerts_create",
            type="primary",
            width="stretch",
            disabled=not can_create_alert,
        ):
            st.session_state.pop("alert_prefill_pool_id", None)
            st.session_state["alert_form_mode"] = "create"
            st.session_state["alert_create_request_key"] = uuid.uuid4().hex
            st.rerun()
    with action_cols[1]:
        st.caption("Delivery channel: Telegram · one verified account connection · no browser-provided routing IDs")

    if can_create_alert and st.session_state.get("alert_form_mode") == "create":
        _alert_form(
            client,
            pool_labels=pool_labels,
            full_signal_access=full_signal_access,
            account_timezone=account_timezone,
            creation_allowed=can_create_alert,
        )

    if not alerts:
        render_state(
            "No alerts yet",
            (
                "Choose an exact pool, then create a Telegram rule for the signal conditions you want monitored. "
                + ("Your verified Telegram connection is ready." if linked else "Telegram must be verified before the first alert can be created.")
            ),
        )
        if st.button("Browse pools for an alert", key="alerts_empty_discover", type="primary"):
            go_to_route("Discover", view="All Pools")
            st.rerun()
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

            controls = st.columns(5)
            pool_is_current = alert.target_pool_id in pool_labels
            if controls[0].button(
                "View pool",
                key=f"alert_pool_{alert.id}",
                width="stretch",
                disabled=not pool_is_current,
                help=None if pool_is_current else "This pool is not present in the current provider response.",
            ):
                open_pool_detail(alert.target_pool_id, return_route="Alerts", return_view="Alerts")
                st.rerun()
            if controls[1].button("Edit", key=f"alert_edit_{alert.id}", width="stretch"):
                st.session_state["alert_edit_id"] = alert.id
                st.rerun()
            if controls[2].button(
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
            if controls[3].button("Send test", key=f"alert_test_{alert.id}", width="stretch", disabled=not alert.enabled):
                try:
                    client.request_test_delivery(alert.id)
                except AutomationStoreError as exc:
                    st.error(str(exc))
                else:
                    st.success("Test queued through the durable Telegram delivery pipeline.")
            if controls[4].button("Delete", key=f"alert_delete_{alert.id}", width="stretch"):
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
                    full_signal_access=full_signal_access,
                    account_timezone=account_timezone,
                    creation_allowed=can_create_alert,
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
if page in {"Discover", "Pool Detail"}:
    for sensitive_key in sensitive_query_keys(st.query_params):
        del st.query_params[sensitive_key]

with st.sidebar:
    render_brand()
    navigation_slot = st.empty()
    with st.expander("Account", expanded=False):
        account_summary_slot = st.empty()
        with st.container(key="account_auth_controls"):
            if st.session_state.get("session_expired"):
                st.caption("Your session ended. Use the recovery controls on this page to sign in again.")
            else:
                login_form()
    with st.expander("Beta help", expanded=False):
        st.caption("Report the page, approximate time, pool, attempted action, and visible error. Never send passwords, magic links, tokens, or session cookies.")
        if BETA_DIAGNOSTICS.support_url:
            st.link_button("Beta feedback ↗", BETA_DIAGNOSTICS.support_url, width="stretch")
            st.caption("External support destination")
        else:
            st.caption("A beta feedback destination is not configured in this build.")

account_user = get_current_user()
signed_in = bool(account_user and account_user.get("_identity_verified"))
session_expired = bool(st.session_state.get("session_expired"))

if signed_in:
    claim_session()
    if not validate_session():
        session_expired = True
        st.session_state["session_expired"] = True
        st.session_state["session_recovery_show_login"] = False
        account_user = None
        signed_in = False
    else:
        st.session_state.pop("session_expired", None)
        st.session_state.pop("session_recovery_show_login", None)
        session_expired = False

if signed_in:
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

capabilities = capabilities_from_current_entitlement(is_pro=is_pro)
watchlists_enabled = can_use_watchlists(capabilities)
alerts_enabled = can_use_alerts(capabilities)
research_modeling_enabled = can_use_research_modeling(capabilities)
pro_tools_enabled = can_use_pro_tools(capabilities)
full_signals_enabled = can_use_full_signals(capabilities)
advanced_sorting_enabled = can_use_advanced_sorting(capabilities)
export_enabled = can_export_csv(capabilities)

admin_user = is_admin(db_user)
guest_mode = not signed_in
st.session_state["access_granted"] = is_pro
st.session_state["furuflow_demo_active"] = bool(db_user.get("demo_active"))
set_demo_side_effect_block(st.session_state["furuflow_demo_active"])

with navigation_slot.container():
    selected_route = render_navigation(
        current_route=page,
        signed_in=signed_in,
        capabilities=capabilities,
        is_admin=admin_user,
    )
if selected_route != page:
    go_to_route(selected_route)
    st.rerun()

account_model = account_control_model(
    account_user if signed_in else None,
    capabilities=capabilities,
    is_admin=admin_user,
)
with account_summary_slot.container():
    st.markdown(f"**{account_model['email']}**")
    st.caption(f"{account_model['plan']} plan · server-authoritative access")
    if signed_in:
        if st.button("Log out", key="logout_button", width="stretch"):
            logout()
            st.rerun()
    else:
        st.caption("Sign in for saved account features. Public research remains available.")

if session_expired:
    render_status(
        "warning",
        "Session expired",
        "Your authenticated session ended. Public market data remains available; account-owned actions now require sign-in.",
    )
    with st.container(key="session_recovery_actions"):
        recovery_actions = st.columns(2)
        if recovery_actions[0].button("Sign In Again", key="session_sign_in_again", type="primary", width="stretch"):
            st.session_state["session_recovery_show_login"] = True
        if recovery_actions[1].button("Continue to Home", key="session_continue_home", width="stretch"):
            st.session_state.pop("session_recovery_show_login", None)
            go_to_route("Home")
            st.rerun()
    if st.session_state.get("session_recovery_show_login"):
        with st.container(border=True, key="session_recovery_login"):
            login_form()

if signed_in and not bool(db_user.get("_account_available", True)):
    render_status(
        "degraded",
        "Account state temporarily unavailable",
        "FuruFlow could not confirm account capabilities. Paid and account-owned actions remain unavailable; refresh or sign in again after the account service recovers.",
    )

allowed, denial_reason = route_access(
    page,
    signed_in=signed_in,
    capabilities=capabilities,
    is_admin=admin_user,
)
if not allowed:
    render_page_heading(page)
    if denial_reason == "authentication_required":
        render_status("auth", "Authentication required", "Open Account in the navigation drawer to sign in securely.")
    elif denial_reason == "capability_required":
        render_status(
            "restricted",
            "Capability not available",
            "This workflow is outside the current account capability set. Pricing shows the planned beta ladder; no unsupported checkout is offered.",
        )
        if st.button("Review plans", key="denied_review_plans", type="primary"):
            go_to_route("Pricing")
            st.rerun()
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
if signed_in and watchlists_enabled:
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
df["signal_available"] = df["pool"].isin(signal_df["pool"]) if not signal_df.empty else False
if "signal" not in df.columns:
    df["signal"] = "Insufficient evidence"
df["signal"] = df["signal"].fillna("Insufficient evidence")
for col in ("apy_delta_7", "tvl_delta_7_pct", "apy_volatility"):
    if col not in df.columns:
        df[col] = pd.NA
    df[col] = pd.to_numeric(df[col], errors="coerce")

if df.empty:
    df["signal_strength"] = pd.Series(dtype="float64")
else:
    df["signal_strength"] = df.apply(
        lambda row: (
            score_signal_movement(row["apy_delta_7"], row["tvl_delta_7_pct"], row["apy_volatility"])
            if bool(row["signal_available"])
            else pd.NA
        ),
        axis=1,
    )

confidence_assessments = [
    assess_confidence(
        evidence_from_mapping(row),
        provider_availability=market_data_status.availability,
        freshness=market_freshness["label"],
    )
    for row in df.to_dict("records")
]
df["evidence_coverage"] = [assessment.coverage.value for assessment in confidence_assessments]
df["confidence_level"] = [assessment.confidence.value for assessment in confidence_assessments]
df["confidence_interpretation"] = [assessment.interpretation for assessment in confidence_assessments]
df["confidence_missing"] = ["; ".join(assessment.missing) for assessment in confidence_assessments]
df["data_freshness"] = market_freshness["label"]

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
    query_filter_model = (
        parse_filter_query(
            st.query_params,
            allowed_values={
                "chains": chains,
                "protocols": projects,
                "strategies": strategies,
                "signals": signals,
            },
        )
        if page in {"Discover", "Pool Detail"}
        else DEFAULT_FILTERS
    )
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
    sort_options = FREE_SORT_OPTIONS + PRO_SORT_OPTIONS if advanced_sorting_enabled else FREE_SORT_OPTIONS
    if filter_defaults["market_sort"] not in sort_options:
        filter_defaults["market_sort"] = DEFAULT_FILTERS.sort_by
    for filter_key, filter_value in filter_defaults.items():
        if filter_key not in st.session_state:
            st.session_state[filter_key] = filter_value

    show_market_filters = market_filters_apply(page)
    if show_market_filters:
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
                on_click=reset_discover_filters,
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
    for query_key in FILTER_QUERY_KEYS:
        if query_key in encoded_filters:
            if str(st.query_params.get(query_key) or "") != encoded_filters[query_key]:
                st.query_params[query_key] = encoded_filters[query_key]
        elif query_key in st.query_params:
            del st.query_params[query_key]

filtered = apply_discovery_filters(df, current_filters)

filtered = filtered.head(POOL_LIMIT)
full_filtered = filtered.copy()
if not advanced_sorting_enabled:
    filtered = filtered.head(FREE_POOL_LIMIT)
watchlist_df = df[df["pool"].isin(saved_pool_ids)].copy()
arb_df = yield_spreads(full_filtered if pro_tools_enabled else filtered)

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
    persist_discover_navigation_state(current_filters, active_view)
    st.caption(
        "Opportunities applies the visible criteria and selected deterministic order to surface a focused investigation set. "
        "All Pools keeps the broader provider universe searchable and sortable without the default opportunity TVL or risk thresholds."
    )
    content_page = {"Opportunities": "Scanner", "All Pools": "Pool Universe"}[active_view]
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
    elif active_view == "Opportunities":
        st.caption("No filters are active. The deterministic default opportunity view is shown.")
    else:
        st.caption("No filters are active. All canonical pools in the current provider response remain eligible.")
elif page == "Research":
    render_page_heading(page)
    active_view = "Comparison"
    content_page = "Research Comparison"
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
    st.button("Retry market data", key=f"market_retry_{page}", type="primary", on_click=refresh_market_data)
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
    render_home_page(
        df,
        full_filtered,
        watchlist_count=len(saved_pool_entries),
        capabilities=capabilities,
        signed_in=signed_in,
        source_label=market_source_label,
        freshness_label=market_freshness["label"],
    )

elif content_page == "Scanner":
    left, right = st.columns([1.6, 1], gap="large")
    with left:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header(
            "Opportunities",
            "Visible investigation candidates",
            "By default, candidates have at least $5M reported TVL and an existing risk score no higher than 70. Investigation priority orders confidence, evidence coverage, lower risk, larger TVL, then reported APY, with canonical pool ID as the final tie-breaker.",
        )
        st.caption(
            f"Current order: {current_filters.sort_by}. Inclusion and order support investigation only; they do not estimate expected return or establish safety."
        )
        top_cards = filtered.head(6)
        if filtered.empty and market_data_status.availability != "unavailable":
            render_status(
                "empty",
                "No pools match the active filters",
                "Remove an active filter or use Clear all filters. The market provider loaded successfully; this is a genuine zero-match result.",
            )
            st.button(
                "Reset filters",
                key="discover_zero_reset",
                type="primary",
                on_click=reset_discover_filters,
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
                        watch_allowed=watchlists_enabled,
                        alert_allowed=alerts_enabled,
                        research_allowed=research_modeling_enabled,
                        watchlist_client=watchlist_client,
                        freshness_label=market_freshness["label"],
                        return_view="Opportunities",
                        alerts_available=market_source_status != "sample",
                    )
        st.markdown("<div style='height:0.5rem;'></div>", unsafe_allow_html=True)
        table_df = compact_table(filtered)
        if not table_df.empty:
            render_internal_pool_table(
                table_df,
                tuple((label, label) for _, label in OPPORTUNITIES_TABLE_COLUMNS),
                return_route="Discover",
                return_view="Opportunities",
                link_columns={"Pool": "Open"},
                formats={"APY": "percent", "Base": "percent", "Rewards": "percent", "TVL (USD)": "money", "Risk": "number"},
                discover_state=encoded_filters,
                max_height=540,
            )
        csv_export = prepare_csv_export(filtered, capabilities)
        if export_enabled and csv_export.allowed:
            st.download_button(
                "Download current table as CSV",
                csv_export.content,
                file_name="furuflow_scanner.csv",
                mime="text/csv",
            )
        elif not export_enabled:
            st.markdown(
                "<div class='signal-card'><div class='signal-title'>CSV export · Pro — $24.99</div>"
                f"<div class='signal-copy'>{html.escape(CSV_UPGRADE_MESSAGE)} The future tier is planned and is not yet purchasable.</div></div>",
                unsafe_allow_html=True,
            )
            render_billing_action(db_user, label="Unlock CSV export")
        else:
            render_status("error", "CSV export unavailable", csv_export.message)
            st.button("Retry CSV generation", key="csv_export_retry")
        st.markdown("</div>", unsafe_allow_html=True)
    with right:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Discovery guidance", "How to investigate an opportunity", "Use the cards for triage, then verify identity, freshness, yield composition, and risk context in Pool Detail.")
        bullets = [
            ("Yield", "APY is provider-reported and can change quickly; unusually high APY is not a guaranteed return."),
            ("Evidence", "Coverage and confidence describe what FuruFlow has actually observed. Missing history is not a neutral signal."),
            ("Risk", "Risk is a separate contextual heuristic. TVL, confidence, or freshness does not make a pool safe."),
        ]
        for title, copy in bullets:
            st.markdown(f"<div class='signal-card'><div class='signal-title'>{title}</div><div class='signal-copy'>{copy}</div></div>", unsafe_allow_html=True)
        mini = filtered.head(12).groupby("risk_band", as_index=False).agg(pools=("pool", "count")) if not filtered.empty else pd.DataFrame()
        if not mini.empty:
            pie = px.pie(mini, values="pools", names="risk_band", hole=0.45)
            st.plotly_chart(plotly_theme(pie, 260), width="stretch")
        st.markdown("</div>", unsafe_allow_html=True)

elif content_page == "Pool Universe":
    st.markdown("<div class='panel'>", unsafe_allow_html=True)
    section_header(
        "All pools",
        "Search the current provider universe",
        "Find pools beyond the surfaced opportunity set. The same persisted controls are available, while default opportunity TVL and risk thresholds stay neutral here.",
    )
    universe_filter_model = all_pools_filters(current_filters)
    universe_df = apply_discovery_filters(pool_universe(df), universe_filter_model)
    if universe_df.empty:
        render_status(
            "empty",
            "No pools match the All Pools filters" if not df.empty else "Pool universe unavailable",
            "Remove an active filter or broaden the search; the provider rows were not replaced with placeholders."
            if not df.empty
            else "The provider returned no usable canonical pool identities.",
        )
        if not df.empty:
            st.button(
                "Reset filters",
                key="universe_zero_reset",
                type="primary",
                on_click=reset_discover_filters,
            )
    else:
        st.caption(
            f"{len(universe_df):,} canonical pool{'s' if len(universe_df) != 1 else ''} match. "
            f"Results use {universe_filter_model.sort_by.lower()} ordering with canonical ID tie-breaking; the table is intentionally capped at 60 rows."
        )
        universe_visible = universe_df.head(60)
        universe_table = compact_table(
            universe_visible,
            return_route="Discover",
            return_view="All Pools",
        )
        render_internal_pool_table(
            universe_table,
            tuple((label, label) for _, label in OPPORTUNITIES_TABLE_COLUMNS),
            return_route="Discover",
            return_view="All Pools",
            link_columns={"Pool": "Open"},
            formats={"APY": "percent", "Base": "percent", "Rewards": "percent", "TVL (USD)": "money", "Risk": "number"},
            max_height=min(620, 120 + 38 * len(universe_table)),
        )
        universe_rows = {str(row["pool"]): row for _, row in universe_visible.iterrows()}
        selected_universe_pool = st.selectbox(
            "Pool actions",
            tuple(universe_rows),
            format_func=lambda pool_id: (
                f"{universe_rows[pool_id]['project']} · {universe_rows[pool_id]['symbol']} · "
                f"{universe_rows[pool_id]['chain']}"
            ),
            key="pool_universe_action_pool",
            help="Type to search within these deterministic results, or refine Search all pools first.",
        )
        selected_universe_row = universe_rows[selected_universe_pool]
        render_opportunity_card(
            selected_universe_row,
            9000,
            selected_universe_pool in saved_pool_ids,
            authenticated=signed_in,
            watch_allowed=watchlists_enabled,
            alert_allowed=alerts_enabled,
            research_allowed=research_modeling_enabled,
            watchlist_client=watchlist_client,
            freshness_label=market_freshness["label"],
            return_route="Discover",
            return_view="All Pools",
            key_prefix="pool_universe",
            alerts_available=market_source_status != "sample",
        )
    st.caption("Provider-unavailable responses remain unavailable; FuruFlow does not substitute fabricated pools or values.")
    st.markdown("</div>", unsafe_allow_html=True)

elif content_page == "Research Comparison":
    st.markdown("<div class='panel'>", unsafe_allow_html=True)
    section_header(
        "1 · Select pools",
        "Build an intentional comparison",
        f"Choose up to {COMPARISON_LIMIT} pools from the full current universe. Research separates provider observations, calculated context, and interpretation; it does not select an investment for you.",
    )
    research_universe = pool_universe(df)
    if research_universe.empty:
        render_status("empty", "Research data unavailable", "The provider returned no usable canonical pools for comparison.")
        if st.button("Return to Discover", key="research_unavailable_discover", type="primary"):
            go_to_route("Discover", view="All Pools")
            st.rerun()
    else:
        if not research_modeling_enabled:
            render_status(
                "restricted",
                f"Research modeling is a {required_tier_name(Capability.RESEARCH_MODELING)} capability",
                f"Free remains open for discovery and Pool Detail. The planned {required_tier_name(Capability.RESEARCH_MODELING)} tier adds selected-pool comparison, transparent weighting, and monitoring workflows; it is not yet purchasable.",
            )
            st.caption("Existing trusted Pro entitlements include this capability during the beta billing compatibility period.")
            st.stop()
        compare_options = research_universe["pool"].astype(str).tolist()
        compare_query = str(st.query_params.get("compare") or "")
        if "research_selection" not in st.session_state:
            st.session_state["research_selection"] = [item for item in compare_query.split(",") if item in compare_options][
                :COMPARISON_LIMIT
            ]
        else:
            st.session_state["research_selection"] = [
                item for item in st.session_state["research_selection"] if item in compare_options
            ][:COMPARISON_LIMIT]
        label_by_pool = {
            str(row["pool"]): f"{row['project']} · {row['symbol']} · {row['chain']}"
            for _, row in research_universe.iterrows()
        }
        available_saved = [pool_id for pool_id in compare_options if pool_id in saved_pool_ids][:COMPARISON_LIMIT]
        if signed_in and st.button(
            "Use Watchlist",
            key="research_use_watchlist",
            disabled=not available_saved,
            help="Load up to four saved pools that have current provider observations.",
        ):
            st.session_state["research_selection"] = available_saved
            st.rerun()
        selected_compare = list(st.session_state["research_selection"])
        if selected_compare:
            st.query_params["compare"] = ",".join(selected_compare)
        elif "compare" in st.query_params:
            del st.query_params["compare"]

        st.markdown("**Selected pools**")
        if selected_compare:
            for pool_id in selected_compare:
                selected_label = label_by_pool.get(pool_id, pool_id)
                selected_label_col, selected_remove_col = st.columns([5, 1])
                selected_label_col.markdown(selected_label)
                selected_remove_col.button(
                    "Remove",
                    key=f"research_selected_remove_{pool_id}",
                    help=f"Remove {selected_label} ({pool_id}) from this comparison.",
                    width="stretch",
                    on_click=remove_research_pool,
                    args=(pool_id,),
                )
        else:
            st.caption("Choose two to four pools.")

        if st.session_state.get("research_pool_addition") in selected_compare:
            st.session_state["research_pool_addition"] = None
        remaining_compare_options = [
            pool_id for pool_id in compare_options if pool_id not in selected_compare
        ]
        st.selectbox(
            "Add pool to comparison",
            remaining_compare_options,
            index=None,
            key="research_pool_addition",
            disabled=len(selected_compare) >= COMPARISON_LIMIT or not remaining_compare_options,
            format_func=lambda pool_id: label_by_pool.get(pool_id, pool_id),
            placeholder=(
                "Remove a pool before adding another"
                if len(selected_compare) >= COMPARISON_LIMIT
                else "Search the current pool universe"
            ),
            on_change=add_research_pool_from_picker,
        )
        st.caption(
            f"{len(selected_compare)} of {COMPARISON_LIMIT} comparison slots used. "
            "Missing values remain unavailable, never zero-filled."
        )
        if st.button(
            "Clear comparison",
            key="clear_comparison",
            disabled=not selected_compare,
            on_click=st.session_state.update,
            args=({"research_selection": []},),
        ):
            track_research_event("comparison_cleared", {"count": len(selected_compare)})
        compared_rows = comparison_rows(df, selected_compare)
        if not compared_rows:
            render_status(
                "empty",
                "Choose pools to research",
                "Carry a pool here from Discover, Pool Detail, Signals, or Pro Tools, select one manually, or load current Watchlist pools.",
            )
            if st.button("Find pools in Discover", key="research_empty_discover", type="primary"):
                go_to_route("Discover", view="All Pools")
                st.rerun()
        else:
            track_research_event("comparison_opened", {"count": len(compared_rows), "view": "Comparison"})
            selected_ids = [str(row["pool"]) for row in compared_rows]
            selected_source = df[df["pool"].astype(str).isin(selected_ids)].copy()
            selected_source["_research_order"] = selected_source["pool"].astype(str).map(
                {pool_id: index for index, pool_id in enumerate(selected_ids)}
            )
            selected_source = selected_source.sort_values("_research_order")
            for source_index, source_row in selected_source.iterrows():
                source_evidence = evidence_from_mapping(source_row)
                if not bool(source_row.get("signal_available", False)):
                    stored_history = load_history(str(source_row["pool"]))
                    if not stored_history.empty:
                        source_evidence = historical_evidence(stored_history)
                source_assessment = assess_confidence(
                    source_evidence,
                    provider_availability=market_data_status.availability,
                    freshness=market_freshness["label"],
                )
                selected_source.at[source_index, "evidence_coverage"] = source_assessment.coverage.value
                selected_source.at[source_index, "confidence_level"] = source_assessment.confidence.value
            compared_rows = comparison_rows(selected_source, selected_ids)
            section_header(
                "2 · Comparison lens",
                "Choose what matters in this selected set",
                "Each dimension is min-max normalized only across these pools. Lower existing risk scores are better; missing dimensions are omitted and disclosed through coverage.",
            )
            balanced_weights = COMPARISON_SCENARIOS["Balanced"]
            for weight_key, weight_default in (
                ("research_weight_yield", balanced_weights.yield_weight),
                ("research_weight_liquidity", balanced_weights.liquidity_weight),
                ("research_weight_risk", balanced_weights.risk_weight),
                ("research_weight_signal", balanced_weights.signal_weight),
            ):
                st.session_state.setdefault(weight_key, weight_default)
            scenario_columns = st.columns(len(COMPARISON_SCENARIOS))
            for scenario_column, (scenario_name, scenario_weights) in zip(
                scenario_columns, COMPARISON_SCENARIOS.items(), strict=True
            ):
                if scenario_column.button(
                    scenario_name,
                    key=f"research_scenario_{scenario_name.lower().replace(' ', '_')}",
                    type="primary" if st.session_state.get("research_scenario", "Balanced") == scenario_name else "secondary",
                    width="stretch",
                ):
                    st.session_state.update(
                        {
                            "research_scenario": scenario_name,
                            "research_weight_yield": scenario_weights.yield_weight,
                            "research_weight_liquidity": scenario_weights.liquidity_weight,
                            "research_weight_risk": scenario_weights.risk_weight,
                            "research_weight_signal": scenario_weights.signal_weight,
                        }
                    )
                    st.rerun()
            weight_columns = st.columns(4)
            yield_weight = weight_columns[0].slider(
                "Yield weight",
                0,
                100,
                step=5,
                key="research_weight_yield",
            )
            liquidity_weight = weight_columns[1].slider(
                "Liquidity weight",
                0,
                100,
                step=5,
                key="research_weight_liquidity",
            )
            risk_weight = weight_columns[2].slider(
                "Risk weight",
                0,
                100,
                step=5,
                key="research_weight_risk",
            )
            signal_weight = weight_columns[3].slider(
                "Signal / momentum weight",
                0,
                100,
                step=5,
                key="research_weight_signal",
            )
            comparison_weights = ComparisonWeights(yield_weight, liquidity_weight, risk_weight, signal_weight)
            analysis = comparison_analysis(selected_source, selected_ids, comparison_weights)
            configured_total = sum(analysis["weights"].values())
            st.caption(
                f"Configured weight total: {configured_total}. Values are proportionally normalized; this is deterministic decision support, not a return prediction."
            )
            if len(analysis["rows"]) >= 2:
                section_header(
                    "3 · Review tradeoffs",
                    "Read ranking, evidence, and risk separately",
                    "The selected-set score explains the configured comparison lens. Independent evidence confidence and existing risk remain separate and are not expected-return estimates.",
                )
                winner = analysis["winner"]
                if winner:
                    render_status(
                        "info",
                        f"{winner['Pool']} ranks first on reported-current metrics under these weights",
                        f"{winner['Reason']} Score {winner['Score']:.2f}/100 with {winner['Coverage %']:.1f}% weighted-data coverage. "
                        f"Its independent evidence confidence is {winner['Confidence']}; this rank is not an expected-return or persistence conclusion.",
                    )
                leader_by_pool = {row["pool"]: row["Pool"] for row in analysis["rows"]}
                leader_notes = []
                for label, key in (
                    ("Highest yield", "highest_yield"),
                    ("Strongest liquidity", "strongest_liquidity"),
                    ("Lowest modeled risk", "lowest_risk"),
                    ("Strongest signal", "strongest_signal"),
                ):
                    leader_id = analysis["leaders"].get(key)
                    if leader_id:
                        leader_notes.append(f"**{label}:** {leader_by_pool[leader_id]}")
                st.markdown("  \n".join(leader_notes))
                spread = analysis["apy_spread"]
                if spread is not None:
                    st.caption(f"Selected-set APY spread: {spread:.2f} percentage points. {analysis['diversification']}")
                ranking_view = pd.DataFrame(analysis["rows"])[
                    [
                        "Overall rank",
                        "Pool",
                        "Score",
                        "Coverage %",
                        "Evidence coverage",
                        "Confidence",
                        "APY",
                        "APY vs median",
                        "TVL (USD)",
                        "TVL vs median %",
                        "Risk",
                        "Signal",
                        "Reason",
                    ]
                ]
                st.dataframe(
                    ranking_view,
                    width="stretch",
                    hide_index=True,
                    height=min(310, 120 + 42 * len(ranking_view)),
                    column_config={
                        "Score": st.column_config.NumberColumn(format="%.2f"),
                        "Coverage %": st.column_config.NumberColumn(format="%.1f%%"),
                        "APY": st.column_config.NumberColumn(format="%.2f%%"),
                        "APY vs median": st.column_config.NumberColumn(format="%+.2f pp"),
                        "TVL (USD)": st.column_config.NumberColumn(format="$%.0f"),
                        "TVL vs median %": st.column_config.NumberColumn(format="%+.1f%%"),
                        "Risk": st.column_config.NumberColumn(format="%.0f"),
                    },
                )
            else:
                st.caption("Select at least two pools to produce relative ranks and cross-pool explanations.")
            research_links = compact_table(
                selected_source,
                return_route="Research",
                return_view="Comparison",
            )
            render_internal_pool_table(
                research_links,
                tuple((label, label) for _, label in OPPORTUNITIES_TABLE_COLUMNS),
                return_route="Research",
                return_view="Comparison",
                link_columns={"Pool": "Open"},
                formats={"APY": "percent", "Base": "percent", "Rewards": "percent", "TVL (USD)": "money", "Risk": "number"},
                max_height=min(310, 120 + 42 * len(research_links)),
            )
            matrix_source = pd.DataFrame(compared_rows)
            matrix_source["Data freshness"] = market_freshness["label"]
            matrix_source["Opportunity"] = (
                matrix_source["Protocol"] + " · " + matrix_source["Pool / assets"] + " · " + matrix_source["Chain"]
            )
            matrix = matrix_source.set_index("Opportunity").drop(columns=["pool", "Pool / assets"]).T
            matrix = matrix.astype("string").fillna("Unavailable")
            st.dataframe(matrix, width="stretch", height=min(420, 120 + 38 * len(matrix.index)))
            st.caption("On narrow screens, comparison tables scroll inside bounded regions; the evidence summaries below stack vertically.")
            current_rows = {str(row["pool"]): row for _, row in selected_source.iterrows()}
            for compared in compared_rows:
                pool_id = compared["pool"]
                current_row = current_rows[pool_id]
                with st.expander(f"{compared['Protocol']} · {compared['Pool / assets']} · {compared['Chain']}"):
                    total_compare = f"{compared['APY']:.2f}%" if compared["APY"] is not None else "Unavailable"
                    base_compare = f"{compared['Base APY']:.2f}%" if compared["Base APY"] is not None else "Unavailable"
                    reward_compare = f"{compared['Reward APY']:.2f}%" if compared["Reward APY"] is not None else "Unavailable"
                    st.markdown("**Provider-reported current metrics**")
                    st.markdown(f"Yield: {total_compare} total · {base_compare} base · {reward_compare} rewards  ")
                    st.markdown(
                        f"TVL: {format_money(compared['TVL (USD)']) if compared['TVL (USD)'] is not None else 'Unavailable'} · "
                        f"Protocol: {compared['Protocol']} · Network: {compared['Chain']}"
                    )
                    st.markdown("**Calculated context**")
                    if compared["Signal evidence"] == "Observed":
                        st.markdown(
                            f"Heuristic risk: {compared['Risk']} · Signal: {compared['Signal']} · "
                            f"APY movement: {float(current_row['apy_delta_7']):.2f} · "
                            f"TVL movement: {float(current_row['tvl_delta_7_pct']):.2f}%"
                        )
                    else:
                        st.markdown(
                            f"Heuristic risk: {compared['Risk']} · Signal evidence: Insufficient evidence. "
                            "No zero movement is inferred from missing history."
                        )
                    st.markdown("**Interpretation**")
                    st.markdown(
                        f"Evidence coverage: {compared['Evidence coverage']} · Confidence: {compared['Confidence']}. "
                        "Compare reported yield with liquidity, reward dependence, token exposure, and data freshness. "
                        "The signal describes detected movement and the risk label is contextual; neither is a prediction or recommendation."
                    )
                    st.caption(f"Provenance: {market_source_label} · {market_freshness['label']} · {market_freshness['age']}.")
                    action_cols = st.columns(4)
                    with action_cols[0]:
                        if st.button("View details", key=f"compare_detail_{pool_id}", width="stretch"):
                            track_research_event("pool_detail_opened", {"pool": pool_id, "view": "Comparison"})
                            open_pool_detail(pool_id, return_route="Research", return_view="Comparison")
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
                    with action_cols[2]:
                        if st.button(
                            "Create alert" if signed_in else "Sign in for alerts",
                            key=f"compare_alert_{pool_id}",
                            width="stretch",
                            disabled=not signed_in or market_source_status == "sample",
                        ):
                            start_alert_creation(pool_id)
                            st.rerun()
                    with action_cols[3]:
                        st.button(
                            "Remove",
                            key=f"compare_remove_{pool_id}",
                            width="stretch",
                            on_click=remove_research_pool,
                            args=(pool_id,),
                        )
    st.markdown("</div>", unsafe_allow_html=True)

elif content_page == "Signals":
    st.markdown(
        """
        <section class="hero-shell"><div class="hero-inner">
            <div class="eyebrow">FuruFlow Intelligence</div>
            <div class="hero-title">Signals Engine</div>
            <div class="hero-subtitle">Rules-based APY and liquidity classification across the current sampled pool set, with context for further investigation.</div>
        </div></section>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("<div class='panel'>", unsafe_allow_html=True)
    section_header("Signals", "Movement classifications with context", "Signal labels summarize recent APY and TVL movement, volatility context, timing, and the affected pool. They are evidence to investigate, not a recommendation.")
    st.markdown("<div class='note'>Read APY movement alongside TVL, incentives, protocol and token exposure, and freshness. A larger movement is not automatically a better or safer opportunity.</div>", unsafe_allow_html=True)
    metric_source = full_filtered if not full_filtered.empty else filtered
    observed_metric_source = metric_source[metric_source["signal_available"].astype(bool)]
    metric_cols = st.columns(4)
    with metric_cols[0]:
        stat_card(
            POOLS_EVALUATED_LABEL,
            f"{len(metric_source):,}",
            "Pools in the current visible signal-analysis universe, including Steady classifications",
        )
    with metric_cols[1]:
        observed_count = int(metric_source["signal_available"].sum()) if not metric_source.empty else 0
        stat_card(
            OBSERVED_SIGNAL_EVIDENCE_LABEL,
            f"{observed_count:,}",
            "Pools with successfully retrieved signal-history observations",
        )
    with metric_cols[2]:
        non_steady_count = int(observed_metric_source["signal"].ne("Steady").sum()) if not observed_metric_source.empty else 0
        stat_card(
            NON_STEADY_CLASSIFICATIONS_LABEL,
            f"{non_steady_count:,}",
            "Visible pools whose rules-based label is not Steady",
        )
    with metric_cols[3]:
        avg_strength = observed_metric_source["signal_strength"].mean() if not observed_metric_source.empty else None
        stat_card(
            "Avg signal strength",
            f"{avg_strength:,.1f}" if avg_strength is not None else "Unavailable",
            "Descriptive movement intensity across pools with observed evidence",
        )
    st.markdown("</div>", unsafe_allow_html=True)

    top_signal_source = full_filtered[full_filtered["signal_available"].astype(bool)].sort_values(
        ["signal_strength", "apy_delta_7", "tvl_delta_7_pct"], ascending=[False, False, False]
    ).head(3)
    if not top_signal_source.empty:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Recent signal evidence", "Largest visible movements", "Ordered by the existing combined signal-strength, APY-movement, and TVL-movement presentation.")
        cols = st.columns(3, gap="medium")
        for idx, (_, row) in enumerate(top_signal_source.iterrows()):
            with cols[idx]:
                render_opportunity_card(
                    row,
                    700 + idx,
                    row["pool"] in saved_pool_ids,
                    authenticated=signed_in,
                    watch_allowed=watchlists_enabled,
                    alert_allowed=alerts_enabled,
                    research_allowed=research_modeling_enabled,
                    watchlist_client=watchlist_client,
                    freshness_label=market_freshness["label"],
                    return_route="Signals",
                    return_view="Signals",
                    key_prefix="signals",
                    alerts_available=market_source_status != "sample",
                )
                st.caption(
                    f"Signal strength: {row['signal_strength']:.1f} • 7d APY Δ: {row['apy_delta_7']:.2f} • "
                    f"7d TVL Δ: {row['tvl_delta_7_pct']:.2f}% • Evidence: {row['evidence_coverage']} • "
                    f"Confidence: {row['confidence_level']}"
                )
        st.markdown("</div>", unsafe_allow_html=True)
    else:
        render_status(
            "empty",
            "Observed signal evidence unavailable",
            "Current pools remain inspectable, but no signal-history observations were retrieved, so movement is not shown as zero.",
        )

    if not full_signals_enabled:
        preview = top_signal_source[["project", "chain", "symbol", "signal", "signal_strength", "apy_delta_7", "tvl_delta_7_pct"]].copy().head(5)
        preview.columns = ["Protocol", "Chain", "Asset", "Signal", "Strength", "7d APY Δ", "7d TVL Δ %"]
        require_pro("Signals", preview_df=preview, preview_note="Free users can scan pools, but the full signal engine is reserved for Pro.")

    left, right = st.columns([1.2, 1], gap="large")
    with left:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Signal engine", "Rules-based yield movement", "Existing deterministic labels surface APY spikes, farm rotations, emerging pools, and whale inflows from recent pool chart movement.")
        signal_table_source = filtered[filtered["signal_available"].astype(bool)].copy()
        sig_view = signal_table_source[[column for column, _ in SIGNAL_ENGINE_TABLE_COLUMNS]].copy().head(20)
        if sig_view.empty:
            render_status(
                "empty",
                "No observed signal rows",
                "Pool navigation remains available through Discover; this table does not substitute missing observations with zero movement.",
            )
        else:
            render_internal_pool_table(
                sig_view,
                SIGNAL_ENGINE_TABLE_COLUMNS,
                return_route="Signals",
                return_view="Signals",
                formats={"signal_strength": "number", "apy_delta_7": "number", "tvl_delta_7_pct": "number", "apy_volatility": "number"},
                max_height=560,
            )
        if not signal_table_source.empty:
            signal_rows = {str(row["pool"]): row for _, row in signal_table_source.head(60).iterrows()}
            selected_signal_pool = st.selectbox(
                "Signal pool actions",
                tuple(signal_rows),
                format_func=lambda pool_id: (
                    f"{signal_rows[pool_id]['project']} · {signal_rows[pool_id]['symbol']} · "
                    f"{signal_rows[pool_id]['chain']} · {signal_rows[pool_id]['signal']}"
                ),
                key="signal_action_pool",
            )
            selected_signal_row = signal_rows[selected_signal_pool]
            render_opportunity_card(
                selected_signal_row,
                9100,
                selected_signal_pool in saved_pool_ids,
                authenticated=signed_in,
                watch_allowed=watchlists_enabled,
                alert_allowed=alerts_enabled,
                research_allowed=research_modeling_enabled,
                watchlist_client=watchlist_client,
                freshness_label=market_freshness["label"],
                return_route="Signals",
                return_view="Signals",
                key_prefix="signal_action",
                alerts_available=market_source_status != "sample",
            )
        st.markdown("</div>", unsafe_allow_html=True)
    with right:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Interpretation", "Operator notes", "These are decision-support signals, not guarantees.")
        st.caption(
            "Confidence uses the same historical-evidence prerequisites as Pool Detail and Research. "
            "Signal strength measures observed movement intensity; it is not evidence confidence."
        )
        guides = [
            ("APY spike", "Yield jumped quickly. Check whether emissions, rewards, or a short-term campaign are driving the move."),
            ("Farm rotation", "Yield and TVL rolled over together. Capital may be leaving after incentives decayed or a newer farm launched."),
            ("Emerging pool", "APY and TVL increased together in the sampled window. Inspect incentives, liquidity depth, and durability before drawing a conclusion."),
            ("Whale inflow", "TVL increased sharply in the sampled window. The label describes capital movement; it does not establish who deposited or why."),
        ]
        for title, copy in guides:
            st.markdown(f"<div class='signal-card'><div class='signal-title'>{title}</div><div class='signal-copy'>{copy}</div></div>", unsafe_allow_html=True)
        if not filtered.empty:
            fig = build_signal_scatter(filtered)
            fig.update_xaxes(title="Average TVL")
            fig.update_yaxes(title="Average APY %")
            st.plotly_chart(plotly_theme(fig, 320), width="stretch")
        st.markdown("</div>", unsafe_allow_html=True)
    render_link_table(
        filtered.sort_values(["signal_strength", "apy_delta_7", "tvl_delta_7_pct"], ascending=[False, False, False]),
        "Signals",
        "Open affected pools in canonical Pool Detail from this evidence view.",
        limit=10,
        return_route="Signals",
        return_view="Signals",
    )

elif content_page == "Arbitrage":
    if not pro_tools_enabled:
        require_pro("Yield Spreads")
    track_research_event("yield_spreads_viewed", {"count": len(arb_df), "view": "Yield Spreads"})
    left, right = st.columns([1.15, 1], gap="large")
    with left:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header("Yield spreads", "Same asset, different chain", "This view identifies APY gaps across chains for the same displayed asset symbol; it does not label them risk-free arbitrage.")
        if arb_df.empty:
            st.info("No meaningful cross-chain APY gaps are visible for the current filters.")
        else:
            spread_columns = (
                ("Higher pool ID", "Higher-yield pool"),
                ("Lower pool ID", "Lower-yield pool"),
                ("Asset", "Asset"),
                ("Higher chain", "Higher chain"),
                ("Higher protocol", "Higher protocol"),
                ("Higher APY", "Higher APY"),
                ("Lower chain", "Lower chain"),
                ("Lower protocol", "Lower protocol"),
                ("Lower APY", "Lower APY"),
                ("APY difference", "APY difference"),
                ("Execution costs", "Execution costs"),
            )
            render_internal_pool_table(
                arb_df,
                spread_columns,
                return_route="Pro Tools",
                return_view="Yield Spreads",
                link_columns={"Higher pool ID": "Open", "Lower pool ID": "Open"},
                formats={"Higher APY": "percent", "Lower APY": "percent", "APY difference": "number"},
                max_height=560,
            )
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
        render_link_table(
            arb_focus,
            "Yield spreads",
            "Open candidate pools in canonical Pool Detail, then carry the same identity into Watchlist or Research.",
            limit=10,
            return_route="Pro Tools",
            return_view="Yield Spreads",
        )
    if not arb_df.empty:
        spread_pair_indexes = tuple(range(min(12, len(arb_df))))
        selected_spread_pair = st.selectbox(
            "Yield spread pair",
            spread_pair_indexes,
            format_func=lambda index: (
                f"{arb_df.iloc[index]['Asset']} · {arb_df.iloc[index]['Higher protocol']} ({arb_df.iloc[index]['Higher chain']}) "
                f"vs {arb_df.iloc[index]['Lower protocol']} ({arb_df.iloc[index]['Lower chain']})"
            ),
            key="yield_spread_pair",
        )
        pair = arb_df.iloc[selected_spread_pair]
        st.caption(
            f"APY spread {float(pair['APY difference']):.2f} pp · "
            f"higher-side TVL {format_money(pair['Higher TVL']) if pair['Higher TVL'] is not None else 'Unavailable'} · "
            f"lower-side TVL {format_money(pair['Lower TVL']) if pair['Lower TVL'] is not None else 'Unavailable'} · "
            f"risk {pair['Higher risk'] if pair['Higher risk'] is not None else 'Unavailable'} vs "
            f"{pair['Lower risk'] if pair['Lower risk'] is not None else 'Unavailable'}"
        )
        if st.button("Compare pair in Research", key="yield_spread_compare_pair", type="primary", width="stretch"):
            open_research_many((str(pair["Higher pool ID"]), str(pair["Lower pool ID"])))
            st.rerun()
        spread_ids = list(
            dict.fromkeys(
                arb_df.head(12)["Higher pool ID"].astype(str).tolist()
                + arb_df.head(12)["Lower pool ID"].astype(str).tolist()
            )
        )
        spread_rows = {
            str(row["pool"]): row
            for _, row in df[df["pool"].astype(str).isin(spread_ids)].iterrows()
        }
        if spread_rows:
            selected_spread_pool = st.selectbox(
                "Yield spread pool actions",
                tuple(pool_id for pool_id in spread_ids if pool_id in spread_rows),
                format_func=lambda pool_id: (
                    f"{spread_rows[pool_id]['project']} · {spread_rows[pool_id]['symbol']} · "
                    f"{spread_rows[pool_id]['chain']}"
                ),
                key="yield_spread_action_pool",
            )
            spread_is_saved = selected_spread_pool in saved_pool_ids
            spread_actions = st.columns(4)
            if spread_actions[0].button(
                "Remove from Watchlist" if spread_is_saved else "Save to Watchlist",
                key="yield_spread_watch",
                width="stretch",
                disabled=watchlist_client is None,
            ):
                if watch_toggle(selected_spread_pool, watched=spread_is_saved, client=watchlist_client):
                    st.rerun()
            if spread_actions[1].button("Open Pool", key="yield_spread_detail", width="stretch"):
                open_pool_detail(selected_spread_pool, return_route="Pro Tools", return_view="Yield Spreads")
                st.rerun()
            if spread_actions[2].button("Research Pool", key="yield_spread_research", width="stretch"):
                open_research(selected_spread_pool)
                st.rerun()
            if spread_actions[3].button(
                "Create Alert",
                key="yield_spread_alert",
                width="stretch",
                disabled=market_source_status == "sample",
            ):
                start_alert_creation(selected_spread_pool)
                st.rerun()

elif content_page == "Pool Detail":
    selected_pool_id = str(st.session_state.get("selected_pool_id") or st.query_params.get("pool") or "")
    detail_return_route = str(st.session_state.get("pool_return_route") or "Discover")
    detail_return_view = str(st.session_state.get("pool_return_view") or "Opportunities")
    if detail_return_route == "Home":
        detail_back_label = "← Back to Home"
    elif detail_return_route == "Watchlists":
        detail_back_label = "← Back to Watchlist"
    elif detail_return_route == "Research":
        detail_back_label = "← Back to Research"
    elif detail_return_route == "Signals":
        detail_back_label = "← Back to Signals"
    elif detail_return_route == "Alerts":
        detail_back_label = "← Back to Alerts"
    elif detail_return_route == "Pro Tools":
        detail_back_label = "← Back to Strategy Results"
    elif detail_return_view == "Signals":
        detail_back_label = "← Back to Signals"
    elif detail_return_view == "All Pools":
        detail_back_label = "← Back to All Pools"
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
        render_page_heading(
            "Pool Detail",
            detail_label=f"{row['project']} · {row['symbol']}",
            parent_route=detail_return_route,
        )
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
        section_header("Decision hub", "Pool research", "Inspect identity, reported yield, liquidity, evidence, risk factors, and next actions without losing your return context.")
        st.markdown("#### Identity")
        st.markdown(
            f"**Pool / assets:** {row['symbol']}  \n**Protocol:** {row['project']}  \n"
            f"**Chain:** {row['chain']}  \n"
            f"**Strategy metadata:** {row['strategy_type']} · **Exposure:** {row['exposure']}"
        )
        st.caption(f"Canonical pool ID: {current_pool_id}")

        cols = st.columns([1.3, 1], gap="large")
        with cols[0]:
            st.markdown("#### History")
            chart, chart_mode = get_pool_chart_with_fallback(row)
            chart_has_apy = "apy" in chart and chart["apy"].notna().any()
            chart_has_tvl = "tvlUsd" in chart and chart["tvlUsd"].notna().any()
            if chart.empty or not (chart_has_apy or chart_has_tvl):
                render_status(
                    "empty",
                    "Historical series unavailable",
                    "No usable live or legitimately stored observations exist for this pool. FuruFlow does not convert missing history to zero or generate a trend from a single snapshot.",
                )
            else:
                fig = go.Figure()
                if chart_has_apy:
                    fig.add_trace(go.Scatter(x=chart["timestamp"], y=chart["apy"], mode="lines", name="APY"))
                if chart_has_tvl:
                    fig.add_trace(go.Scatter(x=chart["timestamp"], y=chart["tvlUsd"], mode="lines", name="TVL", yaxis="y2"))
                    fig.update_layout(yaxis2=dict(overlaying="y", side="right", showgrid=False, title="TVL"))
                fig.update_xaxes(title="Time")
                fig.update_yaxes(title="APY %")
                st.plotly_chart(plotly_theme(fig, 430), width="stretch")
                if not chart_has_apy or not chart_has_tvl:
                    st.caption("Historical coverage is partial; missing APY or TVL observations remain unavailable rather than zero-filled.")
                if chart_mode == "stored":
                    st.caption("The provider history endpoint was unavailable; this chart uses real snapshots previously stored by FuruFlow and may be stale.")
                else:
                    st.caption("Provider-reported historical series retrieved from the DeFiLlama history endpoint; FuruFlow does not independently verify it.")

            detail_assessment = assess_confidence(
                historical_evidence(chart, signal_history_available=bool(row.get("signal_available", False))),
                provider_availability=market_data_status.availability,
                freshness=market_freshness["label"],
            )

        with cols[1]:
            signal_evidence = "Observed" if bool(row.get("signal_available", False)) else "Insufficient evidence"
            signal_classification = row["signal"] if signal_evidence == "Observed" else "Insufficient evidence"
            st.markdown(
                f"<div class='signal-card'><div class='signal-title'>{row['project']} • {row['symbol']}</div><div class='signal-copy'>{row['chain']} • {row['strategy_type']} • {signal_classification}</div></div>",
                unsafe_allow_html=True,
            )

            pool_yield = yield_explanation(row)
            pool_risk = risk_explanation(row)
            st.markdown("#### Reported now")
            reported_stats = pd.DataFrame([
                ["Total APY · reported", f"{pool_yield['total']:.2f}%" if pool_yield["total"] is not None else "Unavailable"],
                ["Base APY · reported", f"{pool_yield['base']:.2f}%" if pool_yield["base"] is not None else "Unavailable"],
                ["Reward APY · reported", f"{pool_yield['reward']:.2f}%" if pool_yield["reward"] is not None else "Unavailable"],
                ["TVL · reported", format_money(row['tvlUsd']) if bool(row.get("tvl_available", True)) else "Unavailable"],
                ["Provider freshness", f"{market_freshness['label']} · {market_freshness['age']}"],
            ], columns=["Metric", "Value"])
            st.dataframe(reported_stats, width="stretch", hide_index=True, height=245)

            st.markdown("#### Evidence")
            evidence_stats = pd.DataFrame([
                ["Evidence coverage", detail_assessment.coverage.value],
                ["Confidence", detail_assessment.confidence.value],
                ["Classification", signal_classification],
                ["Signal evidence", signal_evidence],
                ["7d APY change", f"{float(row['apy_delta_7']):.2f}" if signal_evidence == "Observed" else "Insufficient evidence"],
                ["7d TVL change", f"{float(row['tvl_delta_7_pct']):.2f}%" if signal_evidence == "Observed" else "Insufficient evidence"],
            ], columns=["Metric", "Value"])
            st.dataframe(evidence_stats, width="stretch", hide_index=True, height=285)
            st.caption(detail_assessment.interpretation)
            if detail_assessment.limiting_factors:
                st.caption("Confidence is limited by: " + "; ".join(detail_assessment.limiting_factors) + ".")
            if detail_assessment.missing:
                st.caption("Major evidence missing: " + "; ".join(detail_assessment.missing) + ".")
            if pool_yield["mode"] == "aggregate_only":
                st.caption("The provider reports only aggregate APY for this pool; no yield decomposition is implied.")
            elif pool_yield["reconciles"] is False:
                st.warning(
                    f"Reported base plus reward APY differs from reported total APY by {pool_yield['discrepancy']:.2f} percentage points. Values are shown without forcing reconciliation."
                )

            st.markdown("#### Risk")
            render_status(
                "warning" if pool_risk["score"] is not None and int(pool_risk["score"]) >= 60 else "info",
                f"{pool_risk['label']} risk" if pool_risk["score"] is not None else "Risk unknown",
                f"Existing risk score: {pool_risk['score']}/100. Risk is independent of reported APY and evidence confidence."
                if pool_risk["score"] is not None
                else "Important risk inputs are missing, so FuruFlow does not substitute a reassuring score.",
            )
            risk_factor_rows = list(pool_risk["factors"]) + [
                {"factor": "Audit confidence", "status": f"{int(row['audit_score'])}/100", "detail": "Existing protocol context input."},
                {"factor": "Protocol age", "status": f"{int(row['protocol_age_score'])}/100", "detail": "Existing protocol context input."},
                {"factor": "TVL stability", "status": f"{int(row['tvl_stability_score'])}/100", "detail": "Existing liquidity context input."},
                {"factor": "Pool volatility", "status": f"{int(row['pool_volatility_score'])}/100", "detail": "Existing volatility context input."},
            ]
            st.dataframe(pd.DataFrame(risk_factor_rows), width="stretch", hide_index=True, height=330)
            st.caption(pool_risk["method"])

            st.markdown("#### Data provenance")
            st.markdown(
                f"**Source:** {market_data_status.source}  \n**Availability:** {market_data_status.availability.title()}  \n"
                f"**Freshness:** {market_freshness['label']} · {market_freshness['age']}  \n"
                "**Value origin:** APY and TVL are provider-reported; history is observed; measurements are calculated from that history; confidence and risk are separate FuruFlow interpretations."
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

        st.markdown("#### Actions")
        st.caption("Continue with the same canonical pool. The protocol destination is external; FuruFlow does not execute or recommend a transaction.")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            watched = row["pool"] in saved_pool_ids
            st.markdown("<div class='watch-wrap'>", unsafe_allow_html=True)
            if st.button(
                (
                    "Remove from Watchlist"
                    if watched
                    else "Add to Watchlist"
                    if signed_in and watchlists_enabled and watchlist_client is not None
                    else "Watchlist unavailable"
                    if signed_in and watchlists_enabled
                    else f"Watchlists · {required_tier_name(Capability.WATCHLISTS)}"
                    if signed_in
                    else "Sign in to save"
                ),
                key=f"drill_watch_{current_pool_id}",
                width="stretch",
                disabled=not signed_in or not watchlists_enabled or watchlist_client is None,
            ):
                track_research_event("watchlist_action_initiated", {"pool": current_pool_id, "action": "toggle"})
                if watch_toggle(str(row["pool"]), watched=watched, client=watchlist_client):
                    st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)
        with c2:
            if st.button(
                "Sign in for alerts"
                if not signed_in
                else f"Alerts · {required_tier_name(Capability.ALERTS)}"
                if not alerts_enabled
                else "Create alert",
                key=f"pool_alert_{current_pool_id}",
                width="stretch",
                disabled=not signed_in or not alerts_enabled or market_source_status == "sample",
                help="Sample-mode pools cannot become persistent alerts." if market_source_status == "sample" else None,
            ):
                start_alert_creation(current_pool_id)
                st.rerun()
        with c3:
            if st.button(
                "Research"
                if research_modeling_enabled
                else f"Research · {required_tier_name(Capability.RESEARCH_MODELING)}",
                key=f"pool_research_{current_pool_id}",
                width="stretch",
                disabled=not research_modeling_enabled,
            ):
                open_research(current_pool_id)
                st.rerun()
        with c4:
            with st.container(key="pool_detail_open_pool"):
                st.link_button("Open on protocol ↗", row["pool_url"], width="stretch")
                st.caption("External destination")
        st.markdown("</div>", unsafe_allow_html=True)

elif content_page == "Strategy Builder":
    if not pro_tools_enabled:
        preview = strategy_builder_filter(df, True, 8.0, 10_000_000.0, 40, "Any")[["project", "chain", "symbol", "apy", "risk_score", "signal"]].copy().head(8)
        preview.columns = ["Protocol", "Chain", "Asset", "APY", "Risk", "Signal"]
        require_pro("Strategy Builder", preview_df=preview, preview_note="Build reusable rules-based matching slices in Pro.")
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
            view = strategy_table_source[[column for column, _ in STRATEGY_RESULTS_TABLE_COLUMNS]].copy()
            render_internal_pool_table(
                view,
                STRATEGY_RESULTS_TABLE_COLUMNS,
                return_route="Pro Tools",
                return_view="Strategy Builder",
                formats={"apy": "percent", "tvlUsd": "money", "risk_score": "number"},
                max_height=520,
            )
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
            selected_strategy_row = strategy_rows[selected_strategy_pool]
            st.caption(
                strategy_match_explanation(
                    selected_strategy_row,
                    stable_only=builder_stable,
                    min_apy=builder_min_apy,
                    min_tvl=float(builder_min_tvl),
                    max_risk=builder_max_risk,
                    signal_preference=signal_pref,
                )
            )
            selected_is_saved = selected_strategy_pool in saved_pool_ids
            action_open, action_research, action_watch, action_alert = st.columns(4)
            with action_open:
                if st.button("Open Pool", key="strategy_result_detail", type="primary", width="stretch"):
                    track_research_event("pool_detail_opened", {"pool": selected_strategy_pool, "view": "Strategy Builder"})
                    open_pool_detail(selected_strategy_pool, return_route="Pro Tools", return_view="Strategy Builder")
                    st.rerun()
            with action_research:
                if st.button("Compare / Research", key="strategy_result_research", width="stretch"):
                    open_research(selected_strategy_pool)
                    st.rerun()
            with action_watch:
                watch_label = "Remove from Watchlist" if selected_is_saved else "Save to Watchlist"
                if st.button(
                    watch_label,
                    key="strategy_result_watch",
                    width="stretch",
                    disabled=watchlist_client is None,
                ):
                    if watch_toggle(selected_strategy_pool, watched=selected_is_saved, client=watchlist_client):
                        st.rerun()
            with action_alert:
                if st.button(
                    "Create Alert",
                    key="strategy_result_alert",
                    width="stretch",
                    disabled=market_source_status == "sample",
                ):
                    start_alert_creation(selected_strategy_pool)
                    st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

elif content_page == "Activity & Digests":
    render_recaps_page(
        alert_stats,
        history_latest_df,
        history_trend_df,
        full_signals_enabled,
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
            if st.button("Explore pools to save", key="watchlist_empty_discover", type="primary"):
                go_to_route("Discover", view="All Pools")
                st.rerun()
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
                        watch_allowed=watchlists_enabled,
                        alert_allowed=alerts_enabled,
                        research_allowed=research_modeling_enabled,
                        watchlist_client=watchlist_client,
                        freshness_label=market_freshness["label"],
                        return_route="Watchlists",
                        key_prefix="watchlist",
                        alerts_available=market_source_status != "sample",
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
    render_status(
        "info",
        "Future beta pricing preview",
        "Core, Plus, and the $24.99 Pro plan are planned capability tiers. Their Stripe products and purchase paths do not exist yet.",
    )
    pricing_columns = st.columns(len(PLANNED_TIERS), gap="medium")
    for pricing_column, tier in zip(pricing_columns, PLANNED_TIERS, strict=True):
        with pricing_column:
            st.markdown("<div class='panel'>", unsafe_allow_html=True)
            section_header(tier.name, tier.monthly_price, tier.purpose)
            st.markdown("\n".join(f"- {feature}" for feature in tier.features))
            if tier.name == "Free":
                st.success("Available now")
            else:
                st.info("Planned · not yet purchasable")
            st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='panel'>", unsafe_allow_html=True)
    section_header(
        "Current billing compatibility",
        "Existing Pro remains unchanged during beta compatibility",
        "The current trusted Free/Pro entitlement and existing $20 Pro checkout remain in place until the planned four-tier billing migration.",
    )
    if is_pro:
        st.success(f"Current Pro is active through {billing_access_source(db_user).lower()} and centrally maps to the top-tier beta capability profile.")
    else:
        render_billing_action(db_user, label="Current Pro checkout — $20/month")
    st.caption("No Core, Plus, or $24.99 Pro checkout is enabled. Paid access still appears only after current Stripe fulfillment is verified by FuruFlow.")
    st.markdown("</div>", unsafe_allow_html=True)

elif content_page == "Methodology & Data Status":
    st.markdown("<div class='panel'>", unsafe_allow_html=True)
    section_header(
        "Live data status",
        "Can the current market snapshot support research right now?",
        "Status and coverage below are derived from the current normalized provider response. They are not uptime history, provider SLAs, or invented monitoring data.",
    )
    status_summary = market_status_summary(df)
    availability_labels = {
        "available": "Available",
        "partial": "Partial",
        "sample": "Sample only",
        "unavailable": "Unavailable",
    }
    if market_data_status.availability == "unavailable":
        render_status("error", "Provider unavailable", f"{market_source_label} returned no usable rows; no sample opportunities were substituted.")
        st.button("Retry market data", key="data_status_retry", type="primary", on_click=refresh_market_data)
    elif market_data_status.availability == "sample":
        render_status("degraded", "Development sample mode", f"{market_source_label}; values must not be interpreted as live.")
    elif market_data_status.availability == "partial":
        render_status(
            "degraded",
            "Partial provider response",
            market_data_status.detail or f"{market_source_label} returned usable rows with reported degradation.",
        )
    else:
        render_status(market_freshness["kind"], f"{market_source_label} · {market_freshness['label']}", market_freshness["age"] + ".")

    status_metrics = st.columns(4)
    status_metrics[0].metric("Current availability", availability_labels[market_data_status.availability])
    status_metrics[1].metric("Freshness", market_freshness["label"])
    status_metrics[2].metric("Pools represented", f"{status_summary.pools:,}" if status_summary.pools else "Unavailable")
    status_metrics[3].metric("Networks represented", f"{status_summary.networks:,}" if status_summary.pools else "Unavailable")
    coverage_context = st.columns(3)
    coverage_context[0].metric("Protocols represented", f"{status_summary.protocols:,}" if status_summary.pools else "Unavailable")
    coverage_context[1].metric("Assets represented", f"{status_summary.assets:,}" if status_summary.pools else "Unavailable")
    retrieved_at = market_data_status.retrieved_at
    coverage_context[2].metric(
        "Latest retrieval",
        retrieved_at.astimezone(timezone.utc).strftime("%b %d · %H:%M UTC") if retrieved_at else "Not reported",
    )
    observed_status_count = int(df["signal_available"].fillna(False).astype(bool).sum()) if "signal_available" in df else 0
    non_steady_status_count = (
        int(df.loc[df["signal_available"].fillna(False).astype(bool), "signal"].ne("Steady").sum())
        if observed_status_count and "signal" in df
        else 0
    )
    signal_status = st.columns(3)
    signal_status[0].metric(POOLS_EVALUATED_LABEL, f"{len(df):,}" if len(df) else "Unavailable")
    signal_status[1].metric(OBSERVED_SIGNAL_EVIDENCE_LABEL, f"{observed_status_count:,}")
    signal_status[2].metric(NON_STEADY_CLASSIFICATIONS_LABEL, f"{non_steady_status_count:,}")
    st.caption("A zero observed-evidence count means history was insufficient or unavailable; it does not mean every pool was Steady.")
    st.caption(
        f"Provider: {market_source_label}. {market_freshness['age']}. "
        "The retrieval timestamp describes FuruFlow's current fetch, because the provider does not report a per-pool observation time."
    )

    st.markdown("### Current field coverage")
    st.caption("Each denominator is the total number of pools represented in the current normalized response; missing values are not counted as zero.")
    if status_summary.pools:
        for metric in status_summary.coverage:
            percent = metric.percent or 0.0
            st.progress(
                min(1.0, max(0.0, percent / 100.0)),
                text=f"{metric.label}: {metric.available:,} / {metric.total:,} pools ({percent:.1f}%)",
            )
    else:
        st.info("Coverage is unavailable because the current provider response contains no represented pools.")

    section_header(
        "Methodology",
        "How FuruFlow builds research context",
        "The sections below explain what providers report, what FuruFlow derives, what missing values mean, and where decision support stops.",
    )

    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("### Data sources and freshness")
        st.markdown(
            "FuruFlow requests the DeFiLlama Yields pool feed and accepts only rows with a complete pool ID, network, protocol, and asset identity. "
            "It consumes reported APY components, TVL, volume when present, pool metadata, exposure, and stablecoin metadata. Market snapshots use a 15-minute cache."
        )
        st.markdown(
            "Current means retrieved within 20 minutes, Aging means more than 20 and no more than 60 minutes, and Stale means older than 60 minutes. "
            "A partial response is labelled partial. If providers return no usable data, the market is unavailable rather than silently replaced; sample data appears only in explicit development sample mode."
        )
        st.markdown(
            "Pool Detail requests DeFiLlama pool history separately. If that history endpoint is unavailable, legitimately stored FuruFlow observations may be shown and labelled stored; otherwise the series remains unavailable."
        )

        st.markdown("### Pool identity")
        st.markdown(
            "The provider's canonical pool ID distinguishes pools that may share the same protocol, asset symbol, or network. "
            "FuruFlow carries that same identity through Discover, Pool Detail, Watchlist, Alerts, Signals, Research, and Pro Tools so an action cannot silently target a look-alike pool."
        )

        st.markdown("### Metrics")
        st.markdown(
            "**APY, base APY, reward APY, TVL, and volume** are provider-reported when available. Missing reported values remain unavailable in explanatory views. "
            "**Protocol, network, asset/pair, metadata, and exposure** describe pool identity and composition. "
            "**Signal movement values** summarize recent APY and TVL change plus APY volatility from available chart observations."
        )
        st.markdown("### Evidence and confidence")
        st.markdown(
            "**Evidence coverage** records whether usable APY and TVL history is absent, insufficient, partial, or sufficient. "
            "**Confidence** measures how much evidence supports FuruFlow's analytical assessment—not certainty about future returns. "
            "Risk remains a separate interpretation of the inputs that are available. A fresh current APY, a large TVL, or a high reported APY cannot replace required history."
        )
        st.markdown(
            "Moderate confidence requires at least 14 valid paired APY/TVL observations spanning at least 7 days with at least 70% continuity. "
            "High confidence requires at least 30 valid APY and 30 valid TVL observations spanning at least 30 days with at least 80% continuity, "
            "complete current provider data, sufficient base/reward APY history, and signal history. "
            "Historical evidence older than 48 hours limits confidence. "
            "Missing prerequisites cap confidence explicitly; no expected APY or profitability estimate is created."
        )

        st.markdown("### Discovery methodology")
        st.markdown(
            "Opportunities applies the user's search and filters, then the selected deterministic sort. Filters decide eligibility; sorting decides order. "
            "The default Investigation priority order compares confidence first, then evidence coverage, lower existing risk score, larger reported TVL, and finally higher reported APY; canonical pool ID breaks ties. "
            "This makes APY a visible input without allowing its magnitude alone to dominate the default order. The optional existing FuruFlow rank remains available and unchanged. "
            "All Pools is different: it exposes the normalized provider universe without Discover's default TVL, risk, ranking, or Free/Pro depth thresholds, while preserving the user's explicit filters and sort."
        )
        st.markdown(
            "Missing APY or TVL does not pass a positive minimum for that metric, missing values sort last where applicable, and canonical pool ID breaks stable ties."
        )

        st.markdown("### Signals methodology")
        st.markdown(
            "For a bounded sample of current pools, FuruFlow compares recent chart observations and preserves its existing labels: APY spike, Whale inflow, Emerging pool, Farm rotation, or Steady. "
            "Signal strength uses the existing APY movement, TVL movement, and APY-volatility calculation. Durable signal history and Activity/Digests are separate from the current market snapshot."
        )
        st.markdown(
            f"**{OBSERVED_SIGNAL_EVIDENCE_LABEL}** is field coverage: pools with a successfully retrieved signal-history snapshot out of all pools in the normalized provider response. "
            f"**{POOLS_EVALUATED_LABEL}** is the current visible signal-analysis universe and includes Steady classifications. "
            f"**{NON_STEADY_CLASSIFICATIONS_LABEL}** counts only visible pools with observed signal evidence whose current rules-based label is not Steady."
        )
        st.markdown(
            "A signal describes detected movement in available observations. It does not identify causation, predict persistence, establish safety, or recommend a transaction."
        )

    with right:
        st.markdown("### Risk interpretation")
        st.markdown(
            "Risk labels are contextual heuristics, not an audit, probability of loss, or formal risk rating. The existing UI score uses protocol-age and audit-confidence defaults, TVL stability, reward dependence, and pool-volatility context. "
            "Pool Detail exposes available factors and marks the interpretation unknown when important inputs are missing."
        )

        st.markdown("### Watchlists and alerts")
        st.markdown(
            "A **Watchlist entry** is a durable saved canonical pool used for monitoring. An **Alert** is a separate durable notification rule for a canonical pool, signal tier, minimum strength, timing, timezone, and cooldown. "
            "Saving or removing a pool does not create, pause, resume, or delete an alert; changing an alert does not modify Watchlist. Both objects remain owned by the authenticated user."
        )
        st.markdown(
            "Telegram delivery uses the verified connected destination. FuruFlow never asks the browser to supply or display the raw routing identifier."
        )

        st.markdown("### Research")
        st.markdown(
            "Research analyzes a deliberately selected set of two to four current pools. It min-max normalizes reported APY, reported TVL, the existing risk score (lower is better), and existing signal strength only within that selected set. "
            "User weights are proportionally normalized. Equal known values receive a neutral score, missing dimensions are excluded from that pool's denominator, and weighted-data coverage is disclosed. Yield Seeking, Balanced, and Conservative are transparent presets—not personalized advice. "
            "Rankings are reproducible decision support, not predictions, safety ratings, or recommendations. A different selection changes the normalization context."
        )

        st.markdown("### Product capabilities")
        st.markdown(
            "The planned ladder is Free for discovery, Core for durable Watchlists, Plus for Alerts and Research modeling, and Pro — $24.99 for Strategy Builder, Yield Spreads, CSV export, and workflow acceleration. "
            "The beta does not yet add those Stripe products: today's trusted Free entitlement maps to Free capabilities and today's trusted Pro entitlement centrally maps to all beta capabilities until billing migration."
        )

        st.markdown("### Pro Tools")
        st.markdown(
            "Strategy Builder applies user-chosen constraints to the existing enriched pool data and returns matching candidates. Yield Spreads compares reported APY for the same displayed asset symbol across networks when the existing minimum difference is met. "
            "Unlike Discover, these are intentional advanced analyses; a spread is not an executable or risk-free arbitrage calculation."
        )
        st.caption("Activity & Digests is not in primary beta navigation because the current history store records market signals, not a durable per-user Watchlist/Alert activity timeline.")

        st.markdown("### Limitations")
        st.markdown(
            "- Yields, incentives, TVL, liquidity, and token prices can change quickly.\n"
            "- Provider data can be partial, stale, unavailable, or inconsistent across reported total and component APY.\n"
            "- FuruFlow does not audit smart contracts or eliminate protocol, oracle, bridge, network, governance, or operational risk.\n"
            "- TVL is context about reported pool size, not a guarantee of liquidity, exit capacity, or safety.\n"
            "- Token price exposure and impermanent loss can matter for multi-asset or directional pools.\n"
            "- Historical context may be incomplete, and the current signal sample is bounded.\n"
            "- Signals and heuristic risk labels are descriptive, not predictive, personalized advice, or a promise of return."
        )
    st.markdown("</div>", unsafe_allow_html=True)

elif content_page == "Alerts":
    alert_target_df = df if market_source_status in {"live", "partial"} else df.iloc[0:0]
    render_alerts_page(
        alert_target_df,
        alerts_entitled=alerts_enabled,
        full_signal_access=full_signals_enabled,
        account_timezone=str(db_user.get("timezone") or "UTC"),
    )

elif content_page == "Account & Billing":
    st.markdown("<div class='panel'>", unsafe_allow_html=True)
    plan_presentation = capability_presentation(capabilities)
    section_header(
        "Account & Billing",
        str(db_user.get("email") or "Signed-in account"),
        "Your plan and available actions come from verified FuruFlow account state.",
    )
    current_plan = str(plan_presentation["plan"])
    render_status(
        "success" if is_pro else "info",
        f"{current_plan} plan",
        f"Access source: {billing_access_source(db_user)}. Entitlement is reconstructed from trusted account state.",
    )
    capability_columns = st.columns(2, gap="large")
    with capability_columns[0]:
        st.markdown("### Included now")
        st.markdown("\n".join(f"- {feature}" for feature in plan_presentation["included"]))
    with capability_columns[1]:
        st.markdown("### Not included")
        unavailable_features = plan_presentation["unavailable"]
        if unavailable_features:
            st.markdown("\n".join(f"- {feature}" for feature in unavailable_features))
        else:
            st.markdown("All capabilities in the current beta ladder are available.")
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

    st.markdown("### Telegram")
    if alerts_enabled:
        try:
            account_telegram_status = current_user_notification_client().telegram_status()
        except RuntimeError:
            render_status(
                "degraded",
                "Telegram state unavailable",
                "FuruFlow could not verify the notification connection. No routing identifier was shown or guessed; retry later from Alerts.",
            )
        else:
            telegram_connected = bool(account_telegram_status.get("available"))
            render_status(
                "success" if telegram_connected else "warning",
                "Telegram connected" if telegram_connected else "Telegram not connected",
                (
                    "The verified notification destination is ready; routing identifiers remain hidden."
                    if telegram_connected
                    else "A trusted operator must verify and link Telegram before alert delivery is available."
                ),
            )
    else:
        render_status(
            "restricted",
            f"Telegram Alerts require {required_tier_name(Capability.ALERTS)}",
            "Your current plan does not include durable alert rules.",
        )

    st.markdown("### Beta support and diagnostics")
    st.markdown(
        "When reporting an issue, include the page, approximate time, pool, attempted action, and visible error. "
        "Do not send passwords, magic links, access or refresh tokens, session cookies, or other credentials."
    )
    if BETA_DIAGNOSTICS.support_url:
        st.link_button("Open beta support ↗", BETA_DIAGNOSTICS.support_url)
        st.caption("External support destination")
    else:
        render_status(
            "warning",
            "Support destination not configured",
            "This build has no configured feedback URL. Deployment must set FURUFLOW_SUPPORT_URL to an approved HTTPS destination.",
        )
    diagnostic_columns = st.columns(3)
    diagnostic_columns[0].metric("Environment", BETA_DIAGNOSTICS.environment)
    diagnostic_columns[1].metric("App version", BETA_DIAGNOSTICS.app_version)
    diagnostic_columns[2].metric("Build", BETA_DIAGNOSTICS.build_id or "Not supplied")
    st.caption("Only non-sensitive release metadata is shown. Credentials, connection strings, tokens, and raw service configuration are never displayed.")
    if st.button("Sign out", key="account_page_logout"):
        logout()
        st.rerun()
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
