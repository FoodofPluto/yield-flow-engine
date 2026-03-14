# engine/cli.py
from __future__ import annotations
from typing import Optional, List, Any, Dict, Sequence
from pathlib import Path
import enum
import json
import csv
import re
import typer

from engine.scanner import rank_top_yields


# ---------------- Enums ----------------
class StableMode(str, enum.Enum):
    all = "all"    # every leg is a stable
    any = "any"    # at least one leg is a stable
    none = "none"  # no stables at all


# ---------------- Constants ----------------
STABLE_TICKERS = {
    "USDC","USDT","DAI","FRAX","LUSD","TUSD","USDE","USDS","USDB",
    "GUSD","PYUSD","EURS","FDUSD","BUSD","CRVUSD","USDK","XUSD","USDL"
}

DEX_HINTS = (
    "dex","amm","swap","clmm","clamm",
    "uniswap","sushiswap","velodrome","pancakeswap","kyberswap",
    "curve","balancer","ramses","camelot","joe","cetus","thala","osmosis"
)
LEND_HINTS = (
    "lend","lending","borrow","money market","moneymarket",
    "aave","compound","radiant","morpho","spark","fraxlend","geist","venus"
)


# ---------------- Helpers ----------------
def _csv_to_list(csv: Optional[str]) -> Optional[List[str]]:
    if not csv:
        return None
    return [p.strip() for p in csv.split(",") if p.strip()]

def _norm_chain(x: str) -> str:
    return (x or "").strip().lower()

def _norm_txt(s: str | None) -> str:
    return (s or "").strip().lower()

def _extract_symbols(meta: Dict[str, Any] | None) -> List[str]:
    if not meta:
        return []
    for k in ("symbols","tokens","tokenSymbols","assets"):
        v = meta.get(k)
        if isinstance(v, (list, tuple)):
            return [str(x).upper().replace("-", "/") for x in v]
    sym = str(meta.get("symbol","")).upper()
    return [p.strip() for p in sym.replace("-", "/").split("/") if p.strip()]

def _stable_composition(symbols: Sequence[str]) -> StableMode:
    if not symbols:
        return StableMode.none
    toks = {re.sub(r"[^A-Z0-9]", "", s.upper()) for s in symbols}
    hits = [t for t in toks if t in STABLE_TICKERS]
    if not hits:
        return StableMode.none
    return StableMode.all if len(hits) == len(toks) else StableMode.any

def _infer_category(raw_cat: str | None, name: str | None) -> str:
    cat = (raw_cat or "").lower()
    nm = (name or "").lower()
    hay = f"{cat} {nm}"
    if any(k in hay for k in DEX_HINTS):    return "dex"
    if any(k in hay for k in LEND_HINTS):   return "lending"
    return cat or ""

def _category_matches(raw_cat: str | None, requested: str | None, *, name: str = "") -> bool:
    if not requested:
        return True
    req = _norm_txt(requested)
    cat = _norm_txt(raw_cat)
    if cat and req in cat:
        return True
    # fallback heuristic
    inferred = _infer_category(cat, name)
    return inferred == req


# ---------------- Printing ----------------
def _print_table(
    items: List[Any],
    debug: bool,
) -> None:
    if not items:
        print("No results after filters. Try lowering --min-tvl or raising --max-apy, or relax --category / --stable-mode.")
        return

    header = (
        f"{'Name':40} {'APY%':>8} {'Source':10} {'TVL (USD)':>14} {'Chain':10}"
        if not debug
        else f"{'Name':40} {'APY%':>8} {'Source':10} {'TVL (USD)':>14} {'Chain':10} {'Symbols':18} {'Stable':6} {'Category':12}"
    )
    print(header)
    print("-" * len(header))

    for it in items:
        meta = getattr(it, "meta", {}) or {}
        name = getattr(it, "name", "") or meta.get("name", "")
        apy = float(getattr(it, "apy", 0) or meta.get("apyBase", 0) or meta.get("apy", 0) or 0)
        tvl = float(meta.get("tvlUsd", 0) or getattr(it, "tvl", 0) or 0)
        chain_raw = meta.get("chain") or meta.get("network") or getattr(it, "chain", "")
        symbols = _extract_symbols(meta)
        comp = _stable_composition(symbols).value
        category_val = _infer_category(meta.get("category") or meta.get("type"), name)

        apy_str = f"{apy:,.2f}"
        tvl_str = f"{tvl:,.0f}"
        source = getattr(it, "source", "unknown")

        if debug:
            dbg_symbols = " ".join(symbols) or "-"
            print(
                f"{name:40} {apy_str:>8} {source:10} {tvl_str:>14} {chain_raw:10} "
                f"{dbg_symbols[:18]:18} {comp:6} {str(category_val)[:12]:12}"
            )
        else:
            print(f"{name:40} {apy_str:>8} {source:10} {tvl_str:>14} {chain_raw:10}")


# ---------------- Core Scan ----------------
def _scan_impl(
    top: int,
    source: str,
    category: Optional[str],
    stablecoin_only: bool,
    stable_mode: Optional[StableMode],
    chains: Optional[str],
    min_tvl: float,
    max_apy: float,
    debug: bool,
    *,
    out_path: Optional[str],
    out_format: str,
) -> None:

    requested_chains = {_norm_chain(x) for x in (_csv_to_list(chains) or [])}

    items = rank_top_yields(
        top=top,
        source=source,
        min_tvl=0,
        max_apy=10000,
        stablecoin_only=False,
        chains=None,
    )

    filtered: List[Any] = []
    for it in items:
        meta = getattr(it, "meta", {}) or {}
        name = getattr(it, "name", "") or meta.get("name", "")
        chain = _norm_chain(meta.get("chain") or meta.get("network") or getattr(it, "chain", ""))
        tvl = float((meta.get("tvlUsd") or getattr(it, "tvl", 0) or 0))
        apy = float((meta.get("apyBase") or meta.get("apy") or getattr(it, "apy", 0) or 0))
        symbols = _extract_symbols(meta)
        comp = _stable_composition(symbols)

        # ---- category filter ----
        if not _category_matches(meta.get("category") or meta.get("type") or "", category, name=name):
            if debug:
                print(f"[skip category] {name} — raw={meta.get('category')!r}, requested={category!r}")
            continue

        # ---- chain filter ----
        if requested_chains and chain not in requested_chains:
            if debug:
                print(f"[skip chain] {chain!r} not in {sorted(requested_chains)}")
            continue

        # ---- TVL / APY thresholds ----
        if tvl < min_tvl:
            if debug:
                print(f"[skip tvl] {name} — tvl {tvl:,.0f} < min_tvl {min_tvl:,.0f}")
            continue
        if apy > max_apy:
            if debug:
                print(f"[skip apy] {name} — apy {apy:.2f}% > max_apy {max_apy:.2f}%")
            continue

        # ---- stable filters ----
        eff_mode = stable_mode
        if stablecoin_only and eff_mode is None:
            eff_mode = StableMode.any
        if eff_mode:
            if eff_mode == StableMode.none and comp != StableMode.none:
                if debug:
                    print(f"[skip stable=none] {name} — comp={comp.value}")
                continue
            if eff_mode == StableMode.any and comp not in {StableMode.any, StableMode.all}:
                if debug:
                    print(f"[skip stable=any] {name} — comp={comp.value}")
                continue
            if eff_mode == StableMode.all and comp != StableMode.all:
                if debug:
                    print(f"[skip stable=all] {name} — comp={comp.value}")
                continue

        filtered.append(it)

    # ---- no results ----
    if not filtered:
        typer.echo("No results after filters. Try lowering --min-tvl or raising --max-apy, or relax --category / --stable-mode.")
        return

    # ---- export or print ----
    if out_format.lower() in {"csv", "json"}:
        path = Path(out_path or (f"yield_results.{out_format.lower()}"))
        path.parent.mkdir(parents=True, exist_ok=True)

        if out_format.lower() == "csv":
            # normalize rows
            rows: List[Dict[str, Any]] = []
            for it in filtered:
                meta = getattr(it, "meta", {}) or {}
                name = getattr(it, "name", "") or meta.get("name", "")
                apy = float(getattr(it, "apy", 0) or meta.get("apyBase", 0) or meta.get("apy", 0) or 0)
                tvl = float(meta.get("tvlUsd", 0) or getattr(it, "tvl", 0) or 0)
                chain_raw = meta.get("chain") or meta.get("network") or getattr(it, "chain", "")
                symbols = _extract_symbols(meta)
                comp = _stable_composition(symbols).value
                category_val = _infer_category(meta.get("category") or meta.get("type"), name)
                rows.append({
                    "name": name,
                    "apy_pct": apy,
                    "source": getattr(it, "source", "unknown"),
                    "tvl_usd": tvl,
                    "chain": chain_raw,
                    "symbols": " ".join(symbols),
                    "stable": comp,
                    "category": category_val,
                })
            with path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)
        else:
            # JSON
            out_list = []
            for it in filtered:
                meta = getattr(it, "meta", {}) or {}
                out_list.append({
                    "name": getattr(it, "name", "") or meta.get("name", ""),
                    "apy": getattr(it, "apy", None) or meta.get("apyBase") or meta.get("apy"),
                    "source": getattr(it, "source", "unknown"),
                    "meta": meta,
                })
            path.write_text(json.dumps(out_list, indent=2))

        typer.echo(f"✅ Exported {len(filtered)} rows to {path}")
        return

    # default: print table
    _print_table(filtered, debug=debug)


# ---------------- CLI Entry ----------------
app = typer.Typer(help="Yield Flow Engine CLI")

@app.command()
def root(
    top: int = typer.Option(20, help="Number of top results to show"),
    source: str = typer.Option("defillama", help="Data source (defillama, etc.)"),
    category: Optional[str] = typer.Option(None, help="Category filter (e.g., dex, lending, yield)"),
    stablecoin_only: bool = typer.Option(False, help="Shortcut for requiring a stable in the pool"),
    stable_mode: Optional[StableMode] = typer.Option(None, help="Stable mode: all / any / none"),
    chains: Optional[str] = typer.Option(None, help="Comma-separated chain list"),
    min_tvl: float = typer.Option(0.0, help="Minimum TVL in USD"),
    max_apy: float = typer.Option(1000.0, help="Maximum APY percentage"),
    debug: bool = typer.Option(False, help="Show debug info"),
    # export
    out: Optional[str] = typer.Option(None, help="File path to export results"),
    out_format: str = typer.Option("table", help="Output format: table | csv | json"),
):
    _scan_impl(
        top=top,
        source=source,
        category=category,
        stablecoin_only=stablecoin_only,
        stable_mode=stable_mode,
        chains=chains,
        min_tvl=min_tvl,
        max_apy=max_apy,
        debug=debug,
        out_path=out,
        out_format=out_format,
    )

def cli():
    app()

if __name__ == "__main__":
    cli()
