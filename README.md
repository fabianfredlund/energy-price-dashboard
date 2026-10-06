# Solar Advisor

**A sales tool that answers four questions for an energy advisor sitting with a customer:
is solar worth it, what does it pay back in and save per year, should they get a battery,
and how big.**

🔗 **[Live app](#)** — *link added after deployment; the app sleeps when idle, so the first
load takes a few seconds.*

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
2026**. Selling surplus now earns the bare spot price, while every kWh used on site avoids
spot price *plus* energy tax, grid fee and VAT. The old pitch — "sell your surplus" —
stopped working, so **self-consumption, and therefore batteries, now decides whether solar
pays.**

## What's on the screen

Five inputs at the top: annual consumption, system size, roof orientation, system price,
battery price per kWh. Then an **editable assumptions box**, where every value carries its
source and the date it was last checked. Then, in order:

1. **Two answer cards** — "Solar: Yes — paid back in 19 years, saving 9 176 SEK/year
   (range 7 639 – 11 338)" and either a recommended battery size or a "No" that still names
   the best candidate and how far off it is.
2. **A payback curve** — cumulative savings from minus the investment, for solar alone and
   for solar plus the best battery, with the best and worst of the three years as a band.
3. **A battery size chart** — what each size pays back in, against the warranty.
4. **"Why?"** — an average day, production and spot price on a shared time axis, for summer,
   winter or the full year. The only chart whose job is explanation rather than a verdict.

The hourly simulation runs underneath. **The screen shows conclusions, not data.**

## The headline result, at sourced prices

For a 20 000 kWh villa with 10 kWp facing south, at 17 000 SEK/kWp and 7 000 SEK/kWh:

| | Verdict |
|---|---|
| **Solar** | **Yes** — 19 years, saving 9 176 SEK/year (7 639 – 11 338 across the three years) |
| **Battery** | **No** — no size pays back inside its 10-year warranty; best case 5 kWh at 24 years |

The battery "No" is a finding, not a bug. Break-even is roughly 3 200–3 500 SEK/kWh without
the deduction. The card says so, and adds the honest qualifier when it applies: with the
deduction the best size lands at 12 years — past the warranty, but **inside** a typical
15-year service life.

## How the numbers are made

Every rule is simple enough to explain at a kitchen table. There is no optimiser.

- **Production per hour** = kWp × tilted irradiance (W/m²) ÷ 1000 × 0.85, at 40° tilt. An
  east–west roof is half the array each way.
- **Buy price** = spot × (1 + VAT) + surcharge, where the surcharge is energy tax plus grid
  transfer fee, both incl. VAT. **Sell price** = the bare spot price.
- **Battery, four ordered rules per hour:** solar covers the house first; surplus charges the
  battery then is sold (or curtailed when the price is below zero); the battery covers the
  house in hours above that day's median; and it tops up from the grid in cheap hours only
  when the spread beats the round-trip loss plus a margin, and only for the room the sun is
  not expected to fill.
- **Round trip** 90%, booked entirely on discharge: "put 10 kWh in, get 9 kWh back".
- **Energy balance**, asserted per hour in the tests:
  `production = own use + to battery + sold + curtailed` and
  `consumption = own use + from battery + bought for the house`.
- **Payback** = net investment ÷ average yearly saving. Solar is judged against a 25-year
  life; each battery size against its **warranty**, on its *marginal* saving over solar alone.
- **Green technology deduction**, optional and off by default: 15% on solar, 50% on battery,
  capped at 50 000 SEK per owner. The cap is combined, and when it binds the panels are
  deducted first.

**The window is fixed: Oct 2023 – Sep 2026, three full years**, with today's rules applied to
all three. Fixed rather than rolling so the figures are identical across this README, the
report, the screenshots and the pitch video. Yearly figures are the average of the three
years and are **never shown without the range** — the years differ by enough that an average
alone would claim more certainty than the data supports.

## Known limitations

The honest list. These are why the payback looks long.

- **Payback excludes the capacity charge (effektavgift)** — 49 SEK/kW in this grid area,
  charged on the month's three highest hours. That is exactly where a battery earns, and it
  is not modelled.
- **It also excludes** frequency-regulation income, panel degradation, and any rise or fall
  in electricity prices. **Payback here is simple payback, not a discounted calculation**;
  over 15–25 years that is not a rounding error.
- **Household consumption is a modelled assumption**, not measured data. No open data exists
  for one household's hourly load, so the annual figure is spread using a typical villa shape
  — morning and evening peaks, winter roughly 2.6× heavier than summer. A customer's own
  hourly data would replace it and is the single biggest available improvement.
- **The battery is judged on its warranty, not its service life.** Warranties are typically
  10 years; expected service life is 15–25. The app says when that distinction changes the
  answer, but the verdict uses the conservative number.
- **Grid charging is decided within a calendar day.** On some days the model declines because
  the day's cheapest hours fall at the very end, with nothing left to discharge into. A real
  battery charges across midnight; this is a calendar artefact of the model, not economics.
- **Several assumptions are unverified** and marked ⚠ in the app: the grid transfer fee (it
  varies by operator and housing type — check the customer's bill), the solar lifetime, the
  loss factor, the roof pitch and the battery behaviour parameters.
- **One year of weather is one year of weather.** These are what this system would have done
  over three specific years, not a forecast.
- **Light theme only.** The chart palette was validated against a light surface.

## Data sources

- **Spot prices (SE3)** — *Elpriser tillhandahålls av
  [Elpriset just nu.se](https://www.elprisetjustnu.se).* One static JSON file per day, no key.
- **Solar irradiance** — *Weather data by [Open-Meteo.com](https://open-meteo.com).*
  `global_tilted_irradiance` for Gothenburg (57.71, 11.97), archive endpoint.
  **Open-Meteo's free tier is for non-commercial use; this is a non-commercial course
  project.**
- **Household consumption** — an assumption, as described above.

**Polite use of both APIs.** The window is fixed and wholly in the past, and a settled day's
prices and irradiance never change, so both are served from a committed snapshot. A normal
run makes **zero API requests**. Refilling the snapshot costs about 1 100 price requests and
two irradiance requests, once.

## Run it locally

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/streamlit run app.py
```

Tests:

```bash
.venv/bin/pytest -q      # 202 tests
```

**No test touches the network** — including the ones that drive the real app through
Streamlit's own test runtime.

## Project structure

```
app.py                 # Streamlit entry point: layout and widgets only
src/prices.py          # spot prices, settled days served from the snapshot
src/solar.py           # irradiance, same settled-day fast path
src/cache.py           # day-granularity CSV cache
src/consumption.py     # villa consumption profile (an assumption)
src/battery.py         # the four hourly rules; takes every assumption as an argument
src/economics.py       # three-year aggregation, deduction, payback, the verdicts
src/calc.py            # cheapest-window search (used by the battery's rule 4)
src/config.py          # defaults with source and "last updated"; the UI holds the values
scripts/warm_cache.py  # fill and --verify the committed snapshot
data/cache/            # the committed three-year snapshot
tests/                 # 202 tests, none hitting the network
docs/user-test.md      # the user-test script
SPRINTLOG.md           # the full build log — the report's primary source
```

An engineering rule worth knowing before changing anything in `src/`: **functions never read
`config.py`.** Values arrive as required keyword arguments, because the assumptions box is
editable and a function reading a constant directly would silently ignore the user's edit.
Two tests enforce it.

## Deploying

1. Push to a public GitHub repo.
2. At [share.streamlit.io](https://share.streamlit.io), sign in with GitHub and choose
   **Create app → Deploy a public app from GitHub**.
3. Repository = this repo, Branch = `main`, Main file path = `app.py`.
4. **Advanced settings → Python version → 3.11**, *before* the first deploy. This matters:
   `pandas==3.0.6` requires Python ≥ 3.11 and ships no wheel for 3.10, and pip's failure
   message does not say so clearly.
5. Deploy, then open the URL in a private window to check it as a visitor would.

The committed snapshot covers the whole fixed window, so the deployed app needs no API access
to work. If the window is ever moved, refill it:

```bash
.venv/bin/python scripts/warm_cache.py
.venv/bin/python scripts/warm_cache.py --verify
git add data/cache && git commit -m "chore: refresh cached window"
```

## About this project

Built for **Digital Leadership, University of Gothenburg**, as an exercise in running a design
process rather than just producing software — the process is the deliverable as much as the
app.

It has been through two significant changes of direction. It **pivoted at Sprint 5** from an
industrial load-shifting dashboard for a different fictional client (v1, tagged
`v1-industrial`) after a business-case review found it had no clear user. Then, at **Define
iteration 2**, the problem statement narrowed from five questions to four and most of the UI
built in Sprints 7–8 was deleted — a heatmap, a donut, a date picker and an entire second tab
— because it answered questions nobody had asked.

**[SPRINTLOG.md](SPRINTLOG.md) is the full story**: every sprint's goal, decisions and why
they were made, alternatives rejected, problems hit and how they were solved. It is the
primary source for the course's ideation report, and it includes the things that went wrong.
