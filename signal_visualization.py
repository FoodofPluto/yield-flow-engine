from __future__ import annotations

import math

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


def signal_scatter_data(frame: pd.DataFrame) -> pd.DataFrame:
    """Aggregate Signals chart data without turning missing evidence into zero."""
    grouped = frame.groupby("signal", as_index=False).agg(
        avg_apy=("apy", "mean"),
        avg_tvl=("tvlUsd", "mean"),
        avg_strength=("signal_strength", "mean"),
    )
    for column in ("avg_apy", "avg_tvl", "avg_strength"):
        grouped[column] = pd.to_numeric(grouped[column], errors="coerce").astype("float64")

    finite_position = grouped["avg_apy"].map(math.isfinite) & grouped["avg_tvl"].map(math.isfinite)
    grouped = grouped[finite_position & grouped["avg_tvl"].gt(0)].copy()
    grouped["strength_available"] = grouped["avg_strength"].map(math.isfinite) & grouped["avg_strength"].ge(0)
    grouped["strength_display"] = grouped["avg_strength"].map(
        lambda value: f"{value:.1f}" if math.isfinite(value) and value >= 0 else "No measurable signal strength"
    )
    return grouped


def build_signal_scatter(frame: pd.DataFrame) -> go.Figure:
    """Build a Plotly-safe chart while keeping missing strength semantically unavailable."""
    chart_data = signal_scatter_data(frame)
    measured = chart_data[chart_data["strength_available"]]
    unavailable = chart_data[~chart_data["strength_available"]]
    figure = go.Figure()

    if not measured.empty:
        measured_figure = px.scatter(
            measured,
            x="avg_tvl",
            y="avg_apy",
            size="avg_strength",
            color="signal",
            hover_name="signal",
            custom_data=["strength_display"],
            size_max=42,
            log_x=True,
        )
        for trace in measured_figure.data:
            trace.update(marker_sizemin=6)
            trace.hovertemplate = (
                "<b>%{hovertext}</b><br>Average TVL=%{x}<br>Average APY=%{y}<br>"
                "Average signal strength=%{customdata[0]}<extra></extra>"
            )
            figure.add_trace(trace)

    if not unavailable.empty:
        figure.add_trace(
            go.Scatter(
                x=unavailable["avg_tvl"].tolist(),
                y=unavailable["avg_apy"].tolist(),
                mode="markers",
                marker={"size": 10, "symbol": "x", "color": "#94A3B8"},
                text=unavailable["signal"].tolist(),
                customdata=unavailable[["strength_display"]].to_numpy(),
                hovertemplate=(
                    "<b>%{text}</b><br>Average TVL=%{x}<br>Average APY=%{y}<br>"
                    "Average signal strength=%{customdata[0]}<extra></extra>"
                ),
                name="No measurable signal strength",
            )
        )

    figure.update_xaxes(type="log")
    return figure
