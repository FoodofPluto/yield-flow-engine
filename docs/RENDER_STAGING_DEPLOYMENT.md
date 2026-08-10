# Render staging deployment

This runbook deploys the existing Prompt 2 session architecture to staging. It
does not change authentication or account-control authority. The public Render
web service is the only browser-visible origin; Streamlit and the Flask session
broker are Render private services in `ohio`.

## Deployed services

| Render service | Type | Listener | Responsibility |
|---|---|---:|---|
| `furuflow-staging` | public web service | Render-provided `PORT` | Nginx same-origin reverse proxy |
| `furuflow-staging-streamlit` | private service | `8501` | `streamlit run app.py` |
| `furuflow-staging-session-broker` | private service | `8510` | Gunicorn serving `session_broker:create_app()` |

`render.yaml` obtains both private upstreams through Render Blueprint
`hostport` references. It never uses either private service's public URL; private
services do not have public URLs. The proxy routes only the exact
`/auth/session/activate` path to the broker, returns `404` for
`/v1/session` and `/v1/session/*`, and sends all remaining HTTP and WebSocket
traffic to Streamlit.

The broker remains the only process with the Supabase service-role and session
encryption credentials. Nginx disables access logging on the activation route
so the single-use ticket query is not written to its access log. Gunicorn's
access log is intentionally not enabled for the same reason.

## Environment-variable matrix

`sync: false` means Render prompts for the value during initial Blueprint
creation. `fromService` values are populated by Render and use the private
network where noted. No credential value belongs in Git.

| Variable | Public proxy | Private Streamlit | Private broker | Source |
|---|:---:|:---:|:---:|---|
| `PORT` | yes | no | no | Render default |
| `PYTHON_VERSION` | no | yes | yes | Blueprint: `3.12.10` |
| `ENVIRONMENT` | no | yes | no | Blueprint: `staging` |
| `DEV_MODE` | no | yes | no | Blueprint: `false` |
| `SUPABASE_URL` | no | yes | yes | Render secret input; use the same staging project root on both |
| `SUPABASE_ANON_KEY` | no | yes | no | Render secret input |
| `SUPABASE_SERVICE_ROLE_KEY` | no | no | yes | Render secret input |
| `SUPABASE_REDIRECT_URL_PREVIEW` | no | yes | no | Public proxy `RENDER_EXTERNAL_URL` |
| `SUPABASE_REDIRECT_URL_PRODUCTION` | no | yes | no | Public proxy `RENDER_EXTERNAL_URL` |
| `FURUFLOW_SESSION_BROKER_INTERNAL_HOSTPORT` | no | yes | no | Broker private `hostport`; startup-only helper |
| `FURUFLOW_SESSION_BROKER_INTERNAL_URL` | no | yes | no | Constructed at process start as `http://` plus the broker private `hostport` |
| `FURUFLOW_SESSION_BROKER_PUBLIC_ORIGIN` | no | yes | no | Public proxy `RENDER_EXTERNAL_URL` |
| `FURUFLOW_SESSION_BRIDGE_KEY` | no | yes | yes | Generated once on the broker and copied to Streamlit by `fromService` |
| `FURUFLOW_SESSION_ENCRYPTION_KEY` | no | no | yes | Render secret input; Fernet key |
| `STREAMLIT_UPSTREAM` | yes | no | no | Streamlit private `hostport` |
| `SESSION_BROKER_UPSTREAM` | yes | no | no | Broker private `hostport` |

The staging application needs `SUPABASE_REDIRECT_URL_PREVIEW` because the
existing configuration maps `ENVIRONMENT=staging` to that name. The Blueprint
also supplies the requested `SUPABASE_REDIRECT_URL_PRODUCTION`; both resolve to
the same staging proxy origin. Neither variable contains provider credentials.

Explicitly verify in the Render dashboard that the Streamlit service does not
contain `SUPABASE_SERVICE_ROLE_KEY` or `FURUFLOW_SESSION_ENCRYPTION_KEY`, and
that the proxy contains none of the four session/Supabase credentials.

## Exact staging deployment sequence

1. In a separate staging Supabase project, apply and verify
   `supabase/migrations/202608050001_prompt2_account_control_plane.sql` as
   described in `ACCOUNT_CONTROL_PLANE.md`. Confirm `browser_sessions` and
   `browser_session_tickets` exist. Do not use the production Supabase project.
2. In a trusted local shell, generate a Fernet key for
   `FURUFLOW_SESSION_ENCRYPTION_KEY`:

   ```powershell
   .\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

   Retain it only in the secret manager or another approved secret store. The
   Blueprint generates `FURUFLOW_SESSION_BRIDGE_KEY`; do not replace it with an
   application or Supabase credential.
3. Commit the reviewed deployment files and push branch
   `feat/supabase-auth-demo-access` to the repository connected to Render.
4. In Render, choose **New > Blueprint**, connect `yield-flow-engine`, select
   branch `feat/supabase-auth-demo-access`, and use the root `render.yaml`.
   Confirm the preview shows exactly one public web service and two private
   services, all in `ohio` on the `starter` plan.
5. During initial Blueprint creation, enter only these `sync: false` values:
   - on `furuflow-staging-streamlit`: `SUPABASE_URL` and
     `SUPABASE_ANON_KEY` from the staging Supabase project;
   - on `furuflow-staging-session-broker`: the same `SUPABASE_URL`, the staging
     `SUPABASE_SERVICE_ROLE_KEY`, and the generated
     `FURUFLOW_SESSION_ENCRYPTION_KEY`.
6. Apply the Blueprint and wait for all three initial deploys to become live.
   The broker must show an internal address on port `8510`, Streamlit an
   internal address on port `8501`, and only `furuflow-staging` an external
   `https://...onrender.com` URL. Do not create a public broker or Streamlit
   service as a workaround for a failed private-network check.
7. Copy the public proxy's `RENDER_EXTERNAL_URL`. In the staging Supabase
   Authentication URL configuration, set the staging Site URL deliberately and
   add that exact HTTPS origin/path to the redirect allowlist. The Blueprint
   supplies that same URL to `SUPABASE_REDIRECT_URL_PREVIEW`,
   `SUPABASE_REDIRECT_URL_PRODUCTION`, and
   `FURUFLOW_SESSION_BROKER_PUBLIC_ORIGIN`.
8. Open a Render shell on the private Streamlit service and run the redacted
   deployment diagnostic:

   ```bash
   python scripts/check_supabase_auth_health.py
   ```

   It must pass before staging sign-in testing.
9. From a trusted workstation, replace `STAGING_ORIGIN` below with the proxy's
   external URL and verify routing:

   ```bash
   curl -i "STAGING_ORIGIN/healthz"
   curl -i "STAGING_ORIGIN/_stcore/health"
   curl -i "STAGING_ORIGIN/v1/session/restore"
   curl -i "STAGING_ORIGIN/auth/session/activate"
   ```

   Expected results are `200`, `200`, `404`, and `400`, respectively. The final
   `400` is the broker's safe response to a missing/expired ticket and confirms
   only the activation endpoint is publicly routed.
10. Complete signup/sign-in on the public proxy origin, then refresh the page
    and reconnect the Streamlit WebSocket. In browser developer tools, verify
    the cookie is named `__Host-furuflow_session`, is host-only (no `Domain`),
    and has `Secure`, `HttpOnly`, `SameSite=Lax`, and `Path=/`. Confirm refresh
    restores the identity and logout revokes it.
11. Inspect proxy, Streamlit, and broker logs for the staging test. Activation
    tickets, opaque cookie values, Supabase access/refresh tokens, and secret
    values must not appear. Complete the manual staging verification in
    `AUTHENTICATION.md` before accepting the deployment.

For this first staging deployment, use the Render-provided external URL as the
browser-visible origin. If a custom staging domain is introduced later, update
all three public-origin/redirect variables together to that exact HTTPS origin
before sending traffic; otherwise the `__Host-` cookie would be scoped to the
wrong host. Production promotion is intentionally outside this runbook.

## Cookie and routing invariants

`session_broker.py` issues the cookie with `secure=True`, `httponly=True`,
`samesite="Lax"`, `path="/"`, and no `domain` argument. The proxy passes the
broker's `Set-Cookie` header unchanged and does not configure cookie-domain or
cookie-path rewriting. Therefore activation on the proxy origin produces the
required host-only `__Host-furuflow_session` cookie.

The public Nginx configuration has no general broker upstream. Only the exact
activation location references the broker; both public `/v1/session` forms are
terminated by Nginx. Streamlit reaches `/v1/session/*` directly over Render's
private network using the shared bridge key.
