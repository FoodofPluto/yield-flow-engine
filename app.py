from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
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
                --chip-bg: #91ebff;
                --chip-text: #07111f;
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
                max-width: 1560px;
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

            div[data-baseweb="select"] > div,
            div[data-baseweb="input"] > div,
            div[data-baseweb="popover"] div,
            .stNumberInput div[data-baseweb="input"] > div {
                background: rgba(255,255,255,0.05) !important;
                border-color: rgba(255,255,255,0.08) !important;
                color: var(--text) !important;
            }

            div[data-baseweb="tag"] {
                background: var(--chip-bg) !important;
                border-color: rgba(0,0,0,0.08) !important;
            }

            div[data-baseweb="tag"] span,
            div[data-baseweb="tag"] svg,
            div[data-baseweb="select"] input,
            div[data-baseweb="select"] span,
            div[data-baseweb="select"] div,
            div[data-baseweb="input"] input,
            .stSlider label,
            .stDownloadButton button,
            .stButton button,
            .stSelectbox label,
            .stMultiSelect label,
            .stNumberInput label,
            .stToggle label {
                color: var(--chip-text) !important;
                font-weight: 700 !important;
            }

            .stMultiSelect label,
            .stSelectbox label,
            .stNumberInput label,
            .stSlider label,
            .stToggle label {
                color: var(--text) !important;
                font-weight: 700 !important;
            }

            .stSlider [data-baseweb="slider"] > div > div > div {
                background: var(--accent-2) !important;
            }

            .stSlider [role="slider"] {
                background: var(--chip-bg) !important;
                border: 2px solid #c8f7ff !important;
                box-shadow: 0 0 0 4px rgba(124,226,255,0.15);
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
    data["rank_score"] = (
        data["apy"].clip(lower=0, upper=80) * 0.7
        + (data["tvlUsd"].clip(lower=0).rank(pct=True) * 20)
        - (data["risk_score"] * 0.35)
    )
    data = data.sort_values(["rank_score", "apy", "tvlUsd"], ascending=[False, False, False])
    return data


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
    if any(word in strategy for word in ["farm", "lever", "loop", "volatility"]):
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
    if row.get("stablecoin", False):
        parts.append("Stable")
    else:
        parts.append("Directional")
    if float(row.get("tvlUsd", 0) or 0) >= 100_000_000:
        parts.append("Deep TVL")
    else:
        parts.append("Lighter TVL")
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


inject_css()
raw_df = fetch_pools()
df = enrich(raw_df)

st.markdown(
    f"""
    <section class="hero-shell">
        <div class="hero-inner">
            <div class="eyebrow">DeFi yield workstation • redesigned</div>
            <div class="hero-title">{APP_NAME}</div>
            <div class="hero-subtitle">{APP_TAGLINE}. Built to feel much closer to a public-facing DeFi analytics product: stronger spacing, cleaner hierarchy, more legible controls, fewer cramped tables, better protocol comparison, and a sharper pool drilldown experience on top of live DeFiLlama yield data.</div>
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
    stat_card("Lower-risk share", f"{lower_risk:,.1f}%", "Pools tagged Low or Moderate by the heuristic")
st.markdown("</div>", unsafe_allow_html=True)

main_tab, market_tab, drill_tab = st.tabs(["Scanner", "Market map", "Pool drilldown"])

with main_tab:
    left, right = st.columns([1.55, 1], gap="large")

    with left:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header(
            "Opportunity feed",
            "Cleaner scanner table",
            "The main table now keeps only the fields you actually need in view, so the dashboard reads more like a product and less like a raw export.",
        )
        table_df = compact_table(filtered)
        st.dataframe(
            table_df,
            use_container_width=True,
            hide_index=True,
            height=560,
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
            "What the current slice says",
            "These summary tables make the market feel navigable without forcing the user to inspect dozens of rows first.",
        )
        top_protocols = top_n_summary(filtered, "project", "total_tvl", 8)
        if not top_protocols.empty:
            st.dataframe(
                top_protocols.rename(
                    columns={
                        "project": "Protocol",
                        "total_tvl": "TVL (USD)",
                        "median_apy": "Median APY",
                        "pools": "Pools",
                        "avg_risk": "Avg Risk",
                    }
                ),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "TVL (USD)": st.column_config.NumberColumn(format="$%.0f"),
                    "Median APY": st.column_config.NumberColumn(format="%.2f%%"),
                    "Avg Risk": st.column_config.NumberColumn(format="%.0f"),
                },
                height=260,
            )
        else:
            st.info("No protocol summary is available with the current filters.")

        top_chains = top_n_summary(filtered, "chain", "total_tvl", 8)
        if not top_chains.empty:
            st.dataframe(
                top_chains.rename(
                    columns={
                        "chain": "Chain",
                        "total_tvl": "TVL (USD)",
                        "median_apy": "Median APY",
                        "pools": "Pools",
                        "avg_risk": "Avg Risk",
                    }
                ),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "TVL (USD)": st.column_config.NumberColumn(format="$%.0f"),
                    "Median APY": st.column_config.NumberColumn(format="%.2f%%"),
                    "Avg Risk": st.column_config.NumberColumn(format="%.0f"),
                },
                height=260,
            )
        st.markdown("</div>", unsafe_allow_html=True)

with market_tab:
    c1, c2 = st.columns([1.15, 1], gap="large")
    with c1:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        section_header(
            "Protocol view",
            "Top protocols by visible TVL",
            "A cleaner TVL-first lens that makes the app feel closer to a public analytics terminal.",
        )
        protocol_summary = top_n_summary(filtered, "project", "total_tvl", 12)
        if not protocol_summary.empty:
            chart_df = protocol_summary.set_index("project")[["total_tvl"]]
            st.bar_chart(chart_df, height=390, use_container_width=True)
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
            st.bar_chart(chain_summary.set_index("chain")[["total_tvl"]], height=390, use_container_width=True)
        else:
            st.info("No chain chart is available with the current filters.")
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='panel' style='margin-top: 1rem;'>", unsafe_allow_html=True)
    section_header(
        "Market rows",
        "Sorted leaderboard",
        "This keeps the market map readable and still exportable, while avoiding the sideways-scroll problem from the earlier versions.",
    )
    leaderboard = filtered[["project", "chain", "symbol", "apy", "tvlUsd", "risk_score", "scorecard"]].rename(
        columns={
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
        options_df["label"] = options_df.apply(
            lambda row: f"{row['project']} • {row['symbol']} • {row['chain']} • {row['apy']:.2f}% APY",
            axis=1,
        )
        selected_label = st.selectbox("Choose a pool", options_df["label"].tolist(), index=0)
        selected = options_df.loc[options_df["label"] == selected_label].iloc[0]

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
            numeric_candidates = [c for c in ["apy", "apyBase", "apyReward"] if c in chart_df.columns]
            chart_col = numeric_candidates[0] if numeric_candidates else chart_df.select_dtypes(include="number").columns[0]
            series = chart_df.set_index("timestamp")[[chart_col]].rename(columns={chart_col: "value"})
            st.line_chart(series, height=380, use_container_width=True)
            st.caption("Historical pool chart from the DeFiLlama yield chart endpoint when available.")
        else:
            st.info("Historical chart data was not available for this pool, but the live market data is still active.")

        info_left, info_right = st.columns([1.1, 1], gap="large")
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

st.markdown(
    "<div class='note' style='margin-top: 1rem;'>This build specifically fixes the low-contrast control text issue by making the text inside selection chips, the sort box, the CSV download button, and other interactive controls much darker against brighter control surfaces.</div>",
    unsafe_allow_html=True,
)

errors = raw_df.attrs.get("errors", []) if hasattr(raw_df, "attrs") else []
if errors:
    st.warning("Live API could not be reached, so demo data is currently shown.\n\n" + "\n".join(errors))
