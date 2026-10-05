"""Tests for src/calc.py -- the cheapest-window search.

The does-not-fit cases matter more than they look: battery.py's rule 4
asks for a window inside a single calendar day, and a spring-forward day
has only 23 hours, so "window longer than the series" is a real input,
not a hypothetical.

Sprint 7 removed the v1 planner's tests along with the planner itself.
"""

from src.calc import cheapest_window, window_cost

# -- cheapest_window -----------------------------------------------------------

def test_cheapest_window_basic_non_wrap():
    prices = [10, 10, 1, 1, 10, 10]
    result = cheapest_window(prices, hours=2, wrap=False)
    assert result.start == 2
    assert result.total_price == 2


def test_cheapest_window_wrap_crosses_boundary():
    # cheapest 2-hour window is positions [4, 0] wrapping around the end
    prices = [1, 10, 10, 10, 1]
    result = cheapest_window(prices, hours=2, wrap=True)
    assert result.start == 4
    assert result.total_price == 2


def test_cheapest_window_tie_resolves_to_earliest_start():
    prices = [1, 1, 1, 1]
    result = cheapest_window(prices, hours=2, wrap=False)
    assert result.start == 0


def test_cheapest_window_does_not_fit_non_wrap_returns_none():
    assert cheapest_window([1, 2, 3], hours=4, wrap=False) is None


def test_cheapest_window_does_not_fit_wrap_returns_none():
    assert cheapest_window([1, 2, 3], hours=4, wrap=True) is None


def test_cheapest_window_zero_hours_returns_none():
    assert cheapest_window([1, 2, 3], hours=0, wrap=False) is None


def test_cheapest_window_empty_prices_returns_none():
    assert cheapest_window([], hours=1, wrap=False) is None


def test_cheapest_window_full_length_wrap_is_rotation_invariant():
    prices = [3, 1, 4, 1, 5]
    result = cheapest_window(prices, hours=len(prices), wrap=True)
    assert result.total_price == sum(prices)


# -- window_cost -----------------------------------------------------------------

def test_window_cost_basic():
    prices = [10, 20, 30]
    assert window_cost(prices, start=1, hours=2, power_kw=2.0, wrap=False) == 2.0 * (20 + 30)


def test_window_cost_wrap():
    prices = [10, 20, 30]
    # start=2, hours=2, wrap -> positions 2, 0 -> 30 + 10
    assert window_cost(prices, start=2, hours=2, power_kw=1.0, wrap=True) == 40


def test_window_cost_does_not_fit_past_end_returns_none():
    assert window_cost([1, 2, 3], start=2, hours=2, power_kw=1.0, wrap=False) is None


def test_window_cost_start_out_of_range_returns_none():
    assert window_cost([1, 2, 3], start=5, hours=1, power_kw=1.0, wrap=False) is None


def test_window_cost_zero_hours_returns_none():
    assert window_cost([1, 2, 3], start=0, hours=0, power_kw=1.0, wrap=False) is None
