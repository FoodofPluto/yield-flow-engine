# engine/core.py
# engine/core.py
from typing import Iterable, List, Dict, Optional
# engine/core.py

def _split_tokens(symbol: Optional[str]):
    if not symbol:
        return None, None
    s = symbol.replace(" ", "")
    for sep in ("-", "/", "_", ":"):
        if sep in s:
            t0, t1 = s.split(sep, 1)
            return t0, t1
    return None, None

def fetch_rows_from_sources(source: str):
    rows = []
    wanted = [s.strip() for s in source.split(",")] if source and source != "all" else ["defillama"]

    if "defillama" in wanted:
        try:
            from engine.adapters.defillama import get_yields
            raw = get_yields(limit=200)  # pull a bit more, we’ll filter after
            for d in raw:
                t0, t1 = _split_tokens(d.get("symbol"))
                # Heuristic: if we have two tokens, treat as dex pool
                typ = "dex" if (t0 and t1) else None
                rows.append({
                    "name": d.get("name") or d.get("project") or d.get("pool") or "Unknown",
                    "apy": float(d.get("apy") or 0.0),
                    "tvl_usd": float(d.get("tvlUsd") or 0.0),
                    "chain": d.get("chain"),
                    "type": typ,  # may be None if we can’t infer
                    "token0_symbol": t0,
                    "token1_symbol": t1,
                    "asset_symbol": d.get("symbol"),  # fallback for lending-like rows
                    "source": "defillama",
                })
        except Exception:
            pass

    # If you have a demo adapter, append it here similarly...
    return rows

def fetch_rows_from_sources(source: str):
    """
    Return a flat list[dict] of raw rows for the requested sources.
    Each row should include at least:
      name, apy (float), tvl_usd (float), chain (str), type/category (str).
    For DEX rows also include token0_symbol, token1_symbol.
    For lending rows include asset_symbol (or underlier/token_symbol).
    """
    rows = []
    wanted = [s.strip() for s in source.split(",")] if source and source != "all" else ["defillama", "demo"]

    if "defillama" in wanted:
        # expects engine/adapters/defillama.py -> def fetch_rows() -> list[dict]
        try:
            from engine.adapters.defillama import fetch_rows as llama_fetch
            rows.extend(llama_fetch())
        except Exception:
            pass  # keep going even if one adapter fails

    if "demo" in wanted:
        # expects engine/adapters/demo.py -> def fetch_rows() -> list[dict]
        try:
            from engine.adapters.demo import fetch_rows as demo_fetch
            rows.extend(demo_fetch())
        except Exception:
            pass

    return rows

STABLE_TOKENS = {
    "USDC","USDT","DAI","FRAX","TUSD","USDP","LUSD",
    "CRVUSD","GHO","PYUSD","SDAI","USD0","USDE","USDB"
}

def _norm(sym: Optional[str]) -> str:
    return (sym or "").upper().replace(".E", "").replace("-", "").strip()

def is_stable_symbol(sym: Optional[str]) -> bool:
    return _norm(sym) in STABLE_TOKENS

def is_stable_stable_pool(row: Dict) -> bool:
    t0, t1 = row.get("token0_symbol"), row.get("token1_symbol")
    return bool(t0 and t1 and is_stable_symbol(t0) and is_stable_symbol(t1))

def matches_category(row: Dict, category: Optional[str]) -> bool:
    if not category:
        return True
    typ = (row.get("type") or row.get("category") or "").lower()
    if any(x in typ for x in ["lend", "money market", "lending"]):
        return category == "lend"
    if any(x in typ for x in ["dex", "amm", "pool", "clmm", "lb"]):
        return category == "dex"
    # Heuristic: if it looks like a pool (has two tokens), treat as dex
    if row.get("token0_symbol") and row.get("token1_symbol"):
        return category == "dex"
    return False


def _chain_match(row: Dict, chains: List[str]) -> bool:
    if not chains:
        return True
    chain = (row.get("chain") or row.get("network") or "").strip()
    return chain in chains

def apply_filters(rows: Iterable[Dict], *,
                  min_tvl: float,
                  max_apy: float,
                  stablecoin_only: bool,
                  chains: List[str],
                  category: Optional[str]) -> List[Dict]:
    out: List[Dict] = []
    for r in rows:
        if r.get("tvl_usd", 0.0) < min_tvl:
            continue
        apy = r.get("apy", 0.0)
        if apy is None or not (0 <= apy <= max_apy):
            continue
        if not _chain_match(r, chains):
            continue
        if not matches_category(r, category):
            continue

        if stablecoin_only:
            if category == "dex":
                if not is_stable_stable_pool(r):
                    continue
            elif category == "lend":
                asset = r.get("asset_symbol") or r.get("underlier") or r.get("token_symbol")
                if not is_stable_symbol(asset):
                    # sometimes lending rows also carry token0/token1 — fall back
                    if not is_stable_stable_pool(r):
                        continue
            else:
                # No category chosen: accept either lending stable OR stable-stable pool
                asset = r.get("asset_symbol") or r.get("underlier") or r.get("token_symbol")
                if not (is_stable_symbol(asset) or is_stable_stable_pool(r)):
                    continue

        out.append(r)
    return out

def scan_and_rank(*, top: int, source: str, min_tvl: float, max_apy: float,
                  stablecoin_only: bool, chains: str, category: Optional[str]):
    # ... fetch rows via your adapters based on source ...
    # Convert chains string to list (preserve case)
    chain_list = [c.strip() for c in chains.split(",") if c.strip()] if chains else []
    rows = fetch_rows_from_sources(source)  # your existing implementation
    rows = apply_filters(rows,
                         min_tvl=min_tvl,
                         max_apy=max_apy,
                         stablecoin_only=stablecoin_only,
                         chains=chain_list,
                         category=category)
    # ... sort by apy desc, slice top, return ...
    rows.sort(key=lambda r: (r.get("apy") or 0), reverse=True)
    return rows[:top]
