from __future__ import annotations

import ast
from pathlib import Path

from market_data import PROVIDER_POOL_FIELDS, provider_pool_frame


ROOT = Path(__file__).parents[1]


def test_provider_projection_drops_unused_nested_payloads() -> None:
    frame = provider_pool_frame(
        [
            {
                "pool": "pool-a",
                "chain": "Ethereum",
                "project": "aave-v3",
                "symbol": "USDC",
                "apy": 5.0,
                "tvlUsd": 1_000_000,
                "underlyingTokens": ["token-a", "token-b"],
                "rewardTokens": ["reward-a"],
                "predictions": {"predictedClass": "Stable/Up"},
            }
        ]
    )

    assert tuple(frame.columns) == PROVIDER_POOL_FIELDS
    assert "underlyingTokens" not in frame
    assert "rewardTokens" not in frame
    assert "predictions" not in frame
    assert not any(isinstance(value, (dict, list)) for value in frame.iloc[0])


def test_enriched_snapshot_cache_has_no_dataframe_key_and_is_bounded() -> None:
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}

    cached_snapshot = functions["fetch_enriched_pools"]
    assert [argument.arg for argument in cached_snapshot.args.args] == ["resolver_version"]

    decorator = next(
        decorator
        for decorator in cached_snapshot.decorator_list
        if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
    )
    keywords = {keyword.arg: ast.literal_eval(keyword.value) for keyword in decorator.keywords}
    assert keywords["ttl"] == 900
    assert keywords["max_entries"] == 1

    enrich = functions["enrich"]
    assert not enrich.decorator_list


def test_docker_context_excludes_runtime_market_history() -> None:
    ignored = {
        line.strip()
        for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert "pool_history.json" in ignored
