# Alert authorization boundary (Prompt 18F)

Baseline: `488b080a52cf0a713f5936220b8abb36a9d087b2`. Prompt 18 remains unfrozen.

## Audit and correction

| Operation | Baseline enforcement | Forward migration |
| --- | --- | --- |
| Create | Caller, linked Telegram, no active demo; paid check only for Pro-tier signal; subscription flag omitted | Current admission, paid entitlement and Telegram for every signal tier; owner derived from `auth.uid()` |
| Edit | Owner; paid check only for Pro-tier signal | Owner, then same current protected-operation predicate as creation |
| Resume | Owner, linked Telegram, no active demo | Same current protected-operation predicate as creation |
| Pause / delete | Caller-owned row only | Unchanged; permits capability reduction after access loss |
| List / direct SELECT | Owner-scoped RPC and RLS | Unchanged; no routing identifiers exposed |
| Notification test request | Owner, enabled rule, Telegram, no active demo | Also current admission and paid access |
| Worker list / enqueue / delivery claim / test claim | Missing admission; subscription omitted; some paid checks depend on signal tier | Recheck the shared current predicate for every user-owned rule, including Free-tier signals |

The pre-fix rollback-only probe failed all three expected contract assertions:
subscription-only Pro creation, Free all-tier denial, and unapproved all-tier
denial. Real Telegram messages are never sent by the database tests.

## Authority and synchronization

Render's existing explicit `FURUFLOW_BETA_ENABLED` and
`FURUFLOW_BETA_ALLOWED_USER_IDS` configuration remains the administrative source.
The startup supervisor already receives that source and the service credential.
Before starting any child process/public listener it validates the configuration
and atomically synchronizes `private.beta_admission` through a service-only RPC.
No participant IDs are stored in this repository. Missing configuration, invalid
configuration, failed synchronization, or a missing database snapshot fails closed.

The database snapshot is the runtime authority. Account reconstruction reads a
caller-scoped RPC's admission and current paid decisions, and fails closed if
that RPC is unavailable or malformed. Database decisions supersede an older
process's allowlist and entitlement flags. Administrative changes use the same
server configuration/deployment path; the private snapshot is not a second
independently maintained allowlist. No browser or user metadata can seed it.

The synchronization is part of the existing single web-service startup. A
configuration deployment must complete startup synchronization before it is
considered applied. The separate Telegram cron only reads the shared snapshot;
it does not independently populate it. No service credential is added to the
Streamlit process. There is no new production test endpoint.

## Paid and trust contract

Verified, non-deleted users qualify through authoritative Admin, legacy/current
`pro_active`, lifetime access, or `subscription_pro_active` backed by an active
Stripe subscription whose recorded period has not ended. A null period retains
the existing active-status convention; a known elapsed period fails closed.
Canceled/inactive/expired subscriptions cannot qualify through a stale flag.
Another valid independent paid grant remains sufficient.

Active demo access retains the existing external-delivery prohibition. Demo
product access remains separate from paid external delivery. Admin bypasses
the participant list once admission is initialized, but still requires verified
identity and trusted Telegram and remains subject to the demo prohibition.

Private helpers are not executable by public, anonymous, authenticated or
service roles. Public caller RPCs derive identity from `auth.uid()`. Service
worker functions may evaluate an owner internally; callers cannot invoke that
parameterized predicate to impersonate a user. Existing RPC signatures, owners,
intended role access, empty search paths, user isolation and historical migrations are preserved.
The hosted baseline also granted anonymous execution on creation through legacy
default privileges. Explicit ACL reconciliation removes anonymous execution on
caller RPCs and anonymous/authenticated execution on worker RPCs; function body
guards remain in place as defense in depth.
No dynamic SQL is introduced into production functions.

Worker authorization is checked again at claim time, including retries. A
revocation before a subsequent claim blocks dispatch even if a stale enabled
rule or queued delivery remains. Existing system-owned rules preserve their
separate service-only semantics. As with any external send, a revocation after
an authorized claim cannot retract an already in-flight Telegram request.

## Automated validation and deployment

`scripts/run_database_tests.py --linked --migration
supabase/migrations/202609110001_alert_authorization_boundary.sql` runs pending
DDL and each pgTAP file in its own rollback-only transaction through the existing
Supabase CLI. It checks executed/planned/failed counts rather than relying on
the final SQL statement's exit status. Lock and statement timeouts bound work.
The delivery matrix refuses to run over pending unrelated work; synthetic
fixtures and any candidate DDL are rolled back even after test failure.

The account bootstrap test supports initialized staging without changing real
Admin identities: it asserts bootstrap refusal when an Admin exists, verifies
existing Admins remain, and uses a synthetic actor for grant/audit tests. Its
empty-database branch still requires successful first-Admin bootstrap.

Deployment uses one normal commit/push, exact-SHA CI, `supabase db push`, then
Render auto-deployment/startup synchronization. The migration must be applied
before the new web process can pass startup. Before synchronization the new
database boundary denies protected Alerts, rather than guessing approvals.
Remote migration history, function definitions, ACLs, snapshot initialization,
exact deployment identity and positive/negative lifecycle tests must all be
verified before declaring PASS.

Application rollback may retain the stricter database boundary. Do not restore
the historical insecure functions or remove admission data as an automatic
rollback. Use a reviewed forward correction if SQL behavior needs repair.
