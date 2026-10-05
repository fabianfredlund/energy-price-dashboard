# Solar Advisor Dashboard

> **This project pivoted during Sprint 5.** It was an industrial load-shifting
> dashboard (v1, Sprints 0–4, tagged `v1-industrial`); it is becoming a sales
> tool for a solar installer's energy advisors. Most of this README still
> describes v1 and is rewritten in Sprint 8. `SPRINTLOG.md` has the full story,
> including why the pivot happened.

## (v1) Energy Price Dashboard

A Streamlit dashboard built for a course assignment (Digital Leadership,
University of Gothenburg). It helps a fictional client, Älvdal Industri AB
(a manufacturer in Västra Götaland, electricity price area SE3), see when
spot electricity prices are cheap or expensive, and quantify what shifting
flexible production loads to cheaper hours would save.

See `SPRINTLOG.md` for the full sprint-by-sprint build log — goals,
decisions and why they were made, alternatives rejected, problems hit and
how they were solved. That log is the primary source for the course's
ideation report.

## What's in the app

The dashboard has two modes:

- **History** — explore past spot prices for a chosen date range and price
  area (SE1–SE4, with an option to compare two areas side by side), with an
  optional outdoor-temperature overlay. Includes KPI cards (average price,
  cheapest/most expensive hour, average daily spread) and an hour × weekday
  heatmap, both colour-coded so the cheapest, normal, expensive and spike
  hours are visible at a glance.
- **Plan ahead** — today's and tomorrow's published hourly prices (tomorrow
  appears once elprisetjustnu.se publishes it, usually by ~13:00), with a
  marker for the current hour.

Both modes share a **production planner**: add your flexible loads (name,
power draw, run length, usual start time) in an editable table, and the
planner recommends the cheapest start time for each one, totals the energy
and cost, shows the combined peak power if everything ran at its
recommended time, and estimates a yearly saving.

Every chart uses the same colour scheme — green (cheapest third), grey
(normal), orange (expensive), red (price spike, top 10%) — computed
relative to whatever period is currently shown, so it reads consistently
at any price level or in any area.

## Run locally

```bash
brew install python@3.11
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

The app opens at `http://localhost:8501`. It fetches live prices from
[elprisetjustnu.se](https://www.elprisetjustnu.se) and temperature from
[SMHI Open Data](https://opendata-download-metobs.smhi.se); if either API
is unreachable, it falls back to the snapshots committed in `data/cache/`
and shows a notice rather than crashing.

## Run the tests

```bash
source .venv/bin/activate
pytest -v
```

All real logic (fetching, caching, resampling, colour categorization, and
the production planner's arithmetic) lives in `src/` as plain, pure
functions and is covered by the test suite; `app.py` only wires Streamlit
widgets to those functions and isn't itself unit-tested — it's verified by
running the app and clicking through it instead.

## Project structure

```
app.py                 # Streamlit entry point: layout, widgets, charts only
src/prices.py          # fetch + parse spot prices (elprisetjustnu.se)
src/weather.py         # fetch + parse SMHI temperature data
src/cache.py            # shared day-granularity CSV cache + fallback
src/transform.py       # resampling, aggregation, heatmap tables, colour categorization
src/calc.py             # production planner: cheapest-window search, totals, peak power
data/cache/             # committed CSV snapshots, used as offline fallback
tests/                  # pytest suite for everything in src/
docs/sprint-0-plan.md   # the approved plan Sprint 0 was built from
SPRINTLOG.md            # sprint-by-sprint goals, decisions, and problems hit
```

## Data sources

- **Spot prices**: [elprisetjustnu.se](https://www.elprisetjustnu.se), SE1–SE4.
  These are spot prices only — they exclude VAT, energy tax, grid fees and
  supplier margin, as noted in the app itself.

  Elpriser tillhandahålls av [Elpriset just nu.se](https://www.elprisetjustnu.se).

- **Solar irradiance** (v2, from Sprint 5): [Open-Meteo](https://open-meteo.com)
  — hourly global tilted irradiance for Gothenburg, from the archive API for
  history and the forecast API for tomorrow.

  Weather data by [Open-Meteo.com](https://open-meteo.com). Note that
  Open-Meteo's free tier is for **non-commercial use**.

- ~~**Temperature**: SMHI Open Data, station 71420 "Göteborg A"~~ — removed in
  the Sprint 5 pivot; the temperature overlay became a solar production
  overlay. Still available in the `v1-industrial` tag.

## Deploy to Streamlit Community Cloud

1. Push this repository to GitHub (including the `sprint-*` tags, if you
   want them visible there too):
   ```bash
   git remote add origin <your-repo-url>
   git push -u origin main
   git push --tags
   ```
2. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with
   GitHub.
3. Click **New app**, pick this repository and the `main` branch, and set
   the main file path to `app.py`.
4. Under **Advanced settings**, select **Python 3.11** (the version this
   app is built and tested against).
5. Click **Deploy**. The first build installs `requirements.txt`'s pinned
   versions and starts the app; subsequent pushes to `main` redeploy
   automatically.

## Known limitations (by design, see SPRINTLOG.md)

- No price forecasting beyond tomorrow's already-published day-ahead
  prices, no grid fees/taxes modelling, no user accounts or databases —
  explicitly out of scope per the assignment.
- The production planner's "yearly saving" assumes one run per day; it's
  a stated estimate, not a prediction.
- Fetching SMHI's `corrected-archive` period downloads that station's
  entire historical record (back to 1961) on each call that needs it —
  fine for this project's traffic, but a known cost for a very old or
  very long History date range.
