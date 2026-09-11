# User alerts and notification controls

## Supported behavior

Prompt 6 exposes one deterministic alert type: a pool-specific qualified
FuruFlow signal. The selected canonical provider pool ID must appear in a fresh,
successful run of the existing Prompt 5 scanner, its signal tier must match the
configured tier, and `strength_score` must meet the configured minimum. Missing
pool identity, tier, or strength never matches. Provider or infrastructure
failure never becomes a successful evaluation or trigger.

Users can create, edit, pause, resume, test, and soft-delete alerts on the
authenticated Alerts page. Pool Detail opens the same creation form with the
canonical pool ID held in server-side Streamlit session state. URLs contain only
the normal page route; they contain no account, session, alert, or Telegram
routing data. Display labels come from current market data, while the canonical
pool ID remains the durable identity.

Configuration includes minimum strength, eligible signal tier,
immediate/digest timing, optional quiet hours, timezone, and cooldown. No APY
crossing, risk change, provenance change, email, SMS, push, Discord, or webhook
condition is claimed in this milestone.

## Persistence and ownership

Migration `202608160001_prompt6_user_alerts.sql` extends the Prompt 5
`notification_rules` table rather than adding a second rule system. It adds the
pool target and condition fields, browser request idempotency key, safe Telegram
connection reference, soft-delete timestamp, and authoritative last-evaluated
and last-triggered timestamps. Existing delivery tables remain authoritative
for queue, claim, attempt, retry, receipt, and dead-letter state.

Authenticated browser writes are revoked on the rule table. The UI uses
`security definer` RPCs that derive ownership only from `auth.uid()`:

- `list_my_pool_alerts`
- `create_my_pool_alert`
- `update_my_pool_alert`
- `set_my_pool_alert_enabled`
- `delete_my_pool_alert`
- `get_my_telegram_status`
- existing `request_notification_test`

The RPC payload never accepts `user_id`, a Telegram chat ID, or a bot token.
Creation requires a unique client request key, so a Streamlit rerun cannot
create a second alert for the same submitted request. Delete is an auditable
disabled tombstone and does not erase delivery evidence.

## Safe Telegram linkage

`telegram_connections` contains one service-verified destination per user.
Raw chat IDs are unique, unavailable to `anon` and `authenticated`, and joined
into worker results only through service-role RPCs. The UI receives only
availability, channel, state, and linked time. Revoking a connection disables
all active user rules immediately.

Linking is intentionally operator-mediated for this milestone. First verify the
authenticated account owns the Telegram conversation using an approved support
procedure. Then set these only in a trusted worker shell or managed one-off job:

```powershell
$env:FURUFLOW_LINK_USER_ID = '<verified Supabase user UUID>'
$env:FURUFLOW_LINK_TELEGRAM_CHAT_ID = '<verified Telegram chat ID>'
python telegram_worker.py link-user
```

Revoke without supplying a destination:

```powershell
$env:FURUFLOW_LINK_USER_ID = '<verified Supabase user UUID>'
python telegram_worker.py unlink-user
```

Both commands require the existing `SUPABASE_URL` and service-role secret. They
return only `linked` or `revoked`; no account or routing identifier is printed.
Clear the one-off environment values after use. There is no self-service
Telegram bot handshake yet.

## Automation and monitoring

The Prompt 5 worker lists enabled market rules after each successful scan. A
pool alert matches only the exact canonical pool ID and supported signal fields.
Matches use the existing signal fingerprint and rule/cooldown delivery key, then
enter the existing transactionally persisted queue. Invocation uniqueness,
delivery uniqueness, `FOR UPDATE SKIP LOCKED` claims, bounded retry, ambiguous
outcome handling, abandonment recovery, dead-letter state, and heartbeat health
are unchanged.

After every successful scan, including a legitimate zero-signal result, the
worker records `last_evaluated_at` for evaluated rules and
`last_triggered_at` only for matched rules. The Alerts page shows those values
and the latest authoritative delivery state. It does not infer a delivery from
a trigger. Provider-failed scans do not advance evaluation timestamps;
persistence failures remain separately visible as degraded worker outcomes.

Free users can create eligible Free/all-tier alerts. Pro and admin/lifetime
entitlements can select Pro-tier alerts. Demo access cannot create, resume,
test, or receive external delivery. Checks occur in trusted RPCs and are
rechecked during worker evaluation and delivery claim.

## Manual staging validation

Use only the isolated staging Supabase project, staging worker, synthetic/public
market context, and an approved test Telegram conversation.

1. Apply migrations through `202608160001_prompt6_user_alerts.sql`; run
   `npx supabase test db` and record the passing result.
2. Verify ownership of the approved Telegram conversation, link User A with the
   operator command above, and confirm output contains no identifiers.
3. Sign in as User A, open Alerts, and confirm Telegram reports connected
   without showing a chat ID.
4. Create an alert against a currently qualifying canonical pool shown by the
   existing signal pipeline. Use its observed tier and a threshold at or below
   its current strength.
5. Refresh the browser and rerun the app; confirm exactly one alert persists.
6. Edit strength/timing, refresh, and confirm the edit persists. Pause it, run
   one worker scan, and confirm no delivery is enqueued. Resume it.
7. Open the same pool in Pool Detail, choose **Create alert**, confirm the pool
   is preselected, and cancel or save with a distinct configuration.
8. Sign in as User B in an isolated browser context. Confirm User A's alerts are
   absent and direct requests using User A's alert UUID are rejected. Confirm
   User B cannot create until separately linked.
9. Confirm the chosen pool still appears in a fresh scanner result. Run the
   staging worker once with a new explicit invocation key. Confirm one delivery
   is queued, claimed, and delivered to the approved conversation.
10. Run again with a different invocation key inside the same alert cooldown.
    Confirm the rule is evaluated but no additional logical delivery or
    Telegram message is created.
11. Confirm the alert shows authoritative last-evaluated, last-triggered, and
    latest-delivery state. Confirm `python telegram_worker.py health` reports a
    fresh healthy heartbeat.
12. Use **Send test** once and confirm it enters the durable delivery lifecycle.
    Do not use it as evidence that the market condition matched.
13. Delete the alert; refresh and confirm it is absent. Verify a trusted audit
    query retains its disabled tombstone and prior delivery attempts.
14. Inspect browser URLs, Streamlit/worker logs, and Supabase logs for access or
    refresh tokens, cookies, session tickets, service keys, bot tokens, chat IDs,
    or cross-user alert content. None may appear.
15. Recheck Discover, Pool Detail, Yield Spreads, sign-in, refresh persistence,
    single-session enforcement, logout, Prompt 5 success/retry/dead-letter, and
    worker health behavior.

If no current pool deterministically qualifies, stop the controlled condition
test rather than fabricate a trigger. Local worker/database suites still cover
matching and queue integration; staging sign-off remains pending until a real
qualifying staging signal exists.

## Rollback

Disable or suspend the staging worker before application rollback. Preserve
Prompt 5/6 rules, connections, deliveries, attempts, and runs so idempotency and
ambiguous-outcome evidence survive. Revert the app/worker release while leaving
the additive migration in place. Schema removal requires a separate approved
retention/export plan and must not roll back Prompt 2 account data.
