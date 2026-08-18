# Production billing and subscription fulfillment

## Authority and data flow

FuruFlow keeps Supabase Auth UUIDs as the account boundary. The authoritative
flow is:

`verified Supabase identity -> opaque broker session -> trusted checkout -> Stripe customer/subscription -> signed webhook -> subscriptions -> subscription_pro_active -> normal authorization`

Streamlit receives neither Stripe secrets nor the Supabase service-role key. The
browser POSTs only to fixed `/billing/checkout` or `/billing/portal` paths. The
sidecar resolves the `__Host-furuflow_session` cookie, revalidates its encrypted
Supabase access token with Auth, and checks that the returned UUID matches the
stored browser-session owner. Request bodies cannot select an account, customer,
subscription, status, or entitlement.

Nginx exposes exactly three billing surfaces from the sidecar:

- `POST /billing/checkout` — same-origin request plus verified opaque session;
- `POST /billing/portal` — same controls, with customer and subscription resolved server-side;
- `POST /stripe/webhook` — public for Stripe, but every request requires a valid Stripe signature.

Internal `/v1/session/*` routes remain unavailable through Nginx.

## Environment and startup safety

The trusted broker requires:

- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `STRIPE_PRICE_ID`
- `STRIPE_PRODUCT_ID`
- `FURUFLOW_SESSION_BROKER_PUBLIC_ORIGIN`
- the existing Supabase service-role, session encryption, and bridge variables

Development, test, preview, and staging reject `sk_live_` keys. Production
requires an explicit `sk_live_` key and structurally valid `whsec_`, `price_`,
and `prod_` values. Non-production never falls back to production Stripe
configuration. The supervisor refuses to start the deployed container when a
required broker variable is absent. Values in `.env.example` are placeholders.

The Render staging service must use Stripe test mode. Creating or validating a
live-mode purchase is outside Prompt 8.

## Checkout and customer association

Checkout is available only to a verified, active, non-anonymous, non-demo
identity. The service-role RPC repeats the verified-user and demo checks, so a
bad caller cannot bypass them. Customer creation uses a stable environment/user
idempotency key, then `service_set_stripe_customer` binds exactly one Stripe
customer to one FuruFlow UUID. The partial unique customer index prevents one
customer from belonging to multiple accounts.

Checkout uses only the configured monthly Pro price. FuruFlow supplies its UUID
as Stripe metadata and `client_reference_id` from trusted server state. Success
and cancel URLs contain only `billing=return` or `billing=cancelled`; neither is
an access claim. Account state changes only after signed webhook fulfillment.

## Webhook lifecycle and ordering

Stripe signature verification happens before `webhook_events` is touched.
Valid events are claimed by `service_begin_webhook_event`; processed duplicates
return success without applying state again. Failed fulfillment is marked with
the bounded code `fulfillment_failed` and can be retried. Unknown valid events
are recorded as processed and ignored.

Handled events are:

- `checkout.session.completed` for subscription mode (the subscription is retrieved and checked);
- `customer.subscription.created`, `.updated`, and `.deleted`;
- `invoice.paid`, `invoice.payment_succeeded`, and `invoice.payment_failed` (the subscription is retrieved).

Every subscription must contain both the configured Pro price and product.
Customer/subscription mappings must agree with optional FuruFlow metadata. A
cross-user conflict fails fulfillment without changing either account.

`subscriptions.last_provider_event_created` and
`last_provider_event_id` form the ordering key. An event applies only when its
`(created, id)` tuple is greater than the stored tuple. This makes equal-second
events deterministic and prevents older deliveries from overwriting newer
state, regardless of arrival order.

Webhook records retain event ID, type, state, attempt count, timestamps, and a
bounded safe error code. FuruFlow does not store card data, raw signatures,
invoice bodies, or payment-method details, and logs do not include provider IDs.

## Entitlement rule

There is one subscription rule: **only stored Stripe status `active` sets
`entitlements.subscription_pro_active = true`.** `past_due`, `unpaid`,
`paused`, `incomplete`, `incomplete_expired`, `trialing`, `inactive`, and
`canceled` do not grant subscription-derived Pro. An active subscription with
`cancel_at_period_end=true` remains active until Stripe reports the effective
end state.

Application authorization continues through `auth_service.can_access_pro` and
is the OR of independently trusted components:

- administrator;
- lifetime access;
- manual/admin Pro (`pro_active`);
- subscription Pro (`subscription_pro_active`);
- an environment-bound, unexpired non-production demo.

Subscription cancellation changes only `subscription_pro_active`; it cannot
remove administrator, lifetime, or manual Pro access. Ordinary authenticated
clients can read only safe subscription summary columns and cannot read provider
IDs or write either subscription or entitlement state.

An operator can repair the derived flag from stored subscription state with:

```powershell
.\.venv\Scripts\python.exe scripts\reconcile_billing.py --user-id VERIFIED_SUPABASE_UUID
```

This requires the service-role key and creates an audit record only when a
repair occurs. It does not call Stripe. If stored subscription state itself is
suspect, inspect Stripe in test/staging mode and resend the authoritative event
before running reconciliation.

## Account & Billing and portal behavior

Account & Billing shows only Free/Pro, a safe access-source label, translated
subscription status, and a trustworthy renewal/end date. It never renders
Stripe IDs, webhook IDs, configuration, or raw provider errors. A checkout
return shows only that the user returned; it never claims payment succeeded.
Identity and non-billing account state remain visible during Stripe outages.

The portal endpoint accepts no customer ID. It opens only when the current
verified identity has a server-mapped customer and subscription, and returns the
short-lived Stripe portal URL via a `303` redirect. Card and cancellation
management remain in Stripe's portal.

## Migration and rollback/containment

Apply `202608170002_prompt8_production_billing.sql` after all Prompt 2–7
migrations, then run the complete pgTAP suite. The migration is additive except
for replacing the Prompt 2 Stripe apply RPC and narrowing authenticated
subscription column reads. Existing rows whose entitlement `source='stripe'`
are moved from the old combined `pro_active` flag to
`subscription_pro_active`.

Containment, in order:

1. Disable `/billing/checkout` and `/billing/portal` at Nginx or unset the Stripe price; do not alter existing entitlements.
2. Disable the Stripe webhook endpoint in Stripe if fulfillment is unsafe; retain `webhook_events` for diagnosis.
3. Restore the application/sidecar release while keeping the additive columns and data.
4. Re-enable only after the mapping and latest provider event for affected UUIDs are reconciled.

Do not drop Prompt 2 tables or erase billing rows during incident containment.
A schema rollback may revoke the three new service RPCs and restore the prior
authenticated column grant, but dropping the new columns loses ordering and
subscription-source separation and therefore requires an explicit data backup
and maintenance window.

## Controlled Prompt 8 staging checklist

Use a dedicated Stripe test-mode price/product, webhook secret, and two staging
users. Never use a live key.

1. Apply migrations in timestamp order and run `supabase test db`; record all passing tests.
2. Sign in as verified Free User A and confirm Account & Billing says Free.
3. Confirm signed-out and demo sessions cannot POST checkout and create no Stripe customer.
4. From User A, start exactly one test checkout and verify Stripe is in test mode before entering test card data.
5. Complete checkout and confirm signed lifecycle events reach `/stripe/webhook` with successful responses.
6. Using trusted operator access, confirm one subscription row maps to User A's UUID (do not paste provider IDs into tickets/logs).
7. Confirm Pro appears only after the signed active-subscription event is processed.
8. Refresh/reopen the browser and confirm opaque-session restoration preserves the same Pro account.
9. Confirm Account & Billing shows safe Active/renewal state and no provider identifiers.
10. Open Manage billing; confirm the portal belongs to User A and returns safely to FuruFlow.
11. Schedule cancellation in the portal; confirm access remains through an active paid period, then simulate/end the test subscription and confirm subscription Pro is removed.
12. Resend a processed Stripe event and confirm no duplicate state, audit grant, or access extension.
13. Sign in as User B; confirm no view or action reveals or changes User A's mapping or plan.
14. Inspect browser URLs, rendered HTML, Render logs, and exceptions for secrets, signatures, raw customer/subscription/webhook IDs, or payment data.
15. Re-run Prompt 2 auth/session checks plus minimal Discover/Pool Detail, Telegram worker, Alerts, and Watchlist checks.

Local tests prove deterministic code and database behavior only; they are not
proof that the remote Stripe webhook, portal configuration, or Render routing is
correct. Prompt 8 becomes frozen only after this separate staging gate passes.

