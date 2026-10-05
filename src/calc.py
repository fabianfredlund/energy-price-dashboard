"""Cheapest-window search.

The one piece of v1's calculator that survived the pivot. It now has a
single production consumer: `src/battery.py`'s rule 4, which uses it to
pick the cheapest contiguous hours of a day to charge the battery from
the grid. v1's load-shift planner was removed in Sprint 7 with the
production-units table it served, and `window_cost` in Sprint 8 -- it
priced a window at *constant* power, which is what rule 4 plans but not
what `simulate` realises, so any SEK figure from it would have
contradicted the Tomorrow tab's own totals.

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
    sum.

    Returns the position and the summed price, never a cost: how much
    energy actually moves in those hours is the caller's business, and in
    rule 4's case it is capped hour by hour by the battery's remaining
    room. Multiplying by an assumed constant power here is exactly the
    mistake the deleted `window_cost` made.

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
