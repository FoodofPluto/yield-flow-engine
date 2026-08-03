# FuruFlow Supabase authentication

## Configuration contract

`SUPABASE_URL` is always the project root:

```text
https://PROJECT_REFERENCE.supabase.co
```

The application rejects API subpaths, malformed URLs, URL credentials,
query/fragment material, placeholder-shaped keys, service-role/secret keys,
missing active redirect configuration, and production-like development values.
No code path repairs, truncates, or guesses an invalid URL.

Environment names:

- `ENVIRONMENT`
- `DEV_MODE`
- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_JWKS_URL` (optional exact derived-endpoint override)
- `SUPABASE_REDIRECT_URL_DEVELOPMENT`
- `SUPABASE_REDIRECT_URL_PREVIEW`
- `SUPABASE_REDIRECT_URL_PRODUCTION`
- `SUPABASE_REDIRECT_URL_TEST` (automated tests only)

`ENVIRONMENT=staging` selects `SUPABASE_REDIRECT_URL_PREVIEW`. The active
redirect must be an absolute base URL without a query string or fragment.
Preview/staging/production require HTTPS, a non-loopback host, no custom port,
and `DEV_MODE=false`.

The application adds an `auth_action` callback marker and a random, single-use
`auth_state` value to the configured base:

- `?auth_action=verify` for signup confirmation;
- `?auth_action=signin` for magic-link sign-in;
- `?auth_action=recovery` for password recovery.

Allowlist the configured callback base/path for each deployed environment in
Supabase Authentication > URL Configuration. Use an exact production callback
path; use provider-supported wildcards only for local/preview host patterns, and
confirm the generated query variants with Supabase's redirect matcher. Use the
actual deployed app URL; do not copy placeholder hosts from `.env.example`.

## Lifecycle behavior

| Flow | Provider operation | Application result |
|---|---|---|
| Signup | Auth signup endpoint with PKCE challenge and explicit verification redirect | Immediate verified sessions are accepted; otherwise a non-enumerating verification-pending result is shown. |
| Verification | Authorization-code callback exchange | The code is exchanged server-side, the user is fetched authoritatively, and callback parameters are removed. |
| Password login | `sign_in_with_password` | Provider user state and `email_confirmed_at` must be valid before local identity resolution. |
| Magic link | Auth OTP endpoint with PKCE challenge and implicit signup disabled | Explicit sign-in redirect; callback accepts authorization-code flow only. |
| Refresh | `refresh_session` | Rotated access/refresh values replace the in-memory session; failures clear it. |
| Logout | global provider sign-out | Provider refresh sessions are revoked when reachable; local state is always cleared. |
| Forgot password | Auth recovery endpoint with PKCE challenge | Non-enumerating request result with explicit recovery redirect. |
| Reset completion | recovery code exchange, then `update_user` | Requires the live recovery session and a 12-character minimum password. |
| Expired session | unverified expiry hint followed by provider refresh | Identity is never trusted from the unverified payload; no refresh means fail closed. |
| Revoked/deleted/banned user | authoritative `get_user` failure/state | Session is cleared and access is denied. |
| Duplicate email | provider duplicate response/error | Same verification-pending message; account existence is not disclosed. |

Mutable `user_metadata` is never verification or authorization truth. Tokens are
not included in the returned identity dictionary and never reach SQLite.
An authoritative identity result is cached in the current Streamlit session for
at most 60 seconds to avoid repeated provider calls during one app rerun; a
revoked/deleted/banned account is denied on the next revalidation (or sooner if
refresh fails).

## Callback URL hygiene

Only `code` callbacks with a matching, unexpired, single-use PKCE state are
accepted. The code verifier remains in bounded server memory and is consumed
before exchange. Query-delivered access/refresh tokens are rejected. After
every callback attempt, the app removes `code`, token fields, provider errors,
expiry fields, callback type, `auth_action`, and `auth_state` from the visible
URL while preserving unrelated application parameters.

## Session strategy and bridge boundary

The current safe implementation uses `StreamlitMemorySessionStore`:

- tokens exist only in per-WebSocket server-side `st.session_state`;
- state survives normal Streamlit reruns;
- browser refresh, websocket loss, process restart, and a new browser require
  authentication again;
- no JavaScript/localStorage/sessionStorage/custom-component cookie store is
  used;
- provider clients are created per operation so SDK memory is not shared across
  Streamlit users.

Pending PKCE verifiers are also process-memory-only, expire after 10 minutes,
and are keyed by a random callback state. A process restart or a callback routed
to another unshared application instance requires a new email link. Multi-
instance continuity is another responsibility of the secure backend session
bridge, not a reason to put the verifier or tokens into browser storage.

`auth_session.SecureSessionBridge` is the code boundary for future persistence.
A production implementation requires a separate HTTPS backend/reverse-proxy
component because Streamlit cannot safely issue and manage the required cookie.
That service must:

1. exchange callbacks and retain provider tokens only in an encrypted,
   server-side session store;
2. issue a random opaque `__Host-furuflow_session` cookie with `Secure`,
   `HttpOnly`, `SameSite=Lax`, `Path=/`, and no `Domain`;
3. rotate the opaque ID on authentication/privilege change and enforce absolute
   and idle expiry;
4. expose authenticated identity/session introspection to Streamlit without
   returning provider tokens to the browser;
5. refresh and revoke provider sessions server-side; and
6. enforce callback state/PKCE, CSRF protection for mutations, rate limits, and
   redacted audit events.

Raw Supabase tokens must never become cookies, query parameters, browser
storage, logs, or local application database values.

## Deployment diagnostic

Run in each deployment with its configured environment:

```powershell
poetry run python scripts/check_supabase_auth_health.py
```

The script exits nonzero unless configuration validation, DNS resolution, Auth
health, non-empty JWKS, and the Auth settings request using the configured key
all pass. Output contains only check status and bounded failure reasons. It does
not print URLs, keys, headers, response bodies, tokens, or provider exceptions.

Authentication state logs use bounded event/outcome/reason codes. They omit
email addresses, user IDs, tokens, callback codes, provider response bodies, and
exception text.

## Manual staging verification

1. Confirm the staging `SUPABASE_URL` is the exact project root and belongs to
   the intended project; confirm the publishable/anon key comes from that same
   project.
2. Add the configured staging callback base/path to the Supabase redirect
   allowlist, verify its generated query variants are accepted, and set the Site
   URL deliberately.
3. Run the deploy diagnostic and retain its redacted pass/fail output.
4. Create a new staging address. Confirm signup shows pending verification and
   the message arrives with the staging callback.
5. Open the verification link. Confirm the code is exchanged once, the account
   is verified, and callback parameters disappear from the address bar.
6. Sign out. Confirm global sign-out and that a refresh attempt with the old
   session fails.
7. Test correct and incorrect password login; verify unconfirmed users are
   denied with useful, non-enumerating messages.
8. Request a magic link for an existing user. Confirm it signs in without
   creating an unknown account and that reuse/expiry fails safely.
9. Wait through an access-token expiry or use the staging JWT expiry setting;
   confirm refresh rotates the session without exposing values.
10. Request password recovery, open the recovery link, choose a new password,
    and confirm the old password fails while the new password succeeds.
11. Delete or ban a staging user in the dashboard and confirm the next
    authoritative validation denies access and clears local state.
12. Repeat signup with an existing email and confirm the UI does not disclose
    whether that account exists.
13. Inspect deployment logs and the local SQLite database for the staging token
    sentinels; confirm neither access nor refresh values appear.
14. Repeat callback and redirect checks on the preview hostname and production
    hostname before promoting traffic.

## Configuration migration and rollback

No database migration is included in this authentication-only change.

Configuration migration:

1. Record the existing deployment settings through the provider secret manager
   without copying values into repository files or tickets.
2. Replace `SUPABASE_URL` with the exact live project root and replace the key
   only with the matching project publishable/anon key.
3. add the three environment-specific redirect variables and dashboard
   allowlist entries;
4. remove the obsolete local JWT-secret setting if present; authoritative user
   validation no longer requires it; and
5. run automated tests and the deployment diagnostic before enabling sign-in.

Rollback the code through the normal version-control/deployment release
mechanism. Roll back environment settings by restoring the previous secret
manager version only if those values were themselves valid. Never restore a
`SUPABASE_URL` containing `/rest/v1` or another API path. If a valid prior auth
configuration is unavailable, disable verified sign-in and leave public/free
behavior available rather than weakening validation or persisting browser
tokens.
