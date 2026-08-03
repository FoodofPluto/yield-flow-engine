# FuruFlow

**Find the best DeFi yield opportunities fast, with signal context and direct pool access.**

FuruFlow is a DeFi yield intelligence app built to help users move from raw pool data to faster decisions. Instead of showing only a scanner table, it layers in ranked opportunities, modeled risk, signal context, direct pool links, persistent watchlists, and recap previews that turn one-off browsing into a usable workflow.

## What the product does

FuruFlow helps users:

- scan live yield opportunities across protocols and chains
- sort pools by APY, TVL, risk, and rank-based signal strength
- open pools directly from the app
- track pools in a persistent watchlist
- review recent signal behavior and recap previews
- use Pro workflows for deeper signal intelligence and advanced filtering

## Product structure

The app is now organized around a clearer user journey:

- **Home** — fastest market read, top opportunities, movers, and a quick intelligence summary
- **Scanner** — broader pool discovery and table workflows
- **Signals** — ranked conviction view with APY change, TVL change, volatility context, and direct links
- **Market Map** — broader market shape by risk, chain, and capital concentration
- **Pool Explorer** — single-pool inspection with charting, risk factors, and watchlist actions
- **Watchlist** — lightweight conviction layer for tracked pools
- **Recaps** — daily/weekly recap previews plus signal history and trend summaries
- **Protocol Dashboard / Strategy Builder / Arbitrage** — deeper Pro-oriented workflows

## Free vs Pro

### Free

Free mode is intentionally useful. It includes:

- scanner access
- market map
- pool explorer
- protocol dashboard
- basic sorting
- watchlist
- recap previews

### Pro

FuruFlow Pro adds the intelligence layer:

- full signals view
- deeper scanner depth
- advanced ranking
- arbitrage workflows
- strategy builder
- stronger recap workflows and future alerts

## Core app files

- `app.py` — Streamlit app UI and product experience
- `auth.py` — lightweight email sign-in session helper
- `db.py` — SQLite user database
- `entitlements.py` — access rules for free/admin/pro accounts
- `history_store.py` — local snapshot history support
- `engine/` — scanner, scoring, recap, link, tier, and performance logic
- `post_real_signals.py` — Telegram-facing signal posting and signal history workflow
- `post_to_x.py` — X post generation for signals and recaps

## Quick start

Python 3.10-3.12 is supported. Poetry 2.2.1 and `poetry.lock` are the canonical
dependency source for the Streamlit app, CLI, tests, scheduled jobs, local
development, and CI. Install the locked environment:

```bash
pipx install poetry==2.2.1
pipx inject poetry poetry-plugin-export==1.9.0
poetry install --with dev
```

`requirements.txt` is a checked-in export of the locked runtime dependencies for
Streamlit Community Cloud and other hosts that install from requirements files.
Do not edit it by hand. Regenerate and verify it after dependency changes:

```bash
poetry lock
poetry export --only main --format requirements.txt --without-hashes --output requirements.txt
poetry check --lock
```

Run the app and network-free CLI smoke command:

```bash
poetry run streamlit run app.py
poetry run engine --source demo --top 1
```

Run the complete local baseline:

```bash
poetry run python -m pytest
poetry run python scripts/check_python_syntax.py
poetry run ruff check .
poetry run mypy engine/scanner.py engine/scoring.py engine/tier.py engine/x_format.py signal_formatter.py signal_intelligence.py utils/external_side_effects.py
poetry run engine --source demo --top 1
poetry run python scripts/streamlit_smoke.py
poetry run python scripts/check_tracked_secrets.py
poetry run pip-audit --requirement requirements.txt
```

Tests and smoke checks set `FURUFLOW_DISABLE_EXTERNAL_SIDE_EFFECTS=true` and do
not use production credentials. See `docs/ARCHITECTURE.md` for execution paths
and `docs/STABILIZATION_BASELINE.md` for the recorded baseline.

## Account and entitlement model

The app uses account-based access instead of the old shared access-code workflow.

Pro access is granted only after the app has a verified identity context and one of the following entitlement flags is true:

- user has an explicit admin DB role
- `lifetime_access=True`
- `pro_active=True`

Typed email sessions are treated as legacy, unverified sessions. They can preserve the free browsing flow, but they do not unlock admin or Pro access. `DEV_MODE=true` is blocked in production.

## Admin access

Admin access must be assigned explicitly in the user database and must be paired with a verified identity. The app no longer promotes users to admin from typed email matching.

## Production auth environment

Production startup fails closed when required auth or billing settings are missing.

Required auth variables:

```env
ENVIRONMENT=production
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-public-anon-key
```

Supabase JWT verification uses the project's JWKS endpoint by default:

```env
SUPABASE_JWKS_URL=https://your-project.supabase.co/auth/v1/.well-known/jwks.json
```

`SUPABASE_JWKS_URL` is optional when `SUPABASE_URL` is set, because the app derives the default JWKS URL from `SUPABASE_URL`. Legacy HS256 projects can still set `SUPABASE_JWT_SECRET`; ECC/P-256 signing-key projects should leave `SUPABASE_JWT_SECRET` unset.

Required billing variables:

```env
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

`DEV_MODE=true` is rejected when `ENVIRONMENT=production`.

## Stripe / Pro activation notes

Your current Stripe buy link is a monthly Pro offer, so the production webhook should update `pro_active` based on Stripe subscription events. Fulfillment should use the internal `user_id` in `client_reference_id` or metadata, not a customer-entered email address.

This build includes:

- `stripe_subscription_id` and `subscription_status` fields in the user database
- a webhook example that handles `checkout.session.completed`
- subscription lifecycle syncing for `customer.subscription.created`, `updated`, and `deleted`
- automatic activation/deactivation of Pro based on Stripe subscription state
- webhook idempotency storage for processed Stripe event IDs

## Recommended deployment split

- **Frontend:** Streamlit app on Community Cloud
- **Backend webhook:** a small Flask app on Render, Railway, Fly.io, or another backend host
- **Secrets:** keep Stripe secrets on the backend only

## Important limitation

The legacy email form is a temporary free-session bridge during migration. Supabase Auth is now the verified identity boundary for privileged access. Legacy sessions cannot unlock admin, lifetime, or Pro entitlements.

## Rollout sequence

1. Add Supabase and Stripe production secrets.
2. Deploy with `ENVIRONMENT=production` and `DEV_MODE=false`.
3. Run the app once to apply additive SQLite migrations.
4. Verify Supabase password login or magic-link flow.
5. Migrate paid users by having them sign in with the same verified Supabase email.
6. Assign admin roles only through explicit DB mutation after verified identity exists.
7. Move Stripe checkout creation to a backend endpoint that writes internal `user_id` into Stripe metadata.

Rollback is safe by reverting the auth migration commit. The DB changes are additive nullable columns and new audit/idempotency tables; no existing users are deleted.

## Signal engine notes

Recent additions include:

- signal history logging
- stronger public score and risk labels
- free vs Pro signal splitting
- Telegram posting support
- X post generation for live signals, daily recaps, and weekly winners
- recap previews and trend snapshots inside the app

## Files to edit first

- `app.py`
- `.env.example`
- `stripe_webhook_example.py`
