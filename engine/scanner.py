from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Set

from engine.providers import demo

try:
    from engine.providers import defillama
    HAS_DEFILLAMA = True
except Exception:
    HAS_DEFILLAMA = False


@dataclass
class YieldItem:
    name: str
    apy: float
    source: str
    meta: Dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        return self.meta.get(key, default)

    def __getitem__(self, key: str) -> Any:
        val = self.get(key, None)
        if val is None:
            raise KeyError(key)
        return val


@dataclass
class FilterOptions:
    min_tvl: float = 1_000_000.0
    max_apy: float = 500.0
    stablecoin_only: bool = False
    chains: Optional[Set[str]] = None
    projects: Optional[Set[str]] = None


RISK_LABELS = {
    range(0, 3): "Low",
    range(3, 6): "Moderate",
    range(6, 8): "Elevated",
    range(8, 11): "High",
}


def _risk_label(score: int) -> str:
    for score_range, label in RISK_LABELS.items():
        if score in score_range:
            return label
    return "High"


MAJOR_CHAINS = {
    "ethereum": 0,
    "bitcoin": 0,
    "base": 1,
    "arbitrum": 1,
    "optimism": 1,
    "polygon": 1,
    "avalanche": 1,
    "solana": 1,
    "bnb chain": 2,
    "bsc": 2,
    "fantom": 2,
}


EXOTIC_CATEGORY_PENALTIES = {
    "leveraged": 3,
    "options": 2,
    "delta neutral": 2,
    "basis trading": 2,
    "yield looping": 3,
    "lsd": 1,
    "lst": 1,
    "lp": 1,
}


def compute_risk(meta: Dict[str, Any]) -> Dict[str, Any]:
    tvl = float(meta.get("tvlUsd") or 0.0)
    apy = float(meta.get("apy") or 0.0)
    stable = bool(meta.get("stablecoin") or False)
    il_risk = str(meta.get("ilRisk") or "").lower()
    chain = str(meta.get("chain") or "").lower()
    category = str(meta.get("category") or "").lower()
    project = str(meta.get("project") or "")

    score = 1
    reasons: List[str] = []

    chain_penalty = MAJOR_CHAINS.get(chain, 2)
    score += chain_penalty
    if chain_penalty >= 2 and chain:
        reasons.append(f"less battle-tested chain: {meta.get('chain')}")

    if tvl < 1_000_000:
        score += 3
        reasons.append("very low TVL")
    elif tvl < 10_000_000:
        score += 2
        reasons.append("modest TVL")
    elif tvl < 100_000_000:
        score += 1
        reasons.append("mid TVL")

    if apy >= 80:
        score += 3
        reasons.append("very high APY")
    elif apy >= 30:
        score += 2
        reasons.append("high APY")
    elif apy >= 15:
        score += 1
        reasons.append("above-market APY")

    if not stable:
        score += 1
        reasons.append("volatile asset exposure")

    if il_risk and il_risk not in {"no", "none", "n/a"}:
        score += 1
        reasons.append(f"impermanent loss risk: {meta.get('ilRisk')}")

    for key, penalty in EXOTIC_CATEGORY_PENALTIES.items():
        if key in category:
            score += penalty
            reasons.append(f"strategy category: {meta.get('category')}")
            break

    if not project:
        score += 1
        reasons.append("missing protocol metadata")

    score = max(1, min(int(score), 10))
    label = _risk_label(score)
    return {
        "risk_score": score,
        "risk_label": label,
        "risk_reasons": "; ".join(reasons[:4]) if reasons else "Large-chain, high-liquidity pool profile.",
    }


def _passes_filters(item: YieldItem, filt: FilterOptions) -> bool:
    tvl = float((item.meta or {}).get("tvlUsd") or 0.0)
    stable = bool((item.meta or {}).get("stablecoin") or False)
    chain = (item.meta or {}).get("chain")
    project = (item.meta or {}).get("project")

    if tvl < filt.min_tvl:
        return False
    if item.apy <= 0 or item.apy > filt.max_apy:
        return False
    if filt.stablecoin_only and not stable:
        return False
    if filt.chains and chain not in filt.chains:
        return False
    if filt.projects and project not in filt.projects:
        return False
    return True


def _slugify_protocol(name: str | None) -> str:
    if not name:
        return ""
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in name).strip("-")
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned


def _coerce(d: Dict[str, Any], source: str) -> YieldItem:
    protocol = str(d.get("project") or d.get("name") or d.get("pool") or "Unknown")
    pool_name = str(d.get("poolMeta") or d.get("symbol") or protocol)
    meta = {
        k: v
        for k, v in d.items()
        if k.lower() not in {"name", "apy", "apy (%)", "project", "pool"}
    }
    meta["project"] = protocol
    meta["apy"] = float(d.get("apy") or d.get("APY") or 0.0)
    meta["pool_id"] = d.get("pool")
    meta.setdefault("symbol", d.get("symbol"))
    meta.setdefault("chain", d.get("chain"))
    meta.setdefault("tvlUsd", float(d.get("tvlUsd") or 0.0))
    meta.setdefault("stablecoin", bool(d.get("stablecoin") or False))
    meta.setdefault("url", d.get("url") or "")
    meta.setdefault(
        "protocol_url",
        d.get("protocol_url") or (f"https://defillama.com/protocol/{_slugify_protocol(protocol)}" if protocol else ""),
    )
    meta.setdefault(
        "llama_pool_url",
        d.get("llama_pool_url") or (f"https://defillama.com/yields/pool/{d.get('pool')}" if d.get("pool") else ""),
    )
    meta.update(compute_risk(meta))
    return YieldItem(
        name=f"{protocol} — {pool_name}",
        apy=float(meta["apy"]),
        source=source,
        meta=meta,
    )


def _fetch_from(provider: str, limit: int) -> List[YieldItem]:
    try:
        if provider == "demo":
            data = demo.get_yields(limit=limit)
            return [_coerce(d, "demo") for d in data]
        if provider == "defillama" and HAS_DEFILLAMA:
            data = defillama.get_yields(limit=limit)
            return [_coerce(d, "defillama") for d in data]
    except Exception as e:
        print(f"[{datetime.now().isoformat()}] Provider '{provider}' failed: {e}")
        return []
    return []


def _available_providers() -> List[str]:
    return ["demo"] + (["defillama"] if HAS_DEFILLAMA else [])


def _resolve_providers(source: str | None) -> List[str]:
    if not source or source.lower() == "all":
        return _available_providers()
    parts = [p.strip().lower() for p in source.split(",")]
    return [p for p in parts if p in _available_providers()]


def _merge_batches(
    batches: Iterable[List[YieldItem]], top: int, filt: FilterOptions
) -> List[YieldItem]:
    seen = set()
    merged: List[YieldItem] = []
    for items in batches:
        for it in items:
            key = (
                (it.meta or {}).get("pool_id") or it.name.strip().lower(),
                it.source,
            )
            if key in seen:
                continue
            seen.add(key)
            if _passes_filters(it, filt):
                merged.append(it)

    def _score(x: YieldItem) -> float:
        tvl = float((x.meta or {}).get("tvlUsd") or 0.0)
        risk_score = int((x.meta or {}).get("risk_score") or 5)
        return x.apy + min(tvl / 10_000_000.0, 25.0) - (risk_score * 0.75)

    merged.sort(key=_score, reverse=True)
    return merged[:top]


def rank_top_yields(
    top: int = 10,
    source: str | None = None,
    min_tvl: float = 1_000_000.0,
    max_apy: float = 500.0,
    stablecoin_only: bool = False,
    chains: Optional[list[str]] = None,
    projects: Optional[list[str]] = None,
) -> List[YieldItem]:
    providers = _resolve_providers(source)
    batches = [_fetch_from(p, limit=max(top * 30, 150)) for p in providers]
    filt = FilterOptions(
        min_tvl=min_tvl,
        max_apy=max_apy,
        stablecoin_only=stablecoin_only,
        chains=set(chains) if chains else None,
        projects=set(projects) if projects else None,
    )
    return _merge_batches(batches, top=top, filt=filt)


def list_market_snapshot(source: str | None = None) -> List[YieldItem]:
    providers = _resolve_providers(source)
    items: List[YieldItem] = []
    for provider in providers:
        items.extend(_fetch_from(provider, limit=400))
    return items


def as_rows(items: List[YieldItem]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    refreshed_at = datetime.now(timezone.utc).isoformat()
    for it in items:
        meta = it.meta or {}
        rows.append(
            {
                "name": it.name,
                "apy": float(it.apy),
                "source": it.source,
                "chain": meta.get("chain", ""),
                "project": meta.get("project", ""),
                "symbol": meta.get("symbol", ""),
                "tvl_usd": float(meta.get("tvlUsd") or 0.0),
                "stablecoin": bool(meta.get("stablecoin") or False),
                "apy_base": meta.get("apyBase"),
                "apy_reward": meta.get("apyReward"),
                "apy_pct_1d": meta.get("apyPct1D"),
                "apy_pct_7d": meta.get("apyPct7D"),
                "apy_pct_30d": meta.get("apyPct30D"),
                "il_risk": meta.get("ilRisk", ""),
                "category": meta.get("category", ""),
                "exposure": meta.get("exposure", ""),
                "risk_score": int(meta.get("risk_score") or 0),
                "risk_label": meta.get("risk_label", ""),
                "risk_reasons": meta.get("risk_reasons", ""),
                "protocol_url": meta.get("protocol_url", ""),
                "llama_pool_url": meta.get("llama_pool_url", ""),
                "pool_id": meta.get("pool_id", ""),
                "refreshed_at": refreshed_at,
            }
        )
    return rows
