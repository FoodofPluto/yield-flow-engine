from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from engine.scanner import as_rows, list_market_snapshot, rank_top_yields

st.set_page_config(page_title="Yield Flow Engine v3", page_icon="📈", layout="wide")

APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / ".streamlit_state"
WATCHLIST_FILE = DATA_DIR / "watchlist.json"
ALERTS_FILE = DATA_DIR / "alerts.json"
DATA_DIR.mkdir(exist_ok=True)


def inject_css() -> None:
    st.markdown(
        """
        <style>
            .stApp {
                background:
                    radial-gradient(circle at top right, rgba(41, 98, 255, 0.18), transparent 26%),
                    radial-gradient(circle at top left, rgba(0, 200, 150, 0.14), transparent 20%),
                    linear-gradient(180deg, #08111f 0%, #0b1728 45%, #0d1420 100%);
            }
            .block-container {
                max-width: 1480px;
                padding-top: 1.15rem;
                padding-bottom: 2rem;
            }
            .yf-hero {
                padding: 1.2rem 1.35rem;
                border-radius: 22px;
                background: linear-gradient(135deg, rgba(39, 110, 241, 0.22), rgba(0, 201, 167, 0.14));
                border: 1px solid rgba(255,255,255,0.08);
                box-shadow: 0 14px 40px rgba(0,0,0,0.18);
                margin-bottom: .9rem;
            }
            .yf-title {
                color: #f8fbff;
                font-size: 2rem;
                font-weight: 750;
                line-height: 1.1;
                margin-bottom: .25rem;
            }
            .yf-subtitle {
                color: rgba(248,251,255,0.76);
                font-size: .98rem;
            }
            .yf-chip-row {
                display: flex;
                gap: .45rem;
                flex-wrap: wrap;
                margin-top: .9rem;
            }
            .yf-chip {
                background: rgba(255,255,255,0.08);
                color: #eef6ff;
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 999px;
                padding: .28rem .72rem;
                font-size: .8rem;
            }
            div[data-testid="stMetric"] {
                background: rgba(255,255,255,0.03);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 16px;
                padding: .35rem .25rem;
                box-shadow: 0 10px 24px rgba(0,0,0,0.12);
            }
            .yf-note {
                color: rgba(255,255,255,0.68);
                font-size: .84rem;
            }
            .yf-card {
                padding: .95rem;
                border-radius: 18px;
                background: rgba(255,255,255,0.03);
                border: 1px solid rgba(255,255,255,0.08);
                min-height: 162px;
                box-shadow: 0 12px 28px rgba(0,0,0,0.10);
            }
            .yf-card-title {
                color: white;
                font-weight: 700;
                font-size: 1rem;
                margin-bottom: .25rem;
            }
            .yf-muted { color: rgba(255,255,255,0.66); }
            .yf-low { color: #34d399; font-weight: 700; }
            .yf-medium { color: #fbbf24; font-weight: 700; }
            .yf-high { color: #f87171; font-weight: 700; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def safe_load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def safe_save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


@st.cache_data(ttl=300, show_spinner=False)
def fetch_market_data(top: int, source: str, min_tvl: float, max_apy: float, stablecoin_only: bool) -> pd.DataFrame:
    items = rank_top_yields(
        top=top,
        source=source,
        min_tvl=min_tvl,
        max_apy=max_apy,
        stablecoin_only=stablecoin_only,
    )
    return pd.DataFrame(as_rows(items))


@st.cache_data(ttl=300, show_spinner=False)
def fetch_full_snapshot(source: str) -> pd.DataFrame:
    items = list_market_snapshot(source=source)
    return pd.DataFrame(as_rows(items))


@st.cache_data(show_spinner=False)
def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


@st.cache_data(show_spinner=False)
def to_excel_bytes(df: pd.DataFrame) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="yield_flow")
    return output.getvalue()


def format_money(value: float) -> str:
    if pd.isna(value):
        return "—"
    if value >= 1_000_000_000:
        return f"${value/1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"${value/1_000_000:.1f}M"
    if value >= 1_000:
        return f"${value/1_000:.1f}K"
    return f"${value:,.0f}"


RANKING_HELP = {
    "Best APY": "Pure yield-first ranking. Useful for quick scanning, but can surface fragile or short-lived opportunities.",
    "Best risk-adjusted yield": "Balances APY, TVL depth, and the internal risk score to surface stronger all-around candidates.",
    "Largest TVL": "Favors deeper, more liquid pools that may be easier to size into or out of.",
    "Lowest risk": "Prioritizes lower-risk opportunities based on the internal heuristic.",
    "Stable income": "Leans toward stablecoin pools with moderate APY and lower risk.",
    "Momentum (7D APY)": "Favors pools with stronger 7-day APY change, while still considering TVL and current APY.",
}


def prep_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    numeric_cols = [
        "apy",
        "tvl_usd",
        "apy_base",
        "apy_reward",
        "apy_pct_1d",
        "apy_pct_7d",
        "apy_pct_30d",
        "risk_score",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "stablecoin" in df.columns:
        df["stablecoin"] = df["stablecoin"].fillna(False).astype(bool)
    if "pool_id" not in df.columns:
        df["pool_id"] = df.get("name", "")
    return df


def apply_filters(
    df: pd.DataFrame,
    *,
    stablecoin_only: bool,
    min_tvl: float,
    max_apy: float,
    chains: list[str],
    projects: list[str],
    risk_labels: list[str],
    search_text: str,
    asset_text: str,
) -> pd.DataFrame:
    filtered = df.copy()
    if stablecoin_only and "stablecoin" in filtered.columns:
        filtered = filtered[filtered["stablecoin"]]
    if min_tvl > 0 and "tvl_usd" in filtered.columns:
        filtered = filtered[filtered["tvl_usd"] >= min_tvl]
    if max_apy > 0 and "apy" in filtered.columns:
        filtered = filtered[filtered["apy"] <= max_apy]
    if chains:
        filtered = filtered[filtered["chain"].isin(chains)]
    if projects:
        filtered = filtered[filtered["project"].isin(projects)]
    if risk_labels:
        filtered = filtered[filtered["risk_label"].isin(risk_labels)]
    if search_text:
        needle = search_text.lower().strip()
        filtered = filtered[
            filtered["name"].fillna("").str.lower().str.contains(needle)
            | filtered["project"].fillna("").str.lower().str.contains(needle)
            | filtered["symbol"].fillna("").str.lower().str.contains(needle)
        ]
    if asset_text:
        filtered = filtered[filtered["symbol"].fillna("").str.lower().str.contains(asset_text.lower().strip())]
    return filtered



def add_scores(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    enriched = df.copy()
    tvl_component = (enriched["tvl_usd"].fillna(0) / 50_000_000).clip(upper=5)
    enriched["risk_adjusted_score"] = enriched["apy"].fillna(0) - enriched["risk_score"].fillna(5) * 1.25 + tvl_component
    enriched["stable_income_score"] = (
        enriched["apy"].fillna(0) * 0.8
        + enriched["stablecoin"].astype(int) * 4
        - enriched["risk_score"].fillna(5) * 1.1
        + (enriched["tvl_usd"].fillna(0) / 75_000_000).clip(upper=4)
    )
    enriched["momentum_score"] = (
        enriched["apy_pct_7d"].fillna(0) * 2.2
        + enriched["apy"].fillna(0) * 0.35
        + (enriched["tvl_usd"].fillna(0) / 100_000_000).clip(upper=3)
        - enriched["risk_score"].fillna(5) * 0.5
    )
    enriched["opportunity_score"] = (
        enriched["apy"].fillna(0) * 0.55
        + (enriched["tvl_usd"].fillna(0) / 100_000_000).clip(upper=4) * 5
        - enriched["risk_score"].fillna(5) * 1.8
        + enriched["apy_pct_7d"].fillna(0) * 0.8
    )
    return enriched


def risk_css_class(label: str) -> str:
    mapping = {"Low": "yf-low", "Medium": "yf-medium", "High": "yf-high"}
    return mapping.get(str(label), "yf-medium")


def load_watchlist() -> list[str]:
    return safe_load_json(WATCHLIST_FILE, [])


def save_watchlist(ids: list[str]) -> None:
    safe_save_json(WATCHLIST_FILE, sorted(set(x for x in ids if x)))


def load_alerts() -> list[dict]:
    alerts = safe_load_json(ALERTS_FILE, [])
    return alerts if isinstance(alerts, list) else []


def save_alerts(alerts: list[dict]) -> None:
    safe_save_json(ALERTS_FILE, alerts)


def render_hero(last_refreshed: str, snapshot_filtered: pd.DataFrame) -> None:
    chains = snapshot_filtered["chain"].nunique() if not snapshot_filtered.empty else 0
    protocols = snapshot_filtered["project"].nunique() if not snapshot_filtered.empty else 0
    st.markdown(
        f"""
        <div class="yf-hero">
            <div class="yf-title">Yield Flow Engine v3</div>
            <div class="yf-subtitle">A sharper DeFi analytics dashboard for finding, filtering, and tracking yield opportunities in real time.</div>
            <div class="yf-chip-row">
                <span class="yf-chip">Live market snapshot</span>
                <span class="yf-chip">{len(snapshot_filtered):,} visible pools</span>
                <span class="yf-chip">{protocols:,} protocols</span>
                <span class="yf-chip">{chains:,} chains</span>
                <span class="yf-chip">Updated {last_refreshed} UTC</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_pool_cards(df: pd.DataFrame) -> None:
    st.markdown("### Quick-scan opportunity cards")
    cards = df.head(6).to_dict("records")
    cols = st.columns(3)
    for idx, row in enumerate(cards):
        with cols[idx % 3]:
            risk_class = risk_css_class(row.get("risk_label", "Medium"))
            st.markdown(
                f"""
                <div class="yf-card">
                    <div class="yf-card-title">{row.get('project','N/A')} · {row.get('symbol','N/A')}</div>
                    <div class="yf-muted">{row.get('chain','N/A')}</div>
                    <div style="margin-top:.6rem;color:white;">APY <b>{row.get('apy',0):.2f}%</b></div>
                    <div style="color:white;">TVL <b>{format_money(float(row.get('tvl_usd',0) or 0))}</b></div>
                    <div class="{risk_class}">Risk {int(row.get('risk_score',0) or 0)}/10 · {row.get('risk_label','N/A')}</div>
                    <div class="yf-note" style="margin-top:.45rem;">{row.get('name','')}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            link_col1, link_col2 = st.columns(2)
            protocol_url = row.get("protocol_url") if isinstance(row.get("protocol_url"), str) else ""
            pool_url = row.get("llama_pool_url") if isinstance(row.get("llama_pool_url"), str) else ""
            if protocol_url:
                link_col1.link_button("Protocol", protocol_url, use_container_width=True)
            if pool_url:
                link_col2.link_button("Pool", pool_url, use_container_width=True)


inject_css()

if "refresh_nonce" not in st.session_state:
    st.session_state.refresh_nonce = 0
if "watchlist_ids" not in st.session_state:
    st.session_state.watchlist_ids = load_watchlist()
if "alerts" not in st.session_state:
    st.session_state.alerts = load_alerts()

with st.sidebar:
    st.header("Controls")
    source = st.selectbox("Data source", ["defillama", "all", "demo"], index=0)
    top = st.slider("Results to rank", min_value=10, max_value=250, value=100, step=5)
    min_tvl = st.number_input("Minimum TVL (USD)", min_value=0.0, value=1_000_000.0, step=100_000.0, format="%.0f")
    max_apy = st.number_input("Maximum APY (%)", min_value=1.0, value=250.0, step=5.0)
    stablecoin_only = st.checkbox("Stablecoin only", value=False)
    search_text = st.text_input("Search pools / protocols")
    asset_text = st.text_input("Asset symbol contains")
    refresh = st.button("🔄 Refresh live data", use_container_width=True)
    st.caption("Live data is cached for 5 minutes unless you force-refresh.")

if refresh:
    fetch_market_data.clear()
    fetch_full_snapshot.clear()
    st.session_state.refresh_nonce += 1

with st.spinner("Loading live market snapshot..."):
    snapshot_df = prep_dataframe(fetch_full_snapshot(source))
    ranked_df = prep_dataframe(fetch_market_data(top, source, min_tvl, max_apy, stablecoin_only))

if snapshot_df.empty:
    st.error("No data came back from the provider. Try switching source or refreshing again.")
    st.stop()

available_chains = sorted([c for c in snapshot_df["chain"].dropna().unique().tolist() if c])
available_projects = sorted([p for p in snapshot_df["project"].dropna().unique().tolist() if p])
available_risk_labels = sorted(snapshot_df["risk_label"].dropna().unique().tolist())

filter_col1, filter_col2, filter_col3 = st.columns([1.15, 1.15, 0.9])
selected_chains = filter_col1.multiselect("Chains", available_chains)
selected_projects = filter_col2.multiselect("Protocols", available_projects)
risk_labels = filter_col3.multiselect("Risk bands", available_risk_labels)

snapshot_filtered = apply_filters(
    snapshot_df,
    stablecoin_only=stablecoin_only,
    min_tvl=min_tvl,
    max_apy=max_apy,
    chains=selected_chains,
    projects=selected_projects,
    risk_labels=risk_labels,
    search_text=search_text,
    asset_text=asset_text,
)
ranked_df = apply_filters(
    ranked_df,
    stablecoin_only=stablecoin_only,
    min_tvl=min_tvl,
    max_apy=max_apy,
    chains=selected_chains,
    projects=selected_projects,
    risk_labels=risk_labels,
    search_text=search_text,
    asset_text=asset_text,
)

snapshot_filtered = add_scores(snapshot_filtered)
ranked_df = add_scores(ranked_df)

sort_choice = st.selectbox("Rank by", list(RANKING_HELP.keys()))
st.caption(RANKING_HELP[sort_choice])

if sort_choice == "Best APY":
    ranked_df = ranked_df.sort_values(["apy", "tvl_usd"], ascending=[False, False])
elif sort_choice == "Best risk-adjusted yield":
    ranked_df = ranked_df.sort_values(["risk_adjusted_score", "apy"], ascending=[False, False])
elif sort_choice == "Largest TVL":
    ranked_df = ranked_df.sort_values(["tvl_usd", "apy"], ascending=[False, False])
elif sort_choice == "Lowest risk":
    ranked_df = ranked_df.sort_values(["risk_score", "apy"], ascending=[True, False])
elif sort_choice == "Stable income":
    ranked_df = ranked_df.sort_values(["stable_income_score", "apy"], ascending=[False, False])
else:
    ranked_df = ranked_df.sort_values(["momentum_score", "apy"], ascending=[False, False])

ranked_df = ranked_df.reset_index(drop=True)
last_refreshed = ranked_df["refreshed_at"].iloc[0] if not ranked_df.empty and "refreshed_at" in ranked_df.columns else datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
render_hero(str(last_refreshed), snapshot_filtered)

metric1, metric2, metric3, metric4, metric5, metric6 = st.columns(6)
metric1.metric("Visible pools", f"{len(snapshot_filtered):,}")
metric2.metric("Top APY", f"{snapshot_filtered['apy'].max():.2f}%" if not snapshot_filtered.empty else "—")
metric3.metric("Median APY", f"{snapshot_filtered['apy'].median():.2f}%" if not snapshot_filtered.empty else "—")
metric4.metric("Total TVL", format_money(float(snapshot_filtered["tvl_usd"].sum())) if not snapshot_filtered.empty else "—")
metric5.metric("Avg risk", f"{snapshot_filtered['risk_score'].mean():.1f}/10" if not snapshot_filtered.empty else "—")
metric6.metric("Watchlist", f"{len(st.session_state.watchlist_ids):,}")

st.markdown('<div class="yf-note">Persistent watchlists and alerts are now saved locally for the deployed app instance.</div>', unsafe_allow_html=True)

overview_tab, opportunities_tab, protocols_tab, charts_tab, risk_tab, watchlist_tab, alerts_tab = st.tabs(
    ["Overview", "Opportunities", "Protocols", "Charts", "Risk", "Watchlist", "Alerts"]
)

with overview_tab:
    left, right = st.columns([1.15, 0.85])
    with left:
        st.subheader("Top opportunities")
        top_cols = ["name", "project", "chain", "symbol", "apy", "tvl_usd", "risk_score", "risk_label", "stablecoin"]
        st.dataframe(
            ranked_df[top_cols].head(15),
            use_container_width=True,
            hide_index=True,
            column_config={
                "apy": st.column_config.NumberColumn("APY %", format="%.2f"),
                "tvl_usd": st.column_config.NumberColumn("TVL USD", format="$%.0f"),
            },
        )
    with right:
        st.subheader("Protocol concentration")
        top_protocols = (
            snapshot_filtered.groupby("project", as_index=False)
            .agg(total_tvl=("tvl_usd", "sum"), avg_apy=("apy", "mean"), pools=("project", "count"))
            .sort_values("total_tvl", ascending=False)
            .head(10)
        )
        if not top_protocols.empty:
            chart = alt.Chart(top_protocols).mark_bar(cornerRadiusEnd=4).encode(
                x=alt.X("total_tvl:Q", title="TVL (USD)"),
                y=alt.Y("project:N", sort="-x", title="Protocol"),
                tooltip=["project", alt.Tooltip("total_tvl:Q", format=",.0f"), alt.Tooltip("avg_apy:Q", format=".2f"), "pools"],
            )
            st.altair_chart(chart, use_container_width=True)
        else:
            st.info("No protocol data available for the current filters.")
    render_pool_cards(ranked_df)

with opportunities_tab:
    st.subheader("Opportunities explorer")
    display = ranked_df.copy()
    if not display.empty:
        display["watching"] = display["pool_id"].isin(st.session_state.watchlist_ids)
        display["apy"] = display["apy"].round(2)
        display["tvl_usd"] = display["tvl_usd"].round(0)
        display["protocol_link"] = display["protocol_url"].apply(lambda u: u if isinstance(u, str) else "")
        display["pool_link"] = display["llama_pool_url"].apply(lambda u: u if isinstance(u, str) else "")
        st.dataframe(
            display[
                [
                    "watching",
                    "name",
                    "project",
                    "chain",
                    "symbol",
                    "apy",
                    "tvl_usd",
                    "risk_score",
                    "risk_label",
                    "stablecoin",
                    "opportunity_score",
                    "risk_adjusted_score",
                    "protocol_link",
                    "pool_link",
                ]
            ],
            column_config={
                "apy": st.column_config.NumberColumn("APY %", format="%.2f"),
                "tvl_usd": st.column_config.NumberColumn("TVL USD", format="$%.0f"),
                "opportunity_score": st.column_config.NumberColumn("Opportunity", format="%.2f"),
                "risk_adjusted_score": st.column_config.NumberColumn("Adj score", format="%.2f"),
                "protocol_link": st.column_config.LinkColumn("Protocol", display_text="Open protocol"),
                "pool_link": st.column_config.LinkColumn("Pool page", display_text="Open pool"),
            },
            use_container_width=True,
            hide_index=True,
        )

        exp1, exp2, exp3 = st.columns([1, 1, 1])
        with exp1:
            st.download_button(
                "Download filtered CSV",
                data=to_csv_bytes(display),
                file_name="yield_flow_opportunities.csv",
                mime="text/csv",
                use_container_width=True,
            )
        with exp2:
            st.download_button(
                "Download filtered Excel",
                data=to_excel_bytes(display),
                file_name="yield_flow_opportunities.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        with exp3:
            pool_to_toggle = st.selectbox("Add/remove watchlist pool", display["name"].tolist(), key="watch_toggle")
            chosen = display[display["name"] == pool_to_toggle].iloc[0]
            if st.button("Toggle watchlist", use_container_width=True):
                pool_id = chosen["pool_id"]
                if pool_id in st.session_state.watchlist_ids:
                    st.session_state.watchlist_ids.remove(pool_id)
                elif pool_id:
                    st.session_state.watchlist_ids.append(pool_id)
                save_watchlist(st.session_state.watchlist_ids)
                st.rerun()

        with st.expander("Selected pool details", expanded=True):
            detail_name = st.selectbox("Choose a pool", display["name"].tolist(), key="detail_select")
            selected = display[display["name"] == detail_name].iloc[0]
            a, b, c, d = st.columns(4)
            a.metric("APY", f"{selected['apy']:.2f}%")
            b.metric("TVL", format_money(float(selected["tvl_usd"])))
            c.metric("Risk", f"{int(selected['risk_score'])}/10 · {selected['risk_label']}")
            d.metric("7D APY Δ", f"{selected.get('apy_pct_7d', 0) or 0:.2f}%")
            st.write(selected.get("risk_reasons", ""))
            info1, info2, info3 = st.columns(3)
            info1.write(f"**Category:** {selected.get('category') or 'N/A'}")
            info2.write(f"**Exposure:** {selected.get('exposure') or 'N/A'}")
            info3.write(f"**Stablecoin:** {'Yes' if bool(selected.get('stablecoin')) else 'No'}")
            protocol_link = selected.get("protocol_link") or 'N/A'
            pool_link = selected.get("pool_link") or 'N/A'
            st.markdown(f"**Protocol page:** {protocol_link}")
            st.markdown(f"**Pool page:** {pool_link}")
    else:
        st.info("No opportunities matched the selected filters.")

with protocols_tab:
    st.subheader("Protocol analytics")
    protocols = (
        snapshot_filtered.groupby("project", as_index=False)
        .agg(
            pools=("project", "count"),
            total_tvl=("tvl_usd", "sum"),
            avg_apy=("apy", "mean"),
            avg_risk=("risk_score", "mean"),
            protocol_link=("protocol_url", "first"),
        )
        .sort_values(["total_tvl", "avg_apy"], ascending=[False, False])
    )
    if not protocols.empty:
        st.dataframe(
            protocols,
            column_config={
                "total_tvl": st.column_config.NumberColumn("Total TVL", format="$%.0f"),
                "avg_apy": st.column_config.NumberColumn("Avg APY", format="%.2f"),
                "avg_risk": st.column_config.NumberColumn("Avg risk", format="%.1f"),
                "protocol_link": st.column_config.LinkColumn("Link", display_text="Open protocol"),
            },
            use_container_width=True,
            hide_index=True,
        )
        selected_protocol = st.selectbox("Protocol detail", protocols["project"].tolist())
        protocol_pools = snapshot_filtered[snapshot_filtered["project"] == selected_protocol].sort_values(["tvl_usd", "apy"], ascending=[False, False])
        p1, p2, p3, p4 = st.columns(4)
        p1.metric("Pools", f"{len(protocol_pools):,}")
        p2.metric("Protocol TVL", format_money(float(protocol_pools['tvl_usd'].sum())))
        p3.metric("Avg APY", f"{protocol_pools['apy'].mean():.2f}%")
        p4.metric("Avg risk", f"{protocol_pools['risk_score'].mean():.1f}/10")
        st.dataframe(
            protocol_pools[["name", "chain", "symbol", "apy", "tvl_usd", "risk_score", "risk_label", "llama_pool_url"]],
            column_config={
                "apy": st.column_config.NumberColumn("APY", format="%.2f"),
                "tvl_usd": st.column_config.NumberColumn("TVL USD", format="$%.0f"),
                "llama_pool_url": st.column_config.LinkColumn("Pool link", display_text="Open pool"),
            },
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No protocols available for the current filters.")

with charts_tab:
    st.subheader("Yield charts")
    chart_left, chart_right = st.columns(2)
    with chart_left:
        apy_hist = alt.Chart(snapshot_filtered).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
            x=alt.X("apy:Q", bin=alt.Bin(maxbins=25), title="APY %"),
            y=alt.Y("count():Q", title="Pool count"),
            tooltip=[alt.Tooltip("count():Q", title="Pools")],
        )
        st.altair_chart(apy_hist, use_container_width=True)

        chain_chart_df = (
            snapshot_filtered.groupby("chain", as_index=False)
            .agg(avg_apy=("apy", "mean"), pools=("chain", "count"), total_tvl=("tvl_usd", "sum"))
            .sort_values("avg_apy", ascending=False)
            .head(12)
        )
        chain_chart = alt.Chart(chain_chart_df).mark_bar(cornerRadiusEnd=4).encode(
            x=alt.X("avg_apy:Q", title="Avg APY %"),
            y=alt.Y("chain:N", sort="-x", title="Chain"),
            color=alt.Color("pools:Q", legend=None),
            tooltip=["chain", alt.Tooltip("avg_apy:Q", format=".2f"), alt.Tooltip("total_tvl:Q", format=",.0f"), "pools"],
        )
        st.altair_chart(chain_chart, use_container_width=True)

        top10_protocol_df = (
            snapshot_filtered.groupby("project", as_index=False)
            .agg(avg_apy=("apy", "mean"), pools=("project", "count"))
            .sort_values(["avg_apy", "pools"], ascending=[False, False])
            .head(10)
        )
        top10_protocol_chart = alt.Chart(top10_protocol_df).mark_bar(cornerRadiusEnd=4).encode(
            x=alt.X("avg_apy:Q", title="Average APY %"),
            y=alt.Y("project:N", sort="-x"),
            tooltip=["project", alt.Tooltip("avg_apy:Q", format=".2f"), "pools"],
        )
        st.altair_chart(top10_protocol_chart, use_container_width=True)

    with chart_right:
        scatter = alt.Chart(snapshot_filtered.head(500)).mark_circle(size=90).encode(
            x=alt.X("tvl_usd:Q", title="TVL USD", scale=alt.Scale(type="log")),
            y=alt.Y("apy:Q", title="APY %"),
            color=alt.Color("risk_label:N", title="Risk"),
            tooltip=["name", "project", "chain", alt.Tooltip("tvl_usd:Q", format=",.0f"), alt.Tooltip("apy:Q", format=".2f"), "risk_label"],
        )
        st.altair_chart(scatter, use_container_width=True)

        risk_dist = alt.Chart(snapshot_filtered).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
            x=alt.X("risk_score:O", title="Risk score"),
            y=alt.Y("count():Q", title="Pool count"),
            color=alt.Color("risk_label:N", title="Risk band"),
        )
        st.altair_chart(risk_dist, use_container_width=True)

        stable_mix = (
            snapshot_filtered.assign(stable_group=snapshot_filtered["stablecoin"].map({True: "Stablecoin", False: "Volatile"}))
            .groupby("stable_group", as_index=False)
            .agg(pools=("stable_group", "count"), total_tvl=("tvl_usd", "sum"))
        )
        mix_chart = alt.Chart(stable_mix).mark_arc(innerRadius=45).encode(
            theta=alt.Theta("total_tvl:Q"),
            color=alt.Color("stable_group:N", title="Exposure"),
            tooltip=["stable_group", alt.Tooltip("total_tvl:Q", format=",.0f"), "pools"],
        )
        st.altair_chart(mix_chart, use_container_width=True)

with risk_tab:
    st.subheader("Risk model")
    st.write(
        "This score is a heuristic, not investment advice. It currently weights chain maturity, TVL depth, APY extremeness, "
        "stablecoin exposure, impermanent-loss flags, and certain complex strategy categories."
    )
    risk_summary = (
        snapshot_filtered.groupby("risk_label", as_index=False)
        .agg(pools=("risk_label", "count"), avg_apy=("apy", "mean"), total_tvl=("tvl_usd", "sum"))
        .sort_values("pools", ascending=False)
    )
    st.dataframe(
        risk_summary,
        column_config={
            "avg_apy": st.column_config.NumberColumn("Avg APY", format="%.2f"),
            "total_tvl": st.column_config.NumberColumn("Total TVL", format="$%.0f"),
        },
        use_container_width=True,
        hide_index=True,
    )
    risky = ranked_df.sort_values(["risk_score", "apy"], ascending=[False, False]).head(20)
    st.markdown("### Highest-risk visible pools")
    st.dataframe(
        risky[["name", "project", "chain", "apy", "risk_score", "risk_label", "risk_reasons"]],
        column_config={"apy": st.column_config.NumberColumn("APY", format="%.2f")},
        use_container_width=True,
        hide_index=True,
    )

with watchlist_tab:
    st.subheader("Watchlist")
    watch_df = snapshot_filtered[snapshot_filtered["pool_id"].isin(st.session_state.watchlist_ids)].copy()
    watch_df = add_scores(watch_df)
    if watch_df.empty:
        st.info("Your watchlist is empty. Add pools from the Opportunities tab.")
    else:
        st.dataframe(
            watch_df[["name", "project", "chain", "symbol", "apy", "tvl_usd", "risk_score", "risk_label", "llama_pool_url"]],
            column_config={
                "apy": st.column_config.NumberColumn("APY", format="%.2f"),
                "tvl_usd": st.column_config.NumberColumn("TVL USD", format="$%.0f"),
                "llama_pool_url": st.column_config.LinkColumn("Pool link", display_text="Open pool"),
            },
            use_container_width=True,
            hide_index=True,
        )
        watch_name = st.selectbox("Watchlist pool", watch_df["name"].tolist(), key="watchlist_pick")
        item = watch_df[watch_df["name"] == watch_name].iloc[0]
        c1, c2, c3 = st.columns(3)
        c1.metric("APY", f"{item['apy']:.2f}%")
        c2.metric("TVL", format_money(float(item['tvl_usd'])))
        c3.metric("Risk-adjusted", f"{item['risk_adjusted_score']:.2f}")
        st.write(item.get("risk_reasons", ""))
        if st.button("Remove from watchlist", use_container_width=False):
            st.session_state.watchlist_ids = [pid for pid in st.session_state.watchlist_ids if pid != item["pool_id"]]
            save_watchlist(st.session_state.watchlist_ids)
            st.rerun()

with alerts_tab:
    st.subheader("Opportunity alerts")
    st.write("Create reusable alert rules to surface pools that match your APY, TVL, risk, and chain requirements.")

    with st.expander("Create new alert", expanded=False):
        a1, a2, a3, a4 = st.columns(4)
        alert_name = a1.text_input("Alert name", value="High APY / lower risk")
        alert_min_apy = a2.number_input("Min APY %", min_value=0.0, value=20.0, step=1.0)
        alert_min_tvl = a3.number_input("Min TVL USD", min_value=0.0, value=5_000_000.0, step=100_000.0, format="%.0f")
        alert_max_risk = a4.slider("Max risk", min_value=1, max_value=10, value=5)
        alert_chain = st.selectbox("Chain", ["Any"] + available_chains, key="alert_chain")
        if st.button("Save alert", use_container_width=False):
            st.session_state.alerts.append(
                {
                    "name": alert_name,
                    "min_apy": float(alert_min_apy),
                    "min_tvl": float(alert_min_tvl),
                    "max_risk": int(alert_max_risk),
                    "chain": alert_chain,
                }
            )
            save_alerts(st.session_state.alerts)
            st.rerun()

    if not st.session_state.alerts:
        st.info("No alerts created yet.")
    else:
        updated_alerts = []
        for idx, alert in enumerate(st.session_state.alerts):
            st.markdown(f"### {alert['name']}")
            st.caption(
                f"APY ≥ {alert['min_apy']:.2f}% · TVL ≥ {format_money(alert['min_tvl'])} · Risk ≤ {alert['max_risk']} · Chain: {alert['chain']}"
            )
            matches = snapshot_filtered[
                (snapshot_filtered["apy"] >= alert["min_apy"])
                & (snapshot_filtered["tvl_usd"] >= alert["min_tvl"])
                & (snapshot_filtered["risk_score"] <= alert["max_risk"])
            ].copy()
            if alert["chain"] != "Any":
                matches = matches[matches["chain"] == alert["chain"]]
            matches = add_scores(matches).sort_values(["opportunity_score", "apy"], ascending=[False, False])
            if matches.empty:
                st.warning("No matches right now.")
            else:
                st.success(f"{len(matches):,} match(es) found.")
                st.dataframe(
                    matches[["name", "project", "chain", "symbol", "apy", "tvl_usd", "risk_score", "risk_label", "llama_pool_url"]].head(12),
                    column_config={
                        "apy": st.column_config.NumberColumn("APY", format="%.2f"),
                        "tvl_usd": st.column_config.NumberColumn("TVL USD", format="$%.0f"),
                        "llama_pool_url": st.column_config.LinkColumn("Pool link", display_text="Open pool"),
                    },
                    use_container_width=True,
                    hide_index=True,
                )
            if st.button("Delete alert", key=f"delete_alert_{idx}"):
                continue
            updated_alerts.append(alert)
        if updated_alerts != st.session_state.alerts:
            st.session_state.alerts = updated_alerts
            save_alerts(updated_alerts)
            st.rerun()
