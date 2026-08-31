from __future__ import annotations

import math

import pandas as pd
import pytest

from signal_visualization import build_signal_scatter, signal_scatter_data


def _frame(strengths: list[object]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "signal": [f"Signal {index}" for index in range(len(strengths))],
            "apy": [4.0 + index for index in range(len(strengths))],
            "tvlUsd": [1_000_000.0 + index for index in range(len(strengths))],
            "signal_strength": strengths,
        }
    )


def _marker_sizes(figure) -> list[float]:
    sizes: list[float] = []
    for trace in figure.data:
        value = trace.marker.size
        values = value if hasattr(value, "__iter__") and not isinstance(value, str) else [value]
        sizes.extend(float(item) for item in values)
    return sizes


@pytest.mark.parametrize(
    ("strengths", "available"),
    [
        ([12.0, 24.0], [True, True]),
        ([12.0, float("nan")], [True, False]),
        ([float("nan"), float("nan")], [False, False]),
        ([pd.NA, pd.NA], [False, False]),
        ([float("inf"), float("-inf")], [False, False]),
    ],
)
def test_signal_scatter_data_preserves_missing_semantics_and_marks_availability(
    strengths: list[object], available: list[bool]
) -> None:
    data = signal_scatter_data(_frame(strengths))

    assert data["strength_available"].tolist() == available
    for row, is_available in zip(data.itertuples(), available, strict=True):
        assert math.isfinite(row.avg_strength) is is_available
        if not is_available:
            assert row.strength_display == "No measurable signal strength"


def test_zero_strength_remains_a_measured_zero() -> None:
    data = signal_scatter_data(_frame([0.0]))
    figure = build_signal_scatter(_frame([0.0]))

    assert data.loc[0, "avg_strength"] == 0.0
    assert bool(data.loc[0, "strength_available"])
    assert _marker_sizes(figure) == [0.0]
    assert figure.data[0].marker.sizemin == 6


@pytest.mark.parametrize(
    "strengths",
    [
        [12.0, 24.0],
        [12.0, float("nan")],
        [float("nan"), float("nan")],
        [pd.NA, pd.NA],
        [float("inf"), float("-inf")],
    ],
)
def test_plotly_marker_sizes_are_always_finite_and_non_negative(strengths: list[object]) -> None:
    figure = build_signal_scatter(_frame(strengths))
    sizes = _marker_sizes(figure)

    assert sizes
    assert all(math.isfinite(value) and value >= 0 for value in sizes)


def test_all_missing_strength_uses_a_distinct_neutral_trace() -> None:
    figure = build_signal_scatter(_frame([pd.NA, float("nan")]))

    assert len(figure.data) == 1
    assert figure.data[0].name == "No measurable signal strength"
    assert figure.data[0].marker.symbol == "x"
    assert "No measurable signal strength" in str(figure.data[0].customdata)
