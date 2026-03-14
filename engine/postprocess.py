# engine/postprocess.py
from __future__ import annotations
import os, re, time, json, argparse
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

try:
    import requests  # poetry will already have this in most setups; if not: poetry add requests
except Exception as e:
    raise SystemExit("Missing dependency 'requests'. Run: poetry add requests") from e


ROW_SPLIT = re.compile(r"\s{2,}")  # 2+ spaces as column delimiter


def find_latest_scan_log(runs_dir: Path) -> Optional[Path]:
    logs = sorted(runs_dir.glob("*-scan.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    return logs[0] if logs else None


def parse_table_from_log(text: str) -> List[Dict[str, Any]]:
    """
    Parse the printed table section from engine stdout that looks like:

    Name ... APY% ... TVL (USD) ... Chain ... Symbols ... Stable ... Category
    --------------------------------------------------------------------------
    uniswap-v2  7,791.56  defillama  134,339  Base  TRUMP WETH  none  ...

    We split by 2+ spaces; unknown/missing columns are tolerated.
    """
    lines = [ln.rstrip() for ln in text.splitlines()]
    rows: List[Dict[str, Any]] = []

    # Find header line
    hdr_idx = None
    for i, ln in enumerate(lines):
        if ln.strip().startswith("Name") and "APY%" in ln and "TVL" in ln:
            hdr_idx = i
            break
    if hdr_idx is None:
        return rows

    # Skip the dashed line(s)
    i = hdr_idx + 1
    while i < len(lines) and set(lines[i].strip()) <= {"-", " "}:
        i += 1

    # Consume data lines until blank or log noise
    while i < len(lines):
        ln = lines[i].strip()
        i += 1
        if not ln:
            break
        if ln.startswith("[") or ln.lower().startswith("no results"):
            break

        # Split columns
        cols = ROW_SPLIT.split(ln)
        if len(cols) < 4:
            continue  # too short

        # Map columns defensively (engine sometimes prints Stable/Category, sometimes not)
        # Expected order from your samples:
        # Name | APY% | Source | TVL (USD) | Chain | Symbols | [Stable] | [Category]
        def at(idx, default=""):
            return cols[idx] if idx < len(cols) else default

        name = at(0).strip()
        apy_raw = at(1).replace(",", "").replace("%", "").strip()
        src = at(2).strip()
        tvl_raw = at(3).replace(",", "").strip()
        chain = at(4).strip() if len(cols) >= 5 else ""
        symbols = at(5).strip() if len(cols) >= 6 else ""
        stable = at(6).strip() if len(cols) >= 7 else ""
        category = at(7).strip() if len(cols) >= 8 else ""

        # Parse numbers
        def fnum(s: str) -> Optional[float]:
            try:
                return float(s)
            except Exception:
                return None

        apy = fnum(apy_raw)
        tvl = fnum(tvl_raw)

        rows.append({
            "name": name,
            "apy": apy,
            "source": src,
            "tvl_usd": tvl,
            "chain": chain,
            "symbols": symbols,
            "stable": stable,
            "category": category,
            "raw": ln,
        })
    return rows


def format_for_discord(rows: List[Dict[str, Any]], title: str, limit: int = 10) -> Tuple[str, List[Dict[str, Any]]]:
    rows = [r for r in rows if r.get("apy") is not None]  # keep sane
    rows.sort(key=lambda r: r["apy"], reverse=True)
    rows = rows[:limit]

    # Build a compact monospaced list (Discord supports Markdown code blocks)
    lines = []
    hdr = f"{'APY%':>8}  {'TVL':>10}  {'Chain':<10}  {'Pair':<18}  {'Name'}"
    lines.append(hdr)
    lines.append("-" * len(hdr))
    for r in rows:
        apy = f"{r['apy']:.2f}" if r["apy"] is not None else "?"
        tvl = f"${int(r['tvl_usd']):,}" if isinstance(r["tvl_usd"], (int, float)) and r["tvl_usd"] is not None else "?"
        chain = (r["chain"] or "")[:10]
        pair = (r["symbols"] or "")[:18]
        nm = r["name"]
        lines.append(f"{apy:>8}  {tvl:>10}  {chain:<10}  {pair:<18}  {nm}")

    desc = "```\n" + "\n".join(lines) + "\n```"
    content = f"**{title}**\n{desc}"
    return content, rows


def post_to_discord(webhook_url: str, content: str, *, username="Yield Flow Bot", retries=3) -> None:
    payload = {"content": content, "username": username}
    backoff = 1.0
    for attempt in range(1, retries + 1):
        resp = requests.post(webhook_url, json=payload, timeout=30)
        if resp.status_code in (200, 204, 201):
            return
        if resp.status_code == 429:
            try:
                wait = float(resp.json().get("retry_after", backoff))
            except Exception:
                wait = backoff
            time.sleep(wait)
            backoff *= 2
            continue
        # other transient
        if 500 <= resp.status_code < 600:
            time.sleep(backoff)
            backoff *= 2
            continue
        raise SystemExit(f"Discord webhook error {resp.status_code}: {resp.text}")


def save_json_snapshot(rows: List[Dict[str, Any]], out: Path) -> None:
    out.write_text(json.dumps({"generated_at": datetime.utcnow().isoformat() + "Z", "items": rows}, indent=2))


def main():
    p = argparse.ArgumentParser(description="Postprocess latest scan log and send summary to Discord.")
    p.add_argument("--runs", default="runs", help="Directory with *-scan.log files (default: runs)")
    p.add_argument("--webhook", default=os.environ.get("DISCORD_WEBHOOK_URL", ""), help="Discord webhook URL (or set DISCORD_WEBHOOK_URL)")
    p.add_argument("--top", type=int, default=10, help="How many rows to include (default: 10)")
    p.add_argument("--min-tvl", type=float, default=None, help="Optional filter for minimum TVL in USD")
    p.add_argument("--max-apy", type=float, default=None, help="Optional filter for maximum APY%%")
    p.add_argument("--chains", default="", help="Optional comma list of chains to include (e.g. 'ethereum,base')")
    p.add_argument("--dry-run", action="store_true", help="Parse and print but do not post to Discord")
    p.add_argument("--save-json", default="", help="Optional file path to save JSON snapshot (e.g. runs/latest-scan.json)")
    args = p.parse_args()

    runs_dir = Path(args.runs)
    log_path = find_latest_scan_log(runs_dir)
    if not log_path:
        raise SystemExit(f"No scan logs found in {runs_dir} (looking for *-scan.log).")

    text = log_path.read_text(encoding="utf-8", errors="ignore")
    rows = parse_table_from_log(text)

    if args.min_tvl is not None:
        rows = [r for r in rows if isinstance(r.get("tvl_usd"), (int, float)) and (r["tvl_usd"] or 0) >= args.min_tvl]
    if args.max_apy is not None:
        rows = [r for r in rows if r.get("apy") is not None and r["apy"] <= args.max_apy]
    if args.chains:
        allowed = {c.strip().lower() for c in args.chains.split(",") if c.strip()}
        rows = [r for r in rows if (r.get("chain") or "").lower() in allowed]

    title = f"Yield Flow — Top {min(args.top, len(rows))} from {log_path.name}"
    content, rows_top = format_for_discord(rows, title, limit=args.top)

    if args.save_json:
        save_json_snapshot(rows_top, Path(args.save_json))

    if args.dry_run:
        print(content)
        return

    webhook = args.webhook.strip()
    if not webhook:
        raise SystemExit("No Discord webhook URL. Pass --webhook or set DISCORD_WEBHOOK_URL env var.")
    post_to_discord(webhook, content)
    print(f"Posted {len(rows_top)} rows from {log_path.name} to Discord.")


if __name__ == "__main__":
    main()
