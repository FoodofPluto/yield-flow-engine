# Render staging deployment

This runbook packages the existing Prompt 2 secure browser-session architecture
into one Render Free Web Service and adds one isolated Starter cron job for the
Prompt 5 durable Telegram worker. It is a testing
topology, not the recommended production topology. It does not change
authentication, account-control authority, RLS, entitlements, or cookie
semantics.

## Free staging/testing topology

The browser application remains a single Free Web Service. The Telegram cron
job is a separate paid Starter service because Render does not provide Free
cron jobs. A worker failure therefore cannot terminate the web container. See
`docs/TELEGRAM_AUTOMATION.md` for migration, secrets, controlled testing,
monitoring, disable, and rollback procedures.

The single Docker container runs three supervised processes:

| Process | Bind address | Unix identity | Public reachability |
|---|---|---|---|
| Nginx | `0.0.0.0:$PORT` | root master / `www-data` workers | Render's only public listener |
| Streamlit `app.py` | `127.0.0.1:8501` | `furuflow-streamlit` | Nginx only |
| Gunicorn `session_broker:create_app()` | `127.0.0.1:8510` | `furuflow-broker` | Nginx activation route and Streamlit only |

Nginx routes only the exact `/auth/session/activate` path to the broker,
returns `404` for `/v1/session` and `/v1/session/*`, and proxies every other
HTTP request and Streamlit WebSocket upgrade to `127.0.0.1:8501`. The broker
has no listener on an external interface. `FURUFLOW_SESSION_BROKER_INTERNAL_URL`
is fixed to `http://127.0.0.1:8510`.

The supervisor treats any Nginx, Streamlit, or Gunicorn exit as a container
failure. It terminates the remaining children and exits nonzero, allowing
Render to expose and restart the failed service instead of leaving a partial
deployment running.

## Process environment boundaries

The Render service necessarily has the union of the Streamlit and broker
settings. `deploy/render/supervise.py` creates separate child environments and
separate non-root Unix identities:

| Variable | Supervisor initially | Nginx | Streamlit | Broker |
|---|:---:|:---:|:---:|:---:|
| `PORT` | yes | no; rendered into config | yes | no |
| `ENVIRONMENT` | yes | no | yes | no |
| `DEV_MODE` | yes | no | yes | no |
| `SUPABASE_URL` | yes | no | yes | yes |
| `SUPABASE_ANON_KEY` | yes | no | yes | no |
| `SUPABASE_SERVICE_ROLE_KEY` | yes | no | **no** | yes |
| `SUPABASE_REDIRECT_URL_PREVIEW` | yes | no | yes | no |
| `SUPABASE_REDIRECT_URL_PRODUCTION` | yes | no | yes | no |
| `FURUFLOW_SESSION_BROKER_INTERNAL_URL` | yes | no | yes, forced to loopback | no |
| `FURUFLOW_SESSION_BROKER_PUBLIC_ORIGIN` | yes | no | yes | no |
| `FURUFLOW_SESSION_BRIDGE_KEY` | yes | no | yes | yes |
| `FURUFLOW_SESSION_ENCRYPTION_KEY` | yes | no | **no** | yes |

Nginx receives only a small execution environment and no `SUPABASE_*` or
`FURUFLOW_*` values. The broker receives only its four required application
variables plus a small execution environment. Streamlit receives the service
environment after `SUPABASE_SERVICE_ROLE_KEY` and
`FURUFLOW_SESSION_ENCRYPTION_KEY` have been removed. The supervisor also
removes those two values from its own environment after starting the broker.

This lets the existing production guard in `auth_session.py` continue to reject
an unsafe Streamlit environment. The guard is not weakened or bypassed.

## Same-origin cookie and log invariants

The public Render HTTPS URL remains the only browser-visible origin. The broker
response passes through Nginx without cookie-domain or cookie-path rewriting.
`session_broker.py` therefore continues to issue a host-only
`__Host-furuflow_session` cookie with `Secure`, `HttpOnly`, `SameSite=Lax`,
`Path=/`, and no `Domain` attribute.

Nginx disables access logging for `/auth/session/activate`. Its general log
format records `$uri`, not `$request_uri`, so query strings such as auth codes
and activation tickets are not logged. Gunicorn access logging remains disabled.

## Exact Free Render creation sequence

1. Use a separate staging Supabase project. Apply and verify
   `supabase/migrations/202608050001_prompt2_account_control_plane.sql` as
   described in `ACCOUNT_CONTROL_PLANE.md`. Confirm `browser_sessions` and
   `browser_session_tickets` exist. Do not use the production project.
2. In a trusted local shell, generate a Fernet key for
   `FURUFLOW_SESSION_ENCRYPTION_KEY`:

   ```powershell
   .\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

   Store it only in Render's secret settings or another approved secret store.
   The Blueprint generates an independent `FURUFLOW_SESSION_BRIDGE_KEY`.
3. Before pushing, run the local validation commands in this runbook. Commit
   the reviewed files and push `feat/supabase-auth-demo-access`.
4. In Render, choose **New > Blueprint**, connect `yield-flow-engine`, select
   branch `feat/supabase-auth-demo-access`, and use the root `render.yaml`.
   Confirm the preview contains one Docker web service named
   `furuflow-staging` (`free`) and one Docker cron service named
   `furuflow-telegram-worker-staging` (`starter`), both in `ohio`. There must be
   no private service or separately public Streamlit/broker service.
5. During initial Blueprint creation, provide the web service's four `sync: false` values:
   `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, and
   `FURUFLOW_SESSION_ENCRYPTION_KEY`. Use only values from the staging Supabase
   project. Do not paste any value into `render.yaml` or another tracked file.
   Separately provide the cron service's `SUPABASE_URL`,
   `SUPABASE_SERVICE_ROLE_KEY`, and `TELEGRAM_BOT_TOKEN`. On an existing
   Blueprint, add new secret values manually in the dashboard.
6. Apply the Blueprint and wait for the Docker build and health check to pass.
   The health check is `/_stcore/health`, which Nginx proxies to the localhost
   Streamlit process. In logs, confirm the supervisor starts
   `session-broker`, `streamlit`, and `nginx` and does not print environment
   values.
7. Copy the service's `RENDER_EXTERNAL_URL`. In staging Supabase Authentication
   URL Configuration, set the staging Site URL deliberately and allowlist that
   exact HTTPS callback origin/path. The Blueprint copies the same Render URL
   to `SUPABASE_REDIRECT_URL_PREVIEW`,
   `SUPABASE_REDIRECT_URL_PRODUCTION`, and
   `FURUFLOW_SESSION_BROKER_PUBLIC_ORIGIN`.
8. Run the redacted auth diagnostic locally from a trusted shell with the
   staging public configuration. Render Free Web Services do not provide shell
   or one-off-job access:

   ```powershell
   .\.venv\Scripts\python.exe scripts\check_supabase_auth_health.py
   ```

9. From a trusted workstation, replace `STAGING_ORIGIN` with the service's
   external URL and verify public routing:

   ```bash
   curl -i "STAGING_ORIGIN/healthz"
   curl -i "STAGING_ORIGIN/_stcore/health"
   curl -i "STAGING_ORIGIN/v1/session/restore"
   curl -i "STAGING_ORIGIN/auth/session/activate"
   ```

   Expected results are `200`, `200`, `404`, and `400`. The final response is
   the broker's safe missing/expired-ticket response and confirms the exact
   activation route without exposing `/v1/session/*`.
10. Complete sign-in on the public Render origin. In browser developer tools,
    verify the cookie is host-only and has `Secure`, `HttpOnly`, `SameSite=Lax`,
    and `Path=/`. Press F5 and confirm identity restoration, then verify logout
    revokes the session. Inspect logs for tokens, activation tickets, cookie
    values, and secrets; none may appear.

For this staging test, use the Render-provided URL as the browser origin. A
custom staging domain requires updating all three public-origin/redirect
variables together before traffic is sent.

## F5 restoration on the Free topology

F5 restoration can be tested faithfully. The opaque cookie remains in the
browser and encrypted provider tokens remain in the staging Supabase
`browser_sessions` table, not on Render's ephemeral filesystem. After a rerun,
WebSocket reconnect, container restart, or Free-instance wake, Streamlit starts
with empty memory, reads the opaque cookie, and restores through the loopback
broker exactly as it would through a private-network broker.

Expect a cold-start delay after Render spins down an idle Free service. An auth
flow whose PKCE verifier was only in process memory when the container stopped
cannot resume and must be restarted; that is an existing process-memory
limitation, not a change to F5 restoration for an already activated browser
session.

## Security and reliability tradeoffs

This Free topology preserves the browser security properties, public route
denial, encrypted Supabase session storage, bridge authentication, and child
environment denial. It is still weaker than separate services:

- the Render service configuration and root supervisor initially hold the
  union of all secrets;
- Unix users and sanitized child environments reduce accidental disclosure but
  are not the same as separate container/service isolation;
- a root/container compromise could reach every process and credential;
- all processes share one CPU/memory budget and failure domain;
- Free services can sleep or restart, provide no persistent disk, shell, or
  one-off jobs, and cannot scale beyond one instance.

Use this topology only for staging/testing with a staging Supabase project and
synthetic/public data.

## Recommended production topology

Production should retain the three-service same-origin design:

1. a public Nginx web service that exposes Streamlit and only the broker's exact
   `/auth/session/activate` endpoint;
2. a private Streamlit service that never receives the Supabase service-role or
   session-encryption key; and
3. a private Gunicorn broker service that alone receives those credentials and
   exposes `/v1/session/*` only on Render's private network.

All production services belong in the same Render region. Streamlit and Nginx
must use the broker's private hostname, and Nginx must preserve Streamlit
WebSocket forwarding. This platform-level separation is the recommended
production security boundary even though the Free staging container reproduces
the functional session behavior.

## Local validation

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\poetry.exe check --lock
git diff --check
.\.venv\Scripts\python.exe scripts\check_tracked_secrets.py
.\.venv\Scripts\poetry.exe run pip-audit --requirement requirements.txt
```
