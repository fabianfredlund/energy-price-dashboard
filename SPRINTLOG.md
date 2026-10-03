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
