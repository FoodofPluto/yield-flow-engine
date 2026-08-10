# Market research workflow

This document records the Prompt 4 research boundary in canonical `app.py`. It
does not change authentication, Supabase/RLS authorization, billing, provider
formulas, signal formulas, scoring formulas, or outbound automation.

## Workflow and architecture

The research path is `Discover -> filter/search -> Compare -> Pool Detail`.
Existing Scanner behavior is Discover Opportunities. Existing deterministic
Signals behavior is a nested Discover view and is also shown on opportunity
cards and Pool Detail. The Pro-only cross-chain comparison is user-facing
**Yield Spreads**, not Arbitrage.

`market_research.py` contains pure, provider-free models for deterministic
filters and query serialization, stable missing-last sorting, comparison,
yield decomposition, explainable risk factors, freshness, yield spreads, and a
local product-event envelope. `app.py` owns provider reads and Streamlit
presentation. `ui_shell.py` continues to own routes and authorization-aware
navigation. Authorization and entitlements remain in the Prompt 2 control
plane.

## Discovery and filter state

Primary controls are search, chain, and stablecoin-labelled pools. Protocol,
strategy, signal, TVL, APY, risk, and sorting live in the Advanced surface. The
same state is used at all viewport widths. Defaults are all market dimensions,
no search, no stablecoin constraint, $5 million minimum TVL, maximum existing
risk score 70, minimum APY 0%, and Highest APY sorting.

Active non-default filters are visible as labeled removal buttons. Clear all
returns every field to the defaults. Meaningful state is encoded in
non-sensitive query parameters (`q`, dimensions, thresholds, and sort). Pool
Detail preserves those parameters and the shell preserves its Discover return
view. Streamlit cannot restore browser history and every transient widget value
like a client router; this restores deterministic research context rather than
claiming a full history stack.

Search is case-insensitive literal matching across protocol, asset, chain, pool
ID, and pool metadata. Sorting uses stable mergesort, a pool-ID tie breaker, and
missing-last behavior. A threshold depending on an unavailable value does not
treat that value as zero. Provider failure and successful zero-match filtering
render different states.

## Comparison

Compare is public at the existing Free/Pro result depth. A user selects up to
four visible pools. Four keeps the desktop grid bounded while the per-pool
summaries remain useful on a phone. Missing APY components and TVL remain
`Unavailable`. Selection uses the non-sensitive `compare` query parameter. Pool
Detail opened from Compare records Compare as its return view.

The grid is bounded within the content region instead of creating page-level
overflow. On narrow displays it scrolls inside that region and pool summaries
stack vertically.

## Pool Detail, yield, and risk

Pool Detail identifies the pool/assets, protocol, chain, upstream ID, strategy,
and exposure. Yield presentation uses provider-reported total, base, and reward
APY independently. Aggregate-only data is labeled; absent components remain
unavailable; values are not recalculated for presentation. If reported total
differs from base plus rewards by more than 0.02 percentage points, the
discrepancy is displayed rather than forced to reconcile.

The existing FuruFlow risk score and formulas are unchanged. The UI explains
available liquidity, composition, reward dependence, and unusual yield
characteristics. If TVL, APY, or reward data needed for explanation is missing,
risk presentation becomes **Unknown** even if legacy formula code can emit a
number from normalized defaults. Missing data is never presented as safe.
Protocol-age and audit-confidence values remain FuruFlow metadata, not provider
guarantees or investment advice.

## Provenance and degraded data

The market source is DeFiLlama Yields. The pool response has no suitable
observation timestamp, so FuruFlow shows retrieval time without inventing
provider precision. Market requests retain the existing 15-minute cache.
Centralized terminology is:

- **Current:** retrieved no more than 20 minutes ago (cache plus delivery
  tolerance).
- **Aging:** more than 20 and no more than 60 minutes old.
- **Stale:** more than 60 minutes old.
- **Unavailable:** no usable observation or retrieval time.
- **Sample:** explicit development/test fixture, never live market data.

Responses missing pool identity are unusable. Incomplete but usable responses
are partial/degraded. Provider errors return an empty unavailable data set; the
production app does not substitute sample opportunities. The local five-row
fixture is reachable only with explicit `FURUFLOW_MARKET_SAMPLE_MODE=true` and
is labeled Development sample mode. Automated Streamlit tests set that flag.

Pool history uses the provider chart endpoint when available, then legitimate
stored snapshots. If neither exists, history is unavailable. Prompt 4 no longer
generates a trend from a single current snapshot.

## Yield Spreads and signals

Yield Spreads preserves the existing same-symbol, cross-chain APY-difference
calculation and three-percentage-point threshold. It labels higher and lower
sides, source freshness, and execution costs as not modeled. Gas, bridging,
slippage, timing, taxes, lockups, and reward-token exposure are not assumed to
be zero. The feature is decision support, not guaranteed profit or execution.

Signal labels remain existing rules based on recent APY and TVL movement. No AI
classification was added. Signals explain why a pool is surfaced in Discover
and Pool Detail; existing Pro and direct-route authorization semantics remain.

## Accounts, analytics, accessibility, and limitations

Signed-out users see disabled `Sign in to save` actions rather than fake local
persistence. Signed-in behavior reuses existing watchlist functions; Prompt 4
does not duplicate or redesign persistence. Free, Pro, and administrator
decisions still come from authoritative server account state.

The internal event abstraction creates an allowlisted local structured
envelope. It has no production sink and excludes email, credentials, cookies,
tokens, session IDs, and authorization material. No analytics vendor was added.

Controls use native labeled Streamlit widgets and buttons, status meaning uses
text and color, filter-removal buttons have explicit names, and missing-data
semantics are textual. Prompt 3 focus and reduced-motion CSS remains active.
Manual screen-reader, 200% zoom, OS high-contrast, and real-account mobile
validation remain required; no WCAG conformance claim is made.

Live staging must still validate provider cadence and malformed/partial
responses, shared filter URLs, stored-history age, signed-in durable watchlist
behavior, and Free/Pro/admin presentation with real accounts.
