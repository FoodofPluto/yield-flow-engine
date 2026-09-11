# Closed-beta operational readiness and incident runbook

## Baselines and architecture

The accepted starting descendant is `731845cf17b71ba3e228c72912f127f63137c0bf`.
Prompt 18 is an immutable rollback reference, tag object
`e7e1059703d615701553660ff3c7a6707dad6202`, peeled commit
`79acf65c1f1764f4eedf733f210bd5d03109bd3b`. Never reset accepted history,
move frozen tags, or deploy an unreviewed branch tip as a rollback.

Frozen identities verified against origin at the Prompt 19B starting gate:

| Prompt | Tag object | Peeled commit |
| --- | --- | --- |
| 13 | `c5a3de9c3501cdb84092b5c461a76e5aebbfbecf` | `757c12523e04bbc71404e2c7fccdf54e5d073b61` |
| 14 | `9b0e73676393d5c9721194c81e37508ae905f937` | `049ae4e5c492a8accdb5aec4bedb14b5350f6aee` |
| 15 | `2bf54bb2c794ee1999962845730c6271aedf8d74` | `133e237f8698eff0a165c302b5d70e26255c25b8` |
| 16 | `7c5e71e029479a94c4a6fba9bfdb9568fbb8b3bd` | `a18659ad4a7c20c7d74fcea56b6df3596c1b5694` |
| 17 | `1b499159d7259fa13cf5feaf318c1ce0fa447326` | `b922d8b4d8fc0115a010fb0d896ee21d32a414f9` |
| 18 | `e7e1059703d615701553660ff3c7a6707dad6202` | `79acf65c1f1764f4eedf733f210bd5d03109bd3b` |

Render terminates canonical HTTPS at `https://beta.furuflow.com`. The current
web plan is 1c-2g; older references to Free describe the historical topology.
Nginx exposes liveness and proxies Streamlit and the explicitly allowed broker
routes. Streamlit and Gunicorn bind loopback, run under separate Unix users,
and supervisor failure terminates the container. Broker-only service-role,
encryption and Stripe credentials are removed from Streamlit's environment.
The broker owns opaque cookie/session and billing operations. Supabase owns
authentication, RLS, entitlements, session persistence and durable automation.
The separate Starter cron worker scans DeFiLlama and evaluates/delivers Telegram
notifications every 15 minutes. Worker failure cannot kill the web container.
Supabase, Render, DeFiLlama, Telegram, Stripe and Tally remain independent failure
domains. Stripe health is not inferred from a successful market scan; recovery
email delivery is not inferred from an Auth settings response.

## Operator scorecard and automated report

In the trusted Render **web service Shell**, run:

```sh
python scripts/beta_health.py --expected-sha <accepted-40-character-candidate-sha>
```

Use the independently accepted CI/deployment SHA, never substitute the runtime's
own SHA as the expectation. Compare the worker's Render deployed commit separately.
The report emits safe JSON, observation time, per-check states, and actionable
check names. It never loads a developer `.env`. Required credentials already
exist in the trusted service environment; never copy them into commands or tickets.

| State | Meaning | Exit | Operator response |
| --- | --- | --- | --- |
| healthy | Observed checks meet their thresholds | 0 | Record timestamp and SHA |
| degraded | Known freshness/delivery issue | 1 | Investigate; hold expansion |
| blocked | Unsafe signup, wrong build, failed health/boundary | 2 | Stop acceptance; contain incident |
| insufficient_evidence | Missing, malformed or unavailable telemetry | 3 | Restore visibility; never infer PASS |

Blocked takes precedence, then insufficient evidence, then degraded. A healthy
report is one operational observation, not complete beta acceptance or proof of
end-to-end authentication, Telegram delivery, or financial data correctness.
`/healthz` alone proves only Nginx liveness. The broker probe proves anonymous
rejection and reachability, not authenticated restoration.

The report reads hosted `/auth/v1/settings`; only literal `disable_signup=true`
passes. No Auth mutations or signup probes occur. The hosted state is authoritative.
Local `supabase/config.toml` still enables development signup and must never be
used as hosted safety evidence or blindly synchronized to the beta project.
Application signup must separately be exactly `FURUFLOW_BETA_ALLOW_SIGNUP=false`.

Worker heartbeat must be within 20 minutes; the most recent successful scan must
be within 30 minutes and latest outcome succeeded/zero_signals. Zero qualifying
signals is healthy scanning, not a signal recommendation. Pending retries,
24-hour dead letters and scan failures are separately counted; a nonzero count
requires investigation and an explicit explanation. No recent delivery alone is
not a failure when no notification qualifies.

Data status aggregates the existing instance-local history file: number of pools,
fresh pools (30 minutes), observed APY/TVL and pools with 14 observations. These
counts do **not** establish confidence: existing evidence logic also requires
duration, continuity and other dimensions. Missing/corrupt history is insufficient
evidence; no missing number is replaced with zero. History is ephemeral, bounded,
and rebuilt by normal public market workflows after deployment. The report does
not fetch data to conceal stale state, and this web-instance view is not fleet-wide.

## Minimum alerts and review cadence

The existing Render worker cron uses `python scripts/run_beta_worker.py`, which
runs `beta_health.py --scheduled` after a successful worker invocation without
depending on shell command parsing. Worker execution failure already fails the
job. The narrower scheduled report probes hosted signup, canonical web health and
the existing aggregate worker RPC; it exits nonzero for unsafe or unknown state.
It uses the existing worker service credential only against its configured hosted
Supabase origin, disallows redirects, and never prints response payloads/errors.
No new credential, public admin endpoint, telemetry store or messaging channel is
introduced. Full build/application/history review remains the web-shell report.

Verify the actual Render cron command matches `render.yaml` after deployment and
that Render failure notifications have a responsible operator recipient. This
notification configuration and delivery must be recorded as separate evidence;
a JSON alert list alone does not prove a notification was delivered. Do not send
participant Telegram tests to test operator alerts. Group repeated symptoms into
one incident; do not add a second pager for the same Render job failure. Positive
retry counts can be transient; inspect bounded retry timing before escalating.

Operator reviews: at each deployment, before each invitation batch, daily while
beta is active, and immediately after any platform failure notification. During an
incident review every 15 minutes until recovery is observed. Weekly review trends,
support themes, unknown telemetry, dependency failures and expansion eligibility.
Keep only sanitized SHA/time/status/count evidence for 30 days; discard temporary
diagnostics once resolved. Never paste raw provider logs into support records.

## Privacy and onboarding

Carry forward Prompt 19A.3's accepted Free/Pro login, restoration, entitlement,
isolation and fresh recovery evidence while these boundaries are unchanged.
Password mutation and post-mutation login were intentionally **not exercised**.
Public registration remains denied; existing authorized sign-in and recovery remain
allowed. Provision/invite through the established Supabase operator path, add the
verified identity to beta admission as required, and verify its intended tier
without changing participant entitlements for testing. See ACCOUNT_CONTROL_PLANE.md
and CLOSED_BETA_RELEASE_CANDIDATE.md. Never request passwords or recovery links.

Support: https://tally.so/r/5B7eZv. Verify the form loads without submitting test
data. It requests workflow, time, visible data freshness and symptom; contact is
optional. Do not include credentials, cookies, auth URLs or participant account
exports. Tally and platform log retention/access are operator-owned settings;
the new report adds no participant data. Existing Nginx access logs contain source
address, method, path and status; query strings are excluded and activation logs
are disabled. Broker access logs are disabled. Existing database account/session/
delivery records remain necessary operational data protected by existing authority.
Restrict Render/Supabase access and do not treat their logs as anonymized telemetry.

## Incident actions

| Incident | Triage and containment | Recovery evidence |
| --- | --- | --- |
| Web unavailable | Compare both canonical endpoints, TLS, Render deploy/process events; inspect sanitized errors. Pause invitations and use existing maintenance controls if reachable. | Both endpoints, correct SHA, normal public page and broker boundary pass |
| Worker unhealthy | Check cron schedule, heartbeat, last run, provider failures and service configuration. Do not start duplicate workers or blindly drain queues. | Fresh heartbeat and successful scheduled scan |
| Stale data | Check provider availability and timestamps; preserve stale/insufficient labels. Inspect instance history after normal refresh. | Fresh observed data; confidence only under existing evidence rules |
| Telegram delivery failure | Inspect aggregate retries/dead letters and redacted reason. Bounded retries remain authoritative; ambiguous delivery is terminal and must not be resent automatically. | Queue disposition explained and designated operator test only if needed |
| Auth outage | Check hosted settings and provider status, web/broker boundaries and exact build; preserve signup lockdown. Use designated test identity for affected acceptance subset. | Applicable login/restoration/recovery subset passes |
| Public signup enabled | Treat as blocking security incident; pause invitations/expansion, have authorized operator disable hosted signup, review unintended accounts without deleting participant data. Never use the health tool to mutate Auth. | Fresh hosted literal true and application false; review completed |
| Entitlement failure | Stop affected paid workflow/expansion; inspect authoritative grants/RLS using designated test identities. Do not edit participant subscriptions to test. | Applicable Free/Pro authorization and isolation checks pass |
| Rollback decision | Compare incident onset to candidate, dependencies and schema/config compatibility. Prefer forward correction when rolling back loses accepted recovery messaging. | Exact rollback SHA, CI evidence, canonical smoke and hosted lockdown |
| Credential compromise | Contain affected integration, revoke/rotate through trusted operator controls, invalidate affected sessions where appropriate; review access without copying secrets. Never paste a secret into an incident report. | Replacement credential works, revoked credential denied, impacted boundaries retested |
| Participant escalation | Record sanitized time/build/workflow, acknowledge through established support process, assign operator and severity. No impersonation or destructive participant tests. | Resolution verified and participant informed through approved support workflow |

## Rollback and expansion gates

This change adds no schema migration, account mutation, auth/session behavior or
new secret. Prompt 18 uses the same schema; the accepted descendant differs only
in recovery-expiry handling. Rolling back code can lose that correction and this
monitoring, so it requires an explicit operator decision. Keep hosted signup closed
and restore the old cron command if the target lacks `scripts/beta_health.py`.
Verify all frozen tag objects and peeled commits against origin before/after any
release. Do not perform rollback or move a tag as a readiness test.

Expansion requires seven consecutive daily reviews with canonical health/build
verified, signup gates closed, no unresolved critical/security incidents, no
unexplained dead letters or stale scans, working operator notifications/support,
and complete applicable authentication/authorization/isolation acceptance. Review
freshness and insufficient-evidence rates and investigate regression against the
first seven-day baseline; do not substitute participant count for reliability.
Require a named operator, reviewed rollback procedure and sufficient response
capacity for the next invitation batch. Unknown mandatory evidence blocks expansion.
Success is reliable authorized workflows, honest data evidence, recoverable
incidents and actionable support; no guaranteed yield or signal outcome is a beta
success criterion. The seven-day observation period is an expansion gate, not an
invented claim that a new deployment has already completed seven days of operation.
