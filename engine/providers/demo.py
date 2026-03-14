from __future__ import annotations


def get_yields(limit: int = 15):
    data = [
        {
            "name": "Aave — USDC",
            "project": "Aave",
            "poolMeta": "USDC",
            "symbol": "USDC",
            "chain": "Ethereum",
            "apy": 5.2,
            "tvlUsd": 340000000,
            "stablecoin": True,
            "category": "Lending",
            "ilRisk": "no",
        },
        {
            "name": "Morpho — USDT",
            "project": "Morpho",
            "poolMeta": "USDT",
            "symbol": "USDT",
            "chain": "Base",
            "apy": 8.4,
            "tvlUsd": 48000000,
            "stablecoin": True,
            "category": "Lending",
            "ilRisk": "no",
        },
        {
            "name": "Pendle — ETH",
            "project": "Pendle",
            "poolMeta": "ETH",
            "symbol": "ETH",
            "chain": "Arbitrum",
            "apy": 13.1,
            "tvlUsd": 22000000,
            "stablecoin": False,
            "category": "LSD",
            "ilRisk": "low",
        },
        {
            "name": "Aerodrome — cbBTC/ETH",
            "project": "Aerodrome",
            "poolMeta": "cbBTC/ETH",
            "symbol": "cbBTC-ETH",
            "chain": "Base",
            "apy": 19.6,
            "tvlUsd": 9700000,
            "stablecoin": False,
            "category": "LP",
            "ilRisk": "medium",
        },
    ]
    return data[:limit]
