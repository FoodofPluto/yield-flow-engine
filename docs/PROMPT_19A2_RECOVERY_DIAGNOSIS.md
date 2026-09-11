# Prompt 19A.2 recovery diagnosis — 2026-09-11

## Immutable baseline and scope

Prompt 18 remains at `79acf65c1f1764f4eedf733f210bd5d03109bd3b`, tag object
`e7e1059703d615701553660ff3c7a6707dad6202`. This descendant corrects handling
of a proven provider rejection; successful live recovery remains unverified.
Prompt 19 remains paused.

## Sanitized evidence

The user opened the recovery email on a phone. The initially reported 07:03
Eastern time was when the error was noticed, not an actual click timestamp.
The browser-A observer therefore does not capture this phone navigation.

Trusted Supabase dashboard logs and a read-only query selecting only recovery
flow timestamps, method, and credential-presence boolean established:

| Event on September 11 (EDT, UTC−04:00) | Evidence |
| --- | --- |
| 06:43:25.287 | Recovery flow creation timestamp |
| 06:49:13.900 | Auth-code issuance timestamp for that recovery flow |
| 06:49:13 | `GET /verify`, HTTP 303 |
| 06:49:14 | `POST /token`, PKCE grant, HTTP 422, `flow_state_expired` |
| 06:55:13 and 06:55:22 | Later recovery flows have null code-issuance timestamps |

The rejected flow was approximately 349 seconds old; exchange followed
verification within one second. The error denotes provider flow expiry,
not a proven verifier mismatch. Supabase's recovery flow implementation creates
state on request, and its expiry check uses creation time for recovery flows.
The deployed provider's precise configured expiry duration was not read.

References: [Supabase error codes](https://supabase.com/docs/guides/auth/debugging/error-codes),
[recovery implementation](https://github.com/supabase/auth/blob/master/internal/api/recover.go),
[flow-state expiry implementation](https://github.com/supabase/auth/blob/master/internal/models/flow_state.go).
Upstream implementation is supporting context, not a claim about the deployed
provider version.

## First failing boundary and classification

The proven boundary is authorization-code exchange: Supabase refused the
expired recovery PKCE flow before issuing a session. Primary Prompt 19A.2
category: **C — Callback/PKCE**, specifically provider exchange rejection;
there is no evidence of a successful exchange losing recovery semantics.

FuruFlow's callback must consume a locally valid verifier before attempting
exchange. Its local ten-minute TTL can outlive the provider flow; local
availability does not establish provider acceptance or verifier correctness.
Canonical redirect preservation was not directly captured on the phone.

For this rejected exchange, session storage, broker persistence/activation,
recovery-flag establishment, and new-password rendering were not reached.
The Account/sidebar placement and broker restoration's lack of a recovery flag
remain separate findings, not explanations for the observed exchange failure.

## Minimum remediation

Previously `flow_state_expired` fell through to the generic temporary provider
error: “Authentication could not be completed. Try again shortly.” It now
maps to the existing `expired` classification with instructions to request a
new link and open it promptly. The existing bounded callback log records
`reason=expired`; no new payload logging is introduced.

This correction does not make an expired credential valid or establish that
the full successful recovery journey works. No retry, provider expiry change,
PKCE bypass, template change, or speculative broker/UI change is introduced.

Regression coverage reproduces provider rejection while the local verifier
is valid, checks safe error text and logs, callback scrubbing, no session or
broker activation, rejection of replay, and success of an independent fresh
flow for recovery, sign-in, and verification.

## Preserved gates and acceptance

Trusted Render inspection confirmed the baseline deployment with
`FURUFLOW_BETA_ALLOW_SIGNUP=false` and Supabase `disable_signup=true`.
No signup, account creation, entitlement, Stripe, Watchlist, Alert, Telegram
trust, password, or provider-configuration mutation is part of this change.
No credential values are retained in this report.

Pre-commit validation: Python suite **429 passed, 0 failed, 0 skipped, 0 setup
errors**; linked database suite **220 assertions passed across seven
rollback-only transactions**. The first database invocation stopped before SQL
execution because the sandbox blocked the CLI telemetry-file write; the
authorized retry passed. Syntax, Ruff, both CI type-check groups, secret scan,
CLI demo, Streamlit boot smoke, and `git diff --check` passed.

After complete Python/database validation, exact-commit CI and deployment,
one authorized fresh recovery verification is required. Until that succeeds,
Prompt 19A.2 is not a recovery-flow PASS and Prompt 19 must not resume.
