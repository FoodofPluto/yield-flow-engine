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

The app is organized around a research journey:

- **Home** — fastest market read, top opportunities, movers, and a quick intelligence summary
- **Discover** — deterministic search/filtering, opportunity triage, nested signals, and bounded comparison
- **Pool Detail** — contextual identity, reported yield components, liquidity, risk factors, and provenance
- **Research** — market-map and protocol-depth views
- **Watchlists / Activity & Digests** — authenticated attention and history surfaces
- **Pro Tools** — Strategy Builder and Yield Spreads (reported differences, not guaranteed arbitrage)
- **Methodology & Data Status** — source, freshness, fallback, and scoring conventions

See [`docs/MARKET_RESEARCH.md`](docs/MARKET_RESEARCH.md) for the Discover state
model, Compare, provenance/freshness, explainable yield and risk, degraded data,
and responsive/accessibility limitations.

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
poetry run mypy --follow-imports=skip supabase_client.py auth_session.py furuflow_auth.py auth_service.py auth.py scripts/check_supabase_auth_health.py
poetry run engine --source demo --top 1
poetry run python scripts/streamlit_smoke.py
poetry run python scripts/check_tracked_secrets.py
poetry run pip-audit --requirement requirements.txt
```

Tests and smoke checks set `FURUFLOW_DISABLE_EXTERNAL_SIDE_EFFECTS=true` and do
not use production credentials. See `docs/ARCHITECTURE.md` for execution paths
and `docs/STABILIZATION_BASELINE.md` for the recorded baseline.

The responsive application sitemap, shell/component boundary, contextual Pool
Detail model, navigation authorization rules, and accessibility validation are
documented in `docs/UI_SHELL.md`.

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

Preview/staging and production startup fail closed when auth configuration is
missing, malformed, placeholder-shaped, or unsafe. `SUPABASE_URL` must be the
project root; `/rest/v1`, `/auth/v1`, and every other subpath are rejected.

Required auth variables:

```env
ENVIRONMENT=production
DEV_MODE=false
SUPABASE_URL=https://PROJECT_REFERENCE.supabase.co
SUPABASE_ANON_KEY=REPLACE_WITH_PUBLISHABLE_OR_ANON_KEY
SUPABASE_REDIRECT_URL_DEVELOPMENT=http://localhost:8501
SUPABASE_REDIRECT_URL_PREVIEW=https://PREVIEW_HOST/auth/callback
SUPABASE_REDIRECT_URL_PRODUCTION=https://PRODUCTION_HOST/auth/callback
```

The active redirect variable is selected by `ENVIRONMENT`; `staging` uses the
preview variable. Supabase dashboard redirect allowlists must contain each
deployed callback base/path; production should use an exact path, while preview
host patterns may use Supabase-supported wildcards as documented in
`docs/AUTHENTICATION.md`.

The JWKS endpoint is derived from the validated project root. An optional exact
override may be supplied:

```env
SUPABASE_JWKS_URL=https://PROJECT_REFERENCE.supabase.co/auth/v1/.well-known/jwks.json
```

Run the deploy diagnostic without printing credentials:

```bash
poetry run python scripts/check_supabase_auth_health.py
```

It validates configuration, DNS, Auth health, JWKS availability, and project
URL/key coherence. Identity and email verification are resolved through
Supabase Auth's authoritative user endpoint, not mutable user metadata.

Required billing variables:

```env
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

`DEV_MODE=true`, loopback HTTP redirects, and custom ports are rejected in
preview/staging/production.

## Stripe / Pro activation notes

Your current Stripe buy link is a monthly Pro offer, so the production webhook should update `pro_active` based on Stripe subscription events. Fulfillment should use the internal `user_id` in `client_reference_id` or metadata, not a customer-entered email address.

This build includes:

- migration-managed Supabase `subscriptions`, `entitlements`, and `webhook_events`
- a service-role-only webhook backend that handles `checkout.session.completed`
- subscription lifecycle syncing for `customer.subscription.created`, `updated`, and `deleted`
- automatic activation/deactivation of Pro based on Stripe subscription state
- durable webhook processing/failure/idempotency state

## Recommended deployment split

- **Frontend:** Streamlit app on Community Cloud
- **Backend webhook:** a small Flask app on Render, Railway, Fly.io, or another backend host
- **Secrets:** keep Stripe secrets on the backend only

## Account control plane

Supabase Auth UUIDs are the identity boundary. Supabase Postgres profiles,
entitlements, subscriptions, audits, webhook state, and sessions are the
production authority; SQLite cannot grant access. Browser refresh is handled by
the separate encrypted session broker and opaque HttpOnly cookie. See
`docs/ACCOUNT_CONTROL_PLANE.md` for RLS, bootstrap, demo, migration, rollback,
and deployment procedures.

## Rollout sequence

1. Add the exact Supabase project root, matching publishable key, and active
   redirect setting without changing any local placeholder to a guessed value.
2. Allowlist development, preview/staging, and production callback variants in
   the Supabase dashboard.
3. Run `scripts/check_supabase_auth_health.py` in the deployed environment.
4. Verify signup, email confirmation, password and magic-link sign-in, refresh,
   global logout, and password recovery using staging accounts.
5. Apply the account migration, deploy the same-origin session broker route,
   and verify RLS using two staging users.
6. Bootstrap the first admin by verified UUID from a trusted shell.
7. Deploy production with `ENVIRONMENT=production` and `DEV_MODE=false`.
8. Configure Stripe checkout to write the verified UUID into metadata.

Use the reviewed migration/rollback artifacts described in
`docs/ACCOUNT_CONTROL_PLANE.md`; reverting code alone is not a database rollback.

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
