# CLAUDE.md — Solar Advisor Dashboard (pivot of the Energy Price Dashboard)

## This is a pivot — read this first
This repo contains a working Streamlit prototype (**v1**, Sprints 0–4, tagged
`v1-industrial`): an energy price dashboard for a fictional manufacturer,
Älvdal Industri AB, that recommended when to run production units based on spot
prices.

A business-case review (logged as a Test finding) showed two problems: the
dashboard had no clear user, and its savings case was weak. We therefore pivoted
to a new client and a new use case, described below.

**This is a pivot, not a restart.** Most of v1 carries over, because the new use
case runs on the same core data (hourly spot prices) and needs the same building
blocks: the price pipeline, colour coding, tabs, an overlay chart, KPI cards,
plain-language recommendations, cheapest-window search, caching, tests and
deployment. The job is to **adapt** these and **add** solar production and
battery logic.

**Principle: reuse first.** Adapt existing components before writing new ones.
If rewriting something is cheaper than adapting it, say so and ask first.

All v1 SPRINTLOG entries are kept — the pivot is part of the story the report
tells.

## What the dashboard is for
**In one sentence:** a sales tool that lets Kustsol's energy advisors show a
customer, with real data, whether solar panels — and a battery — pay off for
them, and which package to recommend.

- **Client:** Kustsol AB (fictional), a mid-sized solar installer in the
  Gothenburg region (price area SE3) with its own team of energy advisors.
- **User:** the energy advisor, in the customer meeting and when writing the quote.
- **Not the user:** the homeowner. They are the advisor's customer, looking over
  the advisor's shoulder.
- **Decision supported:** recommend solar only or solar + battery, and which
  battery size, backed by numbers the advisor can stand behind.
- **Why now:** the tax reduction for sold micro-production (60 öre/kWh) was
  abolished on 1 January 2026. Selling surplus now earns roughly the spot price,
  while every kWh used on site avoids spot price + energy tax + grid fee + VAT.
  The old pitch, "sell your surplus", no longer works. Self-consumption — and
  therefore batteries — now decides profitability.

**How an advisor uses it in a meeting:**
1. Enters the customer's annual consumption, system size, roof orientation and
   battery size.
2. Opens "Customer calculation": the last 12 months, hour by hour — when the sun
   produced vs. when electricity was expensive, where the solar power went, and
   the yearly value in SEK for each scenario.
3. Adjusts the battery size live with the customer and lands on a recommendation.
4. Opens "Tomorrow" to make the battery concrete: "this is how your battery
   would run tomorrow".

**What it is NOT:** a homeowner app for steering their own battery (possible
future project — mention only), or a price forecasting tool.

## Problem statement
How might we help Kustsol's energy advisors give every customer a credible,
data-based answer to "Is solar, and a battery, worth it for me now that the
60-öre tax reduction is gone?"

Questions the dashboard must answer:
1. How much would this customer's system have produced, hour by hour, over the
   last 12 months?
2. How well does solar production line up with the expensive hours?
3. Where does the solar power go: own use, battery, or sold?
4. What is the yearly value in SEK for: no solar / solar only / solar + battery?
5. How does roof orientation (south vs. east–west) change that value?

## What the data is used for
| Data | Source | Used for | Where it shows up |
|---|---|---|---|
| Hourly spot prices, SE3 | elprisetjustnu — `src/prices.py` | The value of every kWh: what bought power costs and what sold power earns | Colour-coded price bars, all SEK calculations, tomorrow's plan |
| Hourly solar irradiance on a tilted panel, Gothenburg | Open-Meteo (historical + forecast) — `src/solar.py` | Estimating production each hour, for a south or east–west roof | Production line overlaid on prices, donut, scenarios, tomorrow's plan |
| Household consumption per hour | **Assumption** (no open data): annual kWh × a typical villa profile — `src/consumption.py` | How much solar power the household can use itself each hour | Self-consumption share, donut, scenarios |
| Taxes, grid fee, grid benefit (nätnytta), battery parameters | Constants in `src/config.py` — **TODO: Fabian verifies the values** | Turning spot prices into real buy/sell prices, defining battery behaviour | Assumptions expander, all SEK calculations |

**The insight the data must make visible:** in summer, solar production peaks
midday, when prices are often at their lowest, while prices peak in the morning
and evening. The battery bridges that gap. Every chart should help the advisor
show this.

Data notes:
- **Spot prices:** area fixed to SE3, shown as a label.
- **Open-Meteo:** Gothenburg (57.71, 11.97), `global_tilted_irradiance` with
  `tilt` and `azimuth`. Verified in Sprint 5: the same parameter names work on
  both the archive and forecast endpoints. **Azimuth convention: −90 = East,
  0 = South, +90 = West.** Always request `timezone=UTC` and convert locally —
  asking for `timezone=Europe/Stockholm` returns wall-clock hours that don't
  exist on DST days. Footer attribution: "Weather data by Open-Meteo.com". The
  free tier is non-commercial; note this in the README.
- **Consumption profile:** daily shape with morning and evening peaks × monthly
  factors (higher in winter), documented as an assumption.

## v1 → v2 inventory
Corrected in Sprint 5 against the actual code (four rows in the original table
were wrong; see the Sprint 5 SPRINTLOG entry).

| v1 component | Action | In v2 |
|---|---|---|
| `src/prices.py`, `src/cache.py` (caching + snapshot fallback) | Keep | Unchanged; area fixed to SE3 |
| Colour coding, KPI stats, aggregation (`src/transform.py`) | Keep / Adapt | Same colour logic; heatmap becomes hour × month |
| Two tabs | Adapt | Renamed "Customer calculation" (first) and "Tomorrow" |
| Temperature overlay (`src/weather.py`) | Replaced | Now a solar production line; `weather.py` → `solar.py` (done, Sprint 5) |
| Date range selector | Keep | Defaults to a summer week |
| Cheapest-window search (`src/calc.py`) | Keep | Reused for battery grid charging |
| "Start X at HH:MM" recommendations | Adapt | Same plain-language pattern for the battery plan |
| Production units table + load-shift planner (rest of `calc.py`) | Replace | Customer inputs: consumption, kWp, orientation, battery size |
| Peak power metric | Removed | Done, Sprint 5 |
| Price area dropdown + area comparison | Removed | Done, Sprint 5 — SE3 fixed |
| Tests, SPRINTLOG, deployment setup | Keep | Extended. **Note: v1 was never actually deployed** — no git remote exists yet; Sprint 8 owns it |

## Hard constraints (non-negotiable — set by the assignment)
- The dashboard is built in **Python with Streamlit**. Entry point is `app.py`,
  run with `streamlit run app.py`.
- No other app frameworks or front ends: no Dash, Flask, FastAPI, Django, React
  or custom JavaScript. A Jupyter notebook is not a deliverable.
- All UI uses Streamlit widgets and layout. Charts are Plotly via
  `st.plotly_chart`, or Streamlit's native charts. No custom HTML/JS components.
- Development happens in VS Code. The finished app is deployed on Streamlit
  Community Cloud from the GitHub repo.
- If a task seems to require anything outside Python + Streamlit, stop and ask.

## Calculation model — simple and explainable
An advisor must be able to explain every rule to a customer. No optimisation
solvers.

- **Production per hour (kWh)** = kWp × tilted irradiance (W/m²) ÷ 1000 × 0.85.
  The loss factor is an assumption shown in the UI. An east–west roof is half the
  array each way, i.e. the mean of the −90° and +90° irradiance series.
- **Prices:** buy price per kWh = (spot + energy tax + grid fee) × (1 + VAT).
  Sell price per kWh = spot + grid benefit (nätnytta), no VAT. All constants in
  `src/config.py`. The **fixed** annual grid charge is deliberately excluded: it
  doesn't change with solar or a battery, so it cancels out of every scenario
  difference.
- **Hourly battery rules, applied in this order:**
  1. Solar covers the household's own consumption first.
  2. Surplus charges the battery until full; any remaining surplus is sold.
     Never sell at a negative price — i.e. when the *sell* price is below zero,
     the surplus is curtailed instead.
  3. When consumption exceeds solar, the battery covers it during hours priced
     above that day's median; otherwise buy from the grid.
  4. Grid charging: if the day's most expensive hours are enough more expensive
     than the cheapest hours to beat the round-trip loss **plus a margin in
     SEK/kWh**, charge the battery in the cheapest hours (reuse the
     cheapest-window search). Compare **buy** prices, not spot — you pay tax,
     grid fee and VAT on the energy the round trip throws away.
- **Battery assumptions:** round-trip efficiency 0.9, booked entirely on
  discharge ("10 kWh in, 9 kWh out"); max charge/discharge power = capacity ÷ 2
  per hour. Both in `src/config.py`.
- **Energy balance (mandatory, tested):** for every hour,
  `production = own use + to battery + sold + curtailed` and
  `consumption = from solar + from battery + bought for the house`.
  The fourth production term exists because surplus at a negative sell price is
  neither used, stored nor sold. Grid-charge energy is tracked separately from
  household purchases, or the consumption identity breaks.
- **Scenarios:** no solar (all consumption bought), solar only (battery = 0),
  solar + battery. Yearly cost for each; value = the difference.
- **Optional payback:** simple payback time = battery price ÷ yearly battery
  value. The model deliberately excludes the green-technology deduction,
  capacity/effekt-tariff savings and frequency-regulation income — the three
  places Swedish home-battery economics actually lives. **These exclusions must
  be stated in the UI**, because they are why the honest payback figure looks
  long.

## Dashboard
**Inputs (top of page):** annual consumption (kWh), system size (kWp slider),
roof orientation (South / East–West), battery size (kWh slider, including 0),
optional battery price (SEK).

**Tab 1 — "Customer calculation"** (adapted from History; the sales tool):
- KPI cards: yearly value of solar only, of solar + battery, self-consumption
  share, optional payback time.
- Overlay chart: colour-coded hourly price bars with solar production shown in a
  **second panel sharing the same time axis** — not a second y-axis. Dual-axis
  is a known chart-reading trap, and the shared time axis is the whole point:
  the pitch is *when* production happens versus *when* power is expensive.
- Donut: where the solar power goes (own use / battery / sold / curtailed).
- Scenario comparison: yearly cost in SEK for the three scenarios.
- Heatmap: average price, hour of day × month.

**Tab 2 — "Tomorrow"** (adapted from Plan ahead):
- Tomorrow's colour-coded prices with forecast production overlaid.
- Battery plan in plain language, e.g. "Charge from the grid 02–05, store solar
  11–14, use the battery 17–20".
- If tomorrow's prices are not yet published (before ~13:00), show a clear message.

**General:** all money in SEK (never öre for totals), plain-language labels, one
sentence under each chart saying what to look for, assumptions in an expander,
data attributions in the footer.

## Project structure
```
app.py                 # Streamlit entry point: layout, widgets, charts only
src/prices.py          # spot prices (keep)
src/cache.py           # day-granularity CSV cache + offline fallback (keep)
src/transform.py       # colour categorisation, KPI stats, aggregation (keep)
src/calc.py            # cheapest-window search (keep, reused for grid charging)
src/solar.py           # irradiance fetch + production estimate
src/consumption.py     # villa consumption profile (assumption)
src/battery.py         # hourly battery simulation + scenarios
src/plan.py            # tomorrow's plan in plain language (added Sprint 8:
                       # presentation logic, kept out of battery.py so
                       # user-test wording changes never touch tested physics)
src/config.py          # all constants and assumptions
data/cache/            # snapshots, committed as offline fallback
tests/
SPRINTLOG.md
README.md
requirements.txt
```

## Engineering rules
- Keep logic in `src/` as pure functions (DataFrame in, DataFrame out).
  `app.py` only wires widgets to functions.
- Cache API calls with `st.cache_data` and persist snapshots to `data/cache/`.
  If an API fails, fall back to the snapshot and show a notice. Never crash.
- **Energy balance test is mandatory** — see the calculation model above. Test it
  per hour, for all three scenarios, on fixtures that actually exercise every
  branch.
- Other edge cases to test: battery = 0, zero production (night/winter),
  negative prices, missing price days.
- Timestamps: parse as UTC, convert to Europe/Stockholm afterwards; never do day
  arithmetic with `Timedelta(days=1)` on a local index (use `DateOffset`, or
  group by `index.date`).

## Sprints — do not build ahead of the current sprint
- **Sprint 5 — Pivot setup and spike.** Tag `v1-industrial`, inventory the code,
  remove what the pivot removes, spike Open-Meteo. *Done.*
- **Sprint 6 — Model.** `solar.py`, `consumption.py`, `battery.py`, `config.py`,
  with tests including the energy balance test. Done when: all three scenarios
  return yearly SEK values and all tests pass.
- **Sprint 7 — Adapt "Customer calculation".** Inputs, KPI cards, overlay, donut,
  scenario comparison, heatmap, assumptions expander. Done when: an advisor can
  answer questions 1–5 for a made-up customer.
- **Sprint 8 — Adapt "Tomorrow", test and ship.** Battery plan in plain language,
  polish, user test with 2–3 people acting as advisors, fixes, README, deploy.
  Done when: the public link works in a clean browser.

## After every sprint (mandatory)
1. Append an entry to SPRINTLOG.md using the template below.
2. Commit and tag: `git tag sprint-N`.
3. Remind me to take screenshots of the app for the report.

SPRINTLOG template:
```
## Sprint N — <name> (<date>)
Goal:
Built:
Reused from v1 / adapted / new:
Decisions (and why):
Alternatives considered and rejected (and why):
Problems hit / how solved:
Open questions for next sprint:
```

## How to work with me
- Explain key decisions in one or two sentences so I can defend them in the
  report and the video.
- If you see a better approach than the one described here, propose it and wait
  for my go-ahead.
- Ask before adding dependencies or features outside this scope.
