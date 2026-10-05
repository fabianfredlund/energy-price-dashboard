# Solar Advisor

**A sales tool that lets an energy advisor show a homeowner, with real data, whether
solar panels — and a battery — pay off for them.**

🔗 **[Live app](#)** — *link added after deployment; the app sleeps when idle, so the
first load takes a few seconds.*

---

## Who it's for

The client is **Kustsol AB — a fictional company**, invented for a university course
assignment. It is a mid-sized solar installer in the Gothenburg region (electricity price
area SE3) with its own team of energy advisors.

The **user is the advisor**, in the customer meeting and when writing the quote. The
homeowner is not the user — they are the advisor's customer, looking over their shoulder.

Nothing here is financial advice, and no part of this is a real commercial product.

## Why now

Sweden abolished the 60 öre/kWh tax reduction for sold micro-production on **1 January
2026**. Selling surplus now earns roughly the bare spot price, while every kWh used on
site avoids spot price *plus* energy tax, grid fee and VAT.

The old pitch — "sell your surplus" — stopped working. **Self-consumption, and therefore
batteries, now decides whether solar pays.** That is the question this tool answers.

## What it answers

| Question | Where the app answers it |
|---|---|
| 1. How much would this system have produced, hour by hour, over the last 12 months? | The overlay chart, and the donut's centre total |
| 2. How well does production line up with the expensive hours? | The overlay chart (shared time axis) and the hour × month heatmap |
| 3. Where does the solar power go — own use, battery, or sold? | The donut |
| 4. What is the yearly value in SEK for no solar / solar only / solar + battery? | The scenario bars and the KPI cards |
| 5. How does roof orientation change that value? | A one-line comparison under the KPI cards |

A second tab, **Tomorrow**, makes it concrete: tomorrow's prices and forecast production,
the battery's plan in plain language ("store solar 11:00–14:00, run the house off the
battery 17:00–21:00"), and what it saves on the day.

## Screenshots

*(Added after deployment — the Customer calculation tab, the donut and scenario bars, the
hour × month heatmap, and the Tomorrow tab's plan.)*

## How the numbers are made

Every rule is simple enough for an advisor to explain at a kitchen table. There is no
optimiser.

- **Production per hour** = kWp × tilted irradiance (W/m²) ÷ 1000 × 0.85. An east–west
  roof is modelled as half the array each way.
- **Buy price** = (spot + energy tax + grid fee) × (1 + VAT).
  **Sell price** = spot + grid benefit (*nätnytta*), no VAT.
- **Battery, four ordered rules per hour:** solar covers the house first; surplus charges
  the battery, then is sold (or curtailed if the sell price is below zero); the battery
  covers the house in hours above that day's median price; and it tops up from the grid in
  cheap hours only when the spread beats the round-trip loss plus a margin — and only for
  the room the sun is not expected to fill.
- **Round trip** 90%, booked entirely on discharge: "put 10 kWh in, get 9 kWh back".
- **Energy balance**, asserted per hour in the tests:
  `production = own use + to battery + sold + curtailed` and
  `consumption = own use + from battery + bought for the house`.

**Household consumption is a modelled assumption, not measured data.** No open data exists
for one household's hourly load, so the annual figure the advisor enters is spread over
the year using a typical villa shape — morning and evening peaks, winter roughly 2.6×
heavier than summer. The shape matters more than the total: what drives the whole analysis
is *when* the house uses power relative to when the sun shines.

The **fixed** annual grid charge is deliberately excluded. It does not change with solar or
a battery, so it cancels out of every comparison the app makes.

## Known limitations

The honest list. These are why the payback figure looks long.

- **Payback excludes** the green-technology deduction (*grön teknik*), capacity/effekt
  tariff savings, and frequency-regulation income (FCR-D and similar) — the three places
  Swedish home-battery economics actually lives.
- **`nätnytta` is an unsourced placeholder** (5 öre/kWh). It moves every figure involving
  exported power and should be checked against the customer's grid operator. Flagged in
  the app's Assumptions panel too.
- **Consumption is an assumption**, as above. A customer's own hourly data would replace it
  and is the single biggest available improvement to the self-consumption share — the
  number the whole battery case rests on.
- **Grid charging is decided within a calendar day.** On ~11% of days the model declines to
  charge because the day's cheapest hours fall at the very end, with nothing left to
  discharge into. A real battery charges across midnight; this is a calendar artefact of
  the model, not economics.
- **Tomorrow's plan assumes today runs as modelled**, since the battery's state at midnight
  comes from simulating today.
- **One year of weather is one year of weather.** The figures are what this system would
  have done over the last 12 months, not a forecast.
- **Light theme only.** The chart palette was validated against a light surface, so the app
  pins a light theme rather than following the visitor's dark-mode preference.

## Data sources

- **Spot prices (SE3)** — Elpriset just nu.se.
  *Elpriser tillhandahålls av [Elpriset just nu.se](https://www.elprisetjustnu.se).*
  One static JSON file per day per price area, no API key.
- **Solar irradiance** — *Weather data by [Open-Meteo.com](https://open-meteo.com)*.
  `global_tilted_irradiance` for Gothenburg (57.71, 11.97), archive and forecast endpoints.
  **Open-Meteo's free tier is for non-commercial use; this is a non-commercial course
  project.**
- **Household consumption** — an assumption, as described above.

**Polite use of both APIs.** A settled past day's spot price can never change, so those days
are served from a committed snapshot and the price API is not called at all. A 12-month view
costs zero requests rather than 365, and a cold start makes about three requests in total.

## Run it locally

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/streamlit run app.py
```

Tests:

```bash
.venv/bin/pytest -q      # 201 tests
```

**No test touches the network.** The ones that use real data read the committed snapshot in
`data/cache/` directly.

## Project structure

```
app.py                 # Streamlit entry point: layout and widgets only
src/prices.py          # spot prices, with the settled-day cache fast path
src/cache.py           # day-granularity CSV cache
src/transform.py       # colour categorisation, aggregation, the production split
src/calc.py            # cheapest-window search (used by the battery's rule 4)
src/solar.py           # irradiance fetch + production estimate
src/consumption.py     # villa consumption profile (an assumption)
src/battery.py         # hourly battery simulation + the three scenarios
src/plan.py            # tomorrow's plan in plain language
src/config.py          # every constant and stated assumption
scripts/warm_cache.py  # refresh the committed snapshot before a demo
data/cache/            # committed snapshots: offline fallback and fast path
tests/                 # 201 tests, none hitting the network
SPRINTLOG.md           # the full build log — the report's primary source
```

## Deploying

1. Push to a public GitHub repo.
2. At [share.streamlit.io](https://share.streamlit.io), sign in with GitHub and choose
   **Create app → Deploy a public app from GitHub**.
3. Repository = this repo, Branch = `main`, Main file path = `app.py`.
4. **Advanced settings → Python version → 3.11**, *before* the first deploy. This matters:
   `pandas==3.0.6` requires Python ≥ 3.11 and ships no wheel for 3.10, and pip's failure
   message does not say so clearly.
5. Deploy, then open the URL in a private window to check it as a visitor would.

**Maintenance.** The committed cache covers a rolling 12-month window, and Community Cloud's
filesystem is ephemeral, so the snapshot decays by about one day per day. Before any demo or
examination:

```bash
.venv/bin/python scripts/warm_cache.py
git add data/cache && git commit -m "chore: refresh cached year"
```

## About this project

Built for **Digital Leadership, University of Gothenburg**, as an exercise in running a
design process rather than just producing software — the process is the deliverable as much
as the app.

The project **pivoted at Sprint 5.** It began as an industrial load-shifting dashboard for a
different fictional client (v1, Sprints 0–4, tagged `v1-industrial`); a business-case review
found it had no clear user and a weak savings case, so it became this. Most of the code
carried over — the price pipeline, caching, colour coding, the chart layer and the tests —
while solar, consumption and battery logic were added.

**[SPRINTLOG.md](SPRINTLOG.md) is the full story**: every sprint's goal, decisions and why
they were made, alternatives rejected, problems hit and how they were solved. It is the
primary source for the course's ideation report, and it includes the things that went wrong.
