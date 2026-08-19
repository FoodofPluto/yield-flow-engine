from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd


# Keep only the public market fields consumed by the application. DeFiLlama
# also returns nested prediction/token collections that are not rendered and
# make Streamlit fall back to pickling the entire frame while hashing it.
PROVIDER_POOL_FIELDS = (
    "pool",
    "chain",
    "project",
    "symbol",
    "apy",
    "apyBase",
    "apyReward",
    "tvlUsd",
    "volumeUsd1d",
    "volumeUsd7d",
    "poolMeta",
    "exposure",
    "stablecoin",
)


def provider_pool_frame(rows: Iterable[Mapping[str, Any]]) -> pd.DataFrame:
    """Materialize the bounded public market projection used by FuruFlow."""

    return pd.DataFrame.from_records(rows, columns=list(PROVIDER_POOL_FIELDS))
