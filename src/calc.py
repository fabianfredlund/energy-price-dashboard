"""Production planner: cheapest-window search, totals, peak power.

Pure functions only, no Streamlit, no real "now"/calendar awareness --
every position here is a plain integer offset into whatever price series
the caller passes (a real timestamp-indexed remaining-hours series for
Plan ahead, or a 24-value hour-of-day "typical day" series for History).
app.py owns turning those positions back into real timestamps or HH:MM
labels, since that mapping depends on wall-clock "now" and calendar dates
this module deliberately knows nothing about.
"""

from typing import NamedTuple, Sequence


class CheapestWindow(NamedTuple):
    start: int
    total_price: float


def cheapest_window(prices: Sequence[float], hours: int, wrap: bool = False) -> CheapestWindow | None:
    """Contiguous run of `hours` positions in `prices` with the lowest
    sum. Cost = power_kw * sum(prices in window) and power_kw is a
    constant multiplier over the whole window, so it can never change
    which window is cheapest -- deliberately no power_kw argument; the
    caller multiplies afterwards (see window_cost).

    wrap=False (Plan ahead's finite remaining-hours series): a window
    that doesn't fit (hours > len(prices)) returns None -- "not enough
    priced hours remaining", not a crash.
    wrap=True (History's cyclical typical-day profile): a window may
    wrap from the end back to the start. Still None if hours exceeds
    len(prices) -- a window longer than one full cycle has no single
    well-defined wrap-once start.

    None for hours <= 0 or empty `prices` too. Ties resolve to the
    earliest start position.
    """
    n = len(prices)
    if hours <= 0 or n == 0 or hours > n:
        return None
    prices = list(prices)
    extended = prices + prices[: hours - 1] if wrap else prices
    prefix = [0.0]
    for p in extended:
        prefix.append(prefix[-1] + p)
    last_start = (n - 1) if wrap else (n - hours)
    best_start, best_total = 0, prefix[hours] - prefix[0]
    for start in range(1, last_start + 1):
        total = prefix[start + hours] - prefix[start]
        if total < best_total:
            best_start, best_total = start, total
    return CheapestWindow(best_start, best_total)


def window_cost(
    prices: Sequence[float], start: int, hours: int, power_kw: float, wrap: bool = False
) -> float | None:
    """Cost of running `hours` at `power_kw` starting at position
    `start` in `prices` -- the same window shape cheapest_window
    searches over, but for an arbitrary caller-supplied start (used to
    price a unit's *usual* start for comparison, and to re-price
    cheapest_window's own recommended start so the power_kw
    multiplication happens in exactly one place).

    None if the window doesn't fit: start out of [0, len(prices)) range,
    hours <= 0, empty prices, hours > len(prices), or (wrap=False only)
    start + hours runs past the end. Same does-not-fit contract as
    cheapest_window so callers handle both uniformly.
    """
    n = len(prices)
    if hours <= 0 or n == 0 or hours > n or start < 0 or start >= n:
        return None
    if wrap:
        total = sum(prices[(start + i) % n] for i in range(hours))
    else:
        if start + hours > n:
            return None
        total = sum(prices[start : start + hours])
    return power_kw * total


def energy_kwh(power_kw: float, hours: int) -> float:
    """Energy per run = power_kw * hours. 0 kW or 0 hours -> 0.0, a
    legitimate 'this unit contributes nothing' result, not an error."""
    return power_kw * hours


def combined_peak_power(
    unit_windows: Sequence[tuple[float, int, int]], timeline_length: int, wrap: bool = False
) -> float:
    """Max simultaneous kW across unit_windows = [(power_kw, start,
    hours), ...], each unit running at its own recommended (or usual)
    start. A plain fixed-length accumulator array, not a sweep-line --
    unit counts and timeline lengths here are tiny (a handful of units,
    well under a hundred timeline positions), so O(units * hours)
    accumulation is simple and fast enough.

    0.0 for no units or timeline_length <= 0 -- never max() on an empty
    sequence. A 0 kW or 0-hour unit is skipped (contributes nothing, not
    an error). A position outside [0, timeline_length) with wrap=False
    is silently ignored -- shouldn't occur if the caller only passes
    windows cheapest_window/window_cost already confirmed fit.
    """
    if not unit_windows or timeline_length <= 0:
        return 0.0
    acc = [0.0] * timeline_length
    for power_kw, start, hours in unit_windows:
        if power_kw <= 0 or hours <= 0:
            continue
        for i in range(hours):
            pos = (start + i) % timeline_length if wrap else start + i
            if 0 <= pos < timeline_length:
                acc[pos] += power_kw
    return max(acc)


class UnitPlan(NamedTuple):
    energy_kwh: float
    recommended_start: int | None
    recommended_cost: float | None
    usual_cost: float | None
    fits: bool  # False only if the run length doesn't fit the priced window at all


def plan_unit(
    prices: Sequence[float],
    hours: int,
    power_kw: float,
    usual_start: int | None,
    wrap: bool = False,
) -> UnitPlan:
    """Bundles the per-unit arithmetic (recommended start + cost, usual-
    start cost, energy per run) into one pure, directly testable
    function, so app.py only converts real timestamps/HH:MM to and from
    integer positions and renders the result -- it never re-derives this
    arithmetic.

    0 kW or 0 hours -> a legitimate no-op unit: energy_kwh=0.0,
    recommended_cost=0.0, usual_cost=0.0, fits=True, recommended_start=0
    (nothing to optimize, not an error).

    usual_start=None (app.py could not map the unit's chosen HH:MM onto
    this priced window at all) -> usual_cost is also None;
    recommended_* is still computed independently, so one unit's
    unmappable usual-start never blocks its own recommendation.
    """
    energy = energy_kwh(power_kw, hours)
    if power_kw <= 0 or hours <= 0:
        return UnitPlan(energy, 0, 0.0, 0.0, fits=True)

    found = cheapest_window(prices, hours, wrap=wrap)
    if found is None:
        return UnitPlan(energy, None, None, None, fits=False)

    recommended_cost = window_cost(prices, found.start, hours, power_kw, wrap=wrap)
    usual_cost = (
        window_cost(prices, usual_start, hours, power_kw, wrap=wrap)
        if usual_start is not None
        else None
    )
    return UnitPlan(energy, found.start, recommended_cost, usual_cost, fits=True)


class PlannerTotals(NamedTuple):
    total_energy_kwh: float
    total_usual_cost: float
    total_recommended_cost: float
    total_saving: float


def planner_totals(unit_plans: Sequence[UnitPlan]) -> PlannerTotals:
    """Totals across active units' plans. Empty input -> all-zero
    totals, not a crash (sum of an empty sequence is 0, never max()/
    division). A unit whose usual_cost or recommended_cost is None
    (doesn't fit) contributes 0 to that specific sum rather than
    poisoning the total with None.
    """
    total_energy = sum(p.energy_kwh for p in unit_plans)
    total_usual = sum(p.usual_cost for p in unit_plans if p.usual_cost is not None)
    total_recommended = sum(
        p.recommended_cost for p in unit_plans if p.recommended_cost is not None
    )
    return PlannerTotals(total_energy, total_usual, total_recommended, total_usual - total_recommended)


def yearly_saving_estimate(total_saving_per_run: float, runs_per_year: int = 365) -> float:
    """total_saving_per_run * runs_per_year. Answers "per year" savings
    (CLAUDE.md's problem statement, Q3) from an explicit, stated
    assumption (default: one run per day) rather than a silent guess --
    the caller states that assumption in the UI alongside this figure.
    """
    return total_saving_per_run * runs_per_year
