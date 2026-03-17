# FuruFlow market-readiness pass

## Changes completed
- Public/free mode now opens immediately without forcing login.
- Login remains available in the sidebar for account-based access.
- Pro gating now applies to advanced workflows instead of the whole app.
- Removed the demo-style self-unlock path from the Pro gate.
- Pool Explorer now falls back to a generated preview trend when upstream live chart history is unavailable.
- Sidebar account area now clearly shows whether the user is in Free or Pro mode.

## Recommended next upgrades
- Replace the fallback chart with a true historical cache persisted per pool.
- Add feature comparison cards for Free vs Pro near the upgrade CTA.
- Add clearer empty states when API endpoints are slow or degraded.
- Add public landing metrics above the scanner for first-time visitors.
- Add onboarding tooltips for chains, risk score, and signal meaning.
- Add saved watchlists per signed-in account instead of a shared local file.
- Add protocol detail pages with pool clustering and external research links.
