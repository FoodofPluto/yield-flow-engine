# Closed-beta release candidate operations

This checkpoint hardens the Prompt 17 product without changing its financial,
evidence, confidence, risk, entitlement, or workflow models. Public discovery
may remain available. Account-bearing workflows require both a verified account
and closed-beta participation; paid capabilities still require the independent
server-authoritative entitlement.

## Pre-implementation audit

- `app.py` is the Streamlit entry point, `engine.cli` is the CLI, the private
  `session_broker.py` sidecar owns durable browser sessions and billing, and
  `telegram_worker.py` runs durable notification evaluation/delivery.
- Render exposes Nginx only. `/healthz` is a minimal liveness response and
  `/_stcore/health` preserves Streamlit's health contract. Private session APIs
  are blocked externally; activation and unsupported auth paths retain their
  no-log/no-store behavior.
- Market snapshots already use one 15-minute cache entry per process. Pool
  charts use a bounded one-hour cache, signal snapshots use a bounded 30-minute
  cache over 16 pools and six workers, and all provider calls have finite
  timeouts. No unbounded retry loop was found.
- Market failures were previously collapsed into unavailable, including HTTP
  429. Beta identity was limited to Account diagnostics, first-session guidance
  did not exist, Supabase account creation was open, and there was no beta
  participant gate.
- Watchlists and Alerts are RLS-owned by the verified Supabase user. A missing
  provider row never deletes a saved pool. Research excludes missing dimensions
  rather than zero-filling them. Signals retain missing strength/history as
  unavailable and Plotly receives only finite observed values.
- Auth callback cleanup, single-use activation, strict activation parameters,
  global logout, billing failure separation, Telegram prerequisites, bounded
  delivery retries, and worker heartbeat state were already suitable and were
  not redesigned.

## Beta access model

Set `FURUFLOW_BETA_ENABLED=true` and provide a comma-separated list of canonical
Supabase user UUIDs in `FURUFLOW_BETA_ALLOWED_USER_IDS`. Values that are not UUIDs
are rejected. An enabled beta with an empty/invalid list fails closed at Render
supervisor startup. Verified, server-authoritative admins remain admitted through
the existing admin boundary; merely claiming an admin flag without authoritative
account state does not work.

Beta participation does not grant Watchlists, Alerts, Research modeling, Pro
Tools, export, or any other paid capability. Free participants remain Free.
Current accepted Free/Pro/Watchlist/Alerts user UUIDs must be placed in the list
before candidate deployment. Their entitlement rows must not be changed. The
accepted Admin identity is admitted through the existing authoritative admin
record but may also be listed explicitly for operational clarity.

`FURUFLOW_BETA_ALLOW_SIGNUP` defaults to false while beta mode is enabled, which
hides open account creation while preserving sign-in, magic-link sign-in, and
password recovery for invited identities. Supabase invitation/account provisioning
remains an operator action. Rejected users see generic guidance without email or
participant-list disclosure.

## Release configuration

| Setting | Default | Purpose |
| --- | --- | --- |
| `FURUFLOW_BETA_ENABLED` | `false` | Enables the participant gate and beta UI. |
| `FURUFLOW_BETA_ALLOWED_USER_IDS` | empty | Comma-separated verified Supabase UUIDs; required when enabled. |
| `FURUFLOW_BETA_ALLOW_SIGNUP` | `false` | Explicitly permits account creation if an invitation workflow needs it. |
| `FURUFLOW_BETA_LABEL` | `Closed Beta` | Safe, bounded release label. |
| `FURUFLOW_SUPPORT_URL` | empty | Approved absolute HTTPS feedback destination. |
| `FURUFLOW_MAINTENANCE_MESSAGE` | empty | Optional bounded user-facing maintenance copy. |
| `FURUFLOW_BUILD_ID` | empty | Optional non-sensitive build identifier. |

The maintenance message stops normal Streamlit workflows before provider calls;
Nginx health routes remain available. It does not bypass authentication or expose
configuration. Deployment controls remain the primary rollback mechanism.

## Failure and recovery semantics

The shared taxonomy distinguishes no data, insufficient evidence, stale data,
provider unavailable, temporarily busy/rate limited, authentication required,
authorization required, and server configuration unavailable. Every category
includes a bounded next action. Provider errors are reduced to safe categories;
exception strings, response bodies, URLs, query strings, and credentials are not
rendered.

HTTP 429 stops the market refresh immediately rather than trying the secondary
endpoint, preventing request amplification. Other requests remain bounded by the
existing timeout and at most the two established provider endpoints. Cache and
retrieval timestamps are unchanged. Live provider history, stored FuruFlow
history, current market observations, stale observations, and unavailable data
remain explicitly distinguishable; stored fallback is never labelled current.

## Feedback, privacy, and support

The sidebar and Account page use the configured HTTPS support destination. A
useful data report includes the page, approximate timestamp, protocol/pool,
canonical pool UUID, visible freshness, attempted action, and what appeared
wrong. Users are told never to submit passwords, magic links, access/refresh
tokens, session cookies, wallet seed phrases, or private keys.

Watchlists and Alerts are private to the verified account. Telegram linkage is
account-specific and raw routing identifiers remain hidden. FuruFlow does not
need wallet secrets for the current analytical workflows.

## Domain and environment move checklist

No DNS or hosting change is part of local hardening. Before moving from the
staging hostname to a dedicated beta hostname, update and verify:

1. Render's external service origin and health check.
2. `SUPABASE_REDIRECT_URL_PREVIEW` and `SUPABASE_REDIRECT_URL_PRODUCTION`, plus
   the corresponding Supabase allowed redirect/site origins.
3. `FURUFLOW_SESSION_BROKER_PUBLIC_ORIGIN`; it must exactly match the HTTPS
   public origin used for opaque-cookie activation and billing same-origin checks.
4. Stripe checkout success/cancel and portal return URLs derived from that origin,
   and the Stripe webhook destination for `/stripe/webhook` if the hostname moves.
5. Any Telegram onboarding/support copy that links to the application (delivery
   routing itself is account- and environment-scoped rather than hostname-based).
6. The approved `FURUFLOW_SUPPORT_URL` and any external form origin policy.
7. Supabase project/environment selection, non-production Stripe test keys, the
   staging worker's `ENVIRONMENT`, and the beta UUID list before inviting users.

Render already rejects live Stripe secrets outside production. Broker-only
Supabase service-role, Stripe, and session-encryption values are stripped from
the Streamlit child. The worker has separate secrets and a staging environment;
system Telegram delivery is disabled by default.

## Performance decision

No financial-data transformation or page architecture was changed for speed.
The audit found bounded result presentation (`POOL_LIMIT=400`, Free depth 10,
All Pools table 60, signal sample 16, Research selection 4) and existing cache
reuse sufficient for the current canonical universe. The only call-count change
is deterministic: a 429 market response now produces one provider call instead
of continuing to the second endpoint. Freshness TTLs and provenance are unchanged.
