# Checkpoint C staging runbook

This runbook validates **Subscription Lifecycle -> Entitlement Correctness** in
the existing staging deployment. It is a human-operated release gate, not a
unit-test substitute. Use only the staging Supabase project, the staging
FuruFlow service, and a Stripe sandbox/test-mode account. Never enter a real
card or switch Stripe to live mode.

## Pass rule and evidence record

Create one private evidence record containing:

- deployment commit and UTC start/end times;
- staging origin and Stripe webhook destination name (not secrets);
- User A and User B Supabase UUIDs;
- the relevant `cs_`, `cus_`, `sub_`, and `evt_` test identifiers;
- before/after read-only query results and Stripe delivery response codes;
- PASS/FAIL beside every numbered scenario below.

Provider IDs may be recorded in this controlled operator record, but must not
be pasted into application UI, public tickets, screenshots, or user-visible
logs. Never record the Stripe secret key, webhook signing secret, Supabase
service-role key, browser cookie, access/refresh token, or full webhook body.

Stop immediately on an ownership, invalid-signature, stale-event, or direct
self-grant failure. Do not compensate by editing billing tables.

## 1. Preflight

1. Record the deployed commit. Confirm it is the intended Checkpoint C build.
2. In the Render staging service, confirm `ENVIRONMENT=staging`. Confirm the
   configured Stripe key is test/sandbox mode without displaying or copying it.
3. In Stripe Workbench, confirm the destination is exactly
   `https://STAGING_ORIGIN/stripe/webhook` and subscribes to:
   `checkout.session.completed`, `customer.subscription.created`,
   `customer.subscription.updated`, `customer.subscription.deleted`,
   `invoice.paid`, `invoice.payment_succeeded`, and
   `invoice.payment_failed`.
4. Confirm the configured recurring price/product is the single monthly Pro
   offer. Do not add a plan, coupon, trial, promotion, or usage component.
5. Apply migrations in timestamp order and run the database suite. No
   Checkpoint C migration is expected.
6. Run the repository test suite from the deployed commit.
7. Create or select two active, verified, non-demo staging users. Record their
   UUIDs as `USER_A_UUID` and `USER_B_UUID`.

Use the Supabase SQL editor only for read-only evidence queries such as:

```sql
select user_id, provider_customer_id, provider_subscription_id,
       latest_checkout_session_id, status, current_period_end, cancel_at_period_end,
       last_provider_event_created, last_provider_event_id, created_at, updated_at
from public.subscriptions
where user_id in ('USER_A_UUID', 'USER_B_UUID')
order by user_id;

select user_id, subscription_pro_active, pro_active, lifetime_access, is_admin
from public.entitlements
where user_id in ('USER_A_UUID', 'USER_B_UUID')
order by user_id;
```

Do not `insert`, `update`, or `delete` `subscriptions`, `entitlements`, or
`webhook_events` during this run.

## 2. Baseline and redirect safety

1. Sign in as User A and User B separately. Account & Billing must show Free
   for both, with no manual, lifetime, admin, or demo access obscuring the test.
2. While signed out, manually visit `/?billing=return` and
   `/?billing=cancelled`. Sign in as User B and repeat. These URLs may show a
   notice but must not change either durable query or grant Pro.
3. POST checkout while signed out: expect `401`. From a cross-origin request:
   expect `403`. With any body/query account, customer, subscription, checkout,
   entitlement, or price identifier: expect `400` and no Stripe object.

## 3. User A: Free -> checkout -> durable Pro

1. In User A's authenticated staging browser, select **Upgrade to FuruFlow
   Pro**. Confirm the hosted page is Stripe sandbox/test mode and shows the one
   configured monthly price.
2. Complete Checkout with Stripe's successful interactive test card
   `4242 4242 4242 4242`, any future expiry, and any CVC.
3. Record the resulting `cs_`, `cus_`, `sub_`, and activation `evt_` IDs from
   Stripe's test-mode views. Confirm relevant deliveries returned `2xx`.
4. Read the durable rows. Required: exactly one Stripe subscription row for
   User A, its customer/subscription IDs belong to the Checkout objects, status
   is `active`, and `subscription_pro_active=true`. User B must still have no
   Stripe subscription-derived Pro.
5. Return to Account & Billing. User A must show Pro and an Active subscription.
   The return URL alone is not evidence; the read-only durable rows are.
6. Refresh the page: still Pro. Log out and back in: still Pro. Open a clean
   incognito/private browser, authenticate as User A, and confirm still Pro.
7. Restart/redeploy the same staging commit when operationally practical, then
   repeat one fresh login. User A must still be Pro.

## 4. User B isolation while User A is active

1. Sign in as User B in a separate browser profile. Required: Free.
2. Confirm User B cannot see User A's customer/subscription identifiers.
3. Try the fixed billing routes with User A's UUID and recorded `cus_`, `sub_`,
   and `cs_` values in JSON bodies and query parameters. Every request must be
   rejected before billing service invocation; User A remains Pro and User B
   remains Free.
4. Under User B's authenticated database role, confirm `subscriptions` returns
   no User A row and UPDATE/INSERT on billing or entitlement state is denied.

## 5. Duplicate delivery

1. Open User A's successfully processed activation event in Stripe Workbench
   and click **Resend**, or use:

   ```text
   stripe events resend evt_ID --webhook-endpoint=we_ID
   ```

2. Confirm the resend returns `2xx` and the response reports/behaves as a
   duplicate.
3. Required: one subscription row, unchanged owner, no second entitlement or
   audit grant, User A still Pro, User B still Free.

## 6. Normal subscription update

1. On User A's Stripe test subscription, add a harmless metadata key such as
   `checkpoint_c_revision=1`. Do not alter `furuflow_user_id`, customer, price,
   quantity, or billing cadence.
2. Confirm a newer `customer.subscription.updated` event returns `2xx`.
3. Required: the same internal row and `sub_` identity remain, the event
   ordering tuple advances, status remains active, User A remains Pro, and User
   B is unchanged.

## 7. Scheduled cancellation

1. From FuruFlow as User A, open **Manage billing** and schedule cancellation at
   period end in Stripe's portal.
2. Confirm the `customer.subscription.updated` delivery returns `2xx`.
3. Required durable result: `status='active'`,
   `cancel_at_period_end=true`, `current_period_end` populated, and
   `subscription_pro_active=true`.
4. Required UI result: Pro remains available and Account & Billing says access
   is active until the displayed period end with cancellation scheduled.

## 8. Terminal cancellation and revocation

1. Before terminal cancellation, complete section 10 B4 and prepare the delayed
   older event through B3 steps 1-3. User A must still be active at this point.
2. In Stripe test mode, cancel User A's subscription immediately (or advance an
   already compatible test-clock subscription to its scheduled end). Confirm a
   `customer.subscription.deleted` event returns `2xx`.
3. Required durable result: terminal `canceled` state and
   `subscription_pro_active=false`. User A must be denied Pro-only functions.
4. Refresh: still Free. Log out/in: still Free. Authenticate in a clean browser:
   still Free. Restart/redeploy the same commit when practical and confirm Free.
5. User B remains unchanged.

## 9. Failed-payment/nonpayment behavior

The product intentionally has no trial. Exercise an initial payment failure on
User B without adding one:

1. Start User B's server-created Checkout and use Stripe's
   **decline-after-attaching** test card `4000 0000 0000 0341`, any future
   expiry, and any CVC. Do not complete a second paid subscription for User B in
   this checkpoint run.
2. Observe the signed subscription/invoice events. The applicable durable state
   may be `incomplete` and must leave `subscription_pro_active=false`.
3. Required: User B remains Free, User A's canceled state is unchanged, and no
   redirect or failed invoice grants access.
4. Record which event/status occurred. `past_due`, `unpaid`,
   `incomplete_expired`, and `paused` are also non-entitling under the existing
   strict policy. Automated Python and pgTAP tests cover those deterministic
   mappings plus `past_due -> active` recovery.

If the exact checkout attempt does not emit a mapped nonpayment subscription
event in the configured Stripe sandbox, record it as not practically
reproducible rather than editing the database. A future run may use a Stripe
Simulation/Test Clock only when the FuruFlow-created customer/subscription is
actually attached to that simulation; a separate cloned simulation does not
prove FuruFlow ownership.

## 10. Checkpoint B adversarial regression

### B1: invalid signature

Snapshot both users' durable billing rows, then send a deliberately invalid
signature from a trusted workstation:

```powershell
$stamp = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
Invoke-WebRequest -Method Post -Uri "https://STAGING_ORIGIN/stripe/webhook" `
  -ContentType "application/json" -Body "{}" `
  -Headers @{"Stripe-Signature"="t=$stamp,v1=00"} -SkipHttpErrorCheck
```

Required: HTTP `400`, no webhook-event claim, and no subscription or entitlement
change.

### B2: duplicate

The resend in section 5 must leave one effect and one owner.

### B3: stale/out-of-order distinct event

Use the controlled Checkpoint B delivery-delay procedure, not a duplicate:

1. While User A is active, briefly disable only the staging Stripe destination.
2. Make a harmless subscription metadata update to create an older active
   `customer.subscription.updated` event. Record its `evt_` ID; it must not yet
   be claimed by FuruFlow.
3. Re-enable the destination immediately.
4. Create/process the newer terminal cancellation from section 8 and confirm
   durable cancellation.
5. In Stripe Workbench, manually resend the older, distinct active event.
6. Required: its delivery is safely acknowledged, its `created` value is lower
   than the stored terminal event ordering value, durable state stays canceled,
   and Pro is not resurrected.

Do not run unrelated staging traffic while the destination is disabled.

### B4: ownership conflict

Run this before terminal cancellation if the prior Checkpoint B harness requires
an active subscription:

1. On User A's test subscription only, use the controlled Stripe test command
   from Checkpoint B to emit an update whose `furuflow_user_id` metadata claims
   User B while the customer/subscription IDs remain User A's.
2. Required: fulfillment fails closed, User A keeps the existing ownership and
   entitlement, and User B receives nothing.
3. Restore `furuflow_user_id=USER_A_UUID` in Stripe immediately and confirm the
   resulting legitimate update converges successfully. Never change the
   persisted FuruFlow mapping by hand.

## 11. Minimal frozen-feature smoke gate

Using the same deployment:

- verified login, logout, and session restore pass;
- User A cannot read User B private data and non-admin users cannot enter Admin;
- Discover loads, a filter changes results, and Pool Detail opens;
- each user sees only their own persistent Watchlist/Saved Pools;
- Alerts loads and cross-user alert access is denied;
- Telegram code was not modified, so confirm only its existing worker health/no
  regression signal; do not repeat full delivery validation.

## 12. Freeze decision

Re-run the two read-only queries and the full automated suite. Check application,
Render, Stripe, and browser output for secret/token/cookie leakage. Mark the
checkpoint ready for staging freeze only if every security-critical scenario
passes and the remaining lifecycle rows agree with the UI. Otherwise preserve
the evidence, stop, and report the exact failing invariant.

Stripe references: [test cards](https://docs.stripe.com/testing),
[Billing failure testing](https://docs.stripe.com/billing/testing),
[subscription simulations](https://docs.stripe.com/billing/testing/test-clocks/simulate-subscriptions),
and [manual webhook retries](https://docs.stripe.com/webhooks#event-delivery-behaviors).
