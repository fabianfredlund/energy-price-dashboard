"""Tests for src/battery.py.

The centrepiece is the mandatory energy balance test. It is parametrized
over twelve fixtures x three scenarios and asserts **per hour**, never on
sums -- a sum can hide two equal and opposite errors.

The trap with an invariant test is that it passes trivially on all-zero
data, so `test_balance_fixtures_still_exercise_every_branch` checks that
each fixture actually drives the branch it exists for. Without it, an
edit that quietly zeroes a branch would leave the balance test green.
"""

import inspect
import math

import pandas as pd
import pytest

import src.battery
from src.battery import (
    FLOW_COLUMNS,
    GRID_CHARGE_REASONS,
    SPOT_COLUMN,
    buy_price,
    build_frame,
    grid_charge_allowance,
    grid_charge_plan,
    max_power_kwh_per_hour,
    run_scenario,
    sell_price,
    simulate,
)
from src.calc import cheapest_window
from src.config import Settings

#: One Settings for the whole module. Tests that care about a particular
#: assumption build their own with Settings.defaults(**overrides).
S = Settings.defaults()
POWER = {"max_power_fraction": S.battery_max_power_fraction}
RULE4 = {
    "margin": S.grid_charge_min_margin_sek_per_kwh,
    "efficiency": S.round_trip_efficiency,
    **POWER,
}

TZ = "Europe/Stockholm"


def _day_index(day: str) -> pd.DatetimeIndex:
    """Hours of one local calendar day -- 23, 24 or 25 of them."""
    start = pd.Timestamp(day, tz=TZ)
    return pd.date_range(start, start + pd.DateOffset(days=1), freq="h", tz=TZ, inclusive="left")


def _frame(index, production, consumption, spot) -> pd.DataFrame:
    n = len(index)
    as_list = lambda v: list(v) if hasattr(v, "__len__") else [float(v)] * n
    return pd.DataFrame(
        {
            "production_kwh": as_list(production),
            "consumption_kwh": as_list(consumption),
            SPOT_COLUMN: as_list(spot),
        },
        index=index,
    )


def _bell(n: int, peak: float) -> list[float]:
    """A crude daylight curve: zero at night, peak around midday."""
    return [max(0.0, peak * (1 - ((h - 12) / 6) ** 2)) for h in range(n)]


# -- fixtures, each forcing a specific branch ----------------------------------

def peaky_spring_day():
    idx = _day_index("2026-04-15")
    spot = [0.3] * 6 + [1.6] * 3 + [0.4] * 8 + [1.8] * 4 + [0.5] * 3
    return _frame(idx, _bell(24, 9.0), [1.5] * 24, spot)


def negative_midday_day():
    idx = _day_index("2026-06-20")
    spot = [0.2] * 10 + [-0.30] * 5 + [0.2] * 9  # deeply negative -> curtail
    return _frame(idx, _bell(24, 10.0), [0.8] * 24, spot)


def mildly_negative_day():
    # spot just below zero. Under v2's sell = spot + nätnytta this still
    # paid a positive price and so was SOLD; under sell = spot it pays a
    # negative price and is CURTAILED. ~94% of real negative-spot hours
    # sit in this band, so it is the opposite of a corner case.
    idx = _day_index("2026-06-21")
    return _frame(idx, _bell(24, 10.0), [0.8] * 24, [-0.03] * 24)


def winter_night_no_production():
    idx = _day_index("2026-01-15")
    return _frame(idx, 0.0, 2.5, [0.9] * 24)


def flat_price_day():
    # nothing is strictly above the median, so the battery never discharges
    idx = _day_index("2026-02-10")
    return _frame(idx, _bell(24, 3.0), 2.0, [0.8] * 24)


def huge_surplus_tiny_battery():
    idx = _day_index("2026-07-01")
    return _frame(idx, _bell(24, 30.0), 0.5, [0.4] * 24)


def rising_price_day():
    # cheap night, very expensive evening -> grid charging should fire
    idx = _day_index("2026-11-10")
    spot = [0.05] * 6 + [0.6] * 10 + [3.0] * 5 + [0.6] * 3
    return _frame(idx, 0.0, 2.0, spot)


def zero_consumption_day():
    idx = _day_index("2026-05-20")
    return _frame(idx, _bell(24, 8.0), 0.0, [0.5] * 24)


def spring_forward_day():
    idx = _day_index("2026-03-29")  # 23 hours
    return _frame(idx, _bell(len(idx), 6.0), 1.5, [0.6] * len(idx))


def fall_back_day():
    idx = _day_index("2026-10-25")  # 25 hours
    return _frame(idx, _bell(len(idx), 4.0), 1.5, [0.7] * len(idx))


def day_with_gap():
    idx = _day_index("2026-04-16")
    frame = _frame(idx, _bell(24, 9.0), 1.5, [0.8] * 24)
    return frame.drop(frame.index[8:14])  # six missing priced hours


def single_hour_period():
    idx = _day_index("2026-04-17")[:1]
    return _frame(idx, [5.0], [1.0], [0.5])


def empty_period():
    idx = pd.DatetimeIndex([], tz=TZ)
    return _frame(idx, [], [], [])


BALANCE_FIXTURES = {
    "peaky_spring_day": peaky_spring_day,
    "negative_midday_day": negative_midday_day,
    "mildly_negative_day": mildly_negative_day,
    "winter_night_no_production": winter_night_no_production,
    "flat_price_day": flat_price_day,
    "huge_surplus_tiny_battery": huge_surplus_tiny_battery,
    "rising_price_day": rising_price_day,
    "zero_consumption_day": zero_consumption_day,
    "spring_forward_day": spring_forward_day,
    "fall_back_day": fall_back_day,
    "day_with_gap": day_with_gap,
    "single_hour_period": single_hour_period,
    "empty_period": empty_period,
}

SCENARIOS = [
    pytest.param(0.0, False, id="no_solar"),
    pytest.param(0.0, True, id="solar_only"),
    pytest.param(10.0, True, id="solar_battery"),
    pytest.param(2.0, True, id="solar_tiny_battery"),
]


# -- THE MANDATORY ENERGY BALANCE TEST -----------------------------------------

@pytest.mark.parametrize("fixture_name", sorted(BALANCE_FIXTURES))
@pytest.mark.parametrize("capacity,with_solar", SCENARIOS)
def test_energy_balance_holds_for_every_hour(fixture_name, capacity, with_solar):
    detail = run_scenario(BALANCE_FIXTURES[fixture_name](), capacity, with_solar=with_solar, settings=S).detail
    if detail.empty:
        return  # empty period: nothing to balance, and nothing to hide

    produced = detail["own_use_kwh"] + detail["to_battery_kwh"] + detail["sold_kwh"] + detail["curtailed_kwh"]
    assert ((detail["production_kwh"] - produced).abs() < 1e-9).all()

    consumed = detail["own_use_kwh"] + detail["from_battery_kwh"] + detail["bought_for_house_kwh"]
    assert ((detail["consumption_kwh"] - consumed).abs() < 1e-9).all()

    effective_capacity = capacity if with_solar else 0.0
    assert (detail["soc_kwh"] >= -1e-9).all()
    assert (detail["soc_kwh"] <= effective_capacity + 1e-9).all()

    for col in FLOW_COLUMNS:
        assert (detail[col] >= -1e-9).all(), f"{col} went negative"

    stored = (detail["to_battery_kwh"] + detail["grid_charge_kwh"]).sum()
    released = (detail["from_battery_kwh"] + detail["battery_loss_kwh"]).sum()
    assert stored - released == pytest.approx(detail["soc_kwh"].iloc[-1], abs=1e-9)


def test_balance_fixtures_still_exercise_every_branch():
    """Guards the test above: an invariant holds trivially on all-zero data,
    so each fixture must still drive the branch it was written for."""
    def detail(name, capacity=10.0):
        return run_scenario(BALANCE_FIXTURES[name](), capacity, with_solar=True, settings=S).detail

    assert detail("peaky_spring_day")["to_battery_kwh"].sum() > 0
    assert detail("peaky_spring_day")["from_battery_kwh"].sum() > 0
    assert detail("negative_midday_day")["curtailed_kwh"].sum() > 0
    # inverted in Define iteration 2 along with sell = spot; the positive-price
    # sell branch is still covered by huge_surplus_tiny_battery below
    assert detail("mildly_negative_day")["sold_kwh"].sum() == 0
    assert detail("mildly_negative_day")["curtailed_kwh"].sum() > 0
    assert detail("winter_night_no_production")["bought_for_house_kwh"].sum() > 0
    assert detail("flat_price_day")["from_battery_kwh"].sum() == 0
    assert detail("huge_surplus_tiny_battery", 2.0)["sold_kwh"].sum() > 0
    assert detail("rising_price_day")["grid_charge_kwh"].sum() > 0
    assert detail("zero_consumption_day")["own_use_kwh"].sum() == 0


# -- prices --------------------------------------------------------------------

def test_buy_price_is_vat_on_spot_plus_the_surcharge():
    spot = pd.Series([1.0])
    expected = 1.0 * (1 + S.vat_rate) + S.surcharge_sek_per_kwh
    assert buy_price(
        spot, vat_rate=S.vat_rate, surcharge_sek_per_kwh=S.surcharge_sek_per_kwh
    ).iloc[0] == pytest.approx(expected)


def test_the_new_buy_formula_matches_the_old_one_at_the_equivalent_surcharge():
    """Pins the algebra, so the sprint log's claim is checkable.

    v2 computed `(spot + tax + grid) * (1 + VAT)` with tax 0.36 and grid
    0.27 excl. VAT. That is identical to `spot * 1.25 + 0.7875`. The
    headline numbers moved in Define iteration 2 because the grid fee was
    **corrected** to a sourced 23 öre incl. VAT, not because the formula
    changed -- and this test is what makes that statement verifiable.
    """
    spot = pd.Series([-0.5, 0.0, 0.37, 1.2, 3.0])
    old_form = (spot + 0.36 + 0.27) * 1.25
    new_form = buy_price(spot, vat_rate=0.25, surcharge_sek_per_kwh=0.7875)
    pd.testing.assert_series_equal(old_form, new_form, atol=1e-12)


def test_sell_price_is_the_bare_spot_price():
    """Inverted in Define iteration 2: the `nätnytta` term is gone.

    It was an unsourced 5 öre placeholder from Sprint 6, removed rather
    than guessed at again. The consequence is in the curtailment test
    below, not here.
    """
    assert sell_price(pd.Series([1.0])).iloc[0] == pytest.approx(1.0)
    assert sell_price(pd.Series([-0.03])).iloc[0] == pytest.approx(-0.03)


def test_buying_always_costs_more_than_selling_earns():
    # the whole reason self-consumption beats exporting
    spot = pd.Series([-0.1, 0.0, 0.5, 2.0])
    assert (buy_price(spot, vat_rate=S.vat_rate, surcharge_sek_per_kwh=S.surcharge_sek_per_kwh) > sell_price(spot)).all()


# -- grid charging (rule 4) ----------------------------------------------------

def _allowance(frame, capacity=10.0):
    surplus = (frame["production_kwh"] - frame["consumption_kwh"]).clip(lower=0)
    return grid_charge_allowance(
        buy_price(frame[SPOT_COLUMN], vat_rate=S.vat_rate, surcharge_sek_per_kwh=S.surcharge_sek_per_kwh),
        surplus, capacity, **RULE4,
    )


def test_grid_charge_fires_when_the_evening_is_much_dearer_than_the_night():
    frame = rising_price_day()
    allowance = _allowance(frame)
    assert allowance.sum() > 0
    assert frame.loc[allowance > 0, SPOT_COLUMN].max() < 0.5  # it picked cheap hours


def test_grid_charge_does_not_fire_on_a_flat_day():
    assert not (_allowance(flat_price_day()) > 0).any()


def test_grid_charge_never_fires_without_a_battery():
    assert not (_allowance(rising_price_day(), capacity=0.0) > 0).any()


def test_grid_charge_ignores_cheap_hours_with_nothing_left_to_discharge_into():
    # cheapest hours at the very end of the day -> no later expensive hours
    idx = _day_index("2026-11-11")
    frame = _frame(idx, 0.0, 2.0, [2.0] * 22 + [0.05] * 2)
    assert not (_allowance(frame) > 0).any()


def test_grid_charge_reserves_room_for_the_expected_solar_surplus():
    """The fix for rule 4: on a sunny day the sun is expected to fill the
    battery, so grid charging must stay out of the way and leave the room
    free -- otherwise the battery blocks its own self-consumption."""
    idx = _day_index("2026-06-15")
    # cheap night / dear evening (rule 4 would fire on price alone) but a
    # large midday surplus is coming
    spot = [0.05] * 6 + [0.6] * 10 + [3.0] * 5 + [0.6] * 3
    sunny = _frame(idx, _bell(24, 12.0), 1.0, spot)
    assert not (_allowance(sunny) > 0).any()

    # same prices, same battery, but midwinter with no production at all
    dark = _frame(idx, 0.0, 1.0, spot)
    assert _allowance(dark).sum() > 0


def test_grid_charge_allowance_never_exceeds_the_free_room():
    idx = _day_index("2026-11-12")
    spot = [0.05] * 6 + [0.6] * 10 + [3.0] * 5 + [0.6] * 3
    # a modest surplus leaves only part of the battery for the grid to fill
    frame = _frame(idx, _bell(24, 2.0), 1.0, spot)
    surplus = (frame["production_kwh"] - frame["consumption_kwh"]).clip(lower=0).sum()
    assert _allowance(frame).sum() == pytest.approx(max(0.0, 10.0 - surplus))


def _allowance_reference(buy, expected_surplus, capacity_kwh,
                         margin=S.grid_charge_min_margin_sek_per_kwh,
                         efficiency=S.round_trip_efficiency):
    """`grid_charge_allowance` written the obvious, slow way.

    This is the pre-optimisation version verbatim: it recomputes
    `expected_surplus.index.date` and scans the whole series once per
    calendar day. That scan was 94% of a three-scenario comparison, so the
    real function hoists the lookup into a single groupby. Keeping the
    obvious version here as an oracle means the optimisation is pinned to
    behaviour rather than to a set of SEK figures that shift whenever the
    committed cache gains a day.
    """
    allowance = pd.Series(0.0, index=buy.index)
    power = max_power_kwh_per_hour(capacity_kwh, **POWER)
    if capacity_kwh <= 0 or power <= 0 or buy.empty:
        return allowance
    for day, day_buy in buy.groupby(buy.index.date):
        budget = capacity_kwh - float(
            expected_surplus.loc[expected_surplus.index.date == day].sum()
        )
        if budget <= 0:
            continue
        window_hours = max(1, math.ceil(budget / power))
        found = cheapest_window(day_buy.tolist(), window_hours, wrap=False)
        if found is None:
            continue
        cheap_mean = found.total_price / window_hours
        later = day_buy.iloc[found.start + window_hours:]
        if later.empty:
            continue
        dearest = later.nlargest(min(window_hours, len(later)))
        if dearest.mean() * efficiency - cheap_mean > margin:
            hours = day_buy.index[found.start: found.start + window_hours]
            allowance.loc[hours] = budget / window_hours
    return allowance


def test_grid_charge_allowance_matches_the_obvious_per_day_scan():
    """The optimisation's regression guard: identical output to the slow
    version on a span built to include the cases where a per-day lookup
    could plausibly disagree -- both DST transitions (23- and 25-hour
    days, where "the hours of a calendar day" is not 24) and alternating
    sunny/dark days so some budgets are reduced to zero and some are not.
    """
    days = ["2026-03-28", "2026-03-29", "2026-03-30", "2025-10-25", "2025-10-26"]
    frames = []
    for i, day in enumerate(days):
        idx = _day_index(day)
        production = _bell(len(idx), 12.0) if i % 2 == 0 else [0.0] * len(idx)
        spot = [0.05] * 6 + [0.6] * (len(idx) - 14) + [3.0] * 5 + [0.6] * 3
        frames.append(_frame(idx, production, 1.0, spot))
    frame = pd.concat(frames).sort_index()
    assert len(frame) == 24 + 23 + 24 + 24 + 25  # the DST days really are odd

    buy = buy_price(frame[SPOT_COLUMN], vat_rate=S.vat_rate, surcharge_sek_per_kwh=S.surcharge_sek_per_kwh)
    surplus = (frame["production_kwh"] - frame["consumption_kwh"]).clip(lower=0)

    for capacity in (0.5, 10.0, 30.0):
        optimised = grid_charge_allowance(buy, surplus, capacity, **RULE4)
        reference = _allowance_reference(buy, surplus, capacity)
        pd.testing.assert_series_equal(optimised, reference)

    # and the fixture must actually drive the branch, or the equality above
    # is satisfied by two identical all-zero series
    assert grid_charge_allowance(buy, surplus, 10.0, **RULE4).sum() > 0


def test_grid_charge_allowance_handles_a_day_absent_from_the_surplus_series():
    """The groupby lookup must treat a missing day as zero surplus, not
    raise. Hours can be priced on a day the production series never
    covered -- build_frame intersects the two, but grid_charge_allowance
    is a public function and takes the two series separately."""
    idx = _day_index("2026-11-13")
    frame = _frame(idx, 0.0, 1.0, [0.05] * 6 + [0.6] * 10 + [3.0] * 5 + [0.6] * 3)
    buy = buy_price(frame[SPOT_COLUMN], vat_rate=S.vat_rate, surcharge_sek_per_kwh=S.surcharge_sek_per_kwh)
    empty_surplus = pd.Series(dtype="float64", index=frame.index[:0])

    allowance = grid_charge_allowance(buy, empty_surplus, 10.0, **RULE4)
    assert allowance.sum() == pytest.approx(10.0)  # the whole battery is free room


def test_max_power_is_half_the_capacity():
    assert max_power_kwh_per_hour(10.0, **POWER) == 5.0


# -- rule 4's reason codes -----------------------------------------------------

def _decision(frame, capacity=10.0):
    surplus = (frame["production_kwh"] - frame["consumption_kwh"]).clip(lower=0)
    return grid_charge_plan(
        buy_price(frame[SPOT_COLUMN], vat_rate=S.vat_rate, surcharge_sek_per_kwh=S.surcharge_sek_per_kwh),
        surplus, capacity, **RULE4,
    )


def _only_reason(decision):
    reasons = set(decision.reasons.values())
    assert len(reasons) == 1, f"expected one day's reason, got {decision.reasons}"
    return reasons.pop()


def test_reason_charged_when_the_spread_is_worth_it():
    assert _only_reason(_decision(rising_price_day())) == "charged"


def test_reason_no_battery_when_capacity_is_zero():
    # still reported per day, so the UI can say "no battery selected"
    # rather than falling through to a blank panel
    assert _only_reason(_decision(rising_price_day(), capacity=0.0)) == "no_battery"


def test_reason_solar_fills_it_on_a_sunny_day():
    idx = _day_index("2026-06-15")
    spot = [0.05] * 6 + [0.6] * 10 + [3.0] * 5 + [0.6] * 3
    assert _only_reason(_decision(_frame(idx, _bell(24, 12.0), 1.0, spot))) == "solar_fills_it"


def test_reason_spread_too_small_on_a_flat_day():
    assert _only_reason(_decision(flat_price_day())) == "spread_too_small"


def test_reason_no_later_hours_when_the_cheap_window_ends_the_day():
    """The calendar artefact the README discloses: the cheapest hours fall
    at the very end of the day, so there is nothing left to discharge
    into -- though a real battery would charge across midnight. 40 days of
    the committed year land here."""
    idx = _day_index("2026-11-11")
    frame = _frame(idx, 0.0, 2.0, [2.0] * 22 + [0.05] * 2)
    assert _only_reason(_decision(frame)) == "no_later_hours"


def test_every_reason_code_is_reachable_and_declared():
    """Companion guard, in the Sprint 6 tradition: an edit that quietly
    stops producing a reason would otherwise leave every test above green
    while the UI silently lost its explanation."""
    produced = {
        _only_reason(_decision(rising_price_day())),
        _only_reason(_decision(rising_price_day(), capacity=0.0)),
        _only_reason(_decision(flat_price_day())),
        _only_reason(_decision(_frame(
            _day_index("2026-11-11"), 0.0, 2.0, [2.0] * 22 + [0.05] * 2))),
        _only_reason(_decision(_frame(
            _day_index("2026-06-15"), _bell(24, 12.0), 1.0,
            [0.05] * 6 + [0.6] * 10 + [3.0] * 5 + [0.6] * 3))),
    }
    assert produced == {
        "charged", "no_battery", "spread_too_small", "no_later_hours", "solar_fills_it",
    }
    # and every code the module declares must be a real string we could emit
    assert produced <= set(GRID_CHARGE_REASONS)


def test_grid_charge_plan_allowance_matches_the_wrapper_across_dst():
    """grid_charge_allowance is now a wrapper. simulate() and ten existing
    tests call it, so the two must never diverge -- checked elementwise
    over both DST transitions, where a day is 23 or 25 hours."""
    days = ["2026-03-28", "2026-03-29", "2026-03-30", "2025-10-25", "2025-10-26"]
    frames = []
    for i, day in enumerate(days):
        idx = _day_index(day)
        production = _bell(len(idx), 12.0) if i % 2 == 0 else [0.0] * len(idx)
        spot = [0.05] * 6 + [0.6] * (len(idx) - 14) + [3.0] * 5 + [0.6] * 3
        frames.append(_frame(idx, production, 1.0, spot))
    frame = pd.concat(frames).sort_index()
    buy = buy_price(frame[SPOT_COLUMN], vat_rate=S.vat_rate, surcharge_sek_per_kwh=S.surcharge_sek_per_kwh)
    surplus = (frame["production_kwh"] - frame["consumption_kwh"]).clip(lower=0)

    for capacity in (0.0, 0.5, 10.0, 30.0):
        pd.testing.assert_series_equal(
            grid_charge_plan(buy, surplus, capacity, **RULE4).allowance,
            grid_charge_allowance(buy, surplus, capacity, **RULE4),
        )
    # a reason for every calendar day present, never a silent gap
    decision = grid_charge_plan(buy, surplus, 10.0, **RULE4)
    assert set(decision.reasons) == set(frame.index.date)


# -- CLAUDE.md's named edge cases ----------------------------------------------

def test_zero_capacity_battery_is_a_pure_solar_only_run():
    frame = peaky_spring_day()
    detail = simulate(frame, capacity_kwh=0.0, settings=S)
    assert detail["to_battery_kwh"].sum() == 0
    assert detail["from_battery_kwh"].sum() == 0
    assert detail["grid_charge_kwh"].sum() == 0
    assert (detail["soc_kwh"] == 0).all()


def test_zero_production_night_buys_everything():
    frame = winter_night_no_production()
    detail = simulate(frame, capacity_kwh=0.0, settings=S)
    assert detail["bought_for_house_kwh"].sum() == pytest.approx(frame["consumption_kwh"].sum())
    assert detail["sold_kwh"].sum() == 0


def test_surplus_is_curtailed_when_the_sell_price_is_negative():
    detail = simulate(negative_midday_day(), capacity_kwh=5.0, settings=S)
    negative_hours = detail["sell_price_sek_per_kwh"] < 0
    assert negative_hours.any()
    assert detail.loc[negative_hours, "sold_kwh"].sum() == 0
    assert detail.loc[negative_hours, "curtailed_kwh"].sum() > 0


def test_mildly_negative_spot_is_now_curtailed_because_sell_equals_spot():
    """**Inverted in Define iteration 2.** Previously this band sold.

    "Never sell at a negative price" means the price you receive. With
    `sell = spot + nätnytta` a spot of -3 öre still paid +2, so the surplus
    was sold; with `sell = spot` it pays -3, so it is curtailed instead.

    This is not a corner case. Measured over the cached year, **94% of all
    negative-spot hours sit in the -5..0 öre band** this flipped, so
    removing the nätnytta placeholder raised curtailment several-fold. That
    is a real economic consequence of a modelling honesty fix, and it is
    also the best argument for a battery -- which is why the UI keeps it
    visible.
    """
    detail = simulate(mildly_negative_day(), capacity_kwh=0.0, settings=S)
    assert (detail["sell_price_sek_per_kwh"] < 0).all()
    assert detail["sold_kwh"].sum() == 0
    assert detail["curtailed_kwh"].sum() > 0


def test_missing_price_hours_are_dropped_and_reported():
    idx = _day_index("2026-04-16")
    production = pd.Series(_bell(24, 9.0), index=idx)
    prices = pd.DataFrame({SPOT_COLUMN: [0.8] * 24}, index=idx).drop(idx[8:14])
    frame, missing = build_frame(production, prices, annual_kwh=20000.0)
    assert missing == 6
    assert len(frame) == 18
    assert not frame[SPOT_COLUMN].isna().any()


def test_dst_days_keep_their_real_length():
    assert len(simulate(spring_forward_day(), 10.0, settings=S)) == 23
    assert len(simulate(fall_back_day(), 10.0, settings=S)) == 25


def test_empty_frame_returns_empty_without_raising():
    detail = simulate(empty_period(), capacity_kwh=10.0, settings=S)
    assert detail.empty
    assert "net_cost_sek" in detail.columns


# -- scenarios and payback -----------------------------------------------------

def _year_frame() -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", "2027-01-01", freq="h", tz=TZ, inclusive="left")
    production = [max(0.0, 8.0 * (1 - ((h - 12) / 6) ** 2)) for h in idx.hour]
    # cheap at night, dear morning and evening
    spot = [0.3 if 0 <= h < 6 else 1.4 if h in (7, 8, 18, 19) else 0.7 for h in idx.hour]
    return _frame(idx, production, 2.3, spot)


def test_no_solar_cost_equals_the_closed_form():
    """An anchor: with no solar, cost is simply consumption x buy price."""
    frame = _year_frame()
    result = run_scenario(frame, 0.0, with_solar=False, settings=S)
    expected = (frame["consumption_kwh"] * buy_price(frame[SPOT_COLUMN], vat_rate=S.vat_rate, surcharge_sek_per_kwh=S.surcharge_sek_per_kwh)).sum()
    assert result.cost_sek == pytest.approx(expected)


def test_a_battery_raises_the_self_consumption_share():
    frame = _year_frame()
    without = run_scenario(frame, 0.0, with_solar=True, settings=S).self_consumption_share
    with_battery = run_scenario(frame, 10.0, with_solar=True, settings=S).self_consumption_share
    assert with_battery > without


# -- the editable-assumptions contract -----------------------------------------
#
# The assumptions box is editable, so the characteristic failure of this design
# is a function that reads a config constant directly and silently ignores the
# user's edit. These two tests make the rule mechanical instead of aspirational.

def test_battery_module_reads_nothing_from_config():
    """`src/battery.py` must take every assumption as an argument.

    Not style. If `buy_price` read the surcharge from `config`, editing it in
    the UI would change nothing -- and only *partly* nothing, because the
    surcharge also re-enters rule 4's buy-price comparison, so some numbers
    would move and others would not. A half-wrong screen is worse than an
    obviously broken one.
    """
    source = inspect.getsource(src.battery)
    assert "src.config" not in source
    assert "from src import config" not in source


@pytest.mark.parametrize("func,param", [
    (simulate, "settings"),
    (run_scenario, "settings"),
    (buy_price, "vat_rate"),
    (buy_price, "surcharge_sek_per_kwh"),
    (max_power_kwh_per_hour, "max_power_fraction"),
    (grid_charge_plan, "margin"),
    (grid_charge_plan, "efficiency"),
    (grid_charge_allowance, "margin"),
    (grid_charge_allowance, "efficiency"),
])
def test_threaded_assumptions_have_no_default(func, param):
    """A missing value must be a TypeError at the call, not a wrong SEK figure."""
    parameter = inspect.signature(func).parameters[param]
    assert parameter.default is inspect.Parameter.empty, (
        f"{func.__name__}({param}=...) has a default; a caller could forget it "
        f"and silently get the wrong assumption"
    )
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
