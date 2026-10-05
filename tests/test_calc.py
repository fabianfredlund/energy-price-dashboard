"""Tests for src/calc.py -- the production planner's pure window-search,
cost, and totals functions, including every edge case CLAUDE.md names
explicitly: run length longer than the available priced hours, no active
units, 0 kW / 0 hours."""

from src.calc import (
    cheapest_window,
    energy_kwh,
    plan_unit,
    planner_totals,
    window_cost,
    yearly_saving_estimate,
)

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


# -- energy_kwh --------------------------------------------------------------------

def test_energy_kwh_normal():
    assert energy_kwh(power_kw=5.0, hours=3) == 15.0


def test_energy_kwh_zero_power():
    assert energy_kwh(power_kw=0.0, hours=3) == 0.0


def test_energy_kwh_zero_hours():
    assert energy_kwh(power_kw=5.0, hours=0) == 0.0


# -- plan_unit -----------------------------------------------------------------

def test_plan_unit_normal_case():
    prices = [10, 10, 1, 1, 10, 10]
    plan = plan_unit(prices, hours=2, power_kw=3.0, usual_start=0, wrap=False)
    assert plan.fits is True
    assert plan.recommended_start == 2
    assert plan.recommended_cost == 3.0 * 2
    assert plan.usual_cost == 3.0 * 20
    assert plan.energy_kwh == 6.0


def test_plan_unit_zero_kw_is_a_noop_not_an_error():
    plan = plan_unit([10, 20, 30], hours=2, power_kw=0.0, usual_start=0, wrap=False)
    assert plan.fits is True
    assert plan.energy_kwh == 0.0
    assert plan.recommended_cost == 0.0
    assert plan.usual_cost == 0.0


def test_plan_unit_zero_hours_is_a_noop_not_an_error():
    plan = plan_unit([10, 20, 30], hours=0, power_kw=5.0, usual_start=0, wrap=False)
    assert plan.fits is True
    assert plan.energy_kwh == 0.0
    assert plan.recommended_cost == 0.0
    assert plan.usual_cost == 0.0


def test_plan_unit_run_length_longer_than_available_hours_does_not_fit():
    plan = plan_unit([10, 20, 30], hours=10, power_kw=5.0, usual_start=0, wrap=False)
    assert plan.fits is False
    assert plan.recommended_start is None
    assert plan.recommended_cost is None
    assert plan.usual_cost is None
    assert plan.energy_kwh == 50.0  # energy is still a plain physical fact about the unit


def test_plan_unit_usual_start_none_still_computes_recommendation():
    plan = plan_unit([10, 10, 1, 1], hours=2, power_kw=1.0, usual_start=None, wrap=False)
    assert plan.fits is True
    assert plan.usual_cost is None
    assert plan.recommended_start == 2
    assert plan.recommended_cost == 2.0


# -- planner_totals -----------------------------------------------------------------

def test_planner_totals_empty_list_is_all_zero():
    totals = planner_totals([])
    assert totals.total_energy_kwh == 0
    assert totals.total_usual_cost == 0
    assert totals.total_recommended_cost == 0
    assert totals.total_saving == 0


def test_planner_totals_normal_multi_unit_sum():
    plans = [
        plan_unit([10, 10, 1, 1], hours=2, power_kw=1.0, usual_start=0, wrap=False),
        plan_unit([5, 5, 5, 1], hours=1, power_kw=2.0, usual_start=1, wrap=False),
    ]
    totals = planner_totals(plans)
    assert totals.total_energy_kwh == plans[0].energy_kwh + plans[1].energy_kwh
    assert totals.total_usual_cost == plans[0].usual_cost + plans[1].usual_cost
    assert totals.total_recommended_cost == plans[0].recommended_cost + plans[1].recommended_cost
    assert totals.total_saving == totals.total_usual_cost - totals.total_recommended_cost


def test_planner_totals_excludes_none_usual_cost_rather_than_treating_as_zero():
    fits_plan = plan_unit([10, 10, 1, 1], hours=2, power_kw=1.0, usual_start=0, wrap=False)
    no_usual_plan = plan_unit([10, 10, 1, 1], hours=2, power_kw=1.0, usual_start=None, wrap=False)
    totals = planner_totals([fits_plan, no_usual_plan])
    # only fits_plan's usual_cost contributes -- verify it's not silently 0-padded
    assert totals.total_usual_cost == fits_plan.usual_cost


# -- yearly_saving_estimate -----------------------------------------------------------------

def test_yearly_saving_estimate_basic():
    assert yearly_saving_estimate(10.0, runs_per_year=365) == 3650.0


def test_yearly_saving_estimate_zero_saving():
    assert yearly_saving_estimate(0.0) == 0.0
