# Yield Flow Engine

This project now includes both:
- the original CLI scanner
- a Streamlit app for non-technical users

## Install

Using Poetry:

```bash
poetry install
```

## Run the Streamlit app

```bash
poetry run streamlit run app.py
```

## Run the CLI

```bash
poetry run engine scan --help
```

## Notes

- The Streamlit app uses the existing scanner and provider logic.
- Environment secrets were not included in the packaged zip.
- Cached Python bytecode folders were removed from the package.


## V3 dashboard upgrades

- watchlist tab with session-based favorites
- CSV and Excel export
- protocol drilldown panel
- ranking modes for APY, risk-adjusted, TVL, low-risk, stable income, and 7D momentum
- search and asset filters
- richer charts for protocol, chain, risk, and stable/volatile mix
