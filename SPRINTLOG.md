# Sprint Log

## Sprint 0 — Spike (2026-09-30)

### Goal
Fetch one month of SE3 spot prices and Gothenburg temperature, print
DataFrame shapes, and render one chart in a minimal Streamlit page.
Confirm both APIs are usable end-to-end and surface any surprises before
building the real fetch/cache/transform layers in Sprint 1+.

### Built
- Repo scaffold matching the required structure (`app.py`, `src/`,
  `data/cache/`, `tests/`, `SPRINTLOG.md`, `README.md`, `requirements.txt`).
- `src/prices.py`: `fetch_prices(start_date, end_date, area="SE3") ->
  (DataFrame, failed_days)` — day-by-day fetch from elprisetjustnu.se,
  distinguishes confirmed-no-data (404) from transient fetch failures
  (retried, then reported), tz-aware Europe/Stockholm timestamps,
  resampled to hourly.
- `src/weather.py`: `fetch_temperature(start_date, end_date,
  station_id=71420) -> DataFrame` — two-step SMHI metobs fetch (period
  metadata -> data link -> values), hourly instantaneous temperature for
  Göteborg A.
- `app.py`: minimal page wiring the two functions through `st.cache_data`,
  printing shapes and the failed-day count, rendering one Plotly line
  chart of SE3 price for August 2026.
- `tests/test_prices.py`, `tests/test_weather.py`: smoke tests for the
  pure parsing helpers (see Problems hit below for what they guard
  against), including the two real DST-transition dates.

### Decisions (and why)
1. **Timezone**: parse `time_start` with `pd.to_datetime(..., utc=True)`
   rather than trusting a fixed `+01:00` offset — live requests showed the
   API emits the correct per-record local offset (`+01:00` winter,
   `+02:00` summer), which contradicts the elprisetjustnu docs page.
2. **Resample in UTC, convert to Europe/Stockholm afterwards**: rather
   than localizing to Europe/Stockholm first and resampling on that index,
   resampling happens while the index is still UTC (unambiguous and
   monotonic), and `.tz_convert("Europe/Stockholm")` is applied only to
   the final hourly result. This avoids the two ways a local-time index
   breaks across a DST transition: a repeated wall-clock hour on fall-back
   (two real instants labelled the same local time) and a skipped one on
   spring-forward. Verified against real API data for 2025-10-26
   (fall-back, 100 quarter-hour entries -> 25 hourly rows) and 2026-03-29
   (spring-forward, 92 -> 23).
3. **Aggregation**: always `resample("1h").mean()`, no explicit
   "if 96 entries: resample" branch. Resampling already-hourly data is a
   no-op, and — combined with decision 2 — this handles the 23/25-entry
   DST-transition days correctly without a separate branch. Simpler and
   more robust than an entry-count check.
4. **404 = confirmed no data; anything else is a failure, not silently
   dropped**: elprisetjustnu.se returns HTTP 404 (small error-shaped JSON
   body) for days with nothing published — that's treated as a normal,
   expected "no data" and not retried. A timeout, connection error, or
   any other non-200 status is treated as *transient*: retried (2
   attempts with backoff), and if still failing, the day is collected
   into a `failed_days` list returned alongside the DataFrame, so a real
   fetch problem is never silently indistinguishable from a day that
   genuinely has no data.
5. **Units stay SEK/kWh in `src/prices.py`**: the API gives SEK_per_kWh
   directly; converting to öre/kWh is a display concern and is deferred
   to `app.py` so the data layer stays a plain pass-through of API units.
6. **SMHI period = `latest-months`** for the spike — sufficient for one
   recent month of provisional data. Proper period selection for
   arbitrary historical ranges (`corrected-archive`) is deferred to
   Sprint 1+; `_pick_period()` exists as a placeholder seam.
7. **`st.cache_data` added now, disk snapshot/fallback deferred**: honors
   CLAUDE.md's "cache API calls even at spike stage" cheaply (avoids
   re-fetching on every rerun during dev) without building the heavier
   `data/cache/` snapshot-and-fallback machinery, which is Sprint 1 scope.
8. **`src/transform.py` and `src/calc.py` added as docstring-only stubs**
   so the repo structure matches CLAUDE.md's required layout from the
   first commit, even though neither is implemented yet.
9. **Light smoke tests added now, not deferred wholesale to Sprint 4**:
   cheap (well under a second, no new dependencies) and lock in three
   non-obvious behaviors discovered by trial and error today — the DST
   offset, the DST-transition row counts, and the 404-vs-failed
   distinction — so they can't silently regress while Sprint 1-3 build on
   top of this module.

### Alternatives considered and rejected (and why)
- Explicit `if len(records) > 24: resample else: pass` — rejected, see
  Decision 3.
- Resampling on an already-localized Europe/Stockholm index — rejected,
  see Decision 2; confirmed by testing against the real repeated/skipped
  hour on the two 2025/2026 transition dates.
- Treating all non-200 responses (including 404) identically as
  "skip this day" — rejected; collapses a confirmed-empty day and a real
  fetch failure into the same silent gap, which is exactly the kind of
  thing that would hide a real outage behind what looks like a normal
  missing day.
- Hardcoding earliest available date as 2022-11-01 per the docs page —
  rejected; 2022-10-01 also returned valid data live, so relied on
  graceful 404 handling instead of a hardcoded floor.
- Constructing the SMHI `data.json` URL directly from the documented
  pattern instead of following `data[0].link` from the metadata response
  — rejected for now; following the link is the API's intended usage and
  more resilient to SMHI changing internal paths.
- Committing real CSV snapshots to `data/cache/` during the spike —
  deferred; only `.gitkeep` committed, since the snapshot format belongs
  with Sprint 1's caching layer and writing one now risks a format
  Sprint 1 has to discard.

### Problems hit / how solved
- elprisetjustnu docs claim a fixed `+01:00` offset; live requests show it
  varies with DST. Solved by parsing UTC first, then converting to
  Europe/Stockholm, instead of trusting the stated offset.
- elprisetjustnu docs claim data starts 2022-11-01; a 2022-10-01 request
  returned valid data. Didn't chase the true floor — handled generically
  via 404-as-no-data so any out-of-range date degrades gracefully.
- A day with no data returns HTTP 404 with an error-shaped JSON body, not
  an empty/valid price array — unhandled, this would crash or produce
  garbage rows. Solved by checking `status_code` before parsing as prices,
  and distinguishing it from a real fetch failure (Decision 4).
- The August 2026 spike range sits entirely past the 2025-10-01 resolution
  change (24 -> 96 entries/day), so a fixed "expect N rows/day" assumption
  breaks across a month that spans the boundary. Solved by resampling
  every day to hourly mean regardless of source resolution.
- A naive "resample after localizing to Europe/Stockholm" approach breaks
  on the DST-transition dates (repeated/skipped local hour). Solved by
  resampling in UTC first (Decision 2), verified against real API data
  for 2025-10-26 and 2026-03-29.

### Open questions for next sprint
- What is the true earliest date elprisetjustnu has data for? Not
  critical now (handled via graceful 404s), but worth pinning down before
  Sprint 1's date picker needs a stated minimum.
- Should `data/cache/` snapshots (Sprint 1) store raw per-day price data
  or the already-hourly-resampled series? Affects whether the
  15-min-to-hourly step needs to be redone on cache load.
- SMHI's `latest-months` period is provisional/uncorrected — does a
  cached snapshot need to be re-fetched from `corrected-archive` once
  the date range ages out of that rolling window, and how do we detect
  that a cached snapshot has become stale in that sense?
- The app layer must catch weather API errors (`fetch_temperature`
  currently lets `raise_for_status()` propagate uncaught) and show a
  notice instead of crashing — not yet handled in Sprint 0.
- The UI should show the number of missing/failed days in a proper,
  visible way — Sprint 0's `app.py` only prints a raw count via
  `st.warning`; needs real treatment once there's a date-range picker.
- Verify SMHI's `corrected-archive` and `latest-months` periods overlap
  with no gap, so Sprint 1+ can stitch them together across an arbitrary
  date range without a hole at the boundary.

## Scope update — 2026-10-03

### What changed
Added, ahead of Sprint 2/3 implementation (not built yet — this is a
planning/scope entry):

1. **Two modes** (`st.tabs`): "History" (the existing
   date-range/area/temperature/KPI/heatmap analysis) and "Plan ahead"
   (today + tomorrow's hourly prices, current-hour marker, graceful "not
   published yet" message before elprisetjustnu.se's ~13:00 publish time
   for tomorrow — not forecasting).
2. **Colour-coded prices**: every hour classified by relative tercile +
   top-10%-spike within the displayed period (green/neutral/orange/red),
   applied to both modes, with a plain-language legend. Plan ahead uses
   hourly bars; History uses hourly bars up to 31 days and switches to
   daily bars beyond that (see CLAUDE.md "Colour-coded prices" for the
   reasoning).
3. **Production planner**: a multi-unit planner (`st.data_editor` table
   of named units) with per-unit cheapest-start recommendations, totals,
   combined peak power, and mode-aware price source (actual prices in
   Plan ahead, "typical" hour-of-day averages in History).

### Why
Came out of the Ideate/Prototype step of the design-thinking process —
built a visual mockup in Lovable to pressure-test the UX with the
client's planner/CFO persona before committing Streamlit sprint time to
it. The two-mode split answers a question the single-view design didn't:
"what do I do right now" (Plan ahead) vs. "what's the usual pattern"
(History) — closer to how a production planner would actually use this
day to day. The colour coding and multi-unit planner came out of the
same exercise: a planner juggles several machines, not one, and a
cheap/normal/expensive/spike read is faster to act on at a glance than
raw öre numbers on a line chart.

### What it replaces
- The single load-shift calculator originally scoped (kWh/hours/start-time
  in, one cost comparison out) is replaced by the production planner
  (multiple named units, same underlying cheapest-window logic, now
  per-unit and totalled).
- The plain (uncoloured) price-over-time chart and heatmap from the
  original Sprint 3 scope gain the colour-coding scheme above; the views
  themselves aren't replaced, just recoloured and — for History on long
  ranges — re-aggregated to daily bars.

### Sprint placement
- Sprint 2: modes (`st.tabs`) + colour coding.
- Sprint 3: production planner (replaces the calculator item in that
  sprint).

See CLAUDE.md's "Dashboard scope" and "Sprints" sections for the
updated, authoritative spec.

## Sprint 1 — Data pipeline (2026-10-03)

### Goal
Add caching and fallback to the price and weather modules so the
pipeline is resilient to API outages and works for any date range in
any area, per CLAUDE.md's Sprint 1 scope. Close out the four open
questions Sprint 0 left for this sprint. No new widgets (Sprint 2).

### Built
- `src/cache.py` (new): shared day-granularity CSV cache —
  `data/cache/prices/{AREA}/{date}.csv`, `data/cache/weather/{station}/{date}.csv`.
  Stored in UTC (sidesteps the DST-transition mixed-offset problem
  `_parse_day` already solves for the live API). Read/write are
  best-effort: a missing or corrupt file degrades to "no fallback", a
  write failure is swallowed rather than breaking a successful fetch.
- `src/prices.py`: `fetch_prices` now returns a `PriceFetchResult(df,
  failed_days, fallback_days)` NamedTuple. The per-day fetch loop runs
  through a small `ThreadPoolExecutor` (network I/O only; bookkeeping
  stays sequential afterwards). A successful day writes through to
  cache; a transient failure (not a confirmed 404) falls back to the
  cached snapshot if one exists.
- `src/weather.py`: `fetch_temperature` now returns a
  `WeatherFetchResult` with the same shape. Replaces Sprint 0's
  always-`"latest-months"` placeholder and uncaught-`raise_for_status()`
  behavior with real period selection (`_pick_periods`, a deliberately
  overlapping two-band heuristic — see Decisions), a JSON-or-CSV fetch
  path per period (see Problems hit), merging across periods with
  archive winning ties on overlapping timestamps, and the same
  cache-fallback treatment as prices.
- `app.py`: unpacks the 3-tuples, shows `st.info` for days served from
  cache and `st.warning` for days with no fallback available, and wraps
  the weather fetch in `try/except` → `st.error` so a weather failure
  degrades gracefully instead of crashing the page.
- `tests/test_cache.py` (new), plus additions to `tests/test_prices.py`
  and `tests/test_weather.py`: cache round trips (including a
  DST-transition day), the 404-vs-failed-vs-fallback three-way split,
  the `_pick_periods` boundary cases, a benign-gap-vs-real-failure
  distinction for weather, and a regression test for the CSV-parsing
  bug below. 29 tests total, all passing.
- Real demo cache data committed: `data/cache/prices/SE3/2026-08-*.csv`
  and `data/cache/weather/71420/2026-08-*.csv` (31 days each) — the
  exact range `app.py` demos, so the fallback path is actually
  exercisable, not just theoretically implemented.

### Decisions (and why)
1. **Cache stores the already-resampled hourly DataFrame, not raw
   records** — resolves Sprint 0's open question. The resampling logic
   is already correct and tested; re-deriving it from raw data on every
   cache load would be redundant work for no benefit, since the cache
   is a fallback, not a source of truth.
2. **`_pick_periods` uses two deliberately overlapping age bands
   (try `corrected-archive` once a date is ≥60 days old, try
   `latest-months` up to ≤150 days old) instead of one exclusive
   threshold.** Verified live against station 71420: `corrected-archive`
   covers ages ≥~94 days, `latest-months` covers ages ≤~130 days —
   confirmed overlap, no gap. A single cutoff risks landing on the
   wrong side of that boundary as it drifts forward over the project's
   timeline; two HTTP calls total (never per-day) makes trying both
   periods in the overlap band cheap insurance rather than waste.
3. **A small thread pool (`max_workers=4`) for the price day-fetch
   loop**, fulfilling CLAUDE.md's "fetch day files politely: small
   thread pool, timeouts, retries" rule, which Sprint 0 only partly
   satisfied. Only the network I/O (`_fetch_day`) runs concurrently;
   cache reads/writes and result bucketing stay sequential in the main
   thread afterward, so there's no shared-mutable-state race to reason
   about. Weather does **not** get a pool — it's at most 1-2 HTTP
   requests total regardless of range length, so there's nothing to
   parallelize.
4. **`PriceFetchResult`/`WeatherFetchResult` as `NamedTuple`s**, not
   plain tuples, now that arity has grown to 3. Still unpacks
   positionally (`df, failed, fallback = fetch_prices(...)` keeps
   working), but call sites and tests can also use `.fallback_days` and
   avoid a silent positional mix-up.
5. **Cache stored in UTC, converted to Europe/Stockholm on read** —
   verified live that `pd.read_csv(..., parse_dates=True)` round-trips a
   single-offset tz-aware index cleanly in this pandas version (3.0.6),
   with no manual `tz_localize` needed. Storing in local time instead
   would put two different UTC offsets in the same file on the two real
   DST-transition dates, the exact ambiguity `_parse_day` already avoids
   for the live API.
6. **CSV over parquet for the cache format** — avoids adding
   `pyarrow`/`fastparquet` as a new dependency (CLAUDE.md requires
   asking first) and stays diffable in git, which matters for a course
   project graded partly on process.

### Alternatives considered and rejected (and why)
- A single age threshold for period selection (e.g. "age > 60 →
  archive") — rejected during implementation review: it silently routes
  dates in the ~60-94-day range to `corrected-archive` alone, which
  doesn't have them yet, producing a successful-but-empty response that
  looks identical to "no data here." The two-band heuristic (Decision 2)
  fixes this by trying both periods whenever a date could plausibly be
  in either.
- A cache-fallback attempt on every absent day, including confirmed
  404s / benign gaps in an otherwise-successful payload — rejected;
  there's nothing to "fall back to" when the API has already answered
  "no data here," so fallback is only attempted for days whose fetch
  genuinely failed.
- Threading the weather fetch loop like prices — rejected; weather
  fetches whole periods, not day-by-day, so there's only ever 1-2
  requests to make regardless of range length.

### Problems hit / how solved
- **Real bug found during manual pipeline verification, not covered by
  the original plan**: `corrected-archive`'s metadata only ever offers a
  `text/plain` (CSV) data link, never `application/json` — unlike
  `latest-months` and the other rolling periods, which offer both. The
  original `_fetch_period` only looked for a JSON link, so every
  `corrected-archive`-only date silently landed in `failed_days` (a
  `StopIteration` on the missing JSON link, caught and reported as a
  generic failure) even though the data was genuinely available. Caught
  by manually exercising a January 2026 date range end-to-end (not by
  the unit tests, which hadn't been written against the real payload
  shape yet) — a good reminder that pure-function tests built from
  assumed fixtures don't substitute for hitting the real API at least
  once per code path. Fixed: `_fetch_period` now tries the JSON link
  first and falls back to a dedicated CSV parser (`_parse_archive_csv`)
  when only `text/plain` is offered, so the fix isn't hardcoded to
  "archive is special" — it degrades the same way for any period that
  turns out to be CSV-only.
- The archive CSV itself has real format quirks once found: a
  variable-length Swedish-language preamble (station info, parameter
  info, a position-history table whose row count depends on how many
  times the station has physically moved) before the actual data table;
  a UTF-8 BOM; times given directly in UTC text rather than epoch-ms;
  and ragged row widths (the first few data rows carry extra trailing
  metadata columns that later rows don't have). Solved by locating the
  real header row (`"Datum;..."`) by content rather than a fixed line
  offset, and reading with `usecols` pinned to the first four columns
  regardless of how many trailing columns a given row has. Added a
  regression test (`test_parse_archive_csv_handles_real_format`) using a
  trimmed real sample, plus a test on `_fetch_period` itself confirming
  the JSON-absent-so-fall-back-to-CSV branch.
- A stale `streamlit run` process from an earlier, unrelated session was
  still bound to port 8501 and serving the old Sprint-0-era cached
  result shape, producing a confusing `ValueError: not enough values to
  unpack` that had nothing to do with the new code. Solved by killing
  it and restarting clean — not a pipeline bug, but worth noting since
  it looked like one at first.

### Open questions for next sprint
- Sprint 0's four open questions are now resolved (raw-vs-resampled
  cache storage, weather error handling, missing/failed-day UI
  treatment, and the archive/latest-months overlap) — see Decisions
  above.
- The corrected-archive CSV is the station's entire history (65 years,
  ~334k rows) downloaded in full on every call that needs it, even for
  a 3-day request — fine for a course project's traffic, but worth
  knowing if performance ever becomes a concern.
- `_pick_periods`' 60/150-day bands are a time-boxed heuristic against
  today's measured boundary (ages ~94/~130); if this project is still
  being actively developed many months from now, worth re-verifying the
  live boundary hasn't drifted outside that margin.
