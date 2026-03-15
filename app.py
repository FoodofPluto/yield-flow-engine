from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

APP_NAME = "FuruFlow"
APP_TAGLINE = "A cleaner yield intelligence cockpit for DeFi hunters"
POOL_LIMIT = 300
TIMEOUT = 20

st.set_page_config(
    page_title=APP_NAME,
    page_icon="🐸",
    layout="wide",
    initial_sidebar_state="expanded",
)


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
                --surface-light: #eaf6ff;
                --surface-light-2: #d9f1ff;
                --surface-dark-text: #08111f;
                --surface-dark-text-2: #11233b;
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
                max-width: 1580px;
                padding-top: 1.2rem;
                padding-bottom: 2rem;
                padding-left: 1.6rem;
                padding-right: 1.6rem;
            }

            h1, h2, h3, h4, h5, h6, p, span, label, div {
                color: var(--text);
            }

            .hero-shell {
                border: 1px solid var(--border);
                border-radius: 28px;
                overflow: hidden;
                background: linear-gradient(150deg, rgba(17,32,54,0.98), rgba(9,18,31,0.98));
                box-shadow: 0 30px 80px rgba(0,0,0,0.28);
                margin-bottom: 1rem;
            }

            .hero-inner {
                padding: 1.6rem 1.7rem 1.3rem 1.7rem;
                background:
                    radial-gradient(circle at 85% 0%, rgba(124,226,255,0.12), transparent 22%),
                    linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0));
            }

            .eyebrow {
                display: inline-flex;
                align-items: center;
                gap: 0.45rem;
                padding: 0.34rem 0.7rem;
                border-radius: 999px;
                background: rgba(255,255,255,0.05);
                border: 1px solid var(--border);
                color: var(--accent);
                font-size: 0.78rem;
                font-weight: 800;
                letter-spacing: 0.08em;
                text-transform: uppercase;
                margin-bottom: 0.8rem;
            }

            .hero-title {
                font-size: 2.55rem;
                line-height: 1;
                font-weight: 900;
                margin-bottom: 0.4rem;
                letter-spacing: -0.03em;
            }

            .hero-subtitle {
                max-width: 920px;
                font-size: 1rem;
                line-height: 1.6;
                color: var(--muted);
            }

            .top-band {
                display: grid;
                grid-template-columns: repeat(4, minmax(0, 1fr));
                gap: 0.85rem;
                margin-top: 1rem;
            }

            .stat-card {
                background: linear-gradient(180deg, rgba(18,36,61,0.98), rgba(11,21,37,0.98));
                border: 1px solid var(--border);
                border-radius: 22px;
                padding: 1rem 1rem 0.95rem 1rem;
                box-shadow: 0 12px 28px rgba(0,0,0,0.18);
                min-height: 116px;
            }

            .stat-label {
                color: var(--muted);
                font-size: 0.82rem;
                font-weight: 700;
                margin-bottom: 0.35rem;
            }

            .stat-value {
                color: var(--text);
                font-size: 1.75rem;
                font-weight: 900;
                line-height: 1.05;
                margin-bottom: 0.2rem;
                letter-spacing: -0.02em;
            }

            .stat-note {
                color: var(--muted);
                font-size: 0.82rem;
                line-height: 1.45;
            }

            .panel {
                background: linear-gradient(180deg, rgba(13,27,47,0.96), rgba(9,18,31,0.98));
                border: 1px solid var(--border);
                border-radius: 24px;
                padding: 1rem 1rem 1.1rem 1rem;
                box-shadow: 0 14px 34px rgba(0,0,0,0.16);
            }

            .section-kicker {
                color: var(--accent);
                font-size: 0.77rem;
                font-weight: 800;
                letter-spacing: 0.08em;
                text-transform: uppercase;
                margin-bottom: 0.25rem;
            }

            .section-title {
                color: var(--text);
                font-size: 1.1rem;
                font-weight: 800;
                margin-bottom: 0.2rem;
            }

            .section-copy {
                color: var(--muted);
                font-size: 0.88rem;
                line-height: 1.5;
                margin-bottom: 0.75rem;
            }

            [data-testid="stSidebar"] {
                background: linear-gradient(180deg, rgba(9,18,31,1), rgba(7,16,28,1));
                border-right: 1px solid var(--border);
            }

            [data-testid="stSidebar"] * {
                color: var(--text) !important;
            }

            [data-testid="stSidebar"] .stMarkdown p {
                color: var(--muted) !important;
            }

            div[data-testid="stDataFrame"] {
                border: 1px solid var(--border);
                border-radius: 18px;
                overflow: hidden;
            }

            /* FIX: Make control interiors light with dark readable text */
            div[data-baseweb="select"] > div,
            div[data-baseweb="input"] > div,
            div[data-baseweb="select"] input,
            div[data-baseweb="select"] span,
            div[data-baseweb="select"] div,
            .stNumberInput div[data-baseweb="input"] > div,
            .stSelectbox div[data-baseweb="select"] > div,
            .stMultiSelect div[data-baseweb="select"] > div {
                background: var(--surface-light) !important;
                border-color: rgba(0,0,0,0.08) !important;
                color: var(--surface-dark-text) !important;
            }

            div[data-baseweb="popover"],
            div[data-baseweb="menu"],
            ul[role="listbox"] {
                background: #f6fbff !important;
                color: var(--surface-dark-text) !important;
            }

            li[role="option"],
            div[role="option"],
            ul[role="listbox"] li,
            [data-baseweb="menu"] li,
            [data-baseweb="menu"] div {
                color: var(--surface-dark-text) !important;
                background: #f6fbff !important;
                font-weight: 700 !important;
            }

            li[role="option"][aria-selected="true"],
            div[role="option"][aria-selected="true"] {
                background: #dcefff !important;
                color: var(--surface-dark-text) !important;
            }

            div[data-baseweb="tag"] {
                background: var(--surface-light-2) !important;
                border-color: rgba(0,0,0,0.08) !important;
            }

            div[data-baseweb="tag"] span,
            div[data-baseweb="tag"] svg,
            div[data-baseweb="select"] input,
            div[data-baseweb="select"] span,
            div[data-baseweb="select"] div,
            div[data-baseweb="input"] input,
            .stDownloadButton button,
            .stButton button,
            .stSelectbox label,
            .stMultiSelect label,
            .stNumberInput label,
            .stToggle label {
                color: var(--surface-dark-text) !important;
                font-weight: 700 !important;
            }

            .stMultiSelect label,
            .stSelectbox label,
            .stNumberInput label,
            .stSlider label,
            .stToggle label,
            .stRadio label {
                color: var(--text) !important;
                font-weight: 700 !important;
            }

            .stSlider [data-baseweb="slider"] > div > div > div {
                background: var(--accent-2) !important;
            }

            .stSlider [role="slider"] {
                background: var(--surface-light) !important;
                border: 2px solid #c8f7ff !important;
                box-shadow: 0 0 0 4px rgba(124,226,255,0.15);
            }

            .stSlider [data-testid="stTickBarMin"],
            .stSlider [data-testid="stTickBarMax"],
            .stSlider [data-testid="stWidgetLabel"] + div,
            .stSlider span {
                color: var(--surface-dark-text-2) !important;
            }

            .stDownloadButton button,
            .stButton button {
                background: linear-gradient(180deg, #9beeff, #6eddff) !important;
                border: 1px solid rgba(0,0,0,0.08) !important;
                border-radius: 12px !important;
                padding: 0.58rem 0.9rem !important;
                color: #07111f !important;
                font-weight: 800 !important;
            }

            .stTabs [data-baseweb="tab-list"] {
                gap: 0.45rem;
                background: rgba(255,255,255,0.02);
                padding: 0.3rem;
                border-radius: 16px;
                border: 1px solid var(--border);
            }

            .stTabs [data-baseweb="tab"] {
                height: 44px;
                border-radius: 12px;
                color: var(--muted) !important;
                font-weight: 800;
                padding-left: 1rem;
                padding-right: 1rem;
            }

            .stTabs [aria-selected="true"] {
                background: linear-gradient(180deg, rgba(124,226,255,0.18), rgba(124,226,255,0.08));
                color: var(--text) !important;
            }

            .note {
                color: var(--muted);
                font-size: 0.84rem;
                line-height: 1.5;
            }

            .risk-chip {
                display: inline-flex;
                align-items: center;
                gap: 0.35rem;
                padding: 0.3rem 0.62rem;
                border-radius: 999px;
                font-size: 0.78rem;
                font-weight: 800;
                border: 1px solid var(--border);
                background: rgba(255,255,255,0.05);
            }

            .badge-row {
                display: flex;
                flex-wrap: wrap;
                gap: 0.45rem;
                margin-top: 0.65rem;
                margin-bottom: 0.65rem;
            }

            .badge {
                display: inline-flex;
                align-items: center;
                gap: 0.35rem;
                border-radius: 999px;
                padding: 0.32rem 0.65rem;
                background: rgba(124,226,255,0.12);
                border: 1px solid rgba(124,226,255,0.18);
                color: #dff8ff;
                font-size: 0.76rem;
                font-weight: 800;
            }

            .opp-card {
                border: 1px solid var(--border);
                border-radius: 20px;
                padding: 1rem;
                background: linear-gradient(180deg, rgba(17,34,57,0.98), rgba(9,18,31,0.98));
                box-shadow: 0 12px 28px rgba(0,0,0,0.16);
                min-height: 240px;
            }

            .opp-top {
                display: flex;
                justify-content: space-between;
                align-items: flex-start;
                gap: 0.75rem;
                margin-bottom: 0.75rem;
            }

            .opp-name {
                font-size: 1.05rem;
                font-weight: 900;
                line-height: 1.15;
            }

            .opp-sub {
                color: var(--muted);
                font-size: 0.84rem;
                margin-top: 0.18rem;
            }

            .protocol-dot {
                width: 42px;
                height: 42px;
                border-radius: 14px;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                background: linear-gradient(180deg, rgba(124,226,255,0.24), rgba(94,199,255,0.14));
                border: 1px solid rgba(124,226,255,0.16);
                font-weight: 900;
                color: white;
            }

            .metric-strip {
                display: grid;
                grid-template-columns: repeat(3, minmax(0, 1fr));
                gap: 0.65rem;
                margin-top: 0.75rem;
            }

            .metric-box {
                border-radius: 16px;
                padding: 0.72rem;
                background: rgba(255,255,255,0.035);
                border: 1px solid var(--border);
            }

            .metric-mini-label {
                color: var(--muted);
                font-size: 0.72rem;
                font-weight: 700;
                margin-bottom: 0.18rem;
            }

            .metric-mini-value {
                color: var(--text);
                font-size: 1rem;
                font-weight: 900;
            }

            .watch-pill {
                display: inline-flex;
                align-items: center;
                gap: 0.35rem;
                border-radius: 999px;
                padding: 0.25rem 0.6rem;
                background: rgba(53,212,154,0.12);
                color: #caffec;
                font-size: 0.74rem;
                font-weight: 800;
                border: 1px solid rgba(53,212,154,0.18);
            }

            @media (max-width: 1100px) {
                .top-band {
                    grid-template-columns: repeat(2, minmax(0, 1fr));
                }
                .hero-title {
                    font-size: 2.1rem;
                }
            }

            @media (max-width: 700px) {
                .top-band {
                    grid-template-columns: repeat(1, minmax(0, 1fr));
                }
            }
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
                chart["timestamp"] = pd.to_datetime(chart["timestamp"], errors="coerce")
            elif "date" in chart.columns:
                chart["timestamp"] = pd.to_datetime(chart["date"], errors="coerce")
            chart = chart.dropna(subset=["timestamp"]).sort_values("timestamp")
            return chart
        except Exception:
            continue
    return pd.DataFrame()


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
    data["risk_score"] = data.apply(score_pool, axis=1)
    data["risk_band"] = data["risk_score"].apply(label_risk)
    data["pool_url"] = data.apply(build_pool_url, axis=1)
    data["scorecard"] = data.apply(build_scorecard, axis=1)
    data["chain_project"] = data["chain"] + " • " + data["project"]
    data["protocol_badge"] = data["project"].apply(protocol_badge)
    data["watch_label"] = data.apply(
        lambda row: f"{row['project']} • {row['symbol']} • {row['chain']} • {row['apy']:.2f}%",
        axis=1,
    )
    data["rank_score"] = (
        data["apy"].clip(lower=0, upper=80) * 0.7
        + (data["tvlUsd"].clip(lower=0).rank(pct=True) * 20)
        - (data["risk_score"] * 0.35)
    )
    data = data.sort_values(["rank_score", "apy", "tvlUsd"], ascending=[False, False, False])
    return data


def protocol_badge(project: str) -> str:
    parts = [p for p in str(project).replace("_", "-").split("-") if p]
    letters = "".join(part[0] for part in parts[:2]).upper()
    return letters[:2] if letters else "??"


def score_pool(row: pd.Series) -> int:
    score = 42
    apy = float(row.get("apy", 0) or 0)
    tvl = float(row.get("tvlUsd", 0) or 0)
    exposure = str(row.get("exposure", "")).lower()
    stablecoin = bool(row.get("stablecoin", False))
    strategy = str(row.get("poolMeta", "")).lower()
    rewards = float(row.get("apyReward", 0) or 0)

    if apy > 120:
        score += 35
    elif apy > 60:
        score += 24
    elif apy > 30:
        score += 14
    elif apy > 15:
        score += 7
    elif apy < 8:
        score -= 4

    if rewards > 15:
        score += 8
    elif rewards > 5:
        score += 4

    if tvl < 1_000_000:
        score += 24
    elif tvl < 10_000_000:
        score += 15
    elif tvl < 50_000_000:
        score += 8
    elif tvl > 500_000_000:
        score -= 10

    if exposure in {"multi", "lp"}:
        score += 10
    if stablecoin:
        score -= 7
    if any(word in strategy for word in ["farm", "lever", "loop", "volatility", "dex"]):
        score += 10
    if any(word in strategy for word in ["lend", "borrow", "cdp"]):
        score -= 5

    return max(1, min(100, int(round(score))))


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
    return ""


def build_scorecard(row: pd.Series) -> str:
    parts = []
    parts.append("Stable" if row.get("stablecoin", False) else "Directional")
    parts.append("Deep TVL" if float(row.get("tvlUsd", 0) or 0) >= 100_000_000 else "Lighter TVL")
    parts.append(label_risk(int(row.get("risk_score", 50))))
    return " • ".join(parts)


def sample_pool_data(errors: list[str]) -> pd.DataFrame:
    demo = pd.DataFrame(
        [
            {
                "pool": "demo-1",
                "chain": "Ethereum",
                "project": "aave-v3",
                "symbol": "USDC",
                "tvlUsd": 1450000000,
                "apy": 4.18,
                "apyBase": 3.61,
                "apyReward": 0.57,
                "poolMeta": "Lending",
                "exposure": "single",
                "stablecoin": True,
                "volumeUsd1d": 25000000,
            },
            {
                "pool": "demo-2",
                "chain": "Arbitrum",
                "project": "camelot-v3",
                "symbol": "ETH-USDC",
                "tvlUsd": 23800000,
                "apy": 22.40,
                "apyBase": 10.10,
                "apyReward": 12.30,
                "poolMeta": "LP",
                "exposure": "multi",
                "stablecoin": False,
                "volumeUsd1d": 8200000,
            },
            {
                "pool": "demo-3",
                "chain": "Base",
                "project": "morpho-v1",
                "symbol": "USDC",
                "tvlUsd": 980000000,
                "apy": 7.02,
                "apyBase": 6.22,
                "apyReward": 0.80,
                "poolMeta": "Lending",
                "exposure": "single",
                "stablecoin": True,
                "volumeUsd1d": 17000000,
            },
            {
                "pool": "demo-4",
                "chain": "Sonic",
                "project": "beefy",
                "symbol": "wS-ETH",
                "tvlUsd": 8600000,
                "apy": 29.8,
                "apyBase": 9.6,
                "apyReward": 20.2,
                "poolMeta": "Farm",
                "exposure": "multi",
                "stablecoin": False,
                "volumeUsd1d": 2100000,
            },
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
    st.markdown(
        f"""
        <div class="stat-card">
            <div class="stat-label">{label}</div>
            <div class="stat-value">{value}</div>
            <div class="stat-note">{note}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def section_header(kicker: str, title: str, copy: str) -> None:
    st.markdown(
        f"""
        <div class="section-kicker">{kicker}</div>
        <div class="section-title">{title}</div>
        <div class="section-copy">{copy}</div>
        """,
        unsafe_allow_html=True,
    )


def top_n_summary(df: pd.DataFrame, group_col: str, metric_col: str, n: int = 10) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    summary = (
        df.groupby(group_col, as_index=False)
        .agg(
            total_tvl=("tvlUsd", "sum"),
            median_apy=("apy", "median"),
            pools=("pool", "count"),
            avg_risk=("risk_score", "mean"),
        )
        .sort_values(metric_col, ascending=False)
        .head(n)
    )
    return summary


def make_download_df(df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "project",
        "chain",
        "symbol",
        "strategy_type",
        "apy",
        "apyBase",
        "apyReward",
        "tvlUsd",
        "volumeUsd1d",
        "risk_score",
        "risk_band",
        "scorecard",
        "pool_url",
    ]
    return df[[c for c in cols if c in df.columns]].copy()


def compact_table(df: pd.DataFrame) -> pd.DataFrame:
    table = df[
        [
            "project",
            "chain",
            "symbol",
            "strategy_type",
            "apy",
            "apyBase",
            "apyReward",
            "tvlUsd",
            "risk_score",
            "risk_band",
            "pool_url",
        ]
    ].rename(
        columns={
            "project": "Protocol",
            "chain": "Chain",
            "symbol": "Asset",
            "strategy_type": "Strategy",
            "apy": "APY",
            "apyBase": "Base",
            "apyReward": "Rewards",
            "tvlUsd": "TVL (USD)",
            "risk_score": "Risk",
            "risk_band": "Band",
            "pool_url": "Open",
        }
    )
    return table


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


def render_opportunity_card(row: pd.Series, idx: int, watched: bool) -> None:
    watch_html = '<span class="watch-pill">★ Watched</span>' if watched else ''
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
            {watch_html}
            <div class="badge-row">
                <span class="badge">{row['strategy_type']}</span>
                <span class="badge">{row['risk_band']} risk</span>
                <span class="badge">{row['scorecard']}</span>
            </div>
            <div class="metric-strip">
                <div class="metric-box">
                    <div class="metric-mini-label">APY</div>
                    <div class="metric-mini-value">{row['apy']:.2f}%</div>
                </div>
                <div class="metric-box">
                    <div class="metric-mini-label">TVL</div>
                    <div class="metric-mini-value">{format_money(row['tvlUsd'])}</div>
                </div>
                <div class="metric-box">
                    <div class="metric-mini-label">Risk</div>
                    <div class="metric-mini-value">{int(row['risk_score'])}/100</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    c1, c2 = st.columns(2)
    with c1:
        if watched:
            if st.button("Remove", key=f"remove_watch_{idx}", use_container_width=True):
                st.session_state.watchlist = [p for p in st.session_state.watchlist if p != row["pool"]]
                st.rerun()
        else:
            if st.button("Watch", key=f"add_watch_{idx}", use_container_width=True):
                st.session_state.watchlist = list(dict.fromkeys(st.session_state.watchlist + [row["pool"]]))
                st.rerun()
    with c2:
        st.link_button("Open pool", row["pool_url"] or "https://defillama.com/yields", use_container_width=True)


inject_css()
raw_df = fetch_pools()
df = enrich(raw_df)

if "watchlist" not in st.session_state:
    st.session_state.watchlist = []

st.markdown(
    f"""
    <section class="hero-shell">
        <div class="hero-inner">
            <div class="eyebrow">DeFi yield workstation • redesigned</div>
            <div class="hero-title">{APP_NAME}</div>
            <div class="hero-subtitle">{APP_TAGLINE}. This build pushes the app further toward a real product feel with darker readable control text, richer charting, protocol-style badges, a curated opportunity board, and a true watchlist layer on top of live DeFiLlama yield data.</div>
        </div>
    </section>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown(f"## {APP_NAME}")
    st.markdown("Use the filters below to shape a cleaner opportunity set.")

    chains = sorted(df["chain"].dropna().unique().tolist())
    projects = sorted(df["project"].dropna().unique().tolist())
    strategies = sorted(df["strategy_type"].dropna().unique().tolist())

    selected_chains = st.multiselect("Chains", chains, default=chains[: min(len(chains), 8)])
    selected_projects = st.multiselect("Protocols", projects)
    selected_strategies = st.multiselect("Strategy Type", strategies)
    stable_only = st.toggle("Stablecoin pools only", value=False)
    min_tvl = st.slider("Minimum TVL", min_value=0, max_value=500_000_000, value=5_000_000, step=1_000_000)
    max_risk = st.slider("Maximum risk score", min_value=1, max_value=100, value=65)
    min_apy = st.slider("Minimum APY", min_value=0.0, max_value=200.0, value=0.0, step=0.5)
    sort_by = st.selectbox(
        "Sort by",
        ["FuruFlow rank", "Highest APY", "Largest TVL", "Lowest risk", "Highest 24h volume"],
        index=0,
    )
    st.markdown(
        "<div class='note'>Risk score is a heuristic, not a guarantee. It weighs APY extremity, TVL depth, stablecoin status, rewards dependence, and strategy complexity.</div>",
        unsafe_allow_html=True,
    )

filtered = df.copy()
if selected_chains:
    filtered = filtered[filtered["chain"].isin(selected_chains)]
if selected_projects:
    filtered = filtered[filtered["project"].isin(selected_projects)]
if selected_strategies:
    filtered = filtered[filtered["strategy_type"].isin(selected_strategies)]
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
else:
    filtered = filtered.sort_values(["rank_score", "apy", "tvlUsd"], ascending=[False, False, False])

filtered = filtered.head(POOL_LIMIT)
watchlist_df = df[df["pool"].isin(st.session_state.watchlist)].copy()

visible = len(filtered)
median_apy = filtered["apy"].median() if visible else 0.0
total_tvl = filtered["tvlUsd"].sum() if visible else 0.0
lower_risk = (filtered["risk_band"].isin(["Low", "Moderate"]).mean() * 100) if visible else 0.0

st.markdown("<div class='top-band'>", unsafe_allow_html=True)
metric_cols = st.columns(4)
with metric_cols[0]:
    stat_card("Visible opportunities", f"{visible:,}", "Pools left after your current filters")
with metric_cols[1]:
    stat_card("Median APY", f"{median_apy:,.2f}%", "A more stable view of the current pool set")
with metric_cols[2]:
    stat_card("Aggregate TVL", format_money(total_tvl), "Combined depth across the visible market slice")
with metric_cols[3]:
    stat_card("Watchlist", f"{len(watchlist_df):,}", "Pools you marked for repeat tracking")
st.markdown("</div>", unsafe_allow_html=True)

main_tab, market_tab, drill_tab, watch_tab = st.tabs(["Scanner", "Market map", "Pool drilldown", "Watchlist"])

with main_tab:
    left, right = st.columns([1.55, 1], gap="large")

    with left:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header(
            "Opportunity board",
            "Custom scan view",
            "The scanner now leads with richer cards for the top ideas, then falls back to a compact table for deeper browsing and CSV export.",
        )
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
            height=500,
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
        st.download_button(
            "Download current table as CSV",
            csv,
            file_name=f"{APP_NAME.lower()}_scanner.csv",
            mime="text/csv",
        )
        st.markdown("</div>", unsafe_allow_html=True)

    with right:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header(
            "Fast reads",
            "Protocol and chain pulse",
            "These panels make the market feel navigable without forcing the user to inspect dozens of rows first.",
        )
        top_protocols = top_n_summary(filtered, "project", "total_tvl", 8)
        if not top_protocols.empty:
            protocol_view = top_protocols.rename(
                columns={
                    "project": "Protocol",
                    "total_tvl": "TVL (USD)",
                    "median_apy": "Median APY",
                    "pools": "Pools",
                    "avg_risk": "Avg Risk",
                }
            )
            st.dataframe(
                protocol_view,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "TVL (USD)": st.column_config.NumberColumn(format="$%.0f"),
                    "Median APY": st.column_config.NumberColumn(format="%.2f%%"),
                    "Avg Risk": st.column_config.NumberColumn(format="%.0f"),
                },
                height=250,
            )
        else:
            st.info("No protocol summary is available with the current filters.")

        if not filtered.empty:
            bubble = px.scatter(
                filtered.head(80),
                x="risk_score",
                y="apy",
                size="tvlUsd",
                color="chain",
                hover_name="project",
                hover_data={"symbol": True, "tvlUsd": ':$,.0f', "risk_score": True, "apy": ':.2f'},
                size_max=34,
            )
            bubble.update_traces(marker=dict(line=dict(width=1, color="rgba(255,255,255,0.25)"), opacity=0.78))
            bubble.update_xaxes(title="Risk score")
            bubble.update_yaxes(title="APY %")
            st.plotly_chart(plotly_theme(bubble, 325), use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

with market_tab:
    c1, c2 = st.columns([1.1, 1], gap="large")
    with c1:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header(
            "Protocol view",
            "Top protocols by visible TVL",
            "A cleaner TVL-first lens that makes the app feel closer to a public analytics terminal.",
        )
        protocol_summary = top_n_summary(filtered, "project", "total_tvl", 12)
        if not protocol_summary.empty:
            fig = px.bar(
                protocol_summary,
                x="project",
                y="total_tvl",
                color="median_apy",
                hover_data={"pools": True, "avg_risk": ':.1f', "median_apy": ':.2f', "total_tvl": ':$,.0f'},
            )
            fig.update_xaxes(title="")
            fig.update_yaxes(title="TVL (USD)")
            st.plotly_chart(plotly_theme(fig, 390), use_container_width=True)
        else:
            st.info("No protocol chart is available with the current filters.")
        st.markdown("</div>", unsafe_allow_html=True)

    with c2:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header(
            "Chain view",
            "Chain depth snapshot",
            "Use this to quickly see where filtered capital is concentrated before drilling into individual pools.",
        )
        chain_summary = top_n_summary(filtered, "chain", "total_tvl", 12)
        if not chain_summary.empty:
            fig = px.treemap(
                chain_summary,
                path=["chain"],
                values="total_tvl",
                color="median_apy",
                hover_data={"pools": True, "avg_risk": ':.1f', "median_apy": ':.2f', "total_tvl": ':$,.0f'},
            )
            st.plotly_chart(plotly_theme(fig, 390), use_container_width=True)
        else:
            st.info("No chain chart is available with the current filters.")
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='panel' style='margin-top: 1rem;'>", unsafe_allow_html=True)
    section_header(
        "Leaderboard",
        "Market rows with badges",
        "This keeps the market map readable while avoiding the sideways-scroll problem from earlier versions.",
    )
    leaderboard = filtered[["protocol_badge", "project", "chain", "symbol", "apy", "tvlUsd", "risk_score", "scorecard"]].rename(
        columns={
            "protocol_badge": "Badge",
            "project": "Protocol",
            "chain": "Chain",
            "symbol": "Asset",
            "apy": "APY",
            "tvlUsd": "TVL (USD)",
            "risk_score": "Risk",
            "scorecard": "Scorecard",
        }
    )
    st.dataframe(
        leaderboard,
        use_container_width=True,
        hide_index=True,
        height=380,
        column_config={
            "APY": st.column_config.NumberColumn(format="%.2f%%"),
            "TVL (USD)": st.column_config.NumberColumn(format="$%.0f"),
            "Risk": st.column_config.NumberColumn(format="%.0f"),
        },
    )
    st.markdown("</div>", unsafe_allow_html=True)

with drill_tab:
    st.markdown("<div class='panel'>", unsafe_allow_html=True)
    section_header(
        "Selected pool",
        "Focused drilldown",
        "Secondary details live here instead of crowding the main table, which is one of the biggest fixes for the earlier layout issues.",
    )
    if filtered.empty:
        st.info("Adjust the filters to populate the drilldown panel.")
    else:
        options_df = filtered.copy()
        selected_label = st.selectbox("Choose a Pool", options_df["watch_label"].tolist(), index=0)
        selected = options_df.loc[options_df["watch_label"] == selected_label].iloc[0]

        a, b, c, d = st.columns(4)
        with a:
            stat_card("Selected APY", f"{selected['apy']:.2f}%", f"Base {selected['apyBase']:.2f}% • Rewards {selected['apyReward']:.2f}%")
        with b:
            stat_card("Pool TVL", format_money(selected['tvlUsd']), f"{selected['project']} on {selected['chain']}")
        with c:
            stat_card("Risk band", selected["risk_band"], f"Heuristic score {int(selected['risk_score'])}/100")
        with d:
            daily_volume = float(selected.get("volumeUsd1d", 0) or 0)
            stat_card("24h volume", format_money(daily_volume), selected["scorecard"])

        chart_df = fetch_pool_chart(str(selected["pool"]))
        if not chart_df.empty:
            metric_choices = [col for col in ["apy", "apyBase", "apyReward"] if col in chart_df.columns]
            metric = st.radio("Chart metric", metric_choices or ["apy"], horizontal=True)
            line = px.line(chart_df, x="timestamp", y=metric, markers=False)
            line.update_traces(line=dict(width=3))
            line.update_yaxes(title=f"{metric} %")
            line.update_xaxes(title="")
            st.plotly_chart(plotly_theme(line, 400), use_container_width=True)
            st.caption("Historical pool chart from the DeFiLlama yield chart endpoint when available.")
        else:
            st.info("Historical chart data was not available for this pool, but the live market data is still active.")

        info_left, info_right = st.columns([1.05, 1], gap="large")
        with info_left:
            details = pd.DataFrame(
                {
                    "Field": [
                        "Protocol",
                        "Chain",
                        "Asset",
                        "Strategy",
                        "Exposure",
                        "Stablecoin pool",
                        "Pool link",
                    ],
                    "Value": [
                        selected["project"],
                        selected["chain"],
                        selected["symbol"],
                        selected["strategy_type"],
                        selected["exposure"],
                        "Yes" if selected["stablecoin"] else "No",
                        selected["pool_url"] or "Unavailable",
                    ],
                }
            )
            st.dataframe(details, use_container_width=True, hide_index=True, height=286)

        with info_right:
            st.markdown(
                f"""
                <div class="panel" style="padding: 1rem; background: linear-gradient(180deg, rgba(19,39,65,0.98), rgba(10,20,34,0.98));">
                    <div class="section-kicker">Interpretation</div>
                    <div class="section-title">Why this pool ranks where it does</div>
                    <div class="section-copy" style="margin-bottom: 0;">
                        <span class="risk-chip">{selected['risk_band']} risk</span><br/><br/>
                        This pool is being scored from visible surface-level signals only. Higher APY and thinner TVL push the score upward, while stablecoin exposure and deep TVL reduce it. Use this as a triage layer before deeper due diligence.<br/><br/>
                        <a href="{selected['pool_url']}" target="_blank">Open the pool in DeFiLlama</a>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    st.markdown("</div>", unsafe_allow_html=True)

with watch_tab:
    st.markdown("<div class='panel'>", unsafe_allow_html=True)
    section_header(
        "Saved pools",
        "Watchlist layer",
        "Use this area like a lightweight decision board. Save pools from the scanner, compare them here, and export the subset you care about.",
    )
    if watchlist_df.empty:
        st.info("Your watchlist is empty. Add pools from the Scanner tab.")
    else:
        compare_cols = st.columns([1.15, 1], gap="large")
        with compare_cols[0]:
            compare = watchlist_df[["project", "chain", "symbol", "apy", "tvlUsd", "risk_score"]].copy()
            long_df = compare.melt(id_vars=["project", "chain", "symbol"], value_vars=["apy", "tvlUsd", "risk_score"], var_name="metric", value_name="value")
            long_df["label"] = compare["project"] + " • " + compare["symbol"]
            long_df = watchlist_df[["project", "symbol", "apy", "tvlUsd", "risk_score"]].melt(
                id_vars=["project", "symbol"], value_vars=["apy", "tvlUsd", "risk_score"], var_name="metric", value_name="value"
            )
            long_df["label"] = long_df["project"] + " • " + long_df["symbol"]
            radar_metric = st.selectbox("Compare watchlist by", ["apy", "tvlUsd", "risk_score"], index=0)
            comp_fig = px.bar(
                watchlist_df.sort_values(radar_metric, ascending=False),
                x="watch_label",
                y=radar_metric,
                color="chain",
                hover_data={"project": True, "symbol": True, "tvlUsd": ':$,.0f', "apy": ':.2f', "risk_score": True},
            )
            comp_fig.update_xaxes(title="", tickangle=-25)
            comp_fig.update_yaxes(title=radar_metric)
            st.plotly_chart(plotly_theme(comp_fig, 360), use_container_width=True)
        with compare_cols[1]:
            st.dataframe(
                watchlist_df[["protocol_badge", "project", "chain", "symbol", "apy", "tvlUsd", "risk_band"]].rename(
                    columns={
                        "protocol_badge": "Badge",
                        "project": "Protocol",
                        "chain": "Chain",
                        "symbol": "Asset",
                        "apy": "APY",
                        "tvlUsd": "TVL (USD)",
                        "risk_band": "Band",
                    }
                ),
                use_container_width=True,
                hide_index=True,
                height=360,
                column_config={
                    "APY": st.column_config.NumberColumn(format="%.2f%%"),
                    "TVL (USD)": st.column_config.NumberColumn(format="$%.0f"),
                },
            )
        export_watch = make_download_df(watchlist_df).to_csv(index=False).encode("utf-8")
        st.download_button("Download watchlist as CSV", export_watch, file_name="furuflow_watchlist.csv", mime="text/csv")
    st.markdown("</div>", unsafe_allow_html=True)

st.markdown(
    "<div class='note' style='margin-top: 1rem;'>This version explicitly fixes the contrast problem for the choose-options controls by using darker text inside the Protocols, Strategy Type, Sort by, and Choose a Pool controls, while also upgrading the app with richer visual charts, badge-style protocol identity, and a persistent watchlist layer.</div>",
    unsafe_allow_html=True,
)

errors = raw_df.attrs.get("errors", []) if hasattr(raw_df, "attrs") else []
if errors:
    st.warning("Live API could not be reached, so demo data is currently shown.\n\n" + "\n".join(errors))
