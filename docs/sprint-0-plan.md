# Sprint 0 — Energy Price Dashboard spike

## Context

This is a new University of Gothenburg course project (Digital Leadership): a Streamlit dashboard helping a fictional client (Älvdal Industri AB, price area SE3) see electricity spot-price patterns and the savings from shifting flexible loads to cheaper hours. A `CLAUDE.md` already exists describing the full project (hard constraints, file structure, 5-sprint plan), but **no code exists yet** — the working directory (`/Users/fabianfredlund`) isn't even a git repo, and no scaffold for this project was found anywhere on disk. (A prior unrelated Flask experiment, `elpool_app/`, exists but doesn't fit the Streamlit-only constraint and isn't reused.)

Per CLAUDE.md's sprint discipline ("do not build ahead of the current sprint"), this plan covers **Sprint 0 only**: fetch one month of SE3 prices and Gothenburg temperature, print shapes, show one chart in a minimal Streamlit page, and answer every "verify" item CLAUDE.md lists for the two APIs.

Before planning, I fetched both APIs live and confirmed several things that **correct or extend** what CLAUDE.md's Sprint 0 verify list assumed:

- **Timezone**: elprisetjustnu's docs page claims a fixed `+01:00` offset. Live requests show it's actually real Europe/Stockholm local time with DST (`+01:00` winter, `+02:00` summer). Parsing must convert via UTC, not hardcode an offset.
- **Resolution transition**: confirmed exactly at 2025-09-30 (24 entries/day) → 2025-10-01 (96 entries/day, 15-min).
- **Earliest data**: docs claim 2022-11-01; a live request for 2022-10-01 also returned valid data, so the true floor is unclear (and possibly irrelevant — see below).
- **Missing/future days**: return HTTP 404 with a small error-shaped JSON body, not an empty price array. Must be handled as "skip this day," never parsed as prices.
- **SMHI station**: chose station **71420, "Göteborg A"** (central Gothenburg, active since ~1961, currently active) over airport/inactive alternates.
- **SMHI granularity**: the metobs API has no true "hourly mean" — parameter 1 is hourly *instantaneous* temperature, parameter 2 is a *daily* mean. Parameter 1 is the right (only) choice for an hourly series.
- **SMHI periods**: `latest-months` (rolling ~4 months, provisional) is enough for a one-month spike; `corrected-archive` (quality-controlled) is a Sprint 1+ concern for older ranges.

Separately, this machine only has **Python 3.9.7** (system `python3` and base conda env both), but CLAUDE.md hard-requires 3.11+. You chose to install Python 3.11 via Homebrew and use a standard `venv`, rather than a conda environment.

You also asked me to include a couple of light smoke tests now (not deferred wholesale to Sprint 4), since they're cheap and lock in the DST-offset and 404-handling behavior just discovered by trial and error.

## Approach

### 1. Environment
```bash
brew install python@3.11
mkdir -p ~/projects/energy-price-dashboard
cd ~/projects/energy-price-dashboard
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
```

### 2. Repo scaffold (matches CLAUDE.md's required structure exactly)
```
energy-price-dashboard/
├── .gitignore
├── README.md
├── SPRINTLOG.md
├── requirements.txt
├── app.py
├── src/
│   ├── __init__.py
│   ├── prices.py
│   ├── weather.py
│   ├── transform.py    # docstring-only stub, implemented in a later sprint
│   └── calc.py          # docstring-only stub, implemented in a later sprint
├── data/cache/.gitkeep  # real snapshots start in Sprint 1
└── tests/
    ├── test_prices.py
    └── test_weather.py
```
`git init` this directory (it's a new standalone repo, separate from `~/projects/fieldops`).

`requirements.txt` — loose `>=` pins (no existing lockfile to match yet; tighten to exact versions at Sprint 4 per CLAUDE.md's "README/deploy" milestone):
```
streamlit>=1.38
pandas>=2.2
plotly>=5.24
requests>=2.32
pytest>=8.3
```

`.gitignore`: `__pycache__/`, `*.py[cod]`, `.pytest_cache/`, `.venv/`, `.streamlit/secrets.toml`, `.DS_Store`. `data/cache/` is **not** ignored — CLAUDE.md commits snapshots there as offline fallback — but Sprint 0 only adds a `.gitkeep`, since the snapshot format is a Sprint 1 decision.

### 3. `src/prices.py` — pure fetch+parse, no Streamlit
- `fetch_prices(start_date, end_date, area="SE3") -> tuple[pd.DataFrame, list[date]]`, looping days in range. The second return value is the list of days that **failed to fetch** (as opposed to days confirmed to have no data) — see below.
- `_fetch_day(day, area) -> tuple[list | None, bool]`: builds the URL (`.../{YYYY}/{MM}-{DD}_{AREA}.json`), GETs with a 10s timeout. Only **HTTP 404** means "confirmed no data for this day" → `(None, False)`, no retry needed. Timeouts, connection errors, and any 5xx/other non-200 status are treated as **transient failures**: retry (2 attempts, backoff), and if still failing, return `(None, True)` — a day that *should* exist but couldn't be fetched, never silently dropped like a 404. `fetch_prices` collects every day where `failed=True` into the returned `failed_days` list so the caller can report them, instead of a gap in the chart looking identical to a confirmed 404.
- `_parse_day(records)`: parses `time_start` via `pd.to_datetime(..., utc=True)` (kept in UTC), then **unconditionally** `resample("1h").mean()` **while still in UTC**, and only converts to `Europe/Stockholm` with `.tz_convert(...)` *after* resampling. Resampling in UTC first — rather than on an already-localized Europe/Stockholm index — avoids the ambiguity of DST transitions (fall-back repeats a local hour; spring-forward skips one), where every UTC instant is still unambiguous and monotonic. This also replaces the literal "detect 24 vs 96 and branch" language in CLAUDE.md's verify item: resampling already-hourly data is a no-op, and it correctly handles the 23/25-entry DST-transition days without a separate branch.
- Returns SEK_per_kWh/EUR_per_kWh/EXR as the API gives them (no öre/kWh conversion here — that's a display-layer concern for `app.py`/later sprints, keeping this module a plain pass-through).

### 4. `src/weather.py` — pure fetch+parse, no Streamlit
- `fetch_temperature(start_date, end_date, station_id=71420) -> pd.DataFrame`.
- Two-step fetch per SMHI's API design: period metadata endpoint → follow its `data[0].link` → actual `data.json` with `{date: epoch_ms, value: "14.0", quality: "G"}` records.
- `_pick_period()` returns `"latest-months"` for now (placeholder seam; Sprint 1+ branches to `corrected-archive` for older ranges).
- Unlike `prices.py`, uses `raise_for_status()` on failures — an SMHI error here (bad station id, renamed period) is an unexpected bug, not an confirmed/normal condition like elprisetjustnu's 404s, so it should surface loudly during the spike rather than being swallowed.

### 5. `app.py` — minimal spike page, no widgets yet
- Fetches SE3 prices and Göteborg temperature for **August 2026** (most recent fully-complete month; entirely past the 2025-10-01 resolution change, so it exercises both the resampling and DST-offset logic).
- Wraps both fetches in `st.cache_data(ttl=3600)` — satisfies CLAUDE.md's "cache API calls even at spike stage" cheaply, without building the heavier disk-snapshot/fallback machinery (Sprint 1 scope). Wrappers live in `app.py`, keeping `src/` Streamlit-free per the "DataFrame in, DataFrame out" rule.
- `fetch_prices` now returns `(df, failed_days)` (see above) — `app.py` unpacks both and prints the count of failed days alongside the shapes, so a fetch failure is visible rather than silently invisible in the chart. The richer treatment (a proper notice, distinguishing missing-vs-failed in the UI) is explicitly deferred — see Open questions below.
- `st.write`s both DataFrame shapes (plus failed-day count), `st.dataframe` head previews, and one `st.plotly_chart` line chart of SE3 price over time.
- `fetch_temperature` still uses `raise_for_status()` internally (Step 4) and `app.py` does **not** catch it in Sprint 0 — a real SMHI failure will surface as an unhandled error during the spike, which is intentional for now (see Open questions below) but noted as a gap to close before this is a resilient app.

### 6. `tests/` — light smoke tests (per your go-ahead)
- `test_prices.py`:
  - resampling 96→24 rows, 24→24 identity case
  - DST offset correctness (winter `+01:00` vs summer `+02:00` land on the right UTC instant)
  - **DST transition days**, resampled in UTC then converted: **2025-10-26** (fall-back, 100 synthetic quarter-hour entries spanning the repeated local hour → 25 hourly rows) and **2026-03-29** (spring-forward, 92 quarter-hour entries → 23 hourly rows)
  - `_fetch_day` returns `(None, False)` on a mocked 404 (confirmed no data, no retry)
  - `_fetch_day` returns `(None, True)` after exhausting retries on a mocked timeout/5xx (failed, not silently dropped)
  - all against the pure helpers, no live network calls except where mocked
- `test_weather.py`: `_parse_payload` correctly casts epoch-ms → tz-aware timestamp and string → float temperature.

### 7. `SPRINTLOG.md` and `README.md`
- `SPRINTLOG.md`: Sprint 0 entry using CLAUDE.md's template, with the Decisions/Alternatives/Problems-hit content drawn directly from the findings above (DST correction, UTC-then-convert resampling, 404-vs-failed distinction, earliest-date uncertainty, SMHI period choice). **Open questions for next sprint** includes, in addition to earlier items:
  - the app layer must catch weather API errors (currently `raise_for_status()` propagates uncaught) and show a notice instead of crashing
  - the UI should show the number of missing/failed days in a proper, visible way (Sprint 0 only prints a raw count; needs real treatment)
  - verify SMHI's `corrected-archive` and `latest-months` periods overlap with no gap, for when Sprint 1+ needs to stitch them together across a date range
- `README.md`: thin stub (project description, run instructions, data source links) — fleshed out properly at Sprint 4 per the sprint plan.

### 8. After building
- Two commits: `chore: scaffold repo structure`, then `feat: Sprint 0 spike — fetch SE3 prices and Gothenburg temperature, render one chart`.
- `git tag sprint-0`.
- Copy this plan into the repo at `docs/sprint-0-plan.md`.
- Remind you to screenshot the running app for the report.

## Critical files
- `/Users/fabianfredlund/projects/energy-price-dashboard/src/prices.py`
- `/Users/fabianfredlund/projects/energy-price-dashboard/src/weather.py`
- `/Users/fabianfredlund/projects/energy-price-dashboard/app.py`
- `/Users/fabianfredlund/projects/energy-price-dashboard/SPRINTLOG.md`
- `/Users/fabianfredlund/projects/energy-price-dashboard/requirements.txt`

## Verification
1. `source .venv/bin/activate && pytest` — smoke tests pass, including the two DST-transition cases (2025-10-26 → 25 rows, 2026-03-29 → 23 rows) and the 404-vs-failed distinction in `_fetch_day`.
2. `streamlit run app.py` — page loads, shows both DataFrame shapes (~744 hourly rows expected for August), the failed-day count (expected 0 for a normal August fetch), a data preview, and one price line chart covering all of August 2026 with no gaps or crashes.
3. Manually eyeball that the chart's price scale looks like plausible SEK/kWh values and that the line covers the full month without gaps (confirms the 404-skip logic isn't silently dropping real days, and that no day was misclassified as "failed").
4. Confirm `git log` shows the two commits, `git tag` shows `sprint-0`, and `docs/sprint-0-plan.md` is present in the repo.
