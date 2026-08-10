# FuruFlow design system, shell, and navigation

This document records the Prompt 3 application-shell boundary. It does not
change authentication, Supabase/RLS authorization, billing, market ranking,
risk methodology, data providers, or external-delivery behavior.

## Sitemap

```text
Public
├─ Home
├─ Discover
│  ├─ Opportunities
│  ├─ Signals (Pro view)
│  ├─ Compare
│  └─ Pool Detail (contextual route)
├─ Research
│  ├─ Market Map
│  └─ Protocols
├─ Pricing
└─ Methodology & Data Status

Authenticated
├─ Watchlists
├─ Alerts
├─ Activity & Digests
├─ Pro Tools
│  ├─ Strategy Builder
│  └─ Yield Spreads
└─ Account & Billing

Restricted
└─ Admin
```

Developers is intentionally absent because the application does not yet expose
an API-ready developer product. Alerts is an honest unavailable state; no
delivery setup or fake activity was added.

## Shell and component structure

`ui_shell.py` is the reusable shell boundary. It owns immutable navigation
metadata, public/authenticated/restricted visibility, direct-route access
decisions, legacy-route aliases, compact account-state presentation, Pool
Detail open/back state, page context, status/empty-state components, design
tokens, focus styles, and responsive rules. `app.py` retains the existing
domain calculations and page renderers and maps them into the shell.

The design tokens cover spacing, radii, focus, informational, success, warning,
and danger colors. Reusable visual patterns cover the product mark, page title
and breadcrumb, navigation section labels and active buttons, status banners,
empty/unavailable states, account/plan state, panels, badges, and Pro/restricted
states. Existing cards and data panels remain where they convey market
information; the shell avoids wrapping every element in another identical
container.

## Visibility and authorization rules

- Signed-out visitors see the five public primary destinations and a collapsed
  Account control.
- Verified signed-in users also see the five workspace destinations. Free
  accounts see `Pro tools · Pro`, while entitled users see `Pro tools`.
- Admin is not emitted into navigation unless `auth_service.is_admin()` returns
  true for the server-authoritative verified account.
- A direct request for an authenticated route receives an authentication-required
  state. A direct Admin request receives an unauthorized state unless the same
  backend-derived administrator check passes.
- Admin rendering repeats the authorization guard. No query parameter,
  session-state flag, CSS rule, or visually hidden control grants privilege.
- The existing session broker, opaque secure cookie, Supabase identity restore,
  account-control client, RLS policies, entitlement rules, and logout behavior
  are unchanged.

## Responsive behavior

Streamlit's drawer remains the deterministic navigation host. Navigation is
rendered first, as visible sectioned buttons, followed by the collapsed Account
control and collapsed market-filter groups. This prevents sign-in forms and
account metadata from consuming the initial mobile navigation area.

At 1200 px and below, multi-column content wraps, the content gutter narrows, and
stat groups become two columns. At 520 px and below, stat groups become one
column, headings scale down, panels use the phone gutter, and data frames retain
a bounded horizontal overflow area. Buttons and links have a high-contrast
`focus-visible` outline. Reduced-motion preferences disable nonessential
animation and transitions.

## Pool Detail navigation model

Opportunity cards open `Pool Detail` with a deterministic pool ID in both
session state and the `pool` query parameter. The route records its return route
and nested Discover view. Back restores the Discover results context and removes
the pool query parameter. A shared URL can identify the selected pool, but
Streamlit cannot preserve browser history and every transient widget/filter
value like a client-side router; the return abstraction therefore preserves the
route/view context rather than a full browser-history stack.

Pool Detail uses existing calculations and upstream/stored chart selection.
When neither legitimate source exists, history is explicitly unavailable; the
canonical app does not generate a trend from a single snapshot.

## Shared status conventions

`render_status()` supports loading/refreshing, no data, error, warning,
degraded source, stale cache, authentication required, Pro required,
unauthorized, session expired, informational, and success states. Each uses an
icon and useful text as well as color. The live pool feed is labeled with its
source, retrieval age, and cache window. If upstream pool endpoints fail, the
canonical app renders provider unavailable and does not substitute sample rows.
The sample fixture requires an explicit development/test environment flag.

## Accessibility validation

Automated checks cover shell route order, signed-out/authenticated/admin
visibility, direct-route denial, Pro/free labels, legacy mappings, compact
account state, and Pool Detail open/back behavior. Streamlit AppTest executes a
signed-out Home → Discover → Pool Detail → Discover round trip and a denied
direct Admin route.

Code-level review confirms a navigation-first DOM order, semantic page `h1`,
visible active state, labeled controls, text-plus-icon status meaning,
high-contrast keyboard focus, responsive wrapping, and reduced-motion support.
Streamlit supplies native keyboard behavior and accessible naming for buttons,
radios, form inputs, expanders, and links.

Manual screen-reader testing, OS high-contrast testing, 200% zoom inspection,
and authenticated mobile testing with real ordinary-user/admin accounts remain
required. No unmeasured WCAG conformance score is claimed.

## Rendered validation

The canonical local app was inspected in the in-app browser at 1440×1000,
1024×768, and 390×844. Signed-out Home, Discover, Research, the compact Account
control, direct Admin denial, and a Discover → Pool Detail → Discover round trip
were rendered. The phone opened with the navigation drawer closed; opening it
showed the five public destinations before Account and market filters. The
390 px page had a 390 px document width, opportunity cards stacked at 358 px,
and no page-level horizontal overflow. Keyboard navigation exposed a visible
2.4 px high-contrast focus outline.

The 1024 px inspection initially exposed unreadably narrow opportunity cards
because the open Streamlit sidebar reduced the content width. The responsive
column selector and breakpoint were corrected, then rerendered: cards measured
310 px and labels no longer broke into single-character fragments. The wide
desktop measured 1440 px document width at a 1440 px viewport, with no page-level
horizontal overflow.

Watchlists, Pro Tools, Account & Billing, and the authorized Admin presentation
were rendered using a temporary out-of-repository in-memory presentation fixture
that supplied the same verified, Supabase-authoritative account shape consumed
by the shell. The fixture was deleted after inspection and never changed the
application, cookies, Supabase, RLS, entitlements, or a real account. The real
authorization boundary is covered by the Prompt 2 tests plus the new route-model
tests; this presentation fixture is not evidence of an end-to-end administrator
login. Real-account authenticated/mobile visual validation remains manual work.

## Structural before/after

The previous shell exposed ten unrelated destinations in one flat dropdown and
rendered the full authentication stack plus detailed plan/admin flags before
navigation. The new shell exposes five public primary destinations, adds five
workspace destinations only after verified sign-in, and adds one Admin item only
for a verified administrator. Nine legacy destinations map into four parent
workflows plus contextual Pool Detail. One flat navigation block and two
separate account-summary blocks were replaced by one route model, one visible
navigation block, and one collapsed account control.
