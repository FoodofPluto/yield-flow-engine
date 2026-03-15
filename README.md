# FuruFlow Streamlit Upgrade Pack

This pack is a cleaned-up, deploy-ready replacement for the earlier Yield Flow Engine dashboard.

## What changed
- Higher-contrast typography for dark backgrounds
- Wider layout and more breathing room
- Compact, professional dashboard sections
- Fewer columns in the primary table to reduce sideways scrolling
- Live DeFiLlama-backed pool data with fallback demo data
- Pool links and a pool drilldown view
- Simple risk heuristic for fast sorting
- Rebrand-ready structure

## Files
- `app.py` — upgraded Streamlit dashboard
- `requirements.txt` — Python dependencies
- `revised_prompt.md` — stronger master prompt for future iterations

## Run locally
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy to the same Streamlit app
Replace your repo's existing `app.py` and `requirements.txt` with these versions, commit, and push to the branch connected to Streamlit Cloud.

## Notes
- The app tries live yield endpoints first and falls back to demo data if the endpoint is unavailable.
- The risk score is heuristic-only and should be presented as a sorting aid, not a safety claim.
- The default product name in code is `FuruFlow`. You can rename it by changing `APP_NAME` and `APP_TAGLINE` near the top of `app.py`.
