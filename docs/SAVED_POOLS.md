# Persistent saved pools

Prompt 7 replaces the former repository-local `watchlist.json` behavior with an
authenticated, per-user Supabase Watchlist. The canonical identity is the
DeFiLlama provider `pool` value already used by Discover, Compare, Pool Detail,
and pool Alerts.

## Persistence and ordering

Migration `202608170001_prompt7_saved_pools.sql` creates `public.saved_pools`
with the authenticated owner UUID, canonical pool ID, and save timestamp. Its
composite primary key prevents duplicate saves for one user while allowing two
users to save the same pool independently. The product order is newest save
first, then canonical pool ID ascending as a stable tie breaker.

The browser calls only `list_my_saved_pools()`, `save_my_pool(text)`, and
`delete_my_saved_pool(text)`. Each function requires `auth.uid()` and derives
ownership from it; no RPC accepts a user ID. Direct browser writes are revoked,
and defensive RLS policies restrict table access to `user_id = auth.uid()`.

## Product behavior

Discover, Compare, and Pool Detail expose the same durable saved state. The
Watchlists shell route renders current market information through the existing
opportunity-card model. A current pool opens the existing Pool Detail route and
returns to Watchlists through the existing contextual back state.

If the provider omits a saved canonical ID, the database row remains. The page
shows the canonical ID with current APY, TVL, risk, and provenance explicitly
unavailable, and keeps removal available. No market value is copied into the
saved record or fabricated during degradation.

Saved pools and Alerts are independent. The migration has no trigger, foreign
key, function call, or write path into notification rules, delivery queues,
Telegram connections, automation runs, retries, dead letters, or health state.

## Staging validation

1. Sign in as User A and save a pool from Discover.
2. Confirm the card changes to the saved state, open Watchlists, and confirm the
   pool appears.
3. Refresh, then open Pool Detail and use **Back to Watchlist**.
4. Sign out and back in; confirm the pool remains saved.
5. Remove it, refresh, and confirm it remains removed.
6. Sign in as User B and confirm User A's entries are invisible.
7. Save the same canonical pool as both users and confirm independent records.
8. Validate a saved pool omitted by the current provider shows unavailable
   values, remains saved, and can still be removed.
9. Create or retain an Alert for a pool, save and remove that pool, and confirm
   the Alert and Telegram behavior are unchanged.

Staging validation must precede production deployment.
