# Repository stabilization baseline

Recorded 2026-08-02 in the current FuruFlow repository. Secret values were not
read from `.env` or `.streamlit/secrets.toml`, and no push, deploy, hosted-service
mutation, login submission, or production message was performed.

## Pre-edit status and baseline

- `git status --short --branch`: `## main...origin/main` with no tracked changes.
- Python: 3.12.10. System pip: 25.2.
- The global `poetry` launcher was broken because it referenced a missing Python
  3.13 Poetry environment. A pinned Poetry 2.2.1 toolchain was therefore installed
  inside ignored `.venv` for lock generation and verification.
- Existing tests: 26 tests passed with
  `python -m unittest discover -s tests -p '*_test.py' -v`.
- `python -m pip check`: passed (`No broken requirements found`).
- Typer was absent (`python -m pip show typer` exited 1).
- CLI smoke `python -m engine.cli --source demo --top 1`: exited 1 with
  `ModuleNotFoundError: No module named 'typer'`.

## Preflight inventory findings

- Dependency files: `pyproject.toml`, `poetry.lock`, and `requirements.txt` only.
- Web entry points: `app.py` and alternate `app_linkdebug.py`.
- CLI entry point: Poetry script `engine = engine.cli:cli`; module entry
  `python -m engine.cli`.
- Existing tests: `tests/auth_service_test.py`, `tests/scoring_test.py`, and
  `tests/supabase_auth_test.py`; no pre-existing pytest/unittest config.
- Repository schedule: `.github/workflows/post-telegram-signals.yml`, four runs
  per hour plus manual dispatch, invoking `post_real_signals.py`.
- Deployment: README-only Streamlit Community Cloud and separate Flask-host
  guidance; no deploy command, Dockerfile, IaC, or release workflow is tracked.
- Side-effect-capable paths: Telegram (`telegram_utils.py`,
  `post_real_signals.py`, `engine/alerts.py`, Telegram PowerShell wrappers),
  Discord (`engine/postprocess.py` and PowerShell scripts), X (`post_to_x.py`),
  Supabase Auth/email (`supabase_auth.py`), Stripe webhook handling
  (`stripe_webhook_example.py`), DeFiLlama reads (`app*.py`, scanner provider),
  and optional workbook/runtime-file writes. No separate SMTP implementation was
  found.

## Dependency decision

Poetry was retained because the repository already had a current Poetry lock and
CLI entry point. Making `pyproject.toml` canonical avoids introducing a second
package manager. The generated `requirements.txt` remains only for hosts that
require it, and CI proves it matches the lock. Missing application/job imports
(`typer`, Flask, Stripe, Plotly, Pillow, and the existing runtime set) now share
one locked environment; quality/security tools live in the dev group.

## Commands run during preflight and implementation

Read-only inventory and characterization:

```powershell
Get-ChildItem -Force
Get-ChildItem -Recurse -Force -File -Filter AGENTS.md
Get-Content FURUFLOW_RECOVERY_AUDIT.md
git status --short --branch
git ls-files
Get-Content pyproject.toml
Get-Content requirements.txt
Get-Content .github/workflows/*.yml
rg -n <entry-point, command, import, external-request, and side-effect patterns> .
git diff --no-index --stat -- app.py app_linkdebug.py
git diff --no-index --unified=2 -- app.py app_linkdebug.py
git diff --no-index --unified=2 -- scan-watch-adaptive.backup.ps1 scan-watch-adaptive.ps1
git diff --no-index --unified=2 -- parse-engine.regex.ps1 parse-engine.fixed.ps1
Get-FileHash -Algorithm SHA256 <legacy parser and scan-watch variants>
```

Baseline execution:

```powershell
python --version
python -m pip --version
poetry --version
python -m unittest discover -s tests -p '*_test.py' -v
python -m pip show typer
python -m engine.cli --source demo --top 1
python -m pip check
```

Dependency toolchain and lock generation:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install poetry==2.2.1 poetry-plugin-export==1.9.0
.venv\Scripts\poetry.exe lock
.venv\Scripts\poetry.exe check --lock
.venv\Scripts\poetry.exe export --only main --format requirements.txt --without-hashes --output requirements.txt
```

The first two pip download attempts were blocked by the workspace network
sandbox; the same commands succeeded after the required network approval.

## Verification commands

Post-change results:

- Locked install: passed; 123 project/runtime/dev packages were installed into
  the clean ignored environment and the project installed successfully.
- Lock validation and runtime export comparison: passed with no diff.
- Existing unittest suite: 26/26 passed.
- Canonical pytest suite: 32/32 passed, including outbound-network containment,
  legacy characterization, and deprecated Streamlit API checks.
- AST parsing: 51 tracked/non-ignored Python files passed.
- Ruff correctness lint: passed.
- Mypy: 7 selected deterministic engine/formatting/guard modules passed.
- CLI demo smoke: passed and returned a local demo row; Typer is installed.
- Streamlit boot smoke: passed against the local health endpoint with production
  credentials removed and external side effects disabled.
- Secret scan: 85 tracked/non-ignored files passed with no credential shapes.
- `pip check`: passed.
- pip-audit: the first scan correctly failed on the retained old lock (76 advisory
  records across 13 packages). `poetry lock --regenerate` selected compatible
  fixed releases; the repeat scan passed with `No known vulnerabilities found`.
  The local repeat emitted cache-deserialization warnings from pip-audit's cache,
  but exited 0; a fresh CI runner will not reuse that local cache.
- `git diff --check`: passed. Line-ending conversion warnings are emitted by the
  local Windows Git configuration but are not whitespace errors.

```powershell
poetry install --with dev --no-interaction
poetry check --lock
poetry export --only main --format requirements.txt --without-hashes --output $env:TEMP\furuflow-requirements.generated.txt
git diff --no-index -- requirements.txt $env:TEMP\furuflow-requirements.generated.txt
poetry run python -m pytest
poetry run python scripts/check_python_syntax.py
poetry run ruff check .
poetry run mypy engine/scanner.py engine/scoring.py engine/tier.py engine/x_format.py signal_formatter.py signal_intelligence.py utils/external_side_effects.py
poetry run engine --source demo --top 1
poetry run python scripts/streamlit_smoke.py
poetry run python scripts/check_tracked_secrets.py
poetry run pip-audit --requirement requirements.txt
git diff --check
git status --short --branch
```

Additional implementation/verification commands run:

```powershell
.venv\Scripts\poetry.exe install --with dev --no-interaction
.venv\Scripts\poetry.exe run pip-audit --requirement requirements.txt
.venv\Scripts\poetry.exe lock --regenerate
.venv\Scripts\poetry.exe export --only main --format requirements.txt --without-hashes --output requirements.txt
.venv\Scripts\poetry.exe run python -m unittest discover -s tests -p '*_test.py'
.venv\Scripts\poetry.exe run python -m pytest
.venv\Scripts\poetry.exe run python scripts/check_python_syntax.py
.venv\Scripts\poetry.exe run ruff check .
.venv\Scripts\poetry.exe run mypy engine/scanner.py engine/scoring.py engine/tier.py engine/x_format.py signal_formatter.py signal_intelligence.py utils/external_side_effects.py
.venv\Scripts\poetry.exe run engine --source demo --top 1
.venv\Scripts\poetry.exe run python scripts/streamlit_smoke.py
.venv\Scripts\poetry.exe run python scripts/check_tracked_secrets.py
.venv\Scripts\poetry.exe run python -m pip check
git diff --check
git diff --stat
git diff --name-status
git status --short --branch
```

## Files changed

- `.github/workflows/ci.yml` — required push/PR baseline workflow.
- `README.md` — canonical install and verification commands.
- `app.py` — mechanical Streamlit width argument migration only.
- `app_linkdebug.py` — same mechanical width migration only.
- `docs/ARCHITECTURE.md` — architecture, execution paths, automation, external
  effects, and archival recommendations.
- `docs/STABILIZATION_BASELINE.md` — this audit trail.
- `engine/postprocess.py` — explicit Discord side-effect guard.
- `engine/scoring.py` — type annotation only; formula and runtime result unchanged.
- `poetry.lock` — regenerated cross-platform exact dependency lock.
- `post_to_x.py` — explicit X side-effect guard.
- `pyproject.toml` — canonical runtime/dev dependency manifest and tool config.
- `requirements.txt` — generated pinned runtime export.
- `scripts/check_python_syntax.py` — tracked/non-ignored AST validation.
- `scripts/check_tracked_secrets.py` — redacted tracked credential-shape scan.
- `scripts/streamlit_smoke.py` — local, credential-cleared boot health check.
- `telegram_utils.py` — explicit Telegram side-effect guard.
- `tests/conftest.py` — production credential clearing and universal socket block.
- `tests/external_side_effects_test.py` — transport containment tests.
- `tests/legacy_characterization_test.py` — duplicate/unique legacy behavior tests.
- `tests/streamlit_api_test.py` — deprecated width API regression test.
- `utils/external_side_effects.py` — shared opt-out guard; disabled by default.

No product behavior, auth semantics, market ranking, navigation, billing behavior,
Telegram production behavior, or database architecture was changed. No legacy
file was removed. No secret or local runtime artifact is present in the diff.
