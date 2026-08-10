# FuruFlow Supabase account control plane

## Authority and migration

Apply `supabase/migrations/202608050001_prompt2_account_control_plane.sql` with
the Supabase CLI linked to the intended staging project, inspect the generated
diff, and then run:

```powershell
supabase db push
```

The migration creates `profiles`, `entitlements`, `subscriptions`,
`admin_audit`, `webhook_events`, `account_sessions`, `browser_sessions`, and
`browser_session_tickets`. Every user-owned row is keyed to `auth.users.id`.
New verified accounts receive a privilege-free profile and entitlement row.
Existing verified Auth users receive the same zero-privilege reconciliation.

`furuflow.db` is not read by application authorization, session enforcement,
admin operations, or Stripe fulfillment. Preserve it only as a read-only
migration input and rollback artifact until migration acceptance is signed off.

## RLS contract

RLS is enabled on every control-plane table. There are no broad authenticated
policies:

- a user can select only the profile whose `id = auth.uid()`;
- a user can update only their own `display_name` and `timezone` columns;
- a user can select only entitlement and subscription rows whose `user_id = auth.uid()`;
- authenticated users receive no insert, update, or delete privilege on
  entitlements, subscriptions, audits, webhook events, or session tables;
- session claim/touch/revoke functions bind their work to `auth.uid()`;
- all role, billing, migration, webhook, demo-cleanup, and bootstrap functions
  require the `service_role` JWT role;
- every changed entitlement is written to `admin_audit` in the same database
  function. Repeating an already-applied change is a no-op and does not create
  duplicate audit noise.

The service-role key belongs only in the account CLI, Stripe backend, and
session-broker process. It must not exist in Streamlit's environment.

Run the database isolation suite against the disposable local Supabase stack:

```powershell
supabase test db
```

`supabase/tests/database/account_rls_test.sql` exercises two users, cross-user
visibility, protected-column grants, self-escalation denial, service-role-only
mutation, first-admin bootstrap, and audit creation inside a rolled-back test
transaction.

## Exact first-admin bootstrap

1. Create the user through normal Supabase signup and complete email
   verification.
2. Copy the user's UUID from Supabase Authentication > Users. Do not use or
   configure an email address as the role boundary.
3. In a trusted administrative shell—not the Streamlit host—set the project
   root, publishable key, test/deployment redirect required by configuration,
   and `SUPABASE_SERVICE_ROLE_KEY` through the platform's secret manager.
4. Run:

```powershell
.\.venv\Scripts\python.exe scripts\manage_accounts.py bootstrap-admin `
  --user-id 00000000-0000-0000-0000-000000000000 `
  --reason initial_verified_admin
```

The database rejects an unverified/deleted UUID and rejects a different target
after an admin exists. Re-running the same UUID prints that no change was
needed. The first successful run creates `bootstrap_admin` in `admin_audit`.

Subsequent examples:

```powershell
# Grant or revoke admin, Pro, or compatibility-only lifetime access.
.\.venv\Scripts\python.exe scripts\manage_accounts.py set --user-id TARGET_UUID `
  --actor-user-id ADMIN_UUID --entitlement pro --enabled true --reason support_case_123

.\.venv\Scripts\python.exe scripts\manage_accounts.py set --user-id TARGET_UUID `
  --actor-user-id ADMIN_UUID --entitlement admin --enabled false --reason role_rotation
```

Lifetime is retained only for explicit compatibility. Stripe never infers or
grants lifetime access from a one-time checkout.

## Constrained demo

Demo access is an entitlement on a verified, otherwise-free account. It can be
issued only for `development`, `staging`, or `test`, for at most 24 hours:

```powershell
.\.venv\Scripts\python.exe scripts\manage_accounts.py set --user-id DEMO_UUID `
  --actor-user-id ADMIN_UUID --entitlement demo --enabled true `
  --environment staging --demo-minutes 60 --reason product_walkthrough
```

The database rejects demo grants to admin, Pro, lifetime, or actively billed
accounts and rejects later privileged/billing grants while demo is active.
Application authorization checks both the stored environment and expiry.
Demo watchlist changes remain only in that Streamlit session; persisted product
state is read-only. `external_delivery_allowed()` is false and the application
binds `set_demo_side_effect_block(True)` to the request context, so Telegram,
email, Discord, X, webhook, and alert transports fail before network I/O.
Database functions separately reject Stripe/billing changes for active demos.
The UI does not expose credentials.

The migration installs the `furuflow-demo-cleanup` pg_cron job every five
minutes. The trusted CLI provides an idempotent manual maintenance/fallback:

```powershell
.\.venv\Scripts\python.exe scripts\manage_accounts.py cleanup-demos
```

Expiry already denies access without the job. Cleanup clears expired demo
fields, revokes its server/browser sessions, removes used/expired activation
tickets, and deletes expired revoked browser-session rows.

Use a separate staging/demo Supabase project and public/synthetic data plane.
Do not point demo configuration at production data or delivery credentials.

## Browser-refresh session bridge

`session_broker.py` is a separate Flask sidecar. It encrypts provider tokens
with a Fernet key known only to the broker and stores them in RLS-protected
Supabase rows. The browser receives only a random
`__Host-furuflow_session` cookie with `Secure`, `HttpOnly`, `SameSite=Lax`, and
`Path=/`. A two-minute, single-use activation ticket establishes that cookie.

Deployment separation:

- broker only: `SUPABASE_SERVICE_ROLE_KEY` and
  `FURUFLOW_SESSION_ENCRYPTION_KEY`;
- broker and Streamlit: a random 32+ character
  `FURUFLOW_SESSION_BRIDGE_KEY` over a private network;
- Streamlit only: `FURUFLOW_SESSION_BROKER_INTERNAL_URL` and the same-origin
  `FURUFLOW_SESSION_BROKER_PUBLIC_ORIGIN`;
- reverse proxy: route `/auth/session/activate` on the Streamlit public origin
  to the broker. Do not expose `/v1/session/*` publicly.

The staging Render Blueprint, environment boundary matrix, and exact operator
sequence are in `RENDER_STAGING_DEPLOYMENT.md`.

Generate the encryption key in the trusted broker environment:

```powershell
.\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

After activation, an ordinary refresh sends only the opaque cookie. Streamlit
restores encrypted server state through the private broker, then authoritatively
validates/refreshes against Supabase Auth. Missing, revoked, expired,
undecryptable, or provider-rejected state returns no identity and fails closed.
Logout globally revokes the provider session, the account session, and the
browser session.

## Reviewed SQLite migration and rollback

First make a recoverable copy and restrict the original to migration use:

```powershell
Copy-Item -LiteralPath .\furuflow.db -Destination .\furuflow.pre-supabase-migration.db
```

Create a reviewed mapping file. Every entry must include the legacy internal
UUID, the verified Supabase UUID, and explicit decisions for every privilege:

```json
[
  {
    "legacy_user_id": "LEGACY_INTERNAL_UUID",
    "supabase_user_id": "VERIFIED_SUPABASE_UUID",
    "reviewed_entitlements": {"admin": false, "pro": false, "lifetime": false}
  }
]
```

Dry-run and inspect the redacted report and rollback snapshot:

```powershell
.\.venv\Scripts\python.exe scripts\migrate_legacy_accounts.py migrate `
  --sqlite .\furuflow.db --mapping .\reviewed-account-map.json `
  --report .\account-migration-report.json --rollback-out .\account-migration-rollback.json `
  --actor-user-id ADMIN_UUID
```

The CLI resolves each UUID through the Supabase Auth admin endpoint, requires
an active verified identity, and checks that the reviewed UUID corresponds to
the legacy row. Legacy flags are reported but never copied implicitly. Reports
contain IDs and decisions, not emails, passwords, tokens, keys, or callback
codes. Add `--apply` only after review. Re-running is idempotent.

Rollback remote entitlements and then deploy the prior application revision:

```powershell
.\.venv\Scripts\python.exe scripts\migrate_legacy_accounts.py rollback `
  --rollback .\account-migration-rollback.json --actor-user-id ADMIN_UUID
```

Keep the database copy, reviewed mapping, report, and rollback output in an
access-controlled operational archive, not in Git. Do not delete SQLite until
staging reconciliation and the rollback window are complete.
