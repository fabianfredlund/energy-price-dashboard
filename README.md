# Energy Price Dashboard

A Streamlit dashboard for Älvdal Industri AB (Västra Götaland, price area
SE3) to explore electricity spot price patterns and estimate savings from
shifting flexible loads to cheaper hours. Built for the University of
Gothenburg Digital Leadership course.

## Status

Sprint 0 (spike) — fetch + chart proof of concept. See `SPRINTLOG.md` for
sprint-by-sprint progress and decisions, and `docs/sprint-0-plan.md` for
the plan this sprint was built from.

## Run locally

```bash
brew install python@3.11
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Data sources

- Spot prices: [elprisetjustnu.se](https://www.elprisetjustnu.se) (SE3 area)
- Temperature: [SMHI Open Data](https://opendata-download-metobs.smhi.se)
  (station 71420, Göteborg A)

Full usage docs and methodology will be fleshed out in Sprint 4.
