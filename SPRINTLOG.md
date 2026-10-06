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

## Sprint 2 — Interactions (2026-10-03)

### Goal
Turn the Sprint 1 pipeline into the first real interactive dashboard: the
three required interactions (date range, price area + compare, temperature
overlay), the History/Plan ahead `st.tabs` structure, and colour-coded
prices with a plain-language legend. KPI cards, the heatmap, and the
production planner stay out of scope (Sprint 3).

### Built
- `src/transform.py`: `categorize_by_price(df, price_col)` — adds a
  Cheap/Normal/Expensive/Spike column from the DataFrame's own quantiles
  (relative, not a fixed öre cutoff), and `resample_daily_mean(df,
  columns)` — hourly-to-daily aggregation for the long-range History
  view, DST-safe and gap-aware. 13 new tests.
- `app.py` rebuilt: shared controls (price area, compare toggle,
  temperature toggle) above `st.tabs(["History", "Plan ahead"])`. History
  gets a date-range picker defaulting to the committed Sprint 1 demo
  window; Plan ahead is fixed to today+tomorrow with a "Now" marker.
  Both tabs loop over `[area] + [compare_area]` when comparing, each
  area rendered as its own full chart block. öre/kWh conversion and the
  Elpriset attribution footer (required since Sprint 0, never wired up
  until now) both landed here.
- Chart helper (`_build_price_figure`): price as colour-coded
  `go.Bar` (one trace per category, so each colour becomes its own
  Plotly legend entry for free), temperature as a `go.Scatter` line in a
  **second stacked panel sharing the x-axis** — not a secondary y-axis
  (see Decisions). `add_vline` marks the current hour on Plan ahead.

### Decisions (and why)
1. **Stacked subplots, not dual-axis, for the temperature overlay.** The
   approved plan originally used `make_subplots(secondary_y=True)`. Before
   writing the chart code I loaded this project's `dataviz` skill (as its
   own trigger conditions require before any chart code) and it treats
   dual-axis — two independent y-scales on one plot — as a hard
   non-negotiable ("the #1 chart mistake"), stronger than how the
   approved plan had characterized it. Flagged to Fabian mid-implementation
   and confirmed: price bars on top, temperature line in a second panel
   below sharing one time axis. Keeps temperature visually locked to the
   price chart's timeline (the closest honest match to CLAUDE.md's
   "overlay toggle on the price chart") without implying a false
   correlation between two arbitrarily-aligned scales.
2. **Colour palette reuses the dataviz skill's fixed status palette**
   (good `#0ca30c` → Cheap, serious `#ec835a` → Expensive, critical
   `#d03b3b` → Spike) **plus the skill's own "Muted" grey `#898781` for
   Normal**, per CLAUDE.md's explicit "middle third → neutral grey"
   instruction (not a status colour — there's no neutral status role in
   the skill's four-step good/warning/serious/critical scale). The
   skill's generic categorical-palette validator FAILs this exact
   combination (it assumes every slot is a distinct saturated hue, not
   one deliberate neutral) — ran it directly, understood why it's the
   wrong tool for a status-like severity scale with a neutral injected
   by a hard product requirement, and used the skill's own
   separately-documented, separately-validated status-palette contrast
   numbers instead. Mitigated the one real floor-band CVD pair
   (Expensive↔Normal, ΔE 7.9) with the secondary encoding the skill
   requires for that band: Plotly's always-visible legend, the mandatory
   plain-language caption, and per-bar hover text all state the category
   in words, so colour is never the only signal.
3. **Compare-two-areas renders as two independent, stacked, fully
   colour-coded chart blocks** (one function reused per area) rather
   than one combined chart — keeps each area's colouring meaningful
   against its own distribution, exactly as CLAUDE.md specifies ("where
   its price sits within the period currently shown"), and avoids
   inventing a shared/blended colour scale CLAUDE.md never asked for.
   Applies identically in both tabs (see Problems hit).
4. **Plan ahead's "not published yet" message reuses Sprint 1's existing
   404-vs-failed distinction with zero changes to `src/prices.py`**:
   tomorrow absent from the result + not in `failed_days` → confirmed-404,
   the expected pre-~13:00 case, friendly `st.info`; tomorrow absent +
   in `failed_days` → a real fetch problem, `st.warning`.
5. **Shorter cache TTL for Plan ahead (600s) than History (3600s)** so
   the "tomorrow just got published" transition around 13:00 shows up
   within a session instead of needing a hard refresh.
6. **öre/kWh conversion happens once, immediately after each fetch, in
   `app.py`** — one derived column feeds categorization, the chart axis,
   and the hover tooltip, so there's exactly one place a unit bug could
   hide. `src/prices.py` stays an unchanged plain SEK/kWh pass-through.

### Alternatives considered and rejected (and why)
- Keeping the originally-planned dual-axis chart with mitigations
  (distinct labelled axes, a caption noting independence) — rejected
  once the `dataviz` skill's actual non-negotiable language was read in
  full; the plan's own framing ("a known anti-pattern, worth keeping
  anyway") undersold how hard a line the skill draws. Two stacked panels
  achieve the same product requirement without the anti-pattern.
- A single combined comparison chart (e.g. two line traces, one per
  area, dropping the colour scheme for that view) — rejected in favour
  of decision 3; CLAUDE.md's colour-coding requirement doesn't carve out
  an exception for comparison, and two colour-coded charts are simpler
  to reason about than inventing a cross-area shared palette.
- A single Expensive/Spike/Cheap-only palette with no neutral — rejected;
  CLAUDE.md explicitly names "neutral grey" for the middle third, not a
  fourth hue.

### Problems hit / how solved
- Mid-implementation design change: see Decision 1 — the dual-axis
  design in the approved plan turned out to directly contradict the
  `dataviz` skill's own non-negotiable rules once actually loaded before
  writing chart code (the plan was written before that skill load).
  Flagged and resolved with Fabian before writing the chart function,
  rather than silently shipping either the anti-pattern or an unreviewed
  design change.
- Caught during manual QA, not the automated tests: the "Compare with
  another area" control sits above `st.tabs` as a shared control, but
  the first implementation only wired it into the History tab — Plan
  ahead silently ignored it despite the control visibly showing "Compare
  against: SE1" with the checkbox ticked. Confusing, inconsistent UX for
  a control presented as shared. Fixed by looping Plan ahead over the
  same `[area] + [compare_area]` list History already used (Decision 3's
  helper function made this a small change, not a rewrite).
- A test-fixture bug, not a production bug: the new `resample_daily_mean`
  tests initially used literal UTC midnight as a "day start," which is
  actually 01:00 Stockholm local in winter (CET, +01:00) — the exact
  offset pitfall `test_prices.py`'s fixtures already account for, that I
  didn't carry over when writing the new fixture. Two tests failed with
  3-4 rows instead of 2 until the fixture was corrected to start at
  Stockholm local midnight; `resample_daily_mean` itself was correct the
  whole time.

### Open questions for next sprint
- Sprint 3's heatmap should reuse `categorize_by_price` for its own
  colour scheme per CLAUDE.md ("recoloured to the Sprint 2 scheme") —
  confirm the same relative-quantile logic reads sensibly at hour×weekday
  granularity, where each cell represents a mean over many underlying
  hours rather than a single observation.
- The production planner's "typical" History-mode pricing (average price
  per hour-of-day across the selected period) is a different aggregation
  from anything built this sprint (`resample_daily_mean` collapses to one
  row per day, not one row per hour-of-day across many days) — will need
  its own small transform function in Sprint 3.
- Compare mode currently stacks full chart blocks vertically for each
  area; worth a quick gut-check once KPI cards land in Sprint 3 whether
  that remains the clearest layout or whether side-by-side columns read
  better once there's more content per area.

## Sprint 3 — Insight layer (2026-10-03)

### Goal
KPI cards, the hour × weekday heatmap (recoloured to Sprint 2's scheme),
and the production planner — the last feature sprint before Sprint 4
(test and ship). Done when a non-expert can answer the five problem-
statement questions from the app and get a start-time recommendation +
savings estimate for at least two production units.

### Built
- `src/transform.py`: `price_kpis` (average, cheapest/priciest hour,
  daily spread — always computed from the true hourly frame, never the
  >31-day display aggregation), `hourly_weekday_means` (long-form mean
  price per weekday×hour, feeds `categorize_by_price` unmodified),
  `typical_hour_of_day` (24-value hour-of-day profile, the planner's
  History-mode price source). 7 new tests.
- `src/calc.py` (was an empty stub): the whole production planner —
  `cheapest_window`/`window_cost` (prefix-sum contiguous-window search,
  optional wraparound for History's cyclical typical-day profile),
  `energy_kwh`, `combined_peak_power` (fixed-length accumulator array),
  `plan_unit` (bundles one unit's recommendation + usual-start
  comparison), `planner_totals`, `yearly_saving_estimate`. All pure,
  positions are plain integers — `app.py` owns converting real
  timestamps/HH:MM to and from them. 31 new tests, covering every edge
  case CLAUDE.md names explicitly (no active units, 0 kW/0 hours, run
  length longer than available priced hours).
- `app.py`: a shared `st.data_editor` production-units table above
  `st.tabs` (seeded with two example units), KPI cards + the heatmap in
  History only (per area, reusing the existing per-area loop), and the
  production planner rendered in both tabs via one shared
  `_render_planner` helper with a mode-appropriate price source.

### Decisions (and why)
1. **Three real gaps found between CLAUDE.md's Production planner
   subsection and the rest of the spec, each resolved and documented
   rather than silently picked one way:**
   - *"Per year" savings*: the problem statement's Q3 ("per run and per
     year") is still covered by this sprint's done-when bar, but the
     Production planner subsection's totals list never mentions a yearly
     figure. Added `yearly_saving_estimate` from an explicit, stated
     assumption (1 run/day × 365 days/year) shown with a caveat — no new
     column on the units table, so it doesn't silently exceed the schema
     CLAUDE.md enumerates.
   - *Compare mode and the planner*: the planner uses `area` only, never
     `compare_area`. The client's machines don't run twice against two
     price areas — comparison is a price-pattern exploration feature
     (required interaction #2), not a parallel production schedule.
     Verified live: compare mode shows two independent KPI-card/heatmap
     blocks (one per area) but exactly one planner section.
   - *Plan ahead's "usual start" has no date*: a unit's `HH:MM` is mapped
     to the next upcoming occurrence at or after "now" (today if not yet
     passed, else tomorrow); if neither exists in the actual remaining
     series, that one unit's usual-cost comparison reports as
     unavailable rather than being guessed or crashing.
2. **`cheapest_window`/`window_cost` take no `power_kw` argument.**
   Cost = `power_kw * sum(window prices)` and `power_kw` is a constant
   multiplier over the whole window, so it can never change *which*
   window is cheapest — the search operates purely on the price shape,
   and the caller multiplies afterward. Keeps the search function
   reusable regardless of a unit's power draw.
3. **`combined_peak_power` is a plain fixed-length accumulator array,
   not a sweep-line.** Unit counts and timeline lengths here are tiny (a
   handful of units, at most ~48 hourly positions), so O(units × hours)
   accumulation is simple, obviously correct, and fast enough — a
   sweep-line would buy nothing at this scale.
4. **Heatmap discrete colour bands via a stepped `go.Heatmap` colorscale**
   (each category's colour placed at both ends of its `[i/4,(i+1)/4]`
   band — two same-position anchor points at each boundary read as a
   hard step, not a gradient), `zmin=-0.5/zmax=3.5` centering integer
   category codes within their band, and a 4-tick `colorbar` reusing
   `CATEGORY_ORDER`/`CATEGORY_COLORS` so the heatmap and the price chart
   are visibly the same colour language, per CLAUDE.md's "recoloured to
   the Sprint 2 scheme."
5. **Yearly saving shown in SEK with thousands separators, not raw
   öre.** Caught in manual QA: a real scenario (today's SE3 prices
   happened to swing from near-zero overnight to a moderate morning
   ramp) produced a legitimately large per-run saving that, multiplied
   by 365 and left in öre, rendered as an unreadable "7429769 öre."
   Converting just this one aggregate figure to SEK (divide by 100,
   `:,.0f` formatting) keeps it readable without touching the öre/kWh
   unit used everywhere else in the app.

### Alternatives considered and rejected (and why)
- A `runs_per_week`/`runs_per_year` column on the units table instead of
  a single stated global assumption — rejected; CLAUDE.md enumerates the
  table's exact columns (name, power, hours, usual start, on/off) and
  adding one exceeds that without being asked.
- Duplicating the planner per compared area — rejected (Decision 1); the
  client only buys electricity in one area, so a second parallel
  schedule against a hypothetical SE1 contract would answer a question
  nobody asked.
- A sweep-line for `combined_peak_power` — rejected (Decision 3); more
  code for no real benefit at this problem size.

### Problems hit / how solved
- Caught in manual QA, not the unit tests: the Plan ahead tab's first
  draft of `usual_pos` combined a unit's `usual_start` **including
  minutes** with today's/tomorrow's date and looked for an exact match
  in the hourly-indexed remaining-price series, which only has on-the-
  hour timestamps — any usual_start with non-zero minutes would silently
  read as "unavailable" even though History's equivalent closure already
  correctly used `t.hour` only. Fixed to floor to the hour the same way,
  plus configured the `TimeColumn` widget with `step=3600` so the picker
  itself only offers whole hours.
- A draft from planning sketched `st.data_editor(st.session_state.get(
  "units_df", DEFAULT_UNITS), key="units_editor", ...)` — redundant
  double state management, since a `key`'d widget already persists its
  own edited value in `st.session_state[key]` across reruns. Simplified
  to `st.data_editor(DEFAULT_UNITS, key="units_editor", ...)` before it
  was ever built.
- A surprisingly large "saved X öre vs usual" figure during live
  verification (see Decision 5) looked like a possible bug at first
  glance — reproduced the exact computation directly against live SE3
  prices before accepting it: the "usual" 06:00 start genuinely lands in
  a ~70 öre/kWh morning ramp while the recommended window captures a
  2-6 öre/kWh overnight trough, so a ~20x per-kWh difference on a 480 kWh
  load is mathematically correct, not a bug — just a dramatic real price
  swing on the day this was tested.

### Open questions for next sprint
- Sprint 4 is test-and-ship only (pytest hardening, edge cases from user
  testing, README, Streamlit Community Cloud deploy) — no new features.
  Worth a deliberate pass over `app.py` itself, which has no automated
  tests (by design — it's wiring, not logic) but has grown substantially
  across three sprints; a manual click-through checklist before deploy
  is probably warranted since Sprint 4's "fixes from user tests" implies
  someone other than the builder should try to break it.
- The heatmap's relative colour scale is computed per area per date
  range (up to 168 weekday×hour cells as the population) — worth
  confirming this still reads sensibly for a very short History range
  (e.g. 2-3 days), where the heatmap would have mostly-empty cells and a
  very small population for the quantile thresholds.
- `DEFAULT_UNITS`' two example rows (Induction furnace, Compressor line)
  are permanent seed data shown to every first-time user — confirm this
  is still the desired behaviour once the app is actually deployed and
  used by someone other than the builder, versus starting from an empty
  table.

## Sprint 4 — Test and ship (2026-10-03)

### Goal
pytest suite, edge cases, fixes from user tests, README, deploy to
Streamlit Community Cloud. Done when: the public link works in a clean
browser. No specific bugs were reported from Fabian's own testing at the
start of this sprint, so "fixes from user tests" became a general
hardening/edge-case review pass rather than a list of reported issues.

### Built
- `requirements.txt`: pinned to the exact versions tested against all
  five sprints (`streamlit==1.64.0`, `pandas==3.0.6`, `plotly==7.1.0`,
  `requests==2.34.2`, `pytest==9.1.1`), replacing the loose `>=` pins
  Sprint 0 deliberately deferred — its own committed plan doc said this
  explicitly: "tighten to exact versions at Sprint 4." Verified by
  installing into a completely fresh venv and re-running the full test
  suite there (80 passed), not just trusting `pip freeze` on the
  already-working dev environment.
- `README.md`: full rewrite — project overview, a usage guide per view
  mapped to the five problem-statement questions, run-locally and
  `pytest` instructions (kept, already correct), data sources and the
  required Elpriset attribution, a step-by-step Streamlit Community
  Cloud deploy section, and a "known limitations" section pointing at
  things already documented as deliberate scope boundaries elsewhere
  (SPRINTLOG, the Production planner's own caveats).
- A live, Playwright-driven edge-case walkthrough of the actual running
  app (not just `src/`'s unit tests, which can't prove the UI wires
  things correctly): single-day History range, a 63-day range crossing
  the SMHI `corrected-archive`/`latest-months` boundary with the
  temperature overlay on, compare mode + temperature + the long range
  together, switching all production units inactive, and adding a blank
  (unnamed) unit row. All six rendered correctly with zero console
  errors and no code changes were needed — the incremental per-sprint
  hardening already covered this ground.

### Decisions (and why)
1. **No new `app.py` changes or regression tests this sprint.** The
   edge-case walkthrough was designed to find problems, not to justify
   busywork — every scenario tested held up, so nothing was changed.
   Sprint 4's own plan said explicitly: add a regression test only for a
   *real* bug found, don't pre-add speculative coverage for inputs the
   UI already structurally prevents (e.g. negative hours, blocked by
   `NumberColumn(min_value=1)`).
2. **GitHub push and the Streamlit Community Cloud connection are
   handed off, not scripted.** No git remote existed and the `gh` CLI
   isn't installed on this machine; Fabian will create the GitHub repo
   himself and share the URL for the push, and the actual Cloud deploy
   step needs his own account login, which isn't something this session
   can do. The README's Deploy section documents the exact steps either
   way.
3. **`-0.0 öre/kWh`** showed up as a KPI value during the edge-case
   walkthrough (cheapest hour on a 63-day SE3 range) and, separately,
   **`-5.7 öre/kWh`** for SE1 on the same range — both are genuine,
   correctly-computed small negative spot prices (a real phenomenon in
   Nordic markets during oversupply), not a formatting bug or a sign
   error; `-0.0` is just `:.1f` rounding a tiny negative number. Left
   as-is rather than "fixed," since hiding the sign would misrepresent
   a real (if small) negative price as exactly zero.

### Alternatives considered and rejected (and why)
- Writing new speculative unit tests for every theoretical edge case
  (negative inputs, duplicate unit names, etc.) regardless of whether
  the UI can actually produce them — rejected; CLAUDE.md's own edge-case
  list is specific (empty selection, missing days, single-day range,
  API timeout), and every one of those is already covered either by
  existing `src/` tests or this sprint's live walkthrough.
- Attempting to force the "only a start date picked, end date still
  empty" state through Playwright by clearing the native
  `<input type="date">` element directly — abandoned after it fought
  browser-level native-input semantics (the browser reverts an emptied
  date input to its last committed value rather than firing the change
  Streamlit listens for) without revealing anything about app
  correctness; the guard (`len(date_range) != 2`) is simple, matches
  Streamlit's documented `date_input` contract, and has held up through
  three prior sprints of manual and live-browser testing.

### Problems hit / how solved
- The live-verification Playwright session accumulated real "Running..."
  spinner timing issues (a screenshot taken mid-rerun showed only one of
  two compared areas) — not a bug, just an under-length wait in the test
  script. Solved by polling for the "Running" indicator to disappear
  instead of a fixed timeout, then re-verifying cleanly.
- Streamlit's data-editor grid renders via canvas (Glide Data Grid), so
  individual cells have no DOM elements to target directly — worked out
  pixel-coordinate clicking against the grid's bounding box (toggling
  checkboxes, adding a blank row) instead, which is more brittle than
  normal DOM automation but was enough to verify both scenarios live.

### Open questions for next sprint
None — this was the last sprint in CLAUDE.md's plan. Remaining steps are
operational, not engineering: Fabian creates the GitHub repo and shares
the URL for the push; he then connects Streamlit Community Cloud himself
per the README's Deploy section and shares the resulting public URL for
a final clean-browser check.

---

# v2 — Solar Advisor (pivot)

A business-case review found v1 had no clear user and a weak savings
case. The product pivots to a sales tool for Kustsol AB's energy
advisors: showing a homeowner, with real data, whether solar — and a
battery — pays off now that the 60 öre/kWh tax reduction for sold
micro-production is gone (abolished 2026-01-01). Same core data (hourly
SE3 spot prices), same building blocks, new use case. **v1 is preserved
at the `v1-industrial` tag and all v1 entries above are kept — the pivot
is part of the story.**

## Sprint 5 — Pivot setup and spike (2026-10-05)

### Goal
Tag v1, inventory the real code against CLAUDE.md's keep/adapt/replace/
remove table and correct it, remove everything marked Remove, and spike
Open-Meteo. Done when the existing overlay shows a summer week of SE3
prices with real solar production instead of temperature.

### Built
- `src/solar.py` — Open-Meteo tilted-irradiance fetch (archive + forecast)
  and the production estimate, replacing `src/weather.py`.
- `src/config.py` — the constants Sprint 5 actually uses (location, tilt,
  azimuths, loss factor), each marked for Fabian to verify.
- `tests/test_solar.py` — 16 tests.
- `app.py` rewired: SE3 fixed, area dropdown and comparison gone, peak
  power metric gone, temperature panel replaced by a solar production
  panel, default range now a summer week (2026-06-15..21).

### Reused from v1 / adapted / new
- **Reused unchanged:** `src/prices.py`, `src/cache.py` (day-granularity
  CSV cache + fallback), `src/transform.py` (colour categorisation, KPI
  stats, heatmap aggregation), the stacked-panel chart builder, the
  `(df, failed_days, fallback_days)` result shape and its `st.info`/
  `st.warning` notices, the `cheapest_window`/`window_cost` search, the
  tab structure, the date-range picker, the test fixtures and conftest.
- **Adapted:** the overlay's second panel (temperature line → production
  area); the chart caption; the page title; the default date range.
- **New:** `solar.py`, `config.py`, `test_solar.py`.
- **Removed:** `weather.py`, `test_weather.py`, SMHI cache snapshots,
  `combined_peak_power` + its tests, the SE1 cache (only existed to demo
  area comparison), the area dropdown and comparison UI.

### Decisions (and why)
1. **Four corrections to CLAUDE.md's inventory table**, found by reading
   the actual code rather than trusting the table:
   - *"Earliest start / finish-by constraints"* — **never existed in v1**;
     nothing to remove. The only "earliest" in the codebase is a
     tie-breaking docstring. The peak power metric in the same row did
     exist and was removed.
   - *`src/cache.py` and `src/transform.py` are missing from the new
     project structure*, yet the rows that depend on them (caching,
     colour coding, KPI cards, heatmap) are all marked Keep/Adapt. Both
     must stay; the structure list is incomplete, not the rows.
   - *`src/calc.py` marked "Keep" wholesale* — it actually holds three
     different things (the keep-worthy window search, v1's load-shift
     planner which is Replace, and peak power which is Remove), so it
     needs selective treatment across sprints, not one verdict.
   - *"Deployment setup — Keep"* — deployment never actually happened.
     Sprint 4 ended waiting for a GitHub repo URL and there is still no
     git remote. Sprint 8 still owns the real deploy.
2. **Request Open-Meteo in UTC and convert to Europe/Stockholm here**,
   rather than asking the API for local time. Verified live: asking for
   `timezone=Europe/Stockholm` returns 24 hours for 2026-03-29 including
   a literal `02:00` — an hour Stockholm skips entirely at the
   spring-forward transition. Localising that raises
   `NonExistentTimeError`. Parsing UTC and converting afterwards is the
   same rule `prices.py` has followed since Sprint 0 and makes the 23-
   and 25-hour days come out right for free. Because a UTC day is not a
   Stockholm day, requests are padded a day either side and sliced back.
3. **The cache stores irradiance, not production**, keyed by orientation
   *and* tilt. Irradiance is independent of system size, so Sprint 7's
   kWp slider can move without refetching anything; and a south-facing
   snapshot can never be served for an east–west roof.
4. **Keep the stacked-panel overlay, not the second y-axis** the new
   CLAUDE.md wording implies (your call when I flagged it). It preserves
   the Sprint 2 decision and the dataviz rule, and it is genuinely the
   better chart here: the pitch is *when* production happens versus
   *when* power is expensive, which is read off the shared time axis.
5. **Panel tilt is a fixed documented constant (40°), not a sixth input**
   (your call) — keeps the advisor's input set exactly as specified.
6. **East–west is modelled as the mean of the −90° and +90° irradiance
   series** against the full kWp, i.e. half the array facing each way.

### Alternatives considered and rejected (and why)
- *Deleting `src/transform.py` to match the new project structure* —
  rejected; it would delete the colour coding and KPI stats that the
  table explicitly keeps. The structure list was simply incomplete.
- *Leaving `weather.py` dormant instead of deleting it* — rejected;
  "Replace" is unambiguous and `v1-industrial` makes it recoverable.
  Keeping a dead 266-line module around to feel safe is what tags are for.
- *Adding the orientation dropdown and kWp slider now* so the spike could
  demo east–west in the UI — rejected as building ahead into Sprint 7.
  East–west is proven instead by unit tests plus a live side-by-side
  check (below), which satisfies the spike without pre-empting Sprint 7.

### Problems hit / how solved
- The DST trap in decision 2 would have been a live crash on two days a
  year. Found by probing the API with a known spring-forward date
  *before* writing the parser, rather than discovering it in March.
  Locked in with a regression test.
- **Verifying east–west by physics, not by HTTP status.** A 200 response
  proves nothing about whether the azimuths are handled correctly, so I
  compared both orientations over the same live summer week: south peaks
  at 7.26 kWh with 0.28 kWh at 06:00; east–west peaks 29% lower at 5.14
  kWh but produces 3× as much at 06:00 (0.84 kWh), with ~8% less for the
  week. That flatter, broader, slightly-smaller curve is exactly the
  east–west signature, so the convention and the averaging are right.
- The committed demo cache had drifted: 68 untracked price files had
  accumulated from clicking around the running app (including SE2/SE4
  areas that no longer exist in v2). Cleaned, and the committed set is
  now exactly what the default view needs — the June week's prices plus
  that week's irradiance for both orientations.

### Open questions for next sprint
- **"Last 12 months" is ~365 HTTP calls to the price API** (one file per
  day; the irradiance side is one call for the whole range). With the
  disk cache and `st.cache_data` it is a one-time cost, but Sprint 6/7
  should decide deliberately whether to pre-warm and commit a full year
  of price snapshots or fetch on first use and accept a slow cold start.
- The v1 planner is still on the page and, with genuinely negative
  midday prices in the June week, now recommends windows at *negative*
  cost. Not wrong (it is the cheapest window) but it is v1 logic in a v2
  world — Sprint 7 replaces it with the customer-input panel anyway.
- `config.py`'s values are placeholders pending Fabian's verification;
  Sprint 6 adds the tax/grid/battery constants, which are the ones that
  actually drive the SEK figures an advisor will quote.

## Sprint 6 — Model (2026-10-05)

### Goal
`solar.py`, `consumption.py`, `battery.py`, `config.py` with tests
including the mandatory energy balance test. Done when all three
scenarios return yearly SEK values and all tests pass.

### Built
- `src/config.py`: buy/sell price components (energy tax 36 öre excl VAT,
  grid fee 27 öre, VAT 25%, nätnytta placeholder), battery parameters,
  advisor-input defaults. All marked for verification.
- `src/consumption.py`: the villa load assumption — a 24-hour shape with
  morning and evening peaks × 12 monthly factors, anchored to a reference
  year.
- `src/battery.py`: buy/sell pricing, the four hourly rules, the grid-charge
  allowance, the hourly simulation, the three scenarios and payback.
- `tests/test_consumption.py` (13) and `tests/test_battery.py` (75),
  including the balance test parametrized over 12 fixtures × 4 scenarios.
- A full year of real cached data (SE3 prices + irradiance for both
  orientations, 8760 hours each, zero failures) committed as offline
  fallback.

### Reused from v1 / adapted / new
- **Reused:** `calc.cheapest_window` for the grid-charge window (exactly the
  reuse the pivot table anticipated); `prices.py`'s column name and
  `(df, failed, fallback)` result shape; `cache.py` unchanged; the test
  style and `conftest.py` fixtures.
- **Adapted:** `solar.py`'s `production_kwh` feeds the model directly.
- **New:** `consumption.py`, `battery.py`, the price model, the scenarios.

### Decisions (and why)
1. **The energy balance needed a fourth production term.** `production =
   own use + to battery + sold` cannot hold alongside "never sell at a
   negative price", because that surplus is neither used, stored nor sold.
   Added `curtailed`. On the real year it is only 35 kWh (0.3%), all in
   May, but it is the honest term and it becomes a donut slice in Sprint 7
   — power thrown away is itself an argument for a battery.
2. **`bought_for_house_kwh` is tracked separately from `grid_charge_kwh`.**
   Folding them into one "bought" column silently breaks the consumption
   invariant, because grid-charge energy goes into the battery, not the
   house.
3. **Round-trip loss is booked entirely on discharge** — "10 kWh in, 9 kWh
   out" is one sentence for a customer. Both invariants still hold exactly
   because each closes with a residual: `to_battery` is metered at the
   input, `from_battery` at the output, so the loss lives inside the
   battery and appears in neither identity.
4. **Rule 4 compares buy prices, not spot, and its margin is additive.**
   You pay tax, grid fee and VAT on the ~10% the round trip throws away,
   so a spot-based test recommends grid charging on days that lose money.
   And at a negative price a percentage margin *lowers* the bar instead of
   raising it.
5. **"Never sell at a negative price" means the sell price, not spot.** The
   price received is spot + nätnytta, so the two readings differ exactly in
   the −5..0 öre band where most SE3 negative hours sit.
6. **Consumption is anchored to a reference year, not to the simulated
   period.** Scaling weights to sum to the annual figure over whatever
   index is passed would bill a full year's electricity across a one-week
   simulation — and Sprint 7's Tomorrow view is a single day.
7. **Payback stays exactly as CLAUDE.md specifies** (Fabian's call), with
   the three exclusions — green-technology deduction, capacity/effekt
   tariffs, frequency regulation — stated in config and required in the UI.
   On real data it lands at 23.8 years, which is honest rather than
   flattering, and the advisor can explain what is missing.

### Alternatives considered and rejected (and why)
- *Counting curtailed energy as "sold at 0 SEK"* to preserve the
  three-term identity — rejected; it would mix kWh that earned money with
  kWh that earned nothing and quietly distort Sprint 7's donut.
- *sqrt(0.9) on each side of the round trip* — more conventional, but
  "94.87% each way" is not explainable at a kitchen table.
- *Fetching the year on demand* — rejected (Fabian's call): ~1 MB committed
  buys an instant, API-outage-proof demo in front of a customer.

### Problems hit / how solved
- **Rule 4 as literally specified made the battery actively harmful.**
  Caught by the self-consumption test, not by inspection: on a sunny June
  day the battery grid-charged to 100% at 03:00 and sat full, so the whole
  day's solar surplus had nowhere to go and `to_battery` was exactly zero.
  The battery was *reducing* self-consumption — the opposite of the
  product's thesis. Rule 4 only looks at prices and cannot see that a
  surplus is coming. Fixed (with Fabian's go-ahead) by reserving room for
  the sun: the day's grid-charge budget is `capacity − expected surplus`,
  floored at zero. Verified on the real year — summer now charges from
  solar (1105 kWh vs 37 from the grid) and winter from the grid (791 vs
  129), which is exactly what the rule was written for.
- **A real DST bug in Sprint 5's `solar.py`.** `_slice_to_range` used
  `Timedelta(days=1)` (24 absolute hours) instead of `DateOffset(days=1)`.
  Verified: the 23-hour spring-forward day returned 24 rows spilling into
  the next date, and concatenating days duplicated `2026-03-30 00:00`. It
  would have corrupted exactly the year-long frame this sprint builds.
  Fixed and pinned with two regression tests.
- **The repo's CLAUDE.md was still the v1 industrial brief** — zero
  mentions of solar, battery or Kustsol. The v2 brief existed only in the
  working session, so the repo had no record of what drove Sprints 5–8 and
  a future session could have followed v1 and undone the pivot. Written in
  as a separate commit, with Sprint 5's inventory corrections folded in
  rather than re-introducing the rows already known to be wrong.
- An invariant test passes trivially on all-zero data, so the balance test
  has a companion that asserts each fixture still drives the branch it
  exists for. Without it, an edit that quietly zeroed a branch would leave
  the suite green.

### Open questions for next sprint
- **Payback is 23.8 years on real data.** Honest, but it is the number a
  customer will fixate on. Sprint 7 must present it alongside the three
  stated exclusions, and it is worth deciding whether the green-technology
  deduction belongs in the quoted figure.
- `nätnytta` is still a 5 öre placeholder — the only config constant with
  no source behind it, and it moves every export figure.
- The consumption profile is a plausible shape, not a measured one. If a
  real villa load profile is available it would materially raise the
  credibility of the self-consumption share, which is the single number
  the whole battery case rests on.

## Sprint 7 — Adapt "Customer calculation" (2026-10-05)

### Goal
Inputs, KPI cards, overlay, donut, scenario comparison, heatmap,
assumptions expander. Done when an advisor can answer questions 1–5 for a
made-up customer.

### Built
- `app.py` rewritten around the advisor's five inputs: a bordered input
  panel above two tabs, now "Customer calculation" and "Tomorrow".
- Four KPI cards (`st.metric(border=True)`): value of solar, value of the
  battery, self-consumption share, payback — with two distinct empty
  states for payback ("enter a price" vs "this size saves nothing").
- Overlay chart (price bars + production in a second panel on the same
  time axis), donut, three-scenario horizontal bars, hour × month heatmap,
  assumptions expander reading every number from `config`.
- A cached computation layer: four `st.cache_data` functions keyed on
  scalars only.
- `transform.hourly_month_means` and `transform.production_split` with 10
  new tests; the v1 planner and its 13 tests removed. 164 passing.

### Reused from v1 / adapted / new
- **Reused unchanged:** `_build_price_figure` (stacked panels),
  `_render_fallback_notices`, `CATEGORY_COLORS` and the categorisation,
  `prices.py`, `cache.py`, `solar.py`, the footer attributions.
- **Adapted:** the heatmap's discrete-colour-band technique, now hour ×
  month instead of hour × weekday; the date range selector, now scoping
  the chart rather than the whole page.
- **New:** the input panel, the SEK KPI cards, the donut, the scenario
  bars, the assumptions expander, `hourly_month_means`,
  `production_split`.
- **Removed:** `_render_planner`, `DEFAULT_UNITS`, the production-units
  `st.data_editor`, `calc`'s planner functions,
  `transform.typical_hour_of_day` and `transform.hourly_weekday_means`.

### Decisions (and why)
1. **The date picker scopes the chart only** (Fabian's call). Every yearly
   SEK figure, the donut, the bars and the heatmap always cover the full
   12 months; the picker zooms the overlay. Extrapolating a hand-picked
   sunny week into a "yearly" figure would be indefensible in front of a
   customer. The UI says so in a caption under the KPI row, because the
   two controls sitting on one page otherwise imply they interact.
2. **The 12-month window and the default chart week are both derived, not
   hardcoded.** `end = today − 2 days` (Open-Meteo's archive lag),
   `start = end − 364`; the chart defaults to mid-June inside that window.
   A hardcoded range silently falls outside the window as it rolls
   forward, and the derived one lands exactly on the committed year —
   8760 rows, zero missing hours.
3. **Prices are cached keyed on the window only, never on orientation.**
   Both orientations are computed for question 5; keying them together
   would fetch a year of prices twice on first load.
4. **No `ttl` on the two year-long fetchers.** The cache key *is* the
   window, so it self-invalidates when the window rolls over at midnight,
   and a settled past spot price never changes. The `ttl=3600` carried
   over from v1 would have re-issued 365 requests every hour of a working
   session — a stall mid-meeting and poor citizenship toward a free API.
   `max_entries` is set everywhere instead, because `cache_data` pickles
   and a `ScenarioComparison` carries three 8760-row detail frames.
5. **Question 5 is one caption line, not a fifth KPI card.** Orientation
   moves the battery's value by 24% but the panels' by only 9% (south
   12 204 / 3 153 SEK/yr, east–west 11 060 / 2 403, payback 24 vs 31
   years). That asymmetry is a genuinely useful sales fact — a flatter
   east–west curve already matches the household's morning and evening
   peaks, so less has to go through the battery — and it is invisible if
   the advisor must flip the dropdown and hold a number in their head. A
   fifth card would imply a peer metric; a second chart would double the
   page for one comparison.
6. **The donut's colours were computed, not chosen.** Its four
   destinations are *ordinal* — own use → battery → sold → curtailed is a
   strict value ranking — so the dataviz skill prescribes a one-hue ramp,
   darkest = most valuable. Running its validator settled it: the blue
   ramp passes all four checks, while the obvious four-hue categorical
   alternative **hard-fails** the normal-vision separation floor
   (#eda100 ↔ #eb6834 at ΔE 13.7 against a floor of 15) — and a donut
   compares every slice with every other through its legend. Reusing
   `CATEGORY_COLORS` was out regardless: that is the reserved status
   palette.
7. **The scenario comparison is a bar chart, not a table.** It makes
   "20 201 vs 35 610 SEK" a visible length difference, which three numbers
   in a table do not; with direct SEK labels it is a table as well. One
   hue for all three bars and no legend, since bar length already encodes
   the progression.
8. **Per-kWh rates stay in öre/kWh; every total is SEK.** CLAUDE.md says
   "never öre for totals", and öre/kWh is the conventional Swedish unit
   for a *rate*. Totals use a thin space as the thousands separator.
9. **`window_cost` kept although it is now test-only.** Sprint 8's
   plain-language battery plan ("charge from the grid 02–05") needs to
   price exactly that window shape. Documented in the function itself:
   Sprint 8 either uses it or deletes it, it must not sit dead a third
   sprint.

### Alternatives considered and rejected (and why)
- *Letting the date picker drive everything*, so the KPI cards reflect the
  picked range — rejected per decision 1; it invites quoting a sunny
  week's economics as a yearly figure.
- *A fifth KPI card, or a second chart, for the orientation comparison* —
  rejected per decision 5.
- *Four distinct hues for the donut* — rejected because the validator
  hard-fails it, not on taste.
- *A table for the three scenarios* — rejected per decision 7.
- *Hardcoding the payback figure's exclusions into prose in `app.py`* —
  rejected; the expander reads every number from `config`, so the UI
  cannot drift from the calculation.

### Problems hit / how solved
- **A three-scenario comparison took 1.1–1.3 s, and 94% of it was one
  line.** `grid_charge_allowance` rebuilt `expected_surplus.index.date` —
  an array as long as the whole series — once per calendar day, i.e. 365
  passes over 8760 rows. Replaced with a single `groupby` before the loop:
  1.102 s → 0.301 s (3.7×) south, 1.263 s → 0.335 s (3.8×) east–west,
  output identical to 4.4e-15 across every column of all three detail
  frames. This was outside the sprint's literal scope but it gates
  CLAUDE.md's "adjusts the battery size live with the customer", and it is
  what makes computing both orientations affordable. The old scan is kept
  in the tests as an oracle the optimised version must match elementwise,
  over a span containing both DST transitions; pinned to behaviour rather
  than to SEK figures, which shift whenever the cache gains a day. The
  guard was itself verified by mutating the lookup — it fails.
- **The committed cache is a *fallback*, not a fast path.**
  `fetch_prices` only reads `data/cache/` when a day fails, so a 12-month
  view is 365 live HTTP requests and a cold load is ~13 s. Mitigated with
  spinner messages on the cached fetchers; the real fix is logged below.
- **A test failure that was the fixture, not the function.** A new
  `hourly_month_means` test started at 31 Jan 23:00 UTC expecting to span
  two months — but Stockholm winter midnight is UTC 23:00 the *previous*
  day, so all 48 hours landed in February. The same trap as Sprint 2; the
  fixture now explains it.
- **A date label that hid a year boundary.** Zooming the chart to the full
  window rendered "04 Oct – 03 Oct 2026", which reads as one year. Found
  by driving the app, not by a unit test — `app.py` has no unit tests by
  design. The start now carries its year whenever the two differ.
- **Verifying a Streamlit page without a browser.** Playwright is not in
  the venv. Streamlit's own `AppTest` runs the real script with real
  widget values and surfaces uncaught exceptions, which turned out better
  than a browser for this: it let the scoping claim in decision 1 be
  checked mechanically — change the picker, assert all four KPI cards are
  byte-identical — rather than by eye.

### Open questions for next sprint
- **Make the committed cache a fast path for settled days.** A past day's
  spot price is immutable, so reading cache-first for any day before today
  would be correct and would cut the ~13 s cold load to near nothing. It
  changes `prices.py`'s semantics, so it belongs in Sprint 8, which owns
  deployment — and on Community Cloud, where the app sleeps and cold-starts
  for real visitors, this matters far more than it does locally.
- **The one unverified item is visual.** `kaleido` is not installed, so the
  donut's outside labels at the 0.3% curtailed sliver and the heatmap's
  month order were verified structurally but never rendered to an image.
  Worth an eyeball during the Sprint 8 user test (or installing kaleido as
  a dev dependency, which needs Fabian's go-ahead).
- Payback is 24 years for the default customer and 330 years for a 2 kWp
  system on 1 000 kWh — honest, but Sprint 8's user test should check
  whether advisors read it as useful or as a reason to distrust the tool.
- `nätnytta` is still an unsourced 5 öre placeholder; the assumptions
  expander now flags it in the UI with a warning sign.
- The consumption profile is still a plausible shape, not measured data —
  now disclosed in both the expander and the footer.

## Sprint 8 — Adapt "Tomorrow", test and ship (2026-10-05)

**Written retrospectively on 2026-10-06, reconstructed from the nine commits
`cf46b49..700ce78`.** That is itself the sprint's main process finding — see
*Problems hit*.

### Goal
Battery plan in plain language, polish, user test with 2–3 people acting as
advisors, fixes, README, deploy. Done when: the public link works in a clean
browser.

### Built
- `src/prices.py`: settled past days served from the committed cache with
  **zero HTTP requests** (measured 8.42 s / 365 requests → 1.73 s / 0,
  output identical within 1e-12), with a row-count integrity guard computed
  from the zone so the 23- and 25-hour DST days are not rejected.
- `src/battery.py`: `grid_charge_plan` returning a per-day reason code, with
  `grid_charge_allowance` kept as a wrapper so `simulate` and ten existing
  tests were untouched. `ScenarioResult.yearly_cost_sek` → `cost_sek`.
- `src/plan.py` + 28 tests: one simulated day reduced to ordered,
  plain-language steps, with per-action thresholds, positional run merging
  that survives both DST nights, and a money-reconciliation test.
- The Tomorrow tab: the plan, two money cards with a "one day is not a year"
  guard rail, and a tomorrow-only price-spread line.
- `window_cost` deleted after measurement (see *Decisions*).
- Polish: `.streamlit/config.toml` pinning a light theme, the requirements
  split, zero-value donut slices filtered, `page_icon` and About, labelled
  fallback notices, a "Check again" button.
- README rewritten for v2, `scripts/warm_cache.py`, `docs/user-test.md`.

### Reused from v1 / adapted / new
- **Reused:** `calc.cheapest_window`, `cache.py`, `_build_price_figure`,
  the `(df, failed, fallback)` result shape, the test style.
- **Adapted:** the committed cache, promoted from outage fallback to primary
  fast path for settled days.
- **New:** `plan.py`, the reason codes, the config/requirements split,
  `warm_cache.py`, the user-test script.

### Decisions (and why)
1. **A day must not be simulated alone.** `simulate` starts the battery
   empty, so a day-alone run assumes an empty battery at midnight — wrong on
   **151 of 367 days**, overstating that day's cost by a mean of 2.53 SEK and
   up to 13.21 SEK against a figure displayed as 8–21 SEK. Fixed by
   simulating the 48-hour window already fetched and slicing. One warm-up day
   reproduces a continuous year **exactly**.
2. **`window_cost` deleted, on a measurement rather than tidiness.** It
   prices a window at constant power, which is what rule 4 *plans* but not
   what `simulate` *realises*; the two differ in 8 hours of the year by up to
   4.98 kWh. A SEK figure from it would have contradicted the next tab.
3. **Hour ranges render "17:00–21:00 · 4 h"**, deviating from CLAUDE.md's
   illustrative "17–20": Swedish price apps label an hour by its start, so
   "17–20" is ambiguous on the one line a customer screenshots, and the hour
   count is also the DST disambiguator.
4. **No `ttl` on the year-long fetchers.** The cache key is the window, so it
   self-invalidates at midnight; a ttl would re-issue 365 requests every hour
   of a working session.

### Alternatives considered and rejected (and why)
- *Disclosing the empty-battery assumption instead of fixing it* — rejected;
  it would have meant printing a number known to be wrong by more than half
  on a large minority of days.
- *Keeping `window_cost` another sprint* — rejected once measured.
- *A date picker on the Tomorrow tab* — rejected; it would have turned
  "Tomorrow" into a second history tab.

### Problems hit / how solved
- **This entry is a day late, and the rule in CLAUDE.md is "after every
  sprint".** The sprint ended on a `docs:` commit, which reads as finished,
  so the log step was skipped and `git tag sprint-8` with it. The fix was to
  reconstruct the entry from the commit log and tag the real last commit
  (`700ce78`) rather than the log commit, so the tag means what the other
  seven mean. Worth recording because the process is the deliverable here:
  a sprint is not over when the code is.
- A dark-mode visitor would have seen white charts on a dark page —
  `theme.base` defaults to unset, i.e. follows the visitor's OS, while all
  four Plotly figures hardcode `plotly_white`. Found by checking the default
  rather than by looking at the screen.
- Rendering the charts to PNG (kaleido) caught two flaws invisible in the
  code: a percentage shown to three decimals beside others at one, and a
  comma thousands separator against the thin space used everywhere else.

### Open questions for next sprint
- **The sprint's own done-criterion was not met.** `git remote -v` is still
  empty: the app was never deployed, so "the public link works in a clean
  browser" is false. Deployment needs a GitHub repo and a Community Cloud
  login.
- **The user test was written but never run.** `docs/user-test.md` is a
  script with no recorded results.
- `nätnytta` is still an unsourced placeholder — closed in Define iteration 2
  by removing it entirely.
- The committed cache decays by a day per day while Community Cloud's
  filesystem is ephemeral, so only a commit can heal it.

## Define iteration 2 — problem statement simplified after review (2026-10-06)

Not a sprint. Sprints 0–8 were Build; this is a deliberate return to
**Define**, which is the part of the design-thinking process this course is
actually grading.

### Trigger
A review of the Sprint 7–8 dashboard found it answered **five** questions
where the advisor needed **four**, and that it showed *data* where the
advisor needed an *answer*. An advisor cannot read a heatmap aloud to a
customer. The screen was full of evidence and short of conclusions.

### Decided
- The dashboard answers exactly four questions: is solar worth it; what is
  the payback and the yearly saving; should they get a battery; and how big.
- **Three full years** (Oct 2023 – Sep 2026) instead of twelve months, with
  today's rules applied to all three, reported as an average plus the range.
- The window is **fixed, not rolling**, so the numbers are identical across
  the written report, the screenshots and the pitch video.
- The assumptions box becomes **editable**, each value carrying its own
  source and "last updated" date.
- The green technology deduction is modelled, **off by default**, with a
  combined cap of 50 000 SEK × number of owners.
- `buy = spot × 1.25 + surcharge`, `sell = spot`.

### Removed, and why
| Removed | Why |
|---|---|
| Tomorrow tab (and `src/plan.py`) | Answers none of the four questions. Shipped 2026-10-05, removed 2026-10-06 — the clearest evidence this iteration was a genuine narrowing. |
| Hour × month heatmap | Shows a pattern; the advisor needs a verdict. |
| Donut (where the power goes) | Interesting, not decision-relevant. |
| Date-zoom overlay chart | The screen now shows results, not dates. |
| Four KPI cards | Replaced by two answer cards that state a conclusion in a sentence. |
| `nätnytta` (grid benefit) | An unsourced placeholder since Sprint 6, closed by **deleting the term**, not by sourcing it. `sell = spot`. |

### Decisions (and why)
1. **The removals are the point.** Roughly three sprints of UI is being cut
   because it answered questions nobody asked. Recorded as deliberate
   narrowing, not scope loss.
2. **The model gets more honest by shrinking.** Dropping `nätnytta` closes a
   flagged open question by removing the thing. It is not free: **94% of
   negative-spot hours sit in the −5..0 öre band**, so they flip from sold to
   curtailed and curtailment rises sharply. That is a real effect, and it is
   also the best argument for a battery, so it stays visible in one line.
3. **The buy-price reformulation changes nothing by itself.**
   `(spot + tax + grid) × 1.25 ≡ spot × 1.25 + surcharge` — verified to
   2.8e-17. The numbers move because the **grid fee was corrected** from an
   implied 33.75 öre to a sourced 23 öre incl. VAT, not because the formula
   changed. Separated into its own commit so the diff says so.
4. **Defaults are sourced and not tuned toward a "Yes"**: battery
   7 000 SEK/kWh, battery warranty 10 years, system price 17 000 SEK/kWp.
5. **The payback curve retires the battery at year 10 rather than replacing
   it.** The solar + battery line continues to year 25 accruing solar-only
   savings, so the permanent gap between the two lines *is* the battery's net
   lifetime verdict, readable without arithmetic.

### Alternatives considered and rejected (and why)
- *A rolling three-year window* — rejected: the numbers would drift between
  the report, the screenshots and the video, which have to agree.
- *Keeping the Tomorrow tab behind a toggle* — rejected: a toggle is how a
  simplification quietly fails. It answers none of the four questions.
- *Replacing the battery at year 10 on the payback curve* — rejected: it
  requires an unverifiable assumption about the price of a battery in 2036.
- *Normalising the three years for the 2024 leap day* — rejected on
  measurement: worth ~2.6 SEK against a between-year spread of thousands.

### Open questions for next sprint
- At sourced prices the honest answer is **Solar: Yes, Battery: No** — the
  battery pays back in ~20 years against a 10-year warranty. The card must
  also say that on an expected 15-year service life it *would* pay off with
  the deduction, because that is the question an advisor will be asked next.
- Deployment and the user test are still outstanding from Sprint 8.
