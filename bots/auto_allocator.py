"""
Auto Allocator (Path B) — scaffold
Reads the latest Yield Flow scan log, selects the top pool that passed your filters,
and prepares executable "intents" (enter/exit/claim) with a Web3 client.

Safe defaults:
- DRY_RUN = True (prints tx plans but does not send)
- No private keys hardcoded; uses ENV vars
- Protocol actions are stubs you’ll implement incrementally

Dependencies (add to pyproject.toml):
  web3 = "^6.20.0"
  python-dotenv = "^1.0.1"
  typer = "^0.12.5"
"""

from __future__ import annotations

import os
import re
import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

import typer

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass

# -----------------------------
# Config
# -----------------------------

RUNS_DIR = Path("runs")
STATE_FILE = RUNS_DIR / "positions.json"

# Environment (set these in .env)
RPC_ARBITRUM = os.getenv("RPC_ARBITRUM", "")  # e.g., https://arb-mainnet.g.alchemy.com/v2/KEY
RPC_BASE = os.getenv("RPC_BASE", "")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")  # DO NOT COMMIT THIS
WALLET_ADDR = os.getenv("WALLET_ADDR")  # 0x...

# Safety: start in dry-run mode
DRY_RUN = os.getenv("DRY_RUN", "true").lower() in ("1", "true", "yes")

app = typer.Typer(help="Yield Flow — Auto Allocator (Path B)")

# -----------------------------
# Models
# -----------------------------

@dataclass
class PoolRow:
    name: str
    apy_pct: float
    source: str
    tvl_usd: float
    chain: str
    symbols: str
    stable: str
    category: str

@dataclass
class PositionState:
    active_pool: Optional[PoolRow] = None
    last_action: Optional[str] = None
    last_update: Optional[str] = None  # ISO timestamp
    chain: Optional[str] = None
    notes: Optional[str] = None

# -----------------------------
# Utilities
# -----------------------------

def _load_state() -> PositionState:
    if STATE_FILE.exists():
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        row = data.get("active_pool")
        active_pool = PoolRow(**row) if row else None
        return PositionState(
            active_pool=active_pool,
            last_action=data.get("last_action"),
            last_update=data.get("last_update"),
            chain=data.get("chain"),
            notes=data.get("notes"),
        )
    return PositionState()

def _save_state(state: PositionState) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(state)
    STATE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

def _latest_scan_log() -> Path:
    logs = sorted(RUNS_DIR.glob("*-scan.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not logs:
        raise FileNotFoundError("No scan logs found in ./runs")
    return logs[0]

def _parse_table_rows(text: str) -> List[PoolRow]:
    """
    Expects the standard table that starts with the header:
    Name  APY%  Source  TVL (USD)  Chain  Symbols  Stable  Category
    We ignore [skip ...] lines.
    """
    rows: List[PoolRow] = []

    # Extract lines that look like table rows (have at least 6 columns separated by 2+ spaces)
    in_table = False
    for line in text.splitlines():
        if line.strip().startswith("Name") and "APY%" in line and "Category" in line:
            in_table = True
            continue
        if not in_table:
            continue
        if line.strip().startswith("---") or not line.strip():
            # table divider or blank line — continue but keep in_table True
            continue

        # Skip diagnostics
        if line.strip().startswith("[skip"):
            continue

        parts = [p.strip() for p in re.split(r"\s{2,}", line) if p.strip()]
        if len(parts) < 7:
            # Some logs may have missing 'Stable' -> fill with "any"
            # Try to be forgiving; you can tighten later
            pass

        try:
            # Heuristic mapping by header order:
            # Name | APY% | Source | TVL (USD) | Chain | Symbols | Stable | Category
            name = parts[0]
            apy_pct = float(parts[1].replace(",", "").replace("%", ""))  # "453.62"
            source = parts[2]
            tvl_usd = float(parts[3].replace(",", ""))
            chain = parts[4]
            symbols = parts[5] if len(parts) > 5 else ""
            stable = parts[6] if len(parts) > 6 else "any"
            category = parts[7] if len(parts) > 7 else ""
            rows.append(
                PoolRow(
                    name=name,
                    apy_pct=apy_pct,
                    source=source,
                    tvl_usd=tvl_usd,
                    chain=chain,
                    symbols=symbols,
                    stable=stable,
                    category=category,
                )
            )
        except Exception:
            # Best-effort parsing; skip malformed lines
            continue

    return rows

def _pick_top_pool(rows: List[PoolRow]) -> Optional[PoolRow]:
    """
    Simple policy: highest APY with tvl_usd > 20k and category == 'dex'
    You’ll adapt this to your real policy (IL-aware, symbol allowlist, etc.)
    """
    candidates = [r for r in rows if r.tvl_usd >= 20_000 and r.category.lower() == "dex"]
    if not candidates:
        return None
    return sorted(candidates, key=lambda r: r.apy_pct, reverse=True)[0]

# -----------------------------
# Web3 Client (stubbed)
# -----------------------------

class W3Client:
    def __init__(self, chain: str):
        self.chain = chain.lower()
        self.provider_url = self._rpc_for_chain(self.chain)
        self._w3 = None
        self._acct = None

    def _rpc_for_chain(self, chain: str) -> str:
        if chain == "arbitrum":
            return RPC_ARBITRUM or ""
        if chain == "base":
            return RPC_BASE or ""
        # Add more chains as needed
        return ""

    def connect(self):
        from web3 import Web3  # lazy import
        if not self.provider_url:
            raise RuntimeError(f"No RPC URL configured for chain: {self.chain}")

        self._w3 = Web3(Web3.HTTPProvider(self.provider_url))
        if not self._w3.is_connected():
            raise RuntimeError(f"Failed to connect to {self.chain} RPC")

        if PRIVATE_KEY:
            self._acct = self._w3.eth.account.from_key(PRIVATE_KEY)
        elif not DRY_RUN:
            raise RuntimeError("PRIVATE_KEY missing and DRY_RUN is False")
        return self

    @property
    def w3(self):
        if self._w3 is None:
            raise RuntimeError("Call connect() first")
        return self._w3

    @property
    def account(self):
        return self._acct  # may be None in DRY_RUN

# -----------------------------
# Protocol registry (stubs)
# -----------------------------

class ProtocolHandler:
    """Base class; implement for each protocol you support."""
    def __init__(self, client: W3Client, pool: PoolRow):
        self.client = client
        self.pool = pool

    def approve(self, token_addr: str, spender: str, amount_wei: int) -> Dict[str, Any]:
        # Implement ERC20 approve ABI call
        return {"action": "approve", "token": token_addr, "spender": spender, "amount_wei": amount_wei}

    def deposit(self, amount_wei: int) -> Dict[str, Any]:
        raise NotImplementedError

    def withdraw(self, amount_wei: Optional[int] = None) -> Dict[str, Any]:
        raise NotImplementedError

    def claim(self) -> Dict[str, Any]:
        raise NotImplementedError

class RamsesCLHandler(ProtocolHandler):
    """
    Placeholder for Ramses CL pools on Arbitrum.
    TODO:
      - Load pool/position manager ABIs
      - Deposit (mint) with price range or join existing LP via zap
      - Track LP token address and rewards
    """
    def deposit(self, amount_wei: int) -> Dict[str, Any]:
        return {"action": "deposit", "protocol": "ramses-cl", "amount_wei": amount_wei}

    def withdraw(self, amount_wei: Optional[int] = None) -> Dict[str, Any]:
        return {"action": "withdraw", "protocol": "ramses-cl", "amount_wei": amount_wei}

    def claim(self) -> Dict[str, Any]:
        return {"action": "claim", "protocol": "ramses-cl"}

PROTOCOLS: Dict[str, Any] = {
    "ramses-cl": RamsesCLHandler,
    # "balancer-v2": BalancerHandler, etc.
}

def get_handler(client: W3Client, pool: PoolRow) -> ProtocolHandler:
    key = pool.name.lower().strip()
    cls = PROTOCOLS.get(key)
    if not cls:
        raise NotImplementedError(f"No handler registered for protocol '{pool.name}'")
    return cls(client, pool)

# -----------------------------
# Core flows
# -----------------------------

def select_best_pool() -> PoolRow:
    log = _latest_scan_log()
    text = log.read_text(encoding="utf-8", errors="replace")
    rows = _parse_table_rows(text)
    if not rows:
        raise RuntimeError("No parsed rows found in latest scan log table.")
    top = _pick_top_pool(rows)
    if not top:
        raise RuntimeError("No candidate met selection policy (e.g., tvl>=20k & category='dex').")
    return top

def rotate(capital_usd: float = 200.0):
    """
    Rotation policy:
      - If active pool is None -> Enter best pool
      - If active pool != best pool -> Exit current, Enter best
      - Else -> Do nothing
    """
    state = _load_state()
    best = select_best_pool()

    # Choose chain RPC based on best.chain
    client = W3Client(best.chain).connect()

    # Pick handler by protocol name
    handler = get_handler(client, best)

    plan: List[Dict[str, Any]] = []
    now = datetime.utcnow().isoformat()

    if state.active_pool and state.active_pool.name.lower() != best.name.lower():
        # Exit current
        plan.append({"step": "exit_current", "pool": state.active_pool.name, "chain": state.active_pool.chain})
        plan.append(handler.withdraw())  # You could pass amount_wei here
        plan.append(handler.claim())

    if not state.active_pool or state.active_pool.name.lower() != best.name.lower():
        # Enter new
        amount_wei = _usd_to_wei_guess(capital_usd, symbol_guess=best.symbols)
        plan.append({"step": "enter_new", "pool": best.name, "chain": best.chain, "capital_usd": capital_usd})
        plan.append(handler.deposit(amount_wei))

    if DRY_RUN:
        typer.echo("\n[DRY RUN] Rotation Plan:")
        typer.echo(json.dumps(plan, indent=2))
    else:
        # TODO: execute built txs (sign + send), wait for receipts
        pass

    # Update state
    state.active_pool = best
    state.last_action = "rotate"
    state.last_update = now
    state.chain = best.chain
    state.notes = f"dry_run={DRY_RUN}"
    _save_state(state)

    typer.echo(f"\nSaved state → {STATE_FILE}")
    typer.echo(f"Active pool: {best.name} on {best.chain} | APY {best.apy_pct:.2f}% | TVL ${best.tvl_usd:,.0f}")

def _usd_to_wei_guess(capital_usd: float, symbol_guess: str) -> int:
    """
    SUPER rough placeholder: assumes 1 token ≈ $1 (stable) for demo purposes.
    Replace with on-chain price (Uniswap/1inch) before going live.
    """
    _ = symbol_guess  # unused for now
    return int(capital_usd * (10**18))

# -----------------------------
# CLI
# -----------------------------

@app.command()
def status():
    """Show current position state and most recent candidate."""
    state = _load_state()
    typer.echo(f"State file: {STATE_FILE}")
    typer.echo(json.dumps(asdict(state), indent=2, default=str))
    try:
        top = select_best_pool()
        typer.echo("\nLatest candidate:")
        typer.echo(json.dumps(asdict(top), indent=2))
    except Exception as e:
        typer.echo(f"\nCandidate error: {e}")

@app.command()
def pick():
    """Print the currently selected best pool from the latest scan log."""
    top = select_best_pool()
    typer.echo(json.dumps(asdict(top), indent=2))

@app.command()
def run(capital: float = typer.Option(200.0, help="USD to allocate on entry (rough, see _usd_to_wei_guess)")):
    """Rotate into the latest best pool (DRY_RUN by default)."""
    rotate(capital_usd=capital)

if __name__ == "__main__":
    app()
