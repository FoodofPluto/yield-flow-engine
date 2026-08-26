"""Deterministic, capability-gated CSV export for current pool results."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

import pandas as pd

from product_capabilities import ProductCapabilities, can_export_csv


CSV_COLUMNS = (
    "pool",
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
    "signal",
    "audit_score",
    "protocol_age_score",
    "tvl_stability_score",
    "pool_volatility_score",
    "pool_url",
)

FORMULA_PREFIXES = ("=", "+", "-", "@")
CSV_UPGRADE_MESSAGE = "CSV export is planned for Pro — $24.99 and is not included in Free, Core, or Plus."


@dataclass(frozen=True)
class CsvExportResult:
    allowed: bool
    content: bytes | None
    message: str
    row_count: int = 0


def _plain_cell(value: Any) -> Any:
    """Preserve numbers while neutralizing formula-like plain text."""

    if value is None or value is pd.NA:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, str):
        return f"'{value}" if value.startswith(FORMULA_PREFIXES) else value
    return value


def normalize_csv_rows(rows: pd.DataFrame | Iterable[Mapping[str, Any]]) -> tuple[list[str], list[list[Any]]]:
    """Return the stable schema and normalized rows without UI/global state."""

    frame = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(list(rows))
    columns = [column for column in CSV_COLUMNS if column in frame.columns]
    normalized = [[_plain_cell(value) for value in row] for row in frame.reindex(columns=columns).itertuples(index=False, name=None)]
    return columns, normalized


def serialize_csv(rows: pd.DataFrame | Iterable[Mapping[str, Any]]) -> bytes:
    """Serialize deterministic UTF-8 CSV with an Excel-compatible BOM."""

    columns, normalized = normalize_csv_rows(rows)
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(columns)
    writer.writerows(normalized)
    return stream.getvalue().encode("utf-8-sig")


def prepare_csv_export(
    rows: pd.DataFrame | Iterable[Mapping[str, Any]],
    capabilities: ProductCapabilities,
) -> CsvExportResult:
    """Apply the execution-side capability gate before producing any bytes."""

    if not can_export_csv(capabilities):
        return CsvExportResult(False, None, CSV_UPGRADE_MESSAGE)
    frame = rows if isinstance(rows, pd.DataFrame) else list(rows)
    content = serialize_csv(frame)
    return CsvExportResult(True, content, "CSV export ready.", len(frame))
