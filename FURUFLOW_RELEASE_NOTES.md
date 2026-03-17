# FuruFlow release notes

## Product identity
- Removed visible version labels from the main UI and browser title.
- Updated the hero copy to the launch tagline: **Find the smartest yields. Avoid the dumb ones.**
- Cleaned the sidebar branding so the app reads like a market product instead of a dev build.

## Free vs Pro conversion
- Free mode now centers on basic pools, limited sorting, market map, pool explorer, and protocol dashboard.
- Pro positioning now highlights arbitrage signals, whale-flow intelligence, advanced ranking, CSV export, and future signal-based alerts.
- Added stronger Pro teasers with preview data tables and explicit **$20/month** upgrade messaging.
- Free mode now shows only the top 10 pools from the current filter set, creating a clearer upsell path to the full opportunity set.

## Landing experience
- Added three new high-value landing sections: **Top Opportunities Today**, **Biggest Yield Changes**, and **Safest High APY**.
- Added a stronger upgrade panel near the top of the experience for better conversion without blocking the free product.

## Pool Explorer trust upgrade
- Added `history_store.py` to cache pool snapshots locally and build a real chart history when upstream chart endpoints fail.
- Pool Explorer now prefers: upstream live chart -> stored local history -> generated fallback preview.
- Added clearer captioning so users know whether they are seeing live, stored, or synthetic chart data.

## Notes
- Local snapshot history grows as the app is used. On ephemeral hosting, chart history persists only as long as the underlying filesystem persists.
- A production-grade next step would be moving pool history storage to a managed database or object store.
