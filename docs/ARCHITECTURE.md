# FuruFlow architecture and execution paths

This document records the repository as stabilized. It is descriptive; it does
not redefine product, authentication, ranking, billing, navigation, Telegram, or
database behavior.

## Dependency strategy

`pyproject.toml` is the single editable dependency manifest. `poetry.lock` is the
cross-platform resolved lock and is required for every clean developer and CI
installation. `requirements.txt` is a generated, fully pinned runtime export for
Streamlit Community Cloud and other requirements-based hosts. CI regenerates the
export and fails if it differs, so it cannot silently become a second manifest.

Poetry 2.2.1 and `poetry-plugin-export` 1.9.0 are pinned in documentation and CI.
Runtime packages are in the main group; pytest, Ruff, mypy, request stubs, and
pip-audit are in the dev group. The supported interpreter range is Python
3.10-3.12; CI uses Python 3.12.

## Runtime entry points

| Surface | Canonical command or host action | Code path | External or local effects |
|---|---|---|---|
| Streamlit application | `poetry run streamlit run app.py` | `app.py` -> auth/DB/history/engine helpers | DeFiLlama reads during a user session; local SQLite/history/watchlist writes; no message send on boot |
| Alternate debug app | `poetry run streamlit run app_linkdebug.py` | Near-copy of `app.py` | Same broad app effects; retained only for later archival review |
| Scanner CLI | `poetry run engine ...` or `python -m engine.cli ...` | `engine.cli:cli` -> `engine.scanner.rank_top_yields` -> demo or DeFiLlama provider | Demo source is local; DeFiLlama source performs an HTTP GET |
| Telegram signal poster | `python post_real_signals.py` | scanner/history/formatters -> `telegram_utils.send_telegram_message` | DeFiLlama GET, Telegram POST, local history/dedupe writes |
| X poster | `python post_to_x.py` | signal/recap builders -> `post_tweet` | DeFiLlama GET in signal mode; optional X POST; otherwise local outbox write |
| Daily/weekly recap | `python generate_daily_recap.py`; `python generate_weekly_recap.py` | `engine.recap` | Reads tracked/runtime CSV history and prints recap |
| Discord postprocessor | `python -m engine.postprocess ...` | scan-log parser -> `post_to_discord` | Reads/writes run files and can POST a Discord webhook unless `--dry-run` |
| Legacy scan parser | `python scripts/postprocess_scan.py ...` | standalone scan-log parser | Local file/stdout only |
| Workbook ingestion | `python yf_ingest.py ...` | parser -> pandas/openpyxl | Writes the local tracker workbook |
| Signal-card renderer | `python signal_card.py` | Pillow rendering | Writes local PNG output |
| Auto allocator scaffold | `python bots/auto_allocator.py` | Typer scaffold/stub | Local plan/state behavior; explicitly unfinished and not scheduled |
| Stripe webhook example | Flask host imports `stripe_webhook_example:app` | Stripe signature/lifecycle handlers -> local DB | Receives Stripe requests and mutates local SQLite; no tracked deploy command exists |

`telegram_bot.py`, `test_send.py`, and `stripe_stub.py` are import helpers rather
than independently managed services. The repository contains no Dockerfile,
infrastructure-as-code, release workflow, or command that deploys hosted state.
README deployment guidance is narrative: Streamlit Community Cloud for `app.py`
and a separately hosted Flask example.

## Tests and validation

The canonical test command is `poetry run python -m pytest`. Module execution
keeps repository modules ahead of similarly named third-party packages on the
import path. Pytest collects the existing
`unittest.TestCase` suite plus stabilization tests. `tests/conftest.py` clears
known production credential variables, enables the explicit side-effect guard,
and blocks every outbound socket for every test. A test therefore cannot reach
Telegram, Discord, X, Supabase/email, Stripe, DeFiLlama, or any other network
service even if a local shell contains credentials.

CI also runs tracked-file AST parsing, Ruff correctness linting, targeted mypy
checks for deterministic engine/formatting modules, a demo CLI smoke, a headless
Streamlit health smoke, tracked-secret scanning, and pip-audit against the pinned
runtime export.

## Scheduled and wrapper automation

The only repository-managed schedule is
`.github/workflows/post-telegram-signals.yml`, with cron
`7,22,37,52 * * * *` and manual dispatch. It installs `requirements.txt` and
runs `post_real_signals.py`. The audit found this workflow disabled for
inactivity; stabilization does not re-enable or redesign it.

PowerShell wrappers are not repository-managed schedules, but may be invoked by
Windows Task Scheduler or a human:

- `run_furuflow.ps1` and `run_furuflow_signal_buckets.ps1` run strong, moderate,
  and degen Telegram wrappers.
- `run_furuflow_signal_post.ps1`, `run_furuflow_moderate_signals.ps1`, and
  `run_furuflow_degen_signals.ps1` configure different signal thresholds and run
  `post_real_signals.py`.
- `run_furuflow_x_posts.ps1` runs signal and daily X modes; live X posting is
  disabled by its wrapper setting.
- `scan-watch-adaptive.ps1` and its copies run the Poetry CLI, parse output, write
  scan logs, optionally invoke Discord tooling, and ingest into Excel.
- `scripts/scan-daily.ps1` runs the CLI by chain and then
  `engine.postprocess`; `scripts/scan-watch.ps1` adds dedupe, optional Discord,
  and Excel ingestion.
- `scripts/postprocess-and-discord.ps1` and `scripts/post-to-discord.ps1` format
  and send Discord messages.
- `parse-engine*.ps1`, `scripts/parse-engine*.ps1`, and
  `scripts/Get-ScanRows.ps1` are parsing helpers.

## External integration containment

`FURUFLOW_DISABLE_EXTERNAL_SIDE_EFFECTS=true` makes Python Telegram, Discord,
and X send functions fail before constructing or invoking their transport. The
flag defaults to false, preserving production behavior. Tests add a second,
provider-independent socket block. The Streamlit boot smoke strips known
production credential variables, sets the guard, and checks only the local
health endpoint; it does not open an application websocket and therefore does
not execute user-session market or messaging paths.

## Characterization and later archival recommendations

| Files | Characterization | Later recommendation (not performed here) |
|---|---|---|
| `app_linkdebug.py` | Reduced near-copy: it has all top-level functions from `app.py` except `build_signal_card_assets`; it omits the admin shareable signal-card UI and uses a non-pool-specific `drill_watch` key | Archive after its link-debug intent and any deployment references are confirmed obsolete; keep `app.py` as canonical |
| `scan-watch-adaptive.patched.ps1` | Byte-for-byte duplicate of `scan-watch-adaptive.ps1` | Archive the `.patched` copy after scheduler/task references are checked |
| `scan-watch-adaptive.backup.ps1` | Older variant without the current normalization and inline regex fallback | Archive after retaining parser fixtures for the two supported layouts |
| `parse-engine.fixed.ps1`, `scripts/parse-engine.ps1`, `scripts/parse-engine.backup.ps1` | Byte-for-byte duplicates | Keep one canonical parser and archive the other two after wrapper imports are normalized |
| `parse-engine.regex.ps1` | Separate regex-first parser for the two historical table layouts | Preserve its fixtures, then consolidate with the canonical parser |
| `scripts/scan-daily.ps1`, `scripts/scan-watch.ps1`, root scan/watch scripts | Overlapping CLI scan, parse, file-write, Discord, and workbook behavior; the daily script adds per-chain timeout orchestration, while watch scripts add dedupe/continuous behavior | Assign one owner and one documented job per outcome before archiving overlaps |
| Telegram bucket wrappers | Same poster with unique strong/moderate/degen threshold profiles and separate dedupe files | Preserve profiles as configuration if later consolidating wrappers |
| Discord and X paths | Unique channels not used by the active GitHub Telegram workflow | Keep disabled/unowned until an explicit product/operations decision; do not schedule implicitly |
| `bots/auto_allocator.py` | Unique unfinished allocation scaffold | Quarantine or archive in a later task; never activate as part of repository stabilization |

The characterization tests intentionally preserve duplicate relationships and
the currently unique debug-app behavior. No legacy file is removed in this task.
