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

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the app:

```bash
streamlit run app.py
```

## Account and entitlement model

The app uses account-based access instead of the old shared access-code workflow.

Access is granted when any of the following are true:

- user is admin
- `DEV_MODE=true`
- `lifetime_access=True`
- `pro_active=True`

That means real customers should not get stuck in repeat paywall loops. Their entitlement is stored in the database, not only in a temporary session.

## Give yourself permanent access

Copy `.env.example` to `.env`, then set:

```env
ADMIN_EMAILS=yourrealemail@example.com
```

## Stripe / Pro activation notes

Your current Stripe buy link is a monthly Pro offer, so the production webhook should update `pro_active` based on Stripe subscription events.

This build includes:

- `stripe_subscription_id` and `subscription_status` fields in the user database
- a webhook example that handles `checkout.session.completed`
- subscription lifecycle syncing for `customer.subscription.created`, `updated`, and `deleted`
- automatic activation/deactivation of Pro based on Stripe subscription state

## Recommended deployment split

- **Frontend:** Streamlit app on Community Cloud
- **Backend webhook:** a small Flask app on Render, Railway, Fly.io, or another backend host
- **Secrets:** keep Stripe secrets on the backend only

## Important limitation

The current sign-in flow is lightweight email-based app access, not a full password or magic-link auth system. It is good for an MVP gate, but it is not the same as hardened production authentication.

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
