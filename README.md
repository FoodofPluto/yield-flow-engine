# FuruFlow v8

FuruFlow is a DeFi yield intelligence dashboard built in Streamlit.

## What's in v8

- upgraded from the prior v7 productization pass to a fuller multi-page interface
- fixed low-contrast dropdown and title-box text for Chains, Protocols, Strategy Type, Signal Filter, Sort by, and Choose a Pool
- fixed Watch and Open Pool button readability
- fixed pool-card badge and metric readability
- scanner cards with cleaner visual hierarchy
- richer Plotly charting
- signal engine for APY spikes, farm rotations, emerging pools, and whale inflows
- heuristic risk scoring using protocol age, TVL stability, audit confidence, and pool volatility
- same-asset, cross-chain arbitrage surface
- pool explorer page with chart + score breakdown
- protocol dashboard page
- strategy builder page
- persistent watchlist saved to `watchlist.json`

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy

Push the updated repo to the branch connected to Streamlit Cloud. The app should auto-redeploy.


## Monetization quick start

Set these environment variables in Streamlit Cloud or your local shell before launch:

- `FURUFLOW_PRO_PASSWORD` — the current Pro access code you will share with paid users
- `FURUFLOW_STRIPE_LINK` — your Stripe Payment Link for FuruFlow Pro

The app now keeps the Scanner free while gating Signals, Arbitrage, Strategy Builder, and CSV export behind Pro. Supported protocols can also route `Open Pool` through affiliate-style links when configured in `AFFILIATE_LINKS`.
