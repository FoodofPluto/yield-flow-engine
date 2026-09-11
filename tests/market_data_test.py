from __future__ import annotations

import math

import pandas as pd

from market_data import normalize_provider_numbers, provider_pool_frame


def test_provider_number_normalization_separates_rendering_fallback_from_truth() -> None:
    values, available = normalize_provider_numbers(
        pd.Series([0, "12.5", None, pd.NA, float("nan"), float("inf"), float("-inf"), {"bad": "shape"}])
    )
    assert values.tolist() == [0.0, 12.5, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    assert available.tolist() == [True, True, False, False, False, False, False, False]
    assert all(math.isfinite(float(value)) and float(value) >= 0 for value in values)


def test_provider_projection_preserves_canonical_pool_ids_for_lookalikes() -> None:
    rows = [
        {
            "pool": "aa70268e-4b52-42bf-a116-608b370f9501",
            "project": "aave-v3",
            "symbol": "USDC",
            "chain": "Ethereum",
            "poolMeta": "General",
        },
        {
            "pool": "effcb4a4-4dcb-45e5-935d-f15542c13e6b",
            "project": "aave-v3",
            "symbol": "USDC",
            "chain": "Ethereum",
            "poolMeta": "Prime Instance",
        },
    ]
    frame = provider_pool_frame(rows)
    assert frame["pool"].tolist() == [row["pool"] for row in rows]
    assert frame["pool"].nunique() == 2
