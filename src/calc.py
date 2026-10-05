"""Cheapest-window search.

The one piece of v1's calculator that survived the pivot. It now has a
single production consumer: `src/battery.py`'s rule 4, which uses it to
pick the cheapest contiguous hours of a day to charge the battery from
the grid. v1's load-shift planner (`plan_unit`, `planner_totals`,
`yearly_saving_estimate` and friends) was removed in Sprint 7 together
with the production-units table it served.

Pure functions only, no Streamlit, no real "now"/calendar awareness --
every position here is a plain integer offset into whatever price series
the caller passes. The caller owns turning those positions back into real
timestamps, since that mapping depends on wall-clock "now" and calendar
dates this module deliberately knows nothing about.
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

    wrap=False (what battery.py's rule 4 passes: one calendar day's
    hours): a window that doesn't fit (hours > len(prices)) returns
    None -- "not enough priced hours in this day", not a crash. That
    case is real, since a fall-back day has 25 hours and a spring-
    forward day only 23.
    wrap=True (a cyclical hour-of-day profile): a window may wrap from
    the end back to the start. Still None if hours exceeds len(prices) --
    a window longer than one full cycle has no single well-defined
    wrap-once start. No production caller uses wrap=True since the
    pivot; it is kept because it costs one line and a day-cyclical
    battery schedule is a plausible Sprint 8 need.

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
    searches over, but for an arbitrary caller-supplied start, so a
    chosen window can be priced without re-searching.

    **Currently exercised only by tests.** Its v1 caller was removed in
    Sprint 7 along with the planner. It is kept rather than deleted
    because Sprint 8's plain-language battery plan ("charge from the grid
    02-05") needs to put a SEK figure on exactly this window shape.
    Sprint 8 either uses it or deletes it -- it must not sit here dead
    for a third sprint.

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

