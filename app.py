import math
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import requests
import streamlit as st

APP_NAME = "FuruFlow"
APP_TAGLINE = "Yield intelligence for DeFi hunters"
POOL_LIMIT = 250
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
                --panel: #0d1b2f;
                --panel-2: #12243d;
                --border: rgba(255,255,255,0.08);
                --text: #f5f7fb;
                --muted: #c8d2e6;
                --accent: #63d2ff;
                --good: #2ed29c;
                --warn: #f1b84b;
                --bad: #ff6d7a;
            }

            .stApp {
                background:
                    radial-gradient(circle at top right, rgba(99,210,255,0.10), transparent 28%),
                    linear-gradient(180deg, #07111f 0%, #081425 100%);
                color: var(--text);
            }

            html, body, [class*="css"]  {
                color: var(--text);
                font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            }

            .block-container {
                max-width: 1480px;
                padding-top: 1.6rem;
                padding-bottom: 2rem;
                padding-left: 1.6rem;
                padding-right: 1.6rem;
            }

            h1, h2, h3, h4, h5, h6, p, span, label, div {
                color: var(--text);
            }

            .hero {
                padding: 1.5rem 1.5rem 1.2rem 1.5rem;
                border: 1px solid var(--border);
                border-radius: 24px;
                background: linear-gradient(145deg, rgba(17,34,57,0.96), rgba(9,19,33,0.96));
                box-shadow: 0 24px 60px rgba(0,0,0,0.22);
                margin-bottom: 1rem;
            }

            .eyebrow {
                display: inline-block;
                color: var(--accent);
                font-size: 0.85rem;
                font-weight: 700;
                letter-spacing: 0.08em;
                text-transform: uppercase;
                margin-bottom: 0.7rem;
            }

            .hero-title {
                font-size: 2.25rem;
                line-height: 1.05;
                font-weight: 800;
                margin-bottom: 0.4rem;
            }

            .hero-subtitle {
                font-size: 1rem;
                color: var(--muted);
                max-width: 840px;
                line-height: 1.55;
            }

            .metric-card {
                background: linear-gradient(180deg, rgba(18,36,61,0.98), rgba(11,22,39,0.98));
                border: 1px solid var(--border);
                border-radius: 22px;
                padding: 1rem 1rem 0.9rem 1rem;
                min-height: 126px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.18);
            }

            .metric-label {
                color: var(--muted);
                font-size: 0.84rem;
                font-weight: 600;
                margin-bottom: 0.35rem;
            }

            .metric-value {
                font-size: 1.7rem;
                font-weight: 800;
                margin-bottom: 0.15rem;
            }

            .metric-footnote {
                color: var(--muted);
                font-size: 0.82rem;
                line-height: 1.45;
            }

            .section-card {
                background: linear-gradient(180deg, rgba(13,27,47,0.96), rgba(9,19,33,0.98));
                border: 1px solid var(--border);
                border-radius: 22px;
                padding: 1rem 1rem 1.15rem 1rem;
                margin-top: 0.6rem;
            }

            [data-testid="stSidebar"] {
                background: linear-gradient(180deg, rgba(11,22,39,1), rgba(7,17,31,1));
                border-right: 1px solid var(--border);
            }

            [data-testid="stSidebar"] * {
                color: var(--text) !important;
            }

            .small-note {
                color: var(--muted);
                font-size: 0.84rem;
                line-height: 1.5;
            }

            .risk-pill {
                display: inline-block;
                padding: 0.26rem 0.56rem;
                border-radius: 999px;
                font-size: 0.78rem;
                font-weight: 700;
                border: 1px solid var(--border);
                background: rgba(255,255,255,0.05);
            }

            div[data-testid="stDataFrame"] {
                border: 1px solid var(--border);
                border-radius: 18px;
                overflow: hidden;
            }

            div[data-baseweb="select"] > div,
            div[data-baseweb="input"] > div,
            .stSlider,
            .stMultiSelect {
                background: rgba(255,255,255,0.02);
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data(ttl=900, show_spinner=False)
def fetch_pools() -> pd.DataFrame:
    urls = [
        "https://yields.llama.fi/pools",
        "https://stablecoins.llama.fi/yields/pools",  # fallback in case infra routing changes
    ]
    errors = []
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
            if not chart.empty and "timestamp" in chart.columns:
                chart["timestamp"] = pd.to_datetime(chart["timestamp"], errors="coerce")
                chart = chart.dropna(subset=["timestamp"]).sort_values("timestamp")
                return chart
        except Exception:
            continue
    return pd.DataFrame()


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
                "predictions": {"predictedClass": "Stable"},
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
                "predictions": {"predictedClass": "Speculative"},
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
                "predictions": {"predictedClass": "Stable"},
            },
        ]
    )
    demo.attrs["errors"] = errors
    return demo


@st.cache_data(show_spinner=False)
def enrich(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy()

    for column in ["apy", "apyBase", "apyReward", "tvlUsd", "volumeUsd1d"]:
        if column not in data.columns:
            data[column] = 0.0

    data["apy"] = pd.to_numeric(data["apy"], errors="coerce").fillna(0.0)
    data["apyBase"] = pd.to_numeric(data["apyBase"], errors="coerce").fillna(0.0)
    data["apyReward"] = pd.to_numeric(data["apyReward"], errors="coerce").fillna(0.0)
    data["tvlUsd"] = pd.to_numeric(data["tvlUsd"], errors="coerce").fillna(0.0)
    data["volumeUsd1d"] = pd.to_numeric(data["volumeUsd1d"], errors="coerce").fillna(0.0)

    for col in ["chain", "project", "symbol", "poolMeta", "exposure"]:
        if col not in data.columns:
            data[col] = "Unknown"
        data[col] = data[col].fillna("Unknown").astype(str)

    if "stablecoin" not in data.columns:
        data["stablecoin"] = data["symbol"].str.contains("USDC|USDT|DAI|FRAX|USDe|USD", case=False, na=False)
    data["stablecoin"] = data["stablecoin"].fillna(False)

    data["risk_score"] = data.apply(score_pool, axis=1)
    data["risk_band"] = data["risk_score"].apply(label_risk)
    data["pool_url"] = data.apply(build_pool_url, axis=1)
    data["apy_pct"] = data["apy"].map(lambda x: f"{x:,.2f}%")
    data["tvl_label"] = data["tvlUsd"].map(format_money)
    data["vol_label"] = data["volumeUsd1d"].map(format_money)
    data["strategy_type"] = data["poolMeta"].replace({"Unknown": "General"})

    data = data.sort_values(["risk_score", "apy", "tvlUsd"], ascending=[True, False, False])
    return data



def score_pool(row: pd.Series) -> int:
    score = 45
    apy = float(row.get("apy", 0) or 0)
    tvl = float(row.get("tvlUsd", 0) or 0)
    exposure = str(row.get("exposure", "Unknown")).lower()
    stablecoin = bool(row.get("stablecoin", False))
    pool_meta = str(row.get("poolMeta", "")).lower()

    if apy > 100:
        score += 32
    elif apy > 40:
        score += 20
    elif apy > 20:
        score += 12
    elif apy > 10:
        score += 6
    elif apy < 8:
        score -= 4

    if tvl < 1_000_000:
        score += 26
    elif tvl < 10_000_000:
        score += 16
    elif tvl < 50_000_000:
        score += 8
    elif tvl > 500_000_000:
        score -= 10

    if exposure in {"multi", "lp"}:
        score += 10
    if stablecoin:
        score -= 8
    if "lever" in pool_meta or "farm" in pool_meta:
        score += 10
    if "lend" in pool_meta:
        score -= 6

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
    pool = row.get("pool")
    if isinstance(pool, str) and pool and pool != "Unknown":
        return f"https://defillama.com/yields/pool/{pool}"
    return ""



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



def metric_card(label: str, value: str, footnote: str) -> None:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{value}</div>
            <div class="metric-footnote">{footnote}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )



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
        "pool_url",
    ]
    available = [c for c in cols if c in df.columns]
    return df[available].copy()


inject_css()

raw_df = fetch_pools()
df = enrich(raw_df)

st.markdown(
    f"""
    <section class="hero">
        <div class="eyebrow">Yield dashboard redesign</div>
        <div class="hero-title">{APP_NAME}</div>
        <div class="hero-subtitle">{APP_TAGLINE}. Cleaner spacing, higher-contrast typography, full-width charts, responsive tables, live DeFiLlama-backed yield data, and a simple risk model for fast filtering.</div>
    </section>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("### Filter universe")
    chains = sorted(df["chain"].dropna().unique().tolist())
    projects = sorted(df["project"].dropna().unique().tolist())
    strategy_types = sorted(df["strategy_type"].dropna().unique().tolist())

    selected_chains = st.multiselect("Chains", chains, default=chains[: min(8, len(chains))])
    selected_projects = st.multiselect("Protocols", projects)
    selected_types = st.multiselect("Strategy type", strategy_types)
    stable_only = st.toggle("Stablecoin pools only", value=False)
    max_risk = st.slider("Max risk score", min_value=1, max_value=100, value=65)
    min_tvl = st.number_input("Minimum TVL (USD)", min_value=0, value=1_000_000, step=500_000)
    min_apy = st.slider("Minimum APY", min_value=0.0, max_value=200.0, value=0.0, step=0.5)
    sort_by = st.selectbox(
        "Sort by",
        ["Best risk-adjusted", "Highest APY", "Largest TVL", "Highest 24h volume"],
        index=0,
    )
    st.markdown(
        "<div class='small-note'>Risk score is a lightweight heuristic based on APY, TVL, exposure, and strategy type. It is a triage signal, not a safety guarantee.</div>",
        unsafe_allow_html=True,
    )

filtered = df.copy()
if selected_chains:
    filtered = filtered[filtered["chain"].isin(selected_chains)]
if selected_projects:
    filtered = filtered[filtered["project"].isin(selected_projects)]
if selected_types:
    filtered = filtered[filtered["strategy_type"].isin(selected_types)]
if stable_only:
    filtered = filtered[filtered["stablecoin"] == True]

filtered = filtered[(filtered["risk_score"] <= max_risk) & (filtered["tvlUsd"] >= min_tvl) & (filtered["apy"] >= min_apy)]

if sort_by == "Highest APY":
    filtered = filtered.sort_values(["apy", "tvlUsd"], ascending=[False, False])
elif sort_by == "Largest TVL":
    filtered = filtered.sort_values(["tvlUsd", "apy"], ascending=[False, False])
elif sort_by == "Highest 24h volume":
    filtered = filtered.sort_values(["volumeUsd1d", "apy"], ascending=[False, False])
else:
    filtered = filtered.sort_values(["risk_score", "apy", "tvlUsd"], ascending=[True, False, False])

filtered = filtered.head(POOL_LIMIT)

metric_cols = st.columns(4)
with metric_cols[0]:
    metric_card("Visible opportunities", f"{len(filtered):,}", "Pools after your current filters")
with metric_cols[1]:
    median_apy = filtered["apy"].median() if not filtered.empty else 0
    metric_card("Median APY", f"{median_apy:,.2f}%", "Across the visible opportunity set")
with metric_cols[2]:
    total_tvl = filtered["tvlUsd"].sum() if not filtered.empty else 0
    metric_card("Aggregate TVL", format_money(total_tvl), "Combined TVL for filtered pools")
with metric_cols[3]:
    low_risk_share = (filtered["risk_band"].isin(["Low", "Moderate"]).mean() * 100) if not filtered.empty else 0
    metric_card("Lower-risk share", f"{low_risk_share:,.1f}%", "Pools tagged Low or Moderate")

tab_overview, tab_opps, tab_pool = st.tabs(["Overview", "Opportunities", "Pool drilldown"])

with tab_overview:
    c1, c2 = st.columns([1.2, 1], gap="large")
    with c1:
        st.markdown("#### Top protocols by visible TVL")
        protocol_summary = (
            filtered.groupby("project", as_index=False)
            .agg(total_tvl=("tvlUsd", "sum"), median_apy=("apy", "median"), pools=("pool", "count"))
            .sort_values("total_tvl", ascending=False)
            .head(12)
        )
        if not protocol_summary.empty:
            chart_df = protocol_summary.set_index("project")[["total_tvl"]]
            st.bar_chart(chart_df, height=360, use_container_width=True)
            st.dataframe(
                protocol_summary.rename(
                    columns={
                        "project": "Protocol",
                        "total_tvl": "TVL (USD)",
                        "median_apy": "Median APY",
                        "pools": "Pools",
                    }
                ),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "TVL (USD)": st.column_config.NumberColumn(format="$%.0f"),
                    "Median APY": st.column_config.NumberColumn(format="%.2f%%"),
                },
            )
        else:
            st.info("No pools match the current filter set.")

    with c2:
        st.markdown("#### Chain allocation")
        chain_summary = (
            filtered.groupby("chain", as_index=False)
            .agg(total_tvl=("tvlUsd", "sum"), avg_apy=("apy", "mean"), pools=("pool", "count"))
            .sort_values("total_tvl", ascending=False)
            .head(10)
        )
        if not chain_summary.empty:
            st.bar_chart(chain_summary.set_index("chain")[["total_tvl"]], height=360, use_container_width=True)
            st.dataframe(
                chain_summary.rename(
                    columns={"chain": "Chain", "total_tvl": "TVL (USD)", "avg_apy": "Avg APY", "pools": "Pools"}
                ),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "TVL (USD)": st.column_config.NumberColumn(format="$%.0f"),
                    "Avg APY": st.column_config.NumberColumn(format="%.2f%%"),
                },
            )
        else:
            st.info("No chain allocation to show yet.")

with tab_opps:
    st.markdown("#### Best opportunities")
    display = filtered.copy()
    display["Open"] = display["pool_url"].apply(lambda x: x if x else "")
    compact = display[
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
            "Open",
        ]
    ].rename(
        columns={
            "project": "Protocol",
            "chain": "Chain",
            "symbol": "Asset",
            "strategy_type": "Type",
            "apy": "APY",
            "apyBase": "Base",
            "apyReward": "Rewards",
            "tvlUsd": "TVL (USD)",
            "risk_score": "Risk",
            "risk_band": "Band",
        }
    )

    st.dataframe(
        compact,
        use_container_width=True,
        hide_index=True,
        height=560,
        column_config={
            "APY": st.column_config.NumberColumn(format="%.2f%%", width="small"),
            "Base": st.column_config.NumberColumn(format="%.2f%%", width="small"),
            "Rewards": st.column_config.NumberColumn(format="%.2f%%", width="small"),
            "TVL (USD)": st.column_config.NumberColumn(format="$%.0f", width="medium"),
            "Risk": st.column_config.NumberColumn(width="small"),
            "Open": st.column_config.LinkColumn("Pool link", display_text="view"),
        },
    )

    csv = make_download_df(filtered).to_csv(index=False).encode("utf-8")
    st.download_button("Download current table as CSV", csv, file_name=f"{APP_NAME.lower()}_opportunities.csv", mime="text/csv")

with tab_pool:
    st.markdown("#### Pool drilldown")
    if filtered.empty:
        st.info("Adjust filters to inspect a pool.")
    else:
        options_df = filtered.copy()
        options_df["label"] = options_df.apply(
            lambda row: f"{row['project']} • {row['symbol']} • {row['chain']} • {row['apy']:.2f}% APY",
            axis=1,
        )
        selected_label = st.selectbox("Select a pool", options_df["label"].tolist(), index=0)
        selected_row = options_df.loc[options_df["label"] == selected_label].iloc[0]
        a, b, c = st.columns(3)
        with a:
            metric_card("Selected APY", f"{selected_row['apy']:.2f}%", f"Base {selected_row['apyBase']:.2f}% • Rewards {selected_row['apyReward']:.2f}%")
        with b:
            metric_card("Pool TVL", format_money(selected_row['tvlUsd']), f"{selected_row['project']} on {selected_row['chain']}")
        with c:
            metric_card("Risk band", selected_row['risk_band'], f"Heuristic score: {selected_row['risk_score']}/100")

        pool_chart = fetch_pool_chart(selected_row["pool"])
        if not pool_chart.empty:
            chart_col = "apy" if "apy" in pool_chart.columns else pool_chart.select_dtypes(include="number").columns[0]
            series = pool_chart.set_index("timestamp")[[chart_col]].rename(columns={chart_col: "value"})
            st.line_chart(series, height=380, use_container_width=True)
            st.caption("Historical series sourced from the selected pool endpoint when available.")
        else:
            st.info("Historical chart data was not available for this pool. The live table is still usable.")

        st.markdown(
            f"""
            <div class="section-card">
                <div class="metric-label">Pool notes</div>
                <div class="small-note">
                    Protocol: <strong>{selected_row['project']}</strong><br/>
                    Asset: <strong>{selected_row['symbol']}</strong><br/>
                    Chain: <strong>{selected_row['chain']}</strong><br/>
                    Strategy: <strong>{selected_row['strategy_type']}</strong><br/>
                    Exposure: <strong>{selected_row['exposure']}</strong><br/>
                    Stablecoin pool: <strong>{'Yes' if selected_row['stablecoin'] else 'No'}</strong><br/>
                    Pool link: <a href="{selected_row['pool_url']}" target="_blank">Open in DeFiLlama</a>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

st.markdown(
    f"""
    <div class="small-note" style="margin-top:1rem;">
        {APP_NAME} is designed to feel less cramped than the earlier version: wide layout, better spacing, higher-contrast typography, and slimmer tables so you do not have to horizontally scroll to get core decision data.
    </div>
    """,
    unsafe_allow_html=True,
)

errors = raw_df.attrs.get("errors", []) if hasattr(raw_df, "attrs") else []
if errors:
    st.warning("Live API could not be reached, so demo data is being shown.\n\n" + "\n".join(errors))
