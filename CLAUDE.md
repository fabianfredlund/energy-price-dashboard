# CLAUDE.md — Solar Advisor Dashboard (pivot of the Energy Price Dashboard)

> **Define iteration 2 (2026-10-06).** The problem statement was narrowed from
> five questions to four and most of the Sprint 7–8 UI was deleted (Tomorrow tab,
> heatmap, donut, date-zoom chart, KPI cards). This file describes the state
> **after** that iteration. SPRINTLOG.md has the reasoning and the removal trail.

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
1. Enters the customer's annual consumption, system size, roof orientation,
   system price and battery price per kWh.
2. Reads the two answer cards aloud: solar yes/no with its payback and yearly
   saving, then battery yes/no with the recommended size.
3. If asked "why?", scrolls to the payback curve, the battery-size chart and the
   average day.
4. If a number is wrong for this customer, corrects it in the assumptions box and
   the answers update.

**What it is NOT:** a homeowner app for steering their own battery (possible
future project — mention only), or a price forecasting tool.

## Problem statement
How might we help Kustsol's energy advisors give every customer a credible,
data-based answer to "Is solar, and a battery, worth it for me now that the
60-öre tax reduction is gone?"

**The dashboard answers four questions, nothing else** (narrowed from five in
Define iteration 2 — the old set asked for evidence where the advisor needed a
conclusion):

1. Is solar worth it for this customer? (yes/no)
2. How long until the investment is paid back, and how much does it save per year?
3. Should they get a battery? (yes/no)
4. If yes, how big?

Everything on screen serves one of those four. The hourly simulation stays under
the hood; the screen shows results, not dates.

## What the data is used for
| Data | Source | Used for | Where it shows up |
|---|---|---|---|
| Hourly spot prices, SE3 | elprisetjustnu — `src/prices.py` | The value of every kWh: what bought power costs and what sold power earns | Every SEK figure; the average-day chart |
| Hourly solar irradiance on a tilted panel, Gothenburg | Open-Meteo (archive) — `src/solar.py` | Estimating production each hour, for a south or east–west roof | Every SEK figure; the average-day chart |
| Household consumption per hour | **Assumption** (no open data): annual kWh × a typical villa profile — `src/consumption.py` | How much solar power the household can use itself each hour | Every SEK figure |
| Taxes, grid fee, deduction rates, lifetimes, battery parameters | Defaults in `src/config.py`, **editable in the UI**, each carrying its source and "last updated" date | Turning spot prices into real buy/sell prices, and investment into payback | The assumptions box; all SEK calculations |

**The window is fixed: Oct 2023 – Sep 2026, three full years**, with today's
rules applied to all three. Fixed rather than rolling so the numbers are
identical across the written report, the screenshots and the pitch video. It is
stated on screen. Yearly figures are the **average of the three years, always
shown with the range** — the spread between years is large enough that an average
alone would be a forward-looking claim the data does not support.

**The insight the data must make visible:** in summer, solar production peaks
midday, when prices are often at their lowest, while prices peak in the morning
and evening. The battery bridges that gap. That is what the average-day chart is
for, and it is the only chart whose job is explanation rather than conclusion.

Data notes:
- **Spot prices:** area fixed to SE3, shown as a label. The window spans the
  change from hourly (24/day) to 15-minute (96/day) resolution on 2025-10-01;
  `_parse_day` resamples both to hourly, so one code path handles it.
- **Open-Meteo:** Gothenburg (57.71, 11.97), `global_tilted_irradiance` with
  `tilt` and `azimuth`. Verified in Sprint 5: the same parameter names work on
  both the archive and forecast endpoints. **Azimuth convention: −90 = East,
  0 = South, +90 = West.** Always request `timezone=UTC` and convert locally —
  asking for `timezone=Europe/Stockholm` returns wall-clock hours that don't
  exist on DST days. Footer attribution: "Weather data by Open-Meteo.com". The
  free tier is non-commercial; note this in the README.
- **Consumption profile:** daily shape with morning and evening peaks × monthly
  factors (higher in winter), documented as an assumption.

## v1 → v2 → v3 inventory
Corrected in Sprint 5 against the actual code (four rows in the original table
were wrong; see the Sprint 5 SPRINTLOG entry). The third column was added in
Define iteration 2 — rows are **not** deleted when something is removed, because
the removal trail is part of what the report has to show.

| v1 component | Action | In v2 | v3 (Define 2) |
|---|---|---|---|
| `src/prices.py`, `src/cache.py` (caching + snapshot fallback) | Keep | Unchanged; area fixed to SE3 | Kept. With a fixed, wholly-past window every day is settled, so the cache serves the whole window at zero HTTP requests |
| Colour coding, KPI stats, aggregation (`src/transform.py`) | Keep / Adapt | Same colour logic; heatmap becomes hour × month | **Removed entirely** — every function orphaned by the four-question layout |
| Two tabs | Adapt | Renamed "Customer calculation" (first) and "Tomorrow" | **One page, no tabs.** Tomorrow removed |
| Temperature overlay (`src/weather.py`) | Replaced | Now a solar production line; `weather.py` → `solar.py` (done, Sprint 5) | Kept; the forecast fetcher removed with Tomorrow |
| Date range selector | Keep | Defaults to a summer week | **Removed** — the window is fixed and the screen shows results, not dates |
| Cheapest-window search (`src/calc.py`) | Keep | Reused for battery grid charging | Kept — rule 4 is worth a real share of the battery's value |
| "Start X at HH:MM" recommendations | Adapt | Same plain-language pattern for the battery plan | **Removed** with the Tomorrow tab (`src/plan.py`) |
| Production units table + load-shift planner (rest of `calc.py`) | Replace | Customer inputs: consumption, kWp, orientation, battery size | Inputs become consumption, kWp, orientation, **system price, battery price per kWh**; battery size is now computed, not entered |
| Peak power metric | Removed | Done, Sprint 5 | — |
| Price area dropdown + area comparison | Removed | Done, Sprint 5 — SE3 fixed | — |
| Tests, SPRINTLOG, deployment setup | Keep | Extended | Still not deployed — no git remote. Outstanding from Sprint 8 |

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
- **Prices:** `buy = spot × (1 + VAT) + surcharge`, where the surcharge is energy
  tax + grid transfer fee, both incl. VAT. `sell = spot` — plain, no addition.
  Defaults in `src/config.py`, **editable in the UI**.
  - The buy formula is algebraically identical to v2's
    `(spot + tax + grid) × (1 + VAT)` (verified to 2.8e-17). It was reformulated
    because one editable "surcharge" field is explainable to a customer, where
    two constants inside a bracket are not. **The numbers moved because the grid
    fee was corrected** from an implied 33.75 to a sourced 23 öre incl. VAT.
  - `sell = spot` removes v2's `nätnytta`, an unsourced placeholder since Sprint
    6. Consequence: "never sell below zero" now bites at exactly 0 rather than
    −5 öre, and since ~94% of negative-spot hours sit in that band, curtailment
    rises sharply. That is real, and it is also the best argument for a battery,
    so it stays visible.
  - The **fixed** annual grid charge is still excluded: it doesn't change with
    solar or a battery, so it cancels out of every comparison.
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
- **Scenarios:** no solar (all consumption bought), then battery sizes
  0 / 5 / 10 / 15 kWh with solar. Yearly cost for each, per year, across all
  three years.
- **Decision logic** (this is what the screen reports):
  - Payback = **net investment ÷ average yearly saving**, where net investment is
    after the green technology deduction if it is switched on.
  - **Solar: yes if payback < solar lifetime** (default 25 years).
  - **Battery:** take the size with the shortest payback; recommend it **if that
    payback < the battery's expected service life** (default 15 years).
    Otherwise "No battery" — and the card must still name the best candidate and
    its payback, because a bare "No" is useless to an advisor, plus the extra
    yearly income (see below) that would flip it.
  - **The verdict is judged against the service life, not the warranty** (default
    10 years). *Test finding, 2026-10-06:* judging against the warranty made every
    realistically-priced battery say "No" — a warranty is a manufacturer's defect
    guarantee, not a claim the asset stops being useful the day it expires. When a
    "Yes" relies on the battery outliving its warranty, the card discloses that.
  - Battery payback is **marginal**: battery cost ÷ battery-only saving. That is
    the only reading that makes sense against a battery lifetime, and the UI says
    so, or it will be read as the whole system's payback.
  - **Other battery income** (SEK/year, default 0, editable): grid support
    services and capacity-charge savings, entered by the advisor from a real
    offer or the customer's tariff — not simulated, because the consumption
    profile below is a modelled assumption and a computed capacity-charge saving
    from it would be an assumption dressed up as data. Added straight to the
    battery's yearly saving before payback is computed.
- **Green technology deduction** (optional, **off by default**): 15% on solar,
  50% on battery, capped at 50 000 SEK × number of **owners** (the law requires
  joint ownership and a split invoice). The cap applies to the **combined**
  deduction; when it binds, **solar is deducted first and the battery takes the
  remainder** — solar is bought first, and it keeps the solar card stable while
  the battery sizes are swept.
- **Still excluded from automatic simulation, and the UI must say so:**
  capacity/effekt-tariff savings (49 kr/kW in this grid area) and grid support
  services — creditable only via the advisor-entered "other battery income"
  figure, never derived from the model's own synthetic consumption. Also
  excluded entirely: panel degradation, electricity-price drift, discounting.
  Simple payback is not NPV; over 15–25 years that is not a rounding error.
  These are why an honest payback looks long.

## Dashboard
One page, no tabs. Top to bottom:

**Inputs (top, integers):** annual consumption (kWh), system size (kWp), roof
orientation, system price (SEK), battery price per kWh (SEK/kWh).

**"Assumptions and deductions"** — an expander, **editable**, every value showing
its source and a "last updated" date, with a ⚠ on anything unverified. Holds the
green technology deduction (checkbox off by default; the owners input appears
only when it is ticked), the surcharge, VAT, and the two lifetimes.

1. **Two answer cards.** "Solar: Yes — paid back in X years, saves Z SEK/year
   (range A–B)". "Battery: Yes, 10 kWh — paid back in Y years", or "Battery: No —
   no size pays back within its lifetime", always naming the best candidate.
2. **Payback curve** — cumulative savings per year, starting at minus the
   investment, for solar only and solar + recommended battery. The battery is
   **retired at its lifetime, not replaced**: the combined line then continues
   accruing solar-only savings, so the permanent gap between the two lines is the
   battery's net lifetime verdict.
3. **Battery size chart** — payback per size, with a line at the battery
   lifetime.
4. **"Why?"** — an average day: solar production and spot price by hour, with a
   Summer / Winter / Full year dropdown. Two panels sharing one time axis,
   **never a second y-axis**: dual-axis is a known chart-reading trap, and the
   shared time axis is the whole point.

**General:** all money in SEK (never öre for totals); per-kWh *rates* in öre/kWh,
which is the conventional Swedish unit; plain-language labels; one sentence under
each chart saying what to look for; data attributions in the footer. No prose in
`app.py` restates a number that lives in `config.py`.

## Project structure
```
app.py                 # Streamlit entry point: layout, widgets, charts only
src/prices.py          # spot prices + settled-day cache fast path
src/cache.py           # day-granularity CSV cache + offline fallback
src/calc.py            # cheapest-window search (used by battery rule 4)
src/solar.py           # irradiance fetch + production estimate
src/consumption.py     # villa consumption profile (assumption)
src/battery.py         # hourly battery simulation (the four rules)
src/economics.py       # three-year aggregation, deduction, payback, decisions
src/config.py          # defaults with source + "last updated"; UI holds the values
scripts/warm_cache.py  # refresh the committed snapshot for the fixed window
data/cache/            # committed snapshots: offline fallback AND fast path
tests/
docs/user-test.md
SPRINTLOG.md
README.md
requirements.txt       # runtime only; requirements-dev.txt adds pytest + kaleido
```
Removed in Define iteration 2: `src/transform.py`, `src/plan.py`.

## Engineering rules
- Keep logic in `src/` as pure functions (DataFrame in, DataFrame out).
  `app.py` only wires widgets to functions.
- **Functions in `src/` never read `config.py`.** Values arrive as *required*
  keyword arguments. `config.py` holds the defaults; the widgets hold the current
  values. This is not style: the assumptions box is editable, so a function that
  reads a constant directly would silently ignore the user's edit — and partly,
  which is worse than wholly.
- Cache API calls with `st.cache_data` and persist snapshots to `data/cache/`.
  If an API fails, fall back to the snapshot and show a notice. Never crash.
- **Energy balance test is mandatory** — see the calculation model above. Test it
  per hour, for every scenario, on fixtures that actually exercise every branch.
- **Test that the editable assumptions actually move the numbers.** Read a
  figure, change a widget, assert it changed. A box that silently does nothing is
  this design's characteristic failure.
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
- **Sprint 7 — Adapt "Customer calculation".** *Done.* Most of it removed in
  Define iteration 2.
- **Sprint 8 — Adapt "Tomorrow", test and ship.** *Built, but its done-criterion
  was not met:* there is still no git remote, so the app has never been deployed,
  and the user-test script was written but never run. The Tomorrow tab it
  delivered was removed the next day in Define iteration 2.
- **Define iteration 2 — problem statement simplified.** Five questions → four;
  most of the Sprint 7–8 UI removed. *Done.*
- **Sprint 9 — The four answers.** Editable assumptions, three-year window,
  `economics.py`, the two answer cards and three charts. Done when: an advisor
  can answer the four questions for a made-up customer and every editable
  assumption demonstrably moves the result.
- **Still outstanding from Sprint 8:** deploy, and run the user test.

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
