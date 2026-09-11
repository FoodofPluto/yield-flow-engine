"""Run pgTAP through Supabase in rollback-only transactions, including pending DDL.

The linked target must be the authorized staging project. No durable fixture or
migration writes occur: an error aborts the transaction; success rolls it back.
This supplements (and never replaces) `supabase db push` deployment.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


def transaction_sql(test: Path, migrations: list[Path]) -> str:
    ddl = "\n".join(
        re.sub(r"(?im)^\s*(?:begin|commit);\s*$", "", path.read_text(encoding="utf-8"))
        for path in migrations
    )
    body = test.read_text(encoding="utf-8")
    if not re.search(r"(?im)^rollback;\s*$", body):
        raise ValueError("Database tests must explicitly roll back")
    body = re.sub(r"(?im)^\s*(?:begin|rollback);\s*$", "", body)
    body = re.sub(r"(?im)^select \* from finish\(\);\s*$", "", body)
    body = re.sub(
        r"(?im)^select (?=(?:ok|is|isnt|throws_ok|lives_ok)\s*\(|case\b)",
        "insert into pg_temp.furuflow_tap_results select ", body,
    )
    return (
        "begin;\nset local lock_timeout = '2s';\nset local statement_timeout = '30s';\n"
        + ddl + "\ncreate temporary table furuflow_tap_results(result text);\n"
        "grant insert, select on furuflow_tap_results to anon, authenticated, service_role;\n" + body
        + "\nselect extensions._get('curr_test') as executed, extensions._get('plan') as planned, "
        "extensions.num_failed() as failed, "
        "(select coalesce(jsonb_agg(result), '[]'::jsonb) from pg_temp.furuflow_tap_results "
        "where result like 'not ok%') as failures, "
        "(select coalesce(jsonb_agg(x), '[]'::jsonb) from extensions.finish() x) as diagnostics;\nrollback;\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linked", action="store_true", required=True)
    parser.add_argument("--migration", type=Path, action="append", default=[])
    parser.add_argument("tests", type=Path, nargs="*")
    args = parser.parse_args()
    cli = Path("node_modules/.bin/supabase.cmd" if os.name == "nt" else "node_modules/.bin/supabase").resolve()
    tests = args.tests or sorted(Path("supabase/tests/database").glob("*.sql"))
    total = 0
    for test in tests:
        with tempfile.TemporaryDirectory(prefix="furuflow-pgtap-") as directory:
            sql = Path(directory) / "rollback_test.sql"
            sql.write_text(transaction_sql(test, args.migration), encoding="utf-8")
            result = subprocess.run(
                [str(cli), "db", "query", "--linked", "--file", str(sql)],
                capture_output=True, text=True, timeout=120, check=False,
            )
        if result.returncode:
            # SQL fixtures are synthetic; never print connection/debug output.
            print(f"FAIL {test.name}: database execution failed")
            print(result.stderr[-1500:])
            print(result.stdout[-2000:])
            return 1
        payload = json.loads(result.stdout[result.stdout.index("{"):])
        row = payload["rows"][0]
        print(f"{test.name}: {json.dumps(row, sort_keys=True)}")
        if not row["executed"] or row["failed"] or row["executed"] != row["planned"]:
            return 1
        total += row["executed"]
    print(f"PASS: {total} database assertions across {len(tests)} rollback-only transactions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
