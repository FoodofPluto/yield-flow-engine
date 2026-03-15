# FuruFlow v6

This pack upgrades the Yield Flow app into a more product-like DeFi scanner with:

- fixed dropdown readability for all select menus
- improved Watch / Open Pool button contrast
- readable pool-card badges and metric boxes
- richer scanner cards and a tighter table layout
- same-asset cross-chain arbitrage detection
- smarter heuristic risk scoring using protocol age, TVL stability, audit confidence, and inferred pool volatility
- a rules-based signal layer for APY spikes, farm rotations, emerging pools, and whale inflows
- watchlist workflow and pool drilldown charts

## Deploy

Replace your repo `app.py` and `requirements.txt`, then run:

```powershell
cd C:\Users\andro\Projects\yield-flow-engine
git add app.py requirements.txt README.md
git commit -m "Upgrade FuruFlow to v6 with signal engine, arbitrage detection, and improved UI contrast"
git push origin main
```

Then hard refresh the Streamlit app with `Ctrl + F5`.
