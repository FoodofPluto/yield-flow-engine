# scripts/postprocess_scan.py
from __future__ import annotations
import argparse, re, sys
from datetime import datetime
from pathlib import Path

ROW_SPLIT = re.compile(r"\s{2,}")  # split on 2+ spaces

def parse_table(lines):
    """
    Parse the main table from the scan log.
    Returns list of dict rows.
    """
    rows = []
    header_idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith("Name") and "APY%" in line and "TVL" in line:
            header_idx = i
            break

    if header_idx is None:
        return rows

    header = ROW_SPLIT.split(lines[header_idx].rstrip())
    # find where the dashed separator is (usually header_idx+1)
    sep_idx = header_idx + 1 if header_idx + 1 < len(lines) else None
    # start of data usually header_idx+2
    data_start = header_idx + 2

    for line in lines[data_start:]:
        s = line.rstrip("\n")
        if not s or set(s.strip()) == {"-"}:  # skip blank or dashed separators
            continue
        parts = ROW_SPLIT.split(s)
        if len(parts) < len(header):
            # sometimes trailing blanks; skip short lines
            continue
        row = dict(zip(header, parts))
        rows.append(row)
    return rows

def to_markdown(rows, top=10):
    if not rows:
        return "_No rows parsed from log._"
    header = ["Name","APY%","TVL (USD)","Chain","Symbols","Stable","Category","Source"]
    # keep any header found but normalize ordering where possible
    cols = [c for c in header if c in rows[0]] + [c for c in rows[0].keys() if c not in header]
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"]*len(cols)) + "|"]
    for r in rows[:top]:
        out.append("| " + " | ".join(r.get(c, "") for c in cols) + " |")
    return "\n".join(out)

def to_discord_text(rows, top=5, title="Yield Flow — Top picks"):
    if not rows:
        return f"{title}\n(no rows parsed)"
    lines = [title]
    lines.append(f"{'APY%':>8}   {'TVL':>10}   {'Chain':<9}   {'Name'}")
    lines.append("-"*60)
    for r in rows[:top]:
        apy = r.get("APY%","")
        tvl = r.get("TVL (USD)","")
        chain = r.get("Chain","")
        name = r.get("Name","")
        lines.append(f"{apy:>8}   {tvl:>10}   {chain:<9}   {name}")
    return "\n".join(lines)

def load_latest_log(runs_dir: Path) -> Path|None:
    logs = sorted(runs_dir.glob("*-scan.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    return logs[0] if logs else None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", help="Path to a scan log file. If omitted, use latest in runs/")
    ap.add_argument("--runs-dir", default="runs", help="Directory containing scan logs")
    ap.add_argument("--out-dir", default="runs", help="Directory for generated summaries")
    ap.add_argument("--top", type=int, default=10, help="How many rows to include")
    ap.add_argument("--discord-out", default=None, help="Write a plain-text file formatted for Discord here")
    args = ap.parse_args()

    runs_dir = Path(args.runs_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    log_path = Path(args.log) if args.log else load_latest_log(runs_dir)
    if not log_path or not log_path.exists():
        print("No log found.", file=sys.stderr)
        return 2

    lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    rows = parse_table(lines)

    # filenames based on log name
    stamp = log_path.stem.replace("-scan","")
    md_path = out_dir / f"{stamp}-report.md"
    txt_path = out_dir / f"{stamp}-discord.txt"

    md = f"# Yield Flow — Top {args.top}\n\nGenerated from `{log_path.name}` on {datetime.now().isoformat()}\n\n"
    md += to_markdown(rows, top=args.top)
    md_path.write_text(md, encoding="utf-8")

    discord_text = to_discord_text(rows, top=min(args.top,5), title=f"Yield Flow — Top {min(args.top,5)} from {log_path.name}")
    (Path(args.discord_out) if args.discord_out else txt_path).write_text(discord_text, encoding="utf-8")

    print(f"Wrote {md_path}")
    print(f"Wrote {args.discord_out or txt_path}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
