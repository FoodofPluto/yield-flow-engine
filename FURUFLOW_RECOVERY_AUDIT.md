# FuruFlow recovery and expansion audit

**Audit date:** 2026-08-02  
**Scope:** repository, local rendered application, deployment configuration, public GitHub Actions state, live DeFiLlama availability, and current competitive products.  
**Decision:** do not expand the product until identity, durable state, data provenance, and automation reliability are stabilized.

## 1. Executive summary

FuruFlow has a useful product thesis—turn a broad yield feed into a decision workflow—but it is not yet safe to present as a reliable paid financial-data product or partner service. The strongest assets are a functioning read-only discovery experience, direct pool links, a coherent Free/Pro intent, basic signal/history concepts, and recent auth-hardening tests. The core weakness is that the product is still a prototype assembled around local files: Supabase is used only as an identity provider, while users, sessions, entitlements, Stripe events, watchlists, histories, and deduplication remain in SQLite/JSON/CSV files local to whichever process happens to run them.

Three findings determine the recovery sequence:

1. **Login has a proven configuration fault.** The local deployment-equivalent `SUPABASE_URL` includes `/rest/v1/`; `create_client()` and the JWKS derivation require the project root URL. The resulting auth and JWKS endpoints are wrong. A direct DNS check of the configured host and its root form also returned `getaddrinfo failed`, so the project hostname is stale, mistyped, deleted, or otherwise unreachable. Non-empty-value health checks do not detect either condition.
2. **The Telegram scheduler was automatically disabled for inactivity.** GitHub reports the workflow state as `disabled_inactivity`. The last successful scheduled run was July 28, 2026, about 60 days after the repository was last pushed on May 29. GitHub documents this exact 60-day behavior for public repositories. The job was not dependent on Streamlit visits.
3. **A plaintext Telegram bot token exists locally.** The ignored, untracked `test_telegram.py` contains an active-looking bot token and chat ID. It is absent from current tracked files and Git history by path, but it must be treated as compromised: rotate it immediately, update the GitHub secret and local secret store, then remove the plaintext file.

The weighted product score is **1.48/5 (29.6/100)**. The next commercial milestone should be a trustworthy, observable Free product plus one clearly valuable Pro tier—not more pages. The recommended initial Pro buyer is an active self-directed yield allocator who wants saved screens, history, comparisons, and dependable alerts. Partner/API work begins only after the underlying data contracts, provenance, entitlements, and delivery SLOs exist.

## 2. Current architecture

| Area | Actual implementation and execution path | Assessment |
|---|---|---|
| Web entry point | `app.py` (1,823 lines), run with `streamlit run app.py`; UI, CSS, navigation, fetches, filtering, auth shell, admin controls, pricing CTAs, and all ten pages are in one module. | Operational locally; too coupled for safe iteration. |
| Alternate app | `app_linkdebug.py`, a near-copy of `app.py` with 101 changed lines; tests require it to share auth logic. | Obsolete debugging fork; remove after behavior is captured. |
| CLI | Poetry script `engine = engine.cli:cli`; `engine/cli.py` calls `engine.scanner.rank_top_yields`. | Source path is real, but the documented/runtime `requirements.txt` environment lacks `typer`; execution failed with `ModuleNotFoundError`. |
| Market data | UI calls `https://yields.llama.fi/pools`, then a second fallback URL; engine provider separately calls the primary DeFiLlama endpoint. Pool charts call two DeFiLlama chart endpoints. | Live endpoint returned HTTP 200 and 15,786 pools during audit. No record-level source timestamp or freshness contract is exposed. |
| Data fallback | Any UI fetch exception silently returns five hard-coded demo pools. Pool charts fall back to local snapshots, then a synthetic 14-day trend. | Financially unsafe presentation: demo/synthetic data is not promoted as a global degraded mode. |
| Risk and signals | Two incompatible 1–10 and 1–100 scoring systems in `engine/scoring.py`; UI risk uses hard-coded protocol “audit” and “age” values in `app.py`. Only the first 16 ranked pools receive chart-derived signals. | Heuristic, uncalibrated, and sometimes internally contradictory. Not “AI.” |
| Identity | `supabase_client.py` initializes Supabase; `supabase_auth.py` performs password/OTP calls and validates HS256 or ES256 tokens; Streamlit session state stores access/refresh tokens. | Password path is structurally present but misconfigured. Magic-link completion is absent. |
| User/profile DB | `db.py` initializes a local SQLite database (`furuflow.db`) with `users`, Stripe event, and admin-audit tables. Verified Supabase identity is copied/matched into this DB. | Not a shared production control plane; no Supabase profile table or RLS. |
| Entitlements | `auth_service.can_access_pro()` requires verified identity plus admin, lifetime, or `pro_active` in SQLite. `DEV_MODE` is blocked in production. | Good fail-closed intent; persistence and billing synchronization are not production-safe. |
| Billing | Static Stripe Payment Link; client app appends prefilled email and sometimes `client_reference_id`. `stripe_webhook_example.py` is an undeployed Flask example writing to its own local SQLite path. Local production secrets are placeholder-shaped but pass presence-only boot checks. | Checkout-to-entitlement lifecycle is not proven end to end. |
| Watchlist | One process-global `watchlist.json` for every user, mirrored to session state; read/write errors are swallowed. | Cross-user leakage and lost-update risk; not durable across deployment replacement. |
| History/recaps | `pool_history.json` is read and rewritten on app execution; `signal_history.csv` is appended only by the signal poster. GitHub runners do not persist either file back to the app. | Deployed recaps cannot reliably receive scheduler history; local pool file is 67.5 MB. |
| Telegram | GitHub Actions runs `post_real_signals.py`; it fetches/ranks, formats, posts an aggregate message, may post additional strong alerts, and writes local dedupe/history files. | Scheduler currently disabled. Local state is ephemeral; workflow explicitly allows reposts. |
| Other automation | PowerShell scanner/watch scripts, Discord post-processing, X posting, and an unfinished `bots/auto_allocator.py`. | Multiple legacy paths with unclear ownership; allocator is explicitly scaffold/stub code. |
| Deployment | README recommends Streamlit Community Cloud plus a separate Flask webhook host. No Dockerfile, IaC, health endpoint, release workflow, pinned requirements lock for deployment, or backend deployment config exists. | Architecture is described but not implemented as one deployable system. |
| Secrets | `.env` and `.streamlit/secrets.toml` are ignored; none is tracked. Streamlit Cloud secrets must be entered in deployment settings. | Correct repository exclusion, but validation is weak and a plaintext ignored test token exists. |
| Tests/observability | 26 unit/characterization tests pass. No UI, API contract, live-provider, scheduler, webhook integration, accessibility, load, or end-to-end auth tests. Logging is mostly `print`/stdlib; no central monitor or error tracker. | Useful auth base, insufficient release gate. |

### Actual deployed-state consequence

Streamlit Community Cloud copies the repository into a new environment. The runtime DB/history/watchlist files are intentionally not tracked. Therefore the deployed app and a separate GitHub Actions runner cannot share them. A webhook hosted elsewhere would also update a different SQLite file. This prevents reliable account migration, paid fulfillment, personal watchlists, recap history, and cross-process deduplication.

## 3. P0 blockers

| Blocker | Evidence | Immediate containment / exit condition |
|---|---|---|
| Plaintext Telegram credential | Ignored local `test_telegram.py` contains a bot token and chat ID; current tracked-secret shape scan found zero tracked hits. | Rotate via BotFather now; replace GitHub/local values; delete plaintext test; add secret scanning. Never reuse the old token. |
| Supabase endpoint invalid | Configured URL has `/rest/v1/`; code appends `/auth/v1/...`. Root host also failed DNS resolution on 2026-08-02. | Select the intended live Supabase project; use its exact root URL and matching publishable key; validate DNS, `/auth/v1/health`, JWKS, password sign-in, refresh, and deployed redirect behavior. |
| Split, non-durable control plane | Identity is Supabase, but profiles/entitlements/sessions/Stripe events are local SQLite; app, scheduler, and future webhook do not share storage. | Move account state and durable product state to one managed Postgres/Supabase project with migrations, constraints, RLS, backups, and service-role-only billing writes. |
| Cross-user/global state | All visitors share `watchlist.json`; app rewrites one 67.5 MB history file without locking; errors are swallowed. | User-scope watchlists in DB; move time-series/history to tables/object storage; transactional writes and observable failures. |
| Data provenance failure | Live fetch failure silently becomes demo pools; failed charts can become synthetic trends; UI has no global source/freshness/degraded badge. | Every row/result must carry source and observed time; demo and synthetic modes must be unmistakable and excluded from production ranking/alerts. |
| Misleading risk/“AI” claims | Audit/age scores are hard-coded guesses; public risk can be computed as the inverse of opportunity strength; negative movements increase “signal strength”; UI says “AI layer” although rules are deterministic. | Rename claims, publish methodology and limitations, unify semantics, add data-quality/confidence fields, and validate against expert-labeled cases before paid launch. |
| Paid lifecycle not operational | Stripe config accepts placeholders; webhook is an example; no shared DB; no verified deployed event flow. | Server-created checkout tied to internal user ID; signed/idempotent webhook in shared DB; replay tests; revoke on lifecycle changes; monitoring. |
| No production release gate | CLI fails in requirements-based environment; only unit tests exist; Streamlit emits API-removal warnings. | Reproducible environment, CI on every push, app smoke test, dependency audit, provider contract test, and deploy health check. |

## 4. Weighted product scorecard

Scale: 0 missing, 1 critically deficient, 2 below competitive expectations, 3 functional, 4 strong, 5 differentiating. Weights total 100%.

| Category | Wt. | Score | Evidence | User impact | Business impact | Target | Required corrective work |
|---|---:|---:|---|---|---|---:|---|
| Product clarity/differentiation | 7% | 2 | Strong tagline and signal thesis, but “AI,” scanner, signals, strategies, and arbitrage overlap; proof is thin. | Users cannot tell the primary job or why to pay. | Weak conversion and positioning. | 4 | Define ICP, core promise, evidence hierarchy, and honest rules-based language. |
| Navigation/IA | 6% | 2 | Ten pages in one selectbox plus global controls; pool detail is a top-level page. | High cognitive load and poor orientation. | Lower activation. | 4 | Task-based sitemap; contextual pool detail; separate account/admin/developer surfaces. |
| Scanability/visual hierarchy | 6% | 2 | Modern dark styling, but dense sidebar, many bordered panels/tables, compact controls; mobile drawer starts with full auth stack. | Slow comparison and high scroll cost. | Product appears prototype-grade. | 4 | Design tokens, fewer simultaneous panels, progressive disclosure, responsive comparison cards/table. |
| Ease/workflow completion | 7% | 2 | Browse/open-pool works; saving, alerts, upgrade, and identity do not complete reliably. | Users reach dead ends after discovery. | Poor retention and paid trust. | 4 | End-to-end journey states, contextual CTAs, durable saves, alert setup, account recovery. |
| Yield-data quality/freshness | 10% | 2 | One main upstream; live endpoint works, but no observed timestamp/SLA; demo substitution is silent. | Cannot judge whether an APY is current or real. | Liability and churn risk. | 4 | Ingestion service, timestamps, stale thresholds, provenance, quality flags, reconciliation. |
| Risk communication | 10% | 1 | Hard-coded metadata, conflicting scales, opaque formulas, strength-derived public risk. | False confidence around capital-loss risk. | Severe trust/reputation exposure. | 4 | Versioned methodology, components, confidence, incident history, independent review, disclaimers. |
| Authentication/account lifecycle | 9% | 1 | Invalid endpoint; no signup/reset; magic-link return unhandled; session only in Streamlit state. | Login fails and recovery is unclear. | Blocks Pro and supportability. | 4 | Correct project, complete lifecycle, persistent secure session, verified callback, logout/revocation tests. |
| Security/privacy | 9% | 1 | Plaintext local token; shared watchlist; local PII/entitlements; no RLS/control plane; no security CI. | Possible data leakage or compromised channel. | Incident and partner-diligence blocker. | 4 | Rotate, centralize, least privilege/RLS, secret scanning, threat model, audit logs, review. |
| Performance/accessibility | 5% | 2 | 16 chart calls, 67.5 MB JSON rewrite, unbounded monolith; basic responsive stacking works; no a11y tests. | Slow cold starts and difficult mobile navigation. | Higher hosting/support cost. | 4 | Background ingestion, pagination, DB queries, WCAG checks, keyboard/screen-reader tests. |
| Feature completeness | 6% | 2 | Many surfaces exist, but alerts, recaps, strategy persistence, arbitrage economics, and portfolio context are incomplete. | Breadth without dependable outcomes. | Diluted roadmap. | 4 | Finish fewer workflows; add compare, saved views, net yield, and operational alerts. |
| Free/Pro packaging | 5% | 2 | Ten free rows and two sort modes; Pro gates whole pages; “future alerts” marketed as included. | Paywall appears arbitrary and promises future value. | Low conversion/high refunds. | 4 | Preserve trust/data basics free; monetize automation, depth, history, exports, personalization. |
| Pricing/monetization | 4% | 1 | Static $20/month link; no trial, annual plan, instrumentation, or reliable fulfillment. | Purchase risk is high. | Cannot measure or scale revenue. | 4 | One Pro tier, trial/demo, lifecycle billing, funnel analytics, value-based experiments. |
| Alerts/automation/retention | 6% | 1 | Workflow disabled; ephemeral history; reposts enabled; no user preferences or failure notifications. | No reliable return loop. | Retention engine is absent. | 4 | Durable scheduler/delivery tables, user rules, digests, retries, DLQ, health and failure alerts. |
| Maintainability/testing | 6% | 1 | 1,823-line app, duplicate debug app, multiple legacy scripts; 26 unit tests pass but CLI environment fails. | Regressions and slow fixes. | Expensive roadmap and fragile releases. | 4 | Modularize, retire dead paths, lock dependencies, CI pyramid, typed contracts, structured logs. |
| API/integration/partner readiness | 4% | 0 | No public/internal versioned API, auth, quotas, docs, licensing, SLOs, status, or sandbox. | Partners cannot evaluate integration. | No credible embedded offering. | 3 | Stable data model/API, keys/OAuth, quotas, docs, sandbox, provenance, SLA and legal terms. |

**Weighted result:** `Σ(weight × score) / 100 = 1.48/5`, equivalent to **29.6/100**.

## 5. Core user-journey audit

| Journey | Friction / missing state | Trust and failure problem | Recommendation |
|---|---|---|---|
| Visitor understands FuruFlow | Clear tagline, but no methodology, freshness, proof, ideal-user statement, or sample outcome. | “Smartest” and “AI” are unsupported claims. | One-sentence ICP/promise, three proof points, data timestamp, methodology and non-advice disclosure. |
| Visitor explores markets | Default selects only the first eight alphabetic chains and applies $5M TVL / risk ≤70 without an obvious summary. | Silent demo fallback looks live. | Default to a deliberate liquid universe; show result count, data source/time, degraded status, and active chips. |
| User filters/sorts | Controls are split across three expanders; no search, active chips, reset, saved view, URL state, result-before/after count, or unavailable-choice logic. | Free sort gate is disconnected from user intent. | Primary filter bar plus advanced drawer; atomic Apply/Reset; persistent saved views; mobile filter sheet. |
| User understands yield/risk | APY/base/reward shown, but no net APY, duration, reward-token exposure, methodology, confidence, or incidents. | Risk values are modeled from hard-coded proxies and conflicting formulas. | Component-level risk and yield provenance; freshness; net-yield assumptions; confidence and limitation disclosure. |
| User saves/monitors | Save works from cards/detail, but all users share one JSON file. No notes, thresholds, tags, or change history. | A visitor can see/overwrite another visitor’s selections. | RLS-protected per-user watchlists with notes, alert rules, optimistic concurrency, and guest-to-account migration. |
| User receives alert/recap | Telegram channel is global; no per-user channels/preferences. Scheduler history never reaches app. | Scheduler is disabled and can report success with zero candidates. | Per-user alert rules/digests, durable delivery log, explicit no-signal outcome metric, email/Telegram/webhook options. |
| User creates account/logs in | No signup/reset; password errors are generic; magic-link completion absent; verified form remains visually dominant. | Wrong/unreachable Supabase URL. Session vanishes with Streamlit state. | Complete signup/verify/reset/login/refresh/logout flows and operational status messaging. |
| Free user encounters Pro | Whole pages stop after a preview; claims include future features; checkout can open for a guest. | User cannot verify paid value or fulfillment. | Gate actions/depth, not truth; show exact unlocked benefit; require verified identity before checkout. |
| Pro user manages personalization | No account/billing page, preferences, alert routing, saved strategies, invoices, cancellation state, or data export/delete. | Entitlement can diverge across processes. | Account center with plan, billing portal, saved artifacts, notification settings, data/privacy controls. |
| Demo user accesses Pro | No controlled demo. `DEV_MODE` is global and unsuitable. | A shared production Pro user would expose state and invite abuse. | Isolated demo project/tenant, synthetic/public data, short-lived sessions, read-only policies, rate limits. |
| Partner evaluates integration | Repository and product have no developer entry point. | No contract, provenance, status, security posture, or licensing. | Developer page, sandbox API, sample schema, quickstart, limits, uptime/freshness definitions, contact path. |

## 6. Page-by-page assessment

| Current page/surface | Decision | Rationale and task-linked change |
|---|---|---|
| Home | **Improve** | Keep as market briefing; add freshness/degraded status and three task CTAs; remove redundant tables. |
| Scanner | **Keep + rename to Discover** | This is the core acquisition workflow. Make it the canonical filter/compare surface. |
| Signals | **Merge** into Discover | Use a Pro “Signals” view/ranking within the same results, avoiding duplicated universe and cards. |
| Market Map | **Merge** into Market Research | Useful visual mode, not a separate top-level destination. |
| Pool Explorer | **Relocate + rename to Pool Detail** | Open contextually from every opportunity; retain shareable URL/back-to-results state. |
| Watchlist | **Improve** | Make user-scoped; add notes, thresholds, changes since saved, compare, and alert setup. |
| Recaps | **Rename to Activity & Digests** | Tie to actual deliveries/watchlist changes; distinguish daily/weekly and empty/stale states. |
| Protocol Dashboard | **Merge** into Market Research | Protocol and chain lenses belong together; link into filtered Discover. |
| Strategy Builder | **Improve + relocate** under Pro Tools | Save reusable rules, show result change, and connect results to monitoring. |
| Arbitrage | **Replace/rename to Yield Spreads** | Same symbol across chains is not risk-free arbitrage. Include bridge, fees, lockups, liquidity, and protocol mismatch before using “arbitrage.” |
| Sidebar account/login | **Replace** with compact account control/modal | On mobile it consumes nearly the entire drawer before navigation. |
| Admin panel | **Relocate** to protected Admin route | Remove privileged controls from the ordinary page flow; require recent re-auth for sensitive actions. |
| Pricing | **Create new** | Explain current value, limits, billing cadence, trial, cancellation, and data disclaimers. |
| Alerts/settings | **Create new** | Centralize rules, channels, quiet hours, delivery log, and test delivery. |
| Methodology/status | **Create new** | Publish source, freshness, scoring version, incidents, and availability. |
| Developers | **Create later** | API docs, sandbox key, schemas, rate limits, changelog, SLA/contact. |
| `app_linkdebug.py` | **Remove after characterization** | Stale near-copy increases regression surface. |
| Auto allocator | **Remove/quarantine** | Unsafe placeholder math and unfinished transaction execution are outside the product promise. |
| Legacy PowerShell/Discord/X paths | **Archive or assign owner** | Keep only a documented, tested execution path per job. |

## 7. Revised sitemap and control model

```text
Public
├─ Home
├─ Discover
│  ├─ Opportunities
│  ├─ Signals (Pro view)
│  ├─ Compare
│  └─ Pool Detail (contextual route)
├─ Research
│  ├─ Market Map
│  └─ Protocols
├─ Pricing
├─ Methodology & Data Status
└─ Developers (when API-ready)

Authenticated
├─ Watchlists
├─ Alerts
├─ Activity & Digests
├─ Pro Tools
│  ├─ Strategy Builder
│  └─ Yield Spreads
└─ Account & Billing

Restricted
└─ Admin
```

### Market controls specification

| Requirement | Specification |
|---|---|
| Primary controls | Search asset/protocol; chain; strategy type; stablecoin/exposure; minimum TVL; APY range; risk band; sort. Keep 5–7 immediately visible. |
| Advanced controls | Base vs reward APY, IL/leverage, pool age, protocol maturity, audit evidence, reward-token concentration, TVL/APY change windows, volume, confidence/freshness, exclude lists. |
| Defaults | Liquid universe, all supported core chains, TVL ≥$1M, no APY minimum, exclude stale/invalid rows, “Risk-adjusted relevance” sort; explain every default. Do not choose alphabetic chains. |
| Persistence | URL query for shareable public state; signed-in saved views in DB; device-only last-used state for guests; schema-version saved filters. |
| Active-filter display | Chips above results, result count and universe count, “data observed X min ago,” clear individual chip, “Save view.” |
| Reset | One visible Reset returns documented defaults; confirm only if overwriting a named saved view. Apply advanced changes atomically. |
| Tooltips | Define APY, base/reward, TVL, risk components, confidence, freshness, IL, and net-yield assumptions; link to methodology. |
| Empty | Say which constraint removed the most rows; offer one-click relaxation and preserve current settings. Never show demo data as a normal empty-state substitute. |
| Loading | Skeleton rows/cards, source/time label, cancellable/retry state; keep prior results marked “refreshing” rather than blanking the page. |
| Error | Distinguish stale-cache served, partial-provider outage, no data, and application error; show last good timestamp and incident link. |
| Mobile | Compact header, full-screen filter sheet, sticky result/sort bar, card default with optional horizontal table, account behind avatar—not before navigation. |

Success measures: median time to first useful pool, filter-to-open conversion, zero-result rate, saved-view rate, mobile filter completion, and percentage of results with current provenance/confidence.

## 8. Competitive benchmark

All benchmarks were active on official product/docs pages during this audit.

| Product | Value proposition / discovery | Yield and risk presentation | Personalization, alerts, mobile |
|---|---|---|---|
| [DeFiLlama Yields](https://defillama.com/yields/overview) | Broad, free market dataset; overview and pool exploration; saved filters. | APY/TVL history and filters; explicit disclaimer that listings are not audits or endorsements. | Web-first; saved filters; limited opinionated monitoring. Strong baseline for breadth/transparency. |
| [Exponential](https://exponential.fi/featured) | Curated discovery, assessment, and investment flow. | Prominent yield/TVL plus A–F risk; [published framework](https://exponential.fi/learn/risk-rating) decomposes chain, protocol, asset, and pool risk. | Web-oriented curated experience. Strong pattern: reveal methodology and risk components, not an unexplained number. |
| [DeBank](https://debank.com/) | EVM portfolio monitoring and transaction analysis rather than broad yield discovery. | Position/account context; not a primary independent risk-rating product. | Mobile app; VIP adds time machine, transaction analysis, change/summary views; [OpenAPI](https://docs.cloud.debank.com/en/readme/open-api) and official-account messaging support partner/retention use cases. |
| [Zerion](https://zerion.io/premium) | Multichain wallet, portfolio, P&L, trading, and DeFi positions. | Portfolio and position context, history, and P&L rather than yield-ranking risk research. | Web/mobile/extension; $99/year individual Premium at audit time; notifications and CSV. Its [API](https://zerion.io/api/) offers normalized data, webhooks, transparent tiers, support, and SLA language. |
| [DeFi Saver Notify](https://help.defisaver.com/features/notify) | Position management and automation across integrated lending protocols. | Health/ratio and execution state are tied to an owned position. | Explicit threshold monitors and automation notifications on Ethereum, Arbitrum, Base, and Optimism. Strong pattern: alerts are configured around a user’s actual risk state. |

| Product | Data freshness/trust | Packaging/docs/API/partner pattern | What FuruFlow should learn |
|---|---|---|---|
| DeFiLlama | Broad primary dataset and clear “not an audit” boundary. | Free public experience; Pro API for greater data/rates/support. | Compete on workflow and explanation, not pretending the upstream feed is proprietary. Always show attribution and limitations. |
| Exponential | Published rubric and coverage counts; curated investable subset. | Research supports trust and an execution funnel. | A risk score earns trust through components, sources, update cadence, and disclosed judgment. Do not copy its letter grades or brand. |
| DeBank | Wallet-native state makes the product personally relevant. | VIP consumer tier plus developer API and targeted messaging product. | Personalization is a durable portfolio/time/change workflow, not just a global watchlist. |
| Zerion | Claims block-level freshness and production SLAs; unified schema across 40+ chains. | Free developer entry, usage tiers, docs, webhooks, enterprise support. | Partner readiness needs a productized contract, dashboard, support, quotas, and webhooks—not a repository function. |
| DeFi Saver | Notifications are independent from automation and documented per supported protocol. | Narrow integration scope with explicit supported networks. | Start alerts with a small, testable event set and delivery log; do not market “future alerts.” |

Useful patterns to adapt: visible freshness/provenance, saved filters, risk decomposition, portfolio-aware changes, explicit support/coverage matrices, alert delivery logs, developer quickstarts, and documented limits. Avoid copying visual identity or presenting heuristic rankings as institutional risk research.

## 9. Supabase diagnosis

### Proven failure chain

1. Local Streamlit secrets set `ENVIRONMENT=production`, `DEV_MODE=false`, a publishable key, and a `SUPABASE_URL` ending in `/rest/v1/`.
2. `supabase_client.get_supabase_client()` passes that value to `create_client()`. Supabase expects the unique **project root URL**, not the REST subpath ([Python initialization docs](https://supabase.com/docs/reference/python/initializing)).
3. `get_supabase_jwks_url()` appends `/auth/v1/.well-known/jwks.json`, producing a nonsensical `/rest/v1/auth/v1/...` path.
4. A read-only DNS/health diagnostic showed the configured hostname and root form fail DNS lookup. Even removing the path is therefore insufficient until the correct live project is selected.
5. Startup health checks only verify that strings are non-empty. They neither parse/disallow paths nor test host/project/key coherence, so production starts “healthy.”

Cloud secrets are outside the repository and could differ; the Streamlit deployment settings must be compared directly. If they were copied from the local file, this is the direct login failure.

### Lifecycle gaps after correcting the URL

- Password sign-in can store tokens in `st.session_state`, but browser refresh/new websocket has no durable secure cookie/session bridge.
- Magic link sends no explicit `email_redirect_to` and the app has no callback/code exchange. Supabase says the Site URL is used by default and the redirect must be allowlisted ([OTP](https://supabase.com/docs/reference/python/auth-signinwithotp), [redirect URL docs](https://supabase.com/docs/guides/auth/redirect-urls)).
- There is no signup, resend-verification, forgot/reset password, account deletion, or meaningful locked/rate-limited state.
- Local `users` rows are created after verified identity; there is no `public.profiles` table tied to `auth.users`, and no RLS. Supabase recommends a user table referencing `auth.users` and protecting it with RLS ([user management](https://supabase.com/docs/guides/auth/managing-user-data), [RLS](https://supabase.com/docs/guides/database/postgres/row-level-security)).
- Email verification accepts `user_metadata.email_verified`; user metadata should not be treated as the sole authoritative privilege boundary. Use the provider’s confirmed identity/server verification.
- Logout clears Streamlit state but does not call provider sign-out/revocation.
- Entitlements and Stripe IDs live in SQLite, so a webhook on another host cannot update the app’s file.
- There is no schema/migration artifact for Supabase tables, policies, redirect configuration, or billing functions.

### Acceptance criteria for the later Supabase implementation

1. Dev, staging/demo, and production use distinct projects/config; production startup rejects a URL with any path beyond `/` and rejects placeholder keys/secrets.
2. A deploy health check resolves DNS, calls Auth health/JWKS, and verifies project URL/key coherence without logging secrets.
3. Signup, verification, password login, magic link, refresh, logout, forgot/reset, expired token, revoked user, and duplicate-email migration pass automated tests.
4. Production and preview redirect URLs are allowlisted; magic-link callback exchanges the code and removes sensitive query material from the displayed URL.
5. Sessions survive a Streamlit rerun/browser refresh using a secure, HttpOnly, SameSite cookie or a small backend session layer; tokens never enter logs or SQLite.
6. `profiles`, `entitlements`, `subscriptions`, `watchlists`, `saved_views`, `alert_rules`, `admin_audit`, and `webhook_events` are migration-managed Postgres tables keyed to `auth.users.id`.
7. RLS defaults deny; users read/write only their records; billing/admin fields are service-role-only; policy tests cover cross-user denial. Never expose service-role keys to Streamlit clients.
8. Checkout sessions are created server-side for a verified user ID. Signed Stripe events are idempotent and update subscription status in the shared DB; cancellation/nonpayment is tested.
9. Admin changes require verified admin authorization, recent re-auth for privilege changes, immutable audit events, and a reason.
10. Legacy email-only sessions cannot access or mutate personal/paid data and are removed after a time-boxed migration.
11. Account export/deletion and privacy retention rules are implemented and tested.
12. Operational dashboards expose login success/error rate, callback failure, refresh failure, webhook lag/failure, and entitlement mismatch—without PII in logs.

## 10. Secure demo-access recommendation

Use a **separate demo Supabase project/tenant and demo data plane**, not `DEV_MODE` and not a shared production account.

- “Try Pro demo” asks a small backend to mint a short-lived demo session; no credentials appear in source or browser UI.
- Demo identity carries a server-issued `demo=true` claim/role and an expiry. RLS permits reads only from seeded public/synthetic demo rows and permits writes only to that session’s disposable namespace.
- Disable checkout, admin, API-key creation, external notifications, webhooks, exports containing identifiers, protocol transactions, and expensive queries.
- Rate-limit by session/IP, cap rows and saved artifacts, and reset disposable state on a schedule.
- Display a persistent “Demo data / no production access” banner and synthetic-data timestamps.
- Log demo issuance and denied privileged attempts; provide a kill switch.

Acceptance: a demo user can see every intended Pro screen and create disposable watchlists/alerts; cannot query production tables, see another demo session, send Telegram/email, create billing state, invoke admin, access secrets, or exceed limits; sessions expire and cleanup is verified automatically.

## 11. Telegram and scheduled automation diagnosis

### Root cause and contributing factors

| Candidate | Finding |
|---|---|
| Streamlit inactivity | **Not the cause.** The job runs in GitHub Actions and does not require a page visit. |
| GitHub Actions inactivity | **Definitive cause.** Public API state is `disabled_inactivity`; [last run](https://github.com/FoodofPluto/yield-flow-engine/actions/runs/30321989517) succeeded July 28; last push was May 29. GitHub documents automatic disabling after 60 inactive days for public repositories ([docs](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows?tool=cli)). |
| Missing/expired secrets | Not evidenced as the stop cause. Previous success proves only process exit, not that every run posted. Rotate the plaintext-exposed token regardless. |
| API/data failure | Live DeFiLlama returned 200 during audit. The script exits successfully when no signals qualify, so “success” can mean no post. |
| Scheduling config | Cron is four times/hour, but GitHub schedules can delay/drop under load; workflow is now disabled. |
| Duplicate prevention | Broken by design: workflow sets `ALLOW_REPOSTS=true`; even if false, the JSON dedupe file is lost with each fresh runner. |
| Unhandled exceptions | Network exceptions fail the job after local retries, but no failure notification/DLQ exists. Aggregate send can succeed before a later alert fails, causing duplicates on retry. |
| Local execution | `telegram_utils` reads token/chat at import time before `post_real_signals.py` calls `load_dotenv()`, so `.env` alone does not configure that execution path. |

### Recommended independent architecture

Run a small scheduled worker (managed cron + container/worker service) independently of Streamlit:

1. `scan_runs`: run ID, scheduled time, started/finished, source version, row counts, reject counts, status/error class.
2. `signals`: immutable normalized observation with `observed_at`, methodology version, provenance and confidence.
3. `deliveries`: unique `(channel, recipient, signal_id, rule_id, time_bucket)` key; states pending/sent/failed/dead; provider message ID.
4. Transactionally claim pending deliveries; exponential backoff with jitter; maximum three attempts; classify retryable 429/5xx/timeouts vs terminal 4xx.
5. Never send the aggregate and per-signal alert for the same event unless product rules explicitly request both.
6. Health endpoint and heartbeat metric: last successful scan, last qualifying signal, last delivery, queue depth, error rate, source freshness.
7. Notify operations through a separate channel after consecutive failures or stale heartbeat; attach run ID, never credentials/content containing PII.
8. Retain structured logs and a dead-letter queue; provide a safe replay command that preserves idempotency.

GitHub Actions may be a temporary runner after manual re-enable, token rotation, durable DB state, and failure notifications, but it is not the recommended long-term scheduler for a paused public repository.

## 12. Feature-gap analysis

| Group / feature | User problem / target | Expected value | Required data | Complexity / dependencies | Security | Placement | Priority |
|---|---|---|---|---|---|---|---|
| Foundation: data provenance/status | All users cannot judge freshness. | Trust and support reduction. | Source, observed time, ingestion run, quality flags. | M; ingestion + schema. | Avoid leaking provider keys. | Free | P0 |
| Foundation: durable identity/state | Account users lose or share state. | Enables every personalized workflow. | Auth ID, profiles, entitlements, watchlists. | H; Supabase/RLS/migration. | Tenant isolation, least privilege. | Free base | P0 |
| Foundation: explainable risk v1 | Allocators need to understand loss modes. | Safer decisions and credible differentiation. | Chain/protocol/asset/pool evidence, incidents, audits. | H; methodology/data governance. | Claims/version integrity. | Core rating free; depth Pro | P0/P1 |
| Foundation: observability/release gate | Operators cannot detect regressions. | Reliability and faster recovery. | Logs, metrics, traces, synthetic checks. | M. | Redaction/access controls. | Internal | P0 |
| Parity: saved views/compare | Active users repeat screens and compare alternatives. | Activation and retention. | User filters, pool snapshots. | M; durable state. | RLS. | Free limited / Pro unlimited | P1 |
| Parity: historical APY/TVL/net yield | Headline APY is insufficient. | Better selection and fewer false positives. | Time series, rewards, fees/gas, lockups. | H; ingestion/licensing. | Data integrity. | 7d free / longer Pro | P1 |
| Parity: alert rules/digests | Users cannot monitor continuously. | Primary return loop. | Observations, rules, delivery state. | H; scheduler/channels. | Consent, unsubscribe, rate limits. | Free digest / Pro real-time | P1/P2 |
| Parity: wallet/position context | Yield decisions ignore existing exposure. | Personalized prioritization. | Read-only address positions, chain/protocol exposure. | H; provider/API. | Address privacy/consent. | Pro | P2 |
| Differentiation: yield durability | APY spikes may be temporary emissions. | Surfaces sustainable opportunities. | Base/reward history, incentive schedules, TVL elasticity. | H; validated model. | Explain limitations. | Pro | P2 |
| Differentiation: risk-adjusted net APY | Users need after-cost opportunity value. | Direct decision advantage. | Fees, gas, bridge, lockup, IL/leverage assumptions. | H. | Scenario—not guarantee. | Pro | P2 |
| Differentiation: change/catalyst explanation | Users need “why now?” | Faster, defensible triage. | Structured changes, governance/incentive events, provenance. | H. | Source/licensing; no fabricated causes. | Pro | P3 |
| Differentiation: portfolio fit | Users need diversification and concentration warnings. | Higher-value allocator workflow. | Wallet positions plus risk dependencies. | H. | Sensitive financial profile. | Pro | P3 |
| Partner: versioned API/webhooks | Platforms need normalized signals/data. | New B2B revenue. | Stable schemas, history, delivery contracts. | H; foundation first. | Keys, quotas, tenant isolation. | Partner | P2/P3 |
| Partner: embedded widgets | Partners want low-effort discovery modules. | Distribution. | API plus theming/config. | M/H. | Origin allowlist, CSP, attribution. | Partner | P3 |
| Partner: SLA/admin/usage portal | Buyers need operational confidence. | Enterprise closeability. | Usage, uptime, incidents, billing. | H. | RBAC/audit. | Partner | P3 |

## 13. Monetization analysis

### Recommended model

- **Free-plan purpose:** establish trust and habit. Include current source/freshness, core APY/TVL/risk facts, methodology, basic filters/sort, pool detail, one watchlist, one saved view, and a low-frequency digest. Accuracy, provenance, security, and risk basics must never be paywalled.
- **Pro target:** active self-directed DeFi allocators/analysts, roughly $10k–$250k deployed or frequently rebalanced, who value saved time and monitoring more than another raw table.
- **Upgrade triggers:** second saved view/watchlist, real-time threshold alert, compare >3 pools, >7-day history, CSV/API export, wallet-aware analysis, net-yield scenario, or advanced signal explanation. Trigger after the user sees value, not on navigation.
- **Paid capabilities:** unlimited saved screens/watchlists, real-time/multichannel alerts, longer history, compare/export, wallet context, advanced risk components, yield-durability/net-yield scenarios, strategy templates, and priority support.
- **One consumer paid tier initially:** keep Pro around the current $20/month hypothesis, test an annual discount and 7–14 day verified trial. Do not add multiple consumer tiers until activation, retention, and willingness-to-pay data justify segmentation. Remove lifetime access from normal sales.
- **Partner/API is a separate commercial line:** free sandbox/evaluation; usage-priced startup plan; contracted production/enterprise with SLA, support, redistribution/license terms, and optional embedded modules. Do not bundle API usage into consumer Pro.

The current $20/month offer is not yet sellable because fulfillment, alerts, saved state, and data trust are unproven. Instrument visit → filter → pool open → save → alert setup → checkout → activated → retained before changing price.

## 14. Partner-readiness analysis

Current readiness is **0/5**. Code functions are not an API product. Required gates:

1. Define licensed sources, transformation rights, attribution, retention, and redistribution rights.
2. Publish a canonical versioned schema with IDs, units, null semantics, `observed_at`, provenance, confidence, methodology version, and breaking-change policy.
3. Separate ingestion, scoring, account, and delivery services from Streamlit.
4. Offer sandbox data/API keys, quickstart, OpenAPI spec, examples, quotas, usage dashboard, webhook signing/replay, and SDK only after contract stability.
5. Establish SLOs for availability, maximum data age, incident response, and support; publish status/changelog.
6. Complete security/privacy review: tenant isolation, RLS tests, secrets, dependency/SAST scans, logging/redaction, backups/restore, incident plan, DPA/terms.
7. Build two evaluation paths: a 15-minute sandbox integration and an embeddable read-only opportunity widget with mandatory attribution.

## 15. Technical-debt and security register

| Risk | Sev. | Evidence / consequence | Treatment |
|---|---|---|---|
| Plaintext Telegram token in ignored file | Critical | Credential can control channel bot. | Rotate immediately; delete; secret scanner/pre-commit/CI. |
| Invalid/stale Supabase project configuration | Critical | Login/JWKS cannot work. | Correct project root/key; deploy validation and synthetic auth check. |
| Global watchlist file | Critical | Cross-user disclosure/overwrite. | RLS user table; remove file path from production. |
| Local SQLite entitlements/webhooks | Critical | Paid access diverges/lost; no shared source of truth. | Managed Postgres, service writes, migration and reconciliation. |
| Silent demo/synthetic financial data | Critical | Users may act on invented/stale presentation. | Explicit global degraded state; prohibit production alert/rank mixing. |
| Unvalidated risk claims | High | False confidence and reputational exposure. | Methodology/data review, rename, component/confidence UI. |
| Ephemeral Telegram dedupe/history | High | Duplicate or missing messages; app recaps empty. | Durable delivery/run tables and idempotency. |
| `user_metadata` verification trust | High | Potentially weak privilege boundary. | Authoritative confirmed identity/server verification. |
| Placeholder billing secrets accepted | High | False healthy state and broken fulfillment. | Format/environment validation and webhook synthetic test. |
| App rewrites 67.5 MB JSON | High | Latency, corruption, concurrent lost updates. | Time-series DB/batched ingestion; retention/indexes. |
| Monolith + debug duplicate | Medium | High regression/change cost. | Modular page/services architecture; delete characterized duplicate. |
| Dependency manifests disagree | Medium | CLI failed under installed requirements. | One locked deployment source; CI install/smoke. |
| Broad exception swallowing | Medium | Data/save failures invisible. | Typed errors, user states, structured logs/metrics. |
| Streamlit deprecated width API | Medium | Future upgrade break; runtime warnings. | Mechanical migration under tests. |
| No CSP/legal/methodology/privacy product surfaces | Medium | Partner and user diligence gaps. | Add policies/status/methodology after counsel/review. |
| Unfinished allocator code | High if activated | Placeholder $1/token math and transaction stubs. | Quarantine/remove; separate audited project if ever pursued. |

## 16. Prioritized roadmap

| Priority / item | Evidence | User / business impact | Complexity / dependencies | Acceptance criteria | Owner |
|---|---|---|---|---|---|
| P0 Rotate Telegram credential | Plaintext ignored test file. | Prevent bot/channel takeover and partner red flag. | S; BotFather + GitHub/local secrets. | Old token rejected; new token test through dry-run/staging; no plaintext/secret-scan hits. | Founder/DevOps |
| P0 Reproducible baseline + CI | CLI missing `typer`; 26 tests only. | Stops regressions and shortens recovery. | M; dependency lock. | Clean install; unit, AST/lint, app smoke, demo CLI, secret/dependency scan all green. | Tech lead |
| P0 Correct Supabase and auth lifecycle | Wrong path/DNS; missing flows. | Restores access and paid boundary. | H; live project + redirect control. | All criteria in §9 for identity flows pass in staging and production synthetic checks. | Backend/auth engineer |
| P0 Centralize durable control plane | SQLite/files split processes. | Makes paid/personal state reliable. | H; schema/RLS/migration. | One source of truth; cross-user RLS tests; backup/restore drill; no production local state. | Backend/data engineer |
| P0 Label/protect data modes | Silent demo/synthetic fallback. | Prevents misleading decisions. | M; ingestion metadata. | Every result has source/time/mode; stale/partial/demo are globally visible and excluded from alerts. | Data engineer + product |
| P0 Rebuild risk v1 contract | Hard-coded/conflicting formulas. | Restores financial trust. | H; expert/product/security review. | Versioned methodology, component evidence/confidence, fixtures and review sign-off; no “AI” claim. | Data/risk lead |
| P0 Restore Telegram as durable worker | Workflow disabled; ephemeral state. | Restores channel and operating signal. | H; shared DB/worker/monitoring. | Scheduled runs independent of visits; idempotency, retries/DLQ, heartbeat and failure alert tested. | Backend/DevOps |
| P1 App shell + IA | Ten-page dropdown/mobile auth dominance. | Faster activation and competitive credibility. | M/H; design system after stable state. | Revised sitemap; mobile/desktop usability test; account/admin separated; accessibility baseline. | Product designer + frontend |
| P1 Discover/filter/compare | Fragmented controls and no saved state. | Core workflow quality. | H; IA + durable data. | Control spec in §7; URL state, reset, empty/error/loading, compare, analytics; mobile complete. | Frontend/product |
| P1 Pool detail + trustworthy yield/risk | Missing net/context/method. | Improves decisions and conversion. | H; risk/data contracts. | Provenance, freshness, components, history, confidence, clear action/back state. | Frontend + data |
| P1 Billing/account center | Static link/example webhook. | Enables revenue without support debt. | M/H; auth/control plane. | Server checkout, signed idempotent lifecycle, portal/cancel/invoices, entitlement reconciliation. | Backend |
| P1 Monitoring/release ops | No central telemetry. | Reliability and faster incident response. | M. | SLO dashboard, alert runbook, deploy health, structured redacted logs, status page seed. | DevOps |
| P2 Saved strategies and user alerts | Current builder isn’t saved; no user delivery. | Retention and Pro value. | H; durable worker/account. | Rules persist, preview/test, quiet hours, delivery history, unsubscribe, limits. | Full-stack |
| P2 Wallet-aware portfolio context | No existing-position view. | Stronger paid personalization. | H; provider/licensing/privacy. | Read-only consent, supported-chain matrix, revoke/delete, exposure-aware shortlist. | Product/data |
| P2 Partner API foundation | No API. | Opens B2B validation. | H; stable contracts/SLOs/legal. | Sandbox, OpenAPI, keys/quotas, provenance, usage logs, two design partners. | Platform lead |
| P3 Yield durability/net-yield models | Headline APY only. | Potential differentiation. | H; deep history/cost inputs. | Backtested calibration, scenarios/assumptions, user research shows decision lift. | Data/risk lead |
| P3 Embedded widget/enterprise portal | No integration surface. | Distribution and higher ACV. | H; API/security/support. | Origin-scoped widget, theming, attribution, SLA/usage/admin controls. | Platform + design |

Recommended release gates: **Gate 1** P0 security/access/data; **Gate 2** P1 credible public + paid workflow; **Gate 3** P2 retention and first design partners; **Gate 4** P3 differentiated models/embedded scale.

## 17. Effort estimates

Ranges assume an experienced team, include implementation and proportionate tests/review, and exclude waiting for vendors/legal feedback.

| Workstream | Hours | Notes |
|---|---:|---|
| Repository stabilization, dependency lock, CI, baseline tests | 50–90 | Includes app/CLI smoke and secret/dependency scans. |
| Supabase auth, session bridge, profile/entitlement schema, RLS, migration | 100–170 | Includes staging/prod flows and policy tests. |
| Secure demo environment | 35–65 | Separate project/tenant, short-lived session, restrictions/reset. |
| Durable data/history/watchlist migration | 90–160 | Schema, ingestion, retention, user migration, backups. |
| Risk methodology v1 and data-quality contract | 100–180 | Requires product/risk analyst input, not only engineering. |
| Telegram worker, idempotency, monitoring | 70–120 | Excludes broad consumer alert preferences. |
| Design system, shell, navigation, responsive/a11y | 90–150 | Research, prototype, implementation, QA. |
| Discover/filter/sort/compare/pool detail | 130–220 | Depends on data/risk contracts. |
| Billing/account center | 60–110 | Checkout, webhook, portal, reconciliation and tests. |
| Saved views, alerts and digests | 100–180 | Channels, preferences, delivery history and consent. |
| Wallet/portfolio context | 100–180 | Provider selection/licensing can change range. |
| Partner API sandbox/docs/quotas/webhooks | 180–320 | After contracts and SLOs stabilize. |
| Security/privacy review and remediation | 45–90 | Plus any external assessor time. |
| Product launch analytics/content/support setup | 50–100 | Funnel, docs, runbooks, onboarding. |

**P0 recovery:** approximately **345–605 hours**.  
**P1 competitive-credibility release:** additional **380–660 hours**.  
**P2 retention/partner validation:** additional **380–680 hours**.  
**P3 differentiation/scale experiments:** plan only after evidence; typically **250–500+ hours**.

## 18. Budget formulas and operating scenarios

Use role-specific rates. Example build cost:

`engineering hours × engineer hourly rate + design hours × designer hourly rate + product/risk hours × product/risk rate + QA/security hours × QA/security rate`

### One-time recovery budget formula

- Development: `(backend hours + frontend hours + data/DevOps hours) × respective hourly rates`
- Product design: `90–150 hours × designer hourly rate` for P1 shell/discovery, plus research hours
- Security review: `45–90 internal hours × rate + external fixed bid if used`
- Product/risk methodology: `60–120 hours × analyst/product rate`, included within the broader methodology estimate above
- Contingency: `10–20% × labor subtotal` for migration/provider uncertainty

### Monthly scenarios

| Expense | Low / validation | Base / credible launch | Growth / partner scale |
|---|---:|---:|---:|
| Development | `60–100 h × engineer rate` | `160–280 h × blended engineering rate` | `400–700 h × blended engineering rate` |
| Product design | `8–16 h × designer rate` | `32–64 h × designer rate` | `80–140 h × designer rate` |
| Infrastructure | $50–$250 | $250–$1,000 | $1,000–$6,000 |
| Data/APIs | $0–$300 | $500–$3,000 | $3,000–$20,000 |
| Authentication/database | $25–$150 | $100–$600 | $500–$4,000 |
| Monitoring/logging | $0–$100 | $100–$500 | $500–$2,500 |
| Security review | `4–8 h × security rate` or quarterly reserve | `12–24 h × rate` + $1k–$4k quarterly reserve | `30–60 h × rate` + $10k–$40k annual external program |
| Marketing | $100–$750 | $1,000–$5,000 | $5,000–$30,000 |
| Community management | `0–20 h × community rate` | `40–80 h × rate` | `120–200 h × rate` |
| Content production | `8–20 h × content rate` | `24–60 h × rate` | `80–160 h × rate` |

Assumptions: Low is founder-led with free/low-volume provider tiers and no SLA; Base supports a small paid consumer launch and 1–2 engineers; Growth supports production partner traffic, licensed/premium data, on-call coverage, and stronger security/compliance. Payment fees are `payment volume × contracted percentage + transaction count × contracted fixed fee`. Legal/accounting/support are not included and should be budgeted separately. Validate vendor pricing before commitment.

## 19. Recommended next five Codex prompts

### Prompt 1 — repository stabilization and baseline testing

> Stabilize the FuruFlow repository without changing product behavior. Create one reproducible dependency/lock strategy for the Streamlit app, CLI, tests, and jobs; add CI for clean install, the current 26 tests, AST/lint/type checks, demo CLI smoke, Streamlit boot smoke, secret scanning, and dependency vulnerability checks. Characterize `app_linkdebug.py` and legacy scripts, then propose removals but do not remove behavior without tests. Prevent tests from sending external messages. Replace deprecated Streamlit width usage only if covered mechanically. Report every file changed, command run, remaining failure, and a baseline architecture map. Stop after stabilization; do not change Supabase, navigation, filters, or Telegram production behavior.

### Prompt 2 — Supabase authentication and secure demo access

> Implement FuruFlow’s complete Supabase identity and durable account control plane using the acceptance criteria in `FURUFLOW_RECOVERY_AUDIT.md` §9–10. First verify the correct project root URL/key and staging redirects without exposing secrets. Add migration-managed profiles, entitlements, subscriptions, audit records, user-scoped state, and deny-by-default RLS with cross-user tests. Complete signup, verification, password, magic-link callback, refresh, logout, reset, and account lifecycle. Create a separate constrained demo environment with short-lived read-only/disposable Pro sessions. Do not redesign navigation, market filters, risk scoring, or Telegram. Produce migration/rollback instructions and end-to-end acceptance evidence.

### Prompt 3 — design system, application shell, and navigation

> Redesign only FuruFlow’s design system, responsive application shell, and navigation according to `FURUFLOW_RECOVERY_AUDIT.md` §6–7. Preserve working domain logic. Implement the revised sitemap, compact account control, contextual Pool Detail route, protected Admin surface, loading/error/degraded banners, desktop/mobile navigation, and WCAG-oriented tokens/components. Validate at desktop and mobile breakpoints with keyboard and screen-reader smoke checks. Do not rebuild market filtering/ranking, change risk formulas, add features, or modify Telegram/billing semantics. Report before/after usability measures and all changed files.

### Prompt 4 — market discovery, filtering, sorting, yield, and risk workflows

> Rebuild only the Discover, Compare, and Pool Detail workflows using the filter/control specification in `FURUFLOW_RECOVERY_AUDIT.md` §7 and the approved versioned data/risk contracts. Add source/freshness/confidence, active chips, URL/saved state, reset, primary/advanced controls, honest empty/loading/error modes, mobile filter sheet, comparison, and explainable yield/risk components. Merge Signals as a Discover view and rename Arbitrage to Yield Spreads with cost/risk caveats. Do not alter authentication infrastructure, billing lifecycle, or scheduler. Add analytics events and automated UI/contract tests, then stop.

### Prompt 5 — Telegram automation, retention, and operational monitoring

> Replace FuruFlow’s disabled GitHub-only Telegram workflow with the durable worker architecture in `FURUFLOW_RECOVERY_AUDIT.md` §11. Rotate/use only managed secrets; create scan, signal, rule, and delivery tables; implement transactional idempotency, max-three retries with backoff, dead-letter handling, explicit zero-signal outcomes, heartbeat/health metrics, and separate operations failure notifications. Add user-scoped alert preferences, test delivery, quiet hours, digests, unsubscribe, and delivery history only after the base worker is proven. Do not change auth, navigation, market scoring, or pricing. Provide runbooks, failure-injection tests, rollback, and evidence that no message duplicates across retries.

## Audit diagnostics and changes

No application source, auth configuration, scheduler, secrets, or product behavior was repaired. The only tracked addition is this report.

Read-only diagnostics performed: repository/history/config inspection with secrets redacted; public GitHub API workflow check; live DeFiLlama GET; Supabase DNS/health attempts without credential output; rendered local desktop/mobile inspection; 26 unit tests; dependency check; AST parse; demo CLI smoke; tracked-secret shape scan. No login form was submitted and no Telegram/X/Discord/email message was sent.

Running the local Streamlit app caused its existing production-style side effects:

- ignored `furuflow.db` expanded from **12,288 to 28,672 bytes** as `init_db()` applied additive tables/columns; it contained zero user rows after the audit;
- ignored `pool_history.json` changed from **67,538,163 to 67,539,342 bytes** because the app writes a snapshot during rendering;
- ignored Python bytecode caches were refreshed by execution/tests.

These changes are disclosed rather than silently deleted because the files may be user-owned runtime artifacts. Git status remained clean for tracked files before adding this report.

### Verification summary

- **Pass:** 26/26 unit tests; 45 Python files parsed; `pip check`; Streamlit desktop/mobile render; DeFiLlama endpoint/schema; current tracked files contain no tested secret shapes.
- **Fail:** CLI in requirements-based environment (`typer` missing); configured Supabase DNS/endpoint; production auth configuration semantics; GitHub workflow state (`disabled_inactivity`).
- **Warnings:** Streamlit reports `use_container_width` removal after 2025-12-31; local placeholder billing values pass health checks; no evidence exists for RLS, production webhook deployment, durable scheduler state, or end-to-end paid fulfillment.
