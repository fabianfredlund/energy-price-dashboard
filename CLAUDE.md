# CLAUDE.md — Energy Price Dashboard

## What this project is
Course assignment (Digital Leadership, University of Gothenburg). I (Fabian) act as a consultant helping a client set up a new data analytics department. Deliverables: (1) a Streamlit dashboard, (2) an ideation report following the Stanford design thinking model (Empathize, Define, Ideate, Prototype, Test), (3) a 3-minute pitch video.

You help build (1). The process matters as much as the product: the report is written from the sprint log, so every decision must be logged as we go.

## Hard constraints (non-negotiable — set by the assignment)
- The dashboard is built in **Python with Streamlit**. Entry point is `app.py`, run with `streamlit run app.py`.
- No other app frameworks or front ends: no Dash, Flask, FastAPI, Django, React or custom JavaScript. A Jupyter notebook is not a deliverable.
- All UI uses Streamlit widgets and layout. Charts are Plotly rendered via `st.plotly_chart`, or Streamlit's native charts. No custom HTML/JS components.
- Development happens in VS Code. The finished app is deployed as a Streamlit app (Streamlit Community Cloud) from the GitHub repo.
- If a task seems to require anything outside Python + Streamlit, stop and ask me instead of working around it.

## Client (fictional — working assumptions, to be refined in Empathize)
- Älvdal Industri AB, ~150 employees, manufacturer in Västra Götaland → electricity price area SE3.
- Energy-intensive, partly flexible processes: e.g. heat treatment furnaces, compressors, batch washing and drying.
- Assumption: electricity is bought on a spot-price-linked contract, so hourly price variation reaches the invoice.
- Audience: production planners, controller/CFO, and floor staff new to data-driven work. Many are not data-literate, so clarity beats sophistication.

## Draft problem statement (to be revised in Define)
How might we help Älvdal's planners and management see when electricity is cheap or expensive, and quantify what moving flexible loads to cheaper hours would save?

Questions the dashboard must answer:
1. How does the spot price vary by hour, weekday and season in SE3?
2. Which hours are consistently cheapest and most expensive?
3. What would a given flexible load cost at the cheapest hours vs. our normal schedule, per run and per year?
4. How does outdoor temperature relate to price peaks?
5. How does SE3 compare with the other price areas?

## Data sources

### Spot prices — Elpriset just nu
- `GET https://www.elprisetjustnu.se/api/v1/prices/{YYYY}/{MM}-{DD}_{AREA}.json`, AREA in SE1–SE4. One static JSON file per day and area. No API key.
- Since the day-ahead market moved to 15-minute resolution (autumn 2025), a day may contain 24 or 96 intervals. Detect this and aggregate to hourly mean for all views.
- Verify in Sprint 0: field names, timezone handling, earliest available date, behaviour for missing days.
- These are spot prices only: excluding VAT, energy tax, grid fees and supplier margin. The UI must say so.
- Attribution required in the app footer: "Elpriser tillhandahålls av Elpriset just nu.se" with a link to https://www.elprisetjustnu.se.

### Temperature — SMHI Open Data (meteorological observations)
- Base: `https://opendata-download-metobs.smhi.se/api/`
- Use a Gothenburg station. Find its id via the station list endpoint and verify it has data for the full period.
- Verify in Sprint 0: which period endpoints cover the date range (archive vs. latest months), the data format, and whether to use hourly or daily mean air temperature.

## Tech stack
Python 3.11+ and Streamlit (required). Supporting Python libraries: pandas, plotly, requests, pytest. Nothing else without asking me first.

## Project structure
```
app.py                 # Streamlit entry point: layout, widgets, charts only
src/prices.py          # fetch + parse spot prices
src/weather.py         # fetch + parse SMHI data
src/transform.py       # resampling, aggregation, heatmap tables, price colour categorization
src/calc.py            # production planner: cheapest-window search, totals, peak power
data/cache/            # CSV/parquet snapshots, committed as offline fallback
tests/
SPRINTLOG.md
README.md
requirements.txt
```

## Engineering rules
- Keep logic in `src/` as pure functions (DataFrame in, DataFrame out). `app.py` only wires widgets to functions. This keeps everything testable.
- Cache API calls with `st.cache_data` (with TTL) and persist snapshots to `data/cache/`. If an API fails, fall back to the snapshot and show a notice. Never crash.
- Fetch day files politely: small thread pool, timeouts, retries.
- UI language: English. Show prices in öre/kWh. Plain labels, no jargon. Every chart gets one sentence telling the user what to look for.
- Handle edge cases: empty selection, date range with missing days, single-day range, API timeout.

## Dashboard scope

### Modes
The dashboard has two modes, implemented as `st.tabs`:
- **History** — the existing analysis views (date range, price area, temperature overlay, KPI cards, heatmap). Answers "what do prices usually look like?"
- **Plan ahead** — today's and tomorrow's spot prices hour by hour, with a marker for the current hour. Tomorrow's prices are published by elprisetjustnu.se around 13:00; until then the API returns 404 for tomorrow, so Plan ahead shows a clear "not published yet" message instead of an empty chart or a crash. Plan ahead never shows more than today + tomorrow — this is not price forecasting (see Out of scope).

Price area and temperature-overlay controls are shared across both modes; the date range selector only applies within History (Plan ahead's window is fixed to today/tomorrow by definition, so it needs no date picker).

Required interactions (the assignment demands at least three):
1. Date range selector (History mode)
2. Price area dropdown (SE1–SE4), with an option to compare two areas
3. Temperature overlay toggle on the price chart

### Colour-coded prices
In both modes, every hour is coloured by where its price sits within the period currently shown — relative thresholds computed from the displayed data, so the scheme works in any price area and at any price level, not a fixed öre cutoff:
- cheapest third → green ("Cheap")
- middle third → neutral grey ("Normal")
- top third → orange ("Expensive")
- top 10% → red ("Spike") — carved out of the top third, not stacked on top of it

Plan ahead renders this as bars per hour (24–48 bars, reads cleanly at that density). History defaults to hourly coloured bars for ranges up to 31 days; for longer ranges it switches to one coloured bar per day (coloured by that day's mean-price category). Reasoning: a 30-ish-day span of hourly bars reads as a legible "skyline" (confirmed against the Lovable mockup), but a multi-month range can mean thousands of hourly bars, which stop being legible or fast to render — and the hour × weekday heatmap (below) is already the dedicated view for sub-day patterns over a long period, so daily bars don't lose that detail, just move it to the view built for it. Every chart using this colour scheme includes a short plain-language legend (e.g. "Green = cheap, red = price spike").

Views: KPI cards (average price, cheapest and most expensive hour, daily spread), price over time (coloured per above), hour × weekday heatmap (coloured per above), production planner.

### Production planner
Replaces the single load-shift calculator originally scoped here (see SPRINTLOG.md's 2026-10-03 scope-update entry). The user adds production units in an editable table (`st.data_editor`): name, power draw (kW), run length (hours), usual start time, on/off toggle.

For each active unit: energy per run = kW × hours; find the cheapest contiguous start window of that length within the priced period and show it as "Start <name> at HH:MM — est. cost X SEK". Totals across active units: total energy (kWh), total cost at usual vs. recommended start times, and the saving. Also show the combined peak power (kW) across all active units if each starts at its own recommended time, with a note that grid/capacity charges are not modelled (spot price only, per the existing VAT/tax/fees disclaimer).

Price source depends on mode:
- **Plan ahead**: actual published prices, from the current hour onward.
- **History**: the average price per hour-of-day across the selected period, labelled "typical" savings (not a prediction).

All planner logic lives in `src/calc.py` as pure functions (cheapest-window search, totals, combined peak power), with tests covering the edge cases: run length longer than the available priced hours, no active units, 0 kW / 0 hours.

Out of scope: price forecasting beyond tomorrow's already-published day-ahead prices, modelling grid fees and taxes, user accounts, databases.

## Sprints — do not build ahead of the current sprint
- **Sprint 0 — Spike.** Fetch one month of SE3 prices and temperature, print shapes, and show one chart in a minimal Streamlit page (`streamlit run app.py`). Answer every "verify" item above. Done when: data confirmed, or an alternative proposed.
- **Sprint 1 — Data pipeline.** Price and weather modules, caching, fallback, one line chart in the app. Done when: any date range in any area renders.
- **Sprint 2 — Interactions.** The three required interactions, the History/Plan ahead `st.tabs` structure, and the colour-coded price scheme (bars for Plan ahead, the chosen readable solution for History, plus the plain-language legend). Done when: both modes work, all three interactions work together without errors, Plan ahead shows the "not published yet" message correctly before tomorrow's prices are out, and colour coding renders correctly in both modes.
- **Sprint 3 — Insight layer.** KPI cards, heatmap (recoloured to the Sprint 2 scheme), production planner, explanatory texts. Done when: a non-expert can answer the five questions above using the app, and can get a start-time recommendation and savings estimate for at least two production units.
- **Sprint 4 — Test and ship.** pytest suite, edge cases, fixes from user tests, README, deploy to Streamlit Community Cloud. Done when: the public link works in a clean browser.

## After every sprint (mandatory)
1. Append an entry to SPRINTLOG.md using the template below.
2. Commit and tag: `git tag sprint-N`.
3. Remind me to take screenshots of the app for the report.

SPRINTLOG template:
```
## Sprint N — <name> (<date>)
Goal:
Built:
Decisions (and why):
Alternatives considered and rejected (and why):
Problems hit / how solved:
Open questions for next sprint:
```

## How to work with me
- Explain key decisions in one or two sentences so I can defend them in the report and the video.
- If you see a better approach than the one described here, propose it and wait for my go-ahead.
- Ask before adding dependencies or features outside this scope.
