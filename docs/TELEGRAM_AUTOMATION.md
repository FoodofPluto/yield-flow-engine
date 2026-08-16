# Telegram automation and operations

## Architecture

Prompt 5 replaces the scheduled `post_real_signals.py` path with
`telegram_worker.py`. The worker continues to call
`post_real_signals.get_real_furuflow_signals`, so scanning, scoring, filtering,
enrichment, and tier calculations remain the existing product implementation.
It does not maintain a second signal engine.

The execution sequence is:

1. claim a deterministic schedule-slot key in `automation_runs`;
2. heartbeat as `scanning` and process any explicit test requests;
3. run the existing scanner and record `succeeded`, `zero_signals`,
   `provider_failed`, or `infrastructure_failed`;
4. evaluate enabled notification rules and current entitlements;
5. transactionally store a signal snapshot and insert a delivery by its unique
   logical delivery key;
6. claim due deliveries with `FOR UPDATE SKIP LOCKED`;
7. make one Telegram API attempt and persist the attempt outcome; and
8. heartbeat as `idle` or `degraded`.

A zero-signal scan is stored as a successful `zero_signals` outcome. Provider
failures, delivery failures, and persistence/worker failures use separate
states and error codes. Telegram failures do not run inside Streamlit, the
session broker, or the public web service.

## Durable records and retention

Migration `supabase/migrations/202608150001_prompt5_telegram_automation.sql`
adds:

- `automation_runs` — logical scan invocation, timing, outcome, count, and safe failure code;
- `automation_heartbeats` — last worker instance, state, active run, and time;
- `notification_rules` — account-scoped or operator-managed Telegram rules, filters, quiet hours, and cooldown;
- `signal_snapshots` — the exact market-only payload evaluated for a run;
- `notification_deliveries` — logical work, state, attempt count, provider receipt ID, and diagnostic;
- `notification_delivery_attempts` — immutable numbered-attempt history; and
- `notification_test_requests` — explicit account-scoped test requests.

Detailed automation and delivery history is retained for 90 days. Unreferenced
signal snapshots and test requests are retained for 30 days. Supabase
`pg_cron` runs the private cleanup daily.

## Idempotency and crash behavior

The schedule key is `scan:<environment>:<UTC schedule slot>` unless the
scheduler supplies `--invocation-key`. `automation_runs.invocation_key` is
unique. A concurrent or repeated call exits without scanning. A run abandoned
before completion can be reclaimed after five minutes.

Each signal has a stable SHA-256 fingerprint based on the established pool ID,
or its existing name/chain/category identity when no pool ID exists. Each
delivery key is SHA-256 of rule ID, signal fingerprint, and the rule cooldown
window. `notification_deliveries.logical_delivery_key` is unique, and the
enqueue RPC inserts the snapshot and delivery in one database transaction.

The worker marks a delivery `sending` and creates its numbered attempt inside a
transaction before calling Telegram. Telegram does not accept an idempotency
key. Therefore a timeout, connection loss, invalid success response, process
crash, or stale `sending` claim has an unknown external outcome and is
dead-lettered without automatic resend. This at-most-once rule avoids sending a
second logical message after an ambiguous first result. Explicit HTTP server
failures and rate limits remain safe to retry because Telegram rejected them.

## Retry and dead-letter policy

There are exactly three maximum attempts. Default backoff is 60 seconds after
attempt one and 300 seconds after attempt two; a longer Telegram `retry_after`
wins. HTTP 400/401/403/404 failures are terminal. Explicit 429/5xx failures are
retryable. Ambiguous transport failures are terminal. Every attempt records
only a bounded safe error code—never request URLs, tokens, response bodies,
user identity, or exception text.

A dead-lettered delivery does not block other work. Recovery is an operator
decision because resending an ambiguous item can duplicate an externally
accepted message. Do not change a dead-letter row back to `queued` without
first confirming the provider did not accept the prior attempt.

## User notification controls

Prompt 6 turns this foundation into the authenticated Alerts product surface.
`UserNotificationClient` calls ownership-deriving RPCs for pool-alert CRUD,
safe Telegram status, delivery history, and tests. The client cannot choose a
different `user_id` or submit a raw Telegram destination. Users cannot insert
deliveries, attempts, snapshots, runs, or test-work rows directly. See
`USER_ALERTS.md` for exact semantics, linkage, and staging validation.

Free rules cannot receive Pro signals. Current `is_admin`, `pro_active`, or
`lifetime_access` is checked during rule evaluation and again when a delivery
is claimed. Demo access cannot cause external delivery. Disabling a rule stops
queued work. Quiet hours defer immediate work to the quiet interval's end.
Digest rules defer work until 09:00 in the rule's timezone.

## Required configuration

Store these only in Render/Supabase/GitHub managed secret fields:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `TELEGRAM_BOT_TOKEN`

Do not provide `SUPABASE_ANON_KEY` to the worker. Do not provide the Telegram
token to Streamlit or the session broker. There is no fake staging/production
fallback.

Worker settings:

- `FURUFLOW_AUTOMATION_ENABLED` (default `true`; set `false` to disable safely)
- `FURUFLOW_AUTOMATION_SCHEDULE_MINUTES` (default `15`)
- `FURUFLOW_AUTOMATION_STALE_CLAIM_SECONDS` (default `300`)
- `FURUFLOW_AUTOMATION_HEALTH_STALE_SECONDS` (default `1200`)
- `FURUFLOW_AUTOMATION_MAX_DELIVERIES` (default `100`)
- `FURUFLOW_TELEGRAM_MAX_ATTEMPTS` (must be `3`)
- `FURUFLOW_TELEGRAM_RETRY_1_SECONDS` (default `60`)
- `FURUFLOW_TELEGRAM_RETRY_2_SECONDS` (default `300`)
- `FURUFLOW_SYSTEM_TELEGRAM_RULE_ENABLED` (default `false`)
- `TELEGRAM_CHAT_ID` (required only when the system market rule is enabled)

The existing `FURUFLOW_SIGNAL_*` variables still configure the reused scanner.
The staging Blueprint deliberately leaves the system market rule disabled.

## Deploy and stage

1. Confirm the Prompt 2 account-control migration is already applied.
2. Apply `202608150001_prompt5_telegram_automation.sql` to staging with
   `supabase db push`, then run `supabase test db`.
3. Sync `render.yaml`. It adds the paid Starter cron service
   `furuflow-telegram-worker-staging`; Render does not offer Free cron jobs.
4. On an existing Blueprint, add the three `sync: false` worker secrets in the
   dashboard because later Blueprint syncs do not prompt for new secrets.
5. Keep `FURUFLOW_SYSTEM_TELEGRAM_RULE_ENABLED=false`. Confirm the first cron
   run records `zero_signals` or `succeeded`.
6. Check health and history using the commands and queries below.

Render cron schedules are UTC and Render guarantees one active run per cron
job. Database claims remain authoritative because manual jobs, failover
schedulers, restarts, and different worker instances can still overlap. See
the official [Render cron documentation](https://render.com/docs/cronjobs) and
[Blueprint reference](https://render.com/docs/blueprint-spec).

### Controlled staging test

Set these only on a manually invoked staging job or trusted local environment:

```text
FURUFLOW_ALLOW_TEST_DELIVERY=true
FURUFLOW_TEST_TELEGRAM_CHAT_ID=<managed secret>
```

Then run once with a new, non-sensitive idempotency key:

```powershell
python telegram_worker.py test --test-key staging-smoke-20260815-01
```

The command is refused in production. Reusing the key returns `enqueued: 0`
and never creates a second logical message. The test rule is marked `test`, so
it is excluded from market-signal evaluation.

## Health and incident runbook

From a trusted worker shell with service-role configuration:

```powershell
python telegram_worker.py health
python telegram_worker.py drain
```

`health` reports heartbeat/time, state, stale flag, last run/outcome, last
successful scan/delivery, recent scan failures, pending retries, and 24-hour
dead-letter count. It returns no destinations, messages, user IDs, tokens, or
account data.

Useful trusted-operator queries:

```sql
select scheduled_for, started_at, finished_at, scan_outcome, signal_count, safe_error_code
from public.automation_runs order by started_at desc limit 25;

select worker_name, state, heartbeat_at, active_run_id
from public.automation_heartbeats where worker_name = 'telegram';

select state, delivery_kind, attempt_count, next_attempt_at, delivered_at,
       safe_error_code, ambiguous_outcome, created_at
from public.notification_deliveries order by created_at desc limit 50;

select delivery_id, attempt_number, started_at, finished_at, outcome,
       safe_error_code, ambiguous_outcome
from public.notification_delivery_attempts order by started_at desc limit 100;
```

Interpretation:

- recent `zero_signals`: scanner is healthy; nothing qualified;
- `provider_failed`: market data collection failed;
- `infrastructure_failed`: persistence/rule/enqueue path failed;
- `retry`: an explicitly rejected attempt awaits bounded retry;
- `dead_letter` plus `ambiguous_outcome=true`: do not automatically resend;
- stale heartbeat: inspect Render cron, deployment, and Supabase connectivity;
- no delivery after success: inspect enabled rules, entitlement, quiet/digest time, cooldown, and filters.

To disable without affecting the app, set `FURUFLOW_AUTOMATION_ENABLED=false`
or suspend only the Render cron. The worker writes a `disabled` heartbeat and
exits. Do not change Streamlit, Nginx, or session-broker settings.

## Rollback

1. Disable or suspend only `furuflow-telegram-worker-staging`.
2. Confirm no row remains `sending`; let stale-claim recovery dead-letter
   uncertain claims rather than resending them.
3. Revert the application/Blueprint commit. The GitHub workflow has no schedule
   and must not become an automatic fallback.
4. Leave Prompt 5 tables in place so delivery evidence and dedupe keys survive.
   They are additive and do not affect Prompt 2 account/session behavior.
5. If schema removal is later approved, export history first, then remove the
   retention cron and Prompt 5 objects in reverse dependency order. Do not roll
   back Prompt 2.

Preserving durable records during rollback prevents a redeployed worker from
forgetting messages that Telegram might already have accepted.
