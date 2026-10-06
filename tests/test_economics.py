"""Tests for src/economics.py -- aggregation, deduction and the verdicts.

Pure arithmetic on synthetic costs, so every expected value can be worked
out by hand in the test itself. The one place real data appears is
`year_spans` on the actual window, because that is where a silently clipped
year would hide.

The deduction cap tests matter more than they look: the cap binds at the
default customer, and when it binds the apportionment rule decides both
cards.
"""

from datetime import date

import pandas as pd
import pytest

from src.config import WINDOW_END, WINDOW_START, Settings
from src.economics import (
    Savings,
    YearlyCosts,
    break_even_year,
    green_tech_deduction,
    payback_curve,
    payback_years,
    recommend,
    savings,
    year_spans,
    yearly_net_cost,
)

TZ = "Europe/Stockholm"


# -- year_spans ----------------------------------------------------------------

def test_year_spans_splits_the_real_window_into_three_whole_years():
    spans = year_spans(WINDOW_START, WINDOW_END)
    assert len(spans) == 3
    assert spans[0].start == date(2023, 10, 1)
    assert spans[-1].end == date(2026, 9, 30)
    # contiguous, no gap and no overlap
    for earlier, later in zip(spans, spans[1:]):
        assert (later.start - earlier.end).days == 1


def test_year_spans_labels_read_as_a_period_not_a_date():
    assert year_spans(WINDOW_START, WINDOW_END)[0].label == "Oct 2023 – Sep 2024"


def test_year_spans_rejects_a_window_that_is_not_whole_years():
    """A window quietly clipped to 2 years 11 months would still produce a
    plausible average, and nothing on screen would reveal it."""
    with pytest.raises(ValueError, match="whole number of years"):
        year_spans(date(2023, 10, 1), date(2026, 8, 31))


def test_year_spans_handles_the_leap_year_without_special_casing():
    spans = year_spans(WINDOW_START, WINDOW_END)
    lengths = [(s.end - s.start).days + 1 for s in spans]
    assert lengths == [366, 365, 365]  # 2024-02-29 falls in the first span


# -- yearly_net_cost -----------------------------------------------------------

def test_yearly_net_cost_slices_each_span_without_double_counting():
    index = pd.date_range("2023-10-01", "2026-09-30 23:00", freq="h", tz=TZ)
    detail = pd.DataFrame({"net_cost_sek": [1.0] * len(index)}, index=index)
    spans = year_spans(WINDOW_START, WINDOW_END)

    totals = yearly_net_cost(detail, spans)
    assert len(totals) == 3
    # 1 SEK per hour, so each total is that span's hour count; the three DST
    # pairs cancel within each span, and the leap year carries 24 more
    assert sum(totals) == pytest.approx(len(index))
    assert totals[0] > totals[1]  # the leap year has one extra day


# -- Savings -------------------------------------------------------------------

def test_savings_reports_average_and_both_extremes():
    s = savings(baseline=(100.0, 120.0, 140.0), scenario=(60.0, 60.0, 60.0))
    assert s.per_year == (40.0, 60.0, 80.0)
    assert s.average == pytest.approx(60.0)
    assert s.lowest == pytest.approx(40.0)
    assert s.highest == pytest.approx(80.0)


def test_savings_requires_matching_year_counts():
    with pytest.raises(ValueError):
        savings((1.0, 2.0), (1.0,))


def test_empty_savings_do_not_divide_by_zero():
    assert Savings(()).average == 0.0


# -- the deduction -------------------------------------------------------------

DED = dict(solar_rate=0.15, battery_rate=0.50, cap_per_owner_sek=50000.0)


def test_deduction_is_zero_when_switched_off():
    d = green_tech_deduction(200000.0, 70000.0, enabled=False, owners=1, **DED)
    assert d.total_sek == 0.0
    assert not d.capped


def test_deduction_applies_both_rates_when_the_cap_does_not_bind():
    d = green_tech_deduction(100000.0, 40000.0, enabled=True, owners=1, **DED)
    assert d.solar_sek == pytest.approx(15000.0)
    assert d.battery_sek == pytest.approx(20000.0)
    assert not d.capped


def test_the_cap_is_combined_and_solar_is_deducted_first():
    """Solar 15% of 200k = 30 000, battery 50% of 70k = 35 000, total 65 000
    against a 50 000 cap. Solar takes its full 30 000; the battery gets the
    remaining 20 000, not its full 35 000."""
    d = green_tech_deduction(200000.0, 70000.0, enabled=True, owners=1, **DED)
    assert d.solar_sek == pytest.approx(30000.0)
    assert d.battery_sek == pytest.approx(20000.0)
    assert d.total_sek == pytest.approx(50000.0)
    assert d.capped


def test_two_owners_double_the_cap():
    one = green_tech_deduction(200000.0, 70000.0, enabled=True, owners=1, **DED)
    two = green_tech_deduction(200000.0, 70000.0, enabled=True, owners=2, **DED)
    assert one.capped and not two.capped
    assert two.total_sek == pytest.approx(65000.0)


def test_the_solar_deduction_does_not_move_when_the_battery_size_does():
    """Why solar-first matters: the solar card must not jump about while the
    battery sweep runs."""
    small = green_tech_deduction(200000.0, 35000.0, enabled=True, owners=1, **DED)
    large = green_tech_deduction(200000.0, 105000.0, enabled=True, owners=1, **DED)
    assert small.solar_sek == large.solar_sek == pytest.approx(30000.0)


# -- payback -------------------------------------------------------------------

def test_payback_divides_investment_by_the_average_saving():
    assert payback_years(75000.0, 1500.0) == pytest.approx(50.0)


def test_payback_is_none_rather_than_infinite_when_nothing_is_saved():
    assert payback_years(75000.0, 0.0) is None
    assert payback_years(75000.0, -10.0) is None


# -- recommend -----------------------------------------------------------------

def _costs(no_solar, by_size) -> YearlyCosts:
    return YearlyCosts(
        spans=year_spans(WINDOW_START, WINDOW_END),
        no_solar=no_solar,
        by_size=by_size,
        production_kwh_per_year=10000.0,
        curtailed_kwh_per_year=100.0,
        self_consumption_by_size={0: 0.48, 5: 0.6, 10: 0.66, 15: 0.7},
        grid_charge_days_by_size={0: 0, 5: 100, 10: 138, 15: 180},
    )


def _three(value):
    return (value, value, value)


def test_solar_is_yes_when_it_pays_back_inside_its_lifetime():
    # saves 10 000/yr against a 100 000 net investment -> 10 years
    costs = _costs(_three(30000.0), {0: _three(20000.0), 5: _three(19000.0),
                                     10: _three(18500.0), 15: _three(18200.0)})
    r = recommend(costs, system_price_sek=100000.0, battery_price_per_kwh_sek=7000.0,
                  settings=Settings.defaults())
    assert r.solar_worth_it
    assert r.solar.payback_years == pytest.approx(10.0)


def test_solar_is_no_when_payback_exceeds_its_lifetime():
    costs = _costs(_three(30000.0), {0: _three(29000.0), 5: _three(28900.0),
                                     10: _three(28800.0), 15: _three(28700.0)})
    r = recommend(costs, system_price_sek=100000.0, battery_price_per_kwh_sek=7000.0,
                  settings=Settings.defaults())
    assert not r.solar_worth_it
    assert r.solar.payback_years == pytest.approx(100.0)


def test_the_recommended_battery_is_the_shortest_payback_that_clears_the_warranty():
    # 5 kWh saves 2 000/yr on 35 000 -> 17.5y; 10 kWh saves 7 000 on 70 000 -> 10y;
    # 15 kWh saves 15 000 on 105 000 -> 7y   => 15 kWh wins
    costs = _costs(_three(30000.0), {
        0: _three(20000.0), 5: _three(18000.0), 10: _three(13000.0), 15: _three(5000.0),
    })
    r = recommend(costs, system_price_sek=100000.0, battery_price_per_kwh_sek=7000.0,
                  settings=Settings.defaults())
    assert r.recommended is not None
    assert r.recommended.capacity_kwh == 15
    assert r.recommended.payback_years == pytest.approx(7.0)


def test_battery_is_no_when_no_size_pays_back_but_the_best_candidate_is_still_named():
    """A bare "No" is useless to an advisor, so the best candidate and its
    payback must survive the verdict."""
    costs = _costs(_three(30000.0), {
        0: _three(20000.0), 5: _three(19000.0), 10: _three(18500.0), 15: _three(18300.0),
    })
    r = recommend(costs, system_price_sek=100000.0, battery_price_per_kwh_sek=7000.0,
                  settings=Settings.defaults())
    assert r.recommended is None
    assert r.best_candidate is not None
    assert r.best_candidate.payback_years > Settings.defaults().battery_lifetime_years


def test_a_near_miss_on_the_warranty_is_flagged_against_the_service_life():
    """The sentence the card adds: no on 10 years, yes on 15."""
    # 5 kWh: 35 000 net, saves 3 000/yr -> 11.7 years. Past 10, inside 15.
    costs = _costs(_three(30000.0), {
        0: _three(20000.0), 5: _three(17000.0), 10: _three(17000.0), 15: _three(17000.0),
    })
    r = recommend(costs, system_price_sek=100000.0, battery_price_per_kwh_sek=7000.0,
                  settings=Settings.defaults())
    assert r.recommended is None
    assert r.best_on_service_life is not None
    assert r.best_on_service_life.capacity_kwh == 5


def test_no_service_life_flag_when_the_battery_misses_both_horizons():
    """So the sentence cannot degrade into boilerplate that always appears."""
    costs = _costs(_three(30000.0), {
        0: _three(20000.0), 5: _three(19800.0), 10: _three(19700.0), 15: _three(19600.0),
    })
    r = recommend(costs, system_price_sek=100000.0, battery_price_per_kwh_sek=7000.0,
                  settings=Settings.defaults())
    assert r.recommended is None
    assert r.best_on_service_life is None


def test_no_service_life_flag_when_the_battery_already_pays_back():
    costs = _costs(_three(30000.0), {
        0: _three(20000.0), 5: _three(10000.0), 10: _three(9000.0), 15: _three(8000.0),
    })
    r = recommend(costs, system_price_sek=100000.0, battery_price_per_kwh_sek=7000.0,
                  settings=Settings.defaults())
    assert r.recommended is not None
    assert r.best_on_service_life is None


def test_a_battery_that_saves_nothing_has_no_payback_and_is_not_recommended():
    costs = _costs(_three(30000.0), {
        0: _three(20000.0), 5: _three(20000.0), 10: _three(20000.0), 15: _three(20000.0),
    })
    r = recommend(costs, system_price_sek=100000.0, battery_price_per_kwh_sek=7000.0,
                  settings=Settings.defaults())
    assert all(s.payback_years is None for s in r.sizes)
    assert r.recommended is None
    assert r.best_candidate is None


def test_switching_the_deduction_on_shortens_every_payback():
    costs = _costs(_three(30000.0), {
        0: _three(20000.0), 5: _three(18000.0), 10: _three(13000.0), 15: _three(5000.0),
    })
    kwargs = dict(system_price_sek=100000.0, battery_price_per_kwh_sek=7000.0)
    off = recommend(costs, settings=Settings.defaults(green_tech_enabled=False), **kwargs)
    on = recommend(costs, settings=Settings.defaults(green_tech_enabled=True), **kwargs)
    assert on.solar.payback_years < off.solar.payback_years
    assert on.recommended.payback_years < off.recommended.payback_years


# -- the payback curve ---------------------------------------------------------

def _recommendation_with_a_battery():
    costs = _costs(_three(30000.0), {
        0: _three(20000.0), 5: _three(18000.0), 10: _three(13000.0), 15: _three(5000.0),
    })
    return recommend(costs, system_price_sek=100000.0, battery_price_per_kwh_sek=7000.0,
                     settings=Settings.defaults())


def test_the_curve_starts_at_minus_the_investment():
    r = _recommendation_with_a_battery()
    curve = payback_curve(r, solar_lifetime_years=25, battery_lifetime_years=10)
    first = curve[curve["year"] == 0]
    solar_row = first[first["series"] == "Solar only"].iloc[0]
    assert solar_row["average"] == pytest.approx(-r.solar.net_investment_sek)


def test_the_curve_crosses_zero_at_the_payback_year():
    r = _recommendation_with_a_battery()
    curve = payback_curve(r, solar_lifetime_years=25, battery_lifetime_years=10)
    crossing = break_even_year(curve, "Solar only")
    assert crossing == pytest.approx(round(r.solar.payback_years), abs=1)


def test_the_battery_is_retired_at_its_lifetime_not_replaced():
    """After the warranty year the combined line keeps accruing solar-only
    savings, so the two lines stay a fixed distance apart -- and that gap is
    the battery's net lifetime result."""
    r = _recommendation_with_a_battery()
    curve = payback_curve(r, solar_lifetime_years=25, battery_lifetime_years=10)
    combined = f"Solar + {r.recommended.capacity_kwh} kWh battery"

    def gap(year):
        at = curve[curve["year"] == year]
        return (float(at[at["series"] == combined]["average"].iloc[0])
                - float(at[at["series"] == "Solar only"]["average"].iloc[0]))

    # the gap still moves while the battery is alive...
    assert gap(10) != pytest.approx(gap(9))
    # ...and is frozen afterwards, because the battery stopped earning
    assert gap(25) == pytest.approx(gap(10))


def test_both_series_run_to_the_solar_lifetime():
    r = _recommendation_with_a_battery()
    curve = payback_curve(r, solar_lifetime_years=25, battery_lifetime_years=10)
    for series, rows in curve.groupby("series"):
        assert rows["year"].max() == 25


def test_the_curve_carries_the_range_as_well_as_the_average():
    r = _recommendation_with_a_battery()
    curve = payback_curve(r, solar_lifetime_years=25, battery_lifetime_years=10)
    last = curve[(curve["series"] == "Solar only") & (curve["year"] == 25)].iloc[0]
    assert last["lowest"] <= last["average"] <= last["highest"]


def test_the_curve_has_only_a_solar_series_when_no_battery_ever_pays():
    costs = _costs(_three(30000.0), {
        0: _three(20000.0), 5: _three(20000.0), 10: _three(20000.0), 15: _three(20000.0),
    })
    r = recommend(costs, system_price_sek=100000.0, battery_price_per_kwh_sek=7000.0,
                  settings=Settings.defaults())
    curve = payback_curve(r, solar_lifetime_years=25, battery_lifetime_years=10)
    assert set(curve["series"]) == {"Solar only"}
