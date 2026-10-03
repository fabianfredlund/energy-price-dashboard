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
