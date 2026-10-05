"""Tests for src/plan.py -- reducing a simulated day to readable steps.

Two groups. The first is pure logic on synthetic flow tables, where the
thresholds and run-merging rules can be pinned exactly. The second reads
real days out of the committed cache (no network) and pins the *shape* of
the output rather than its SEK figures, which shift whenever the cache
gains a day.

The money-reconciliation test is the important one: a step may never claim
a saving the simulation did not book. It is also what replaced
calc.window_cost, which priced a window at constant power and so
disagreed with what simulate actually realises.
"""

from datetime import date
from functools import lru_cache
from pathlib import Path

import pandas as pd
import pytest

from src.battery import buy_price, build_frame, grid_charge_plan, simulate
from src.config import SYSTEM_LOSS_FACTOR
from src.plan import (
    ACTION_ORDER,
    GRID_CHARGE_EXPLANATION,
    MAX_GAP_HOURS,
    MIN_PLAN_KWH,
    PEAK_FRACTION,
    build_day_plan,
    describe_step,
    format_hour_range,
)

TZ = "Europe/Stockholm"
CACHE = Path(__file__).resolve().parents[1] / "data" / "cache"

FLOW_COLS = [
    "grid_charge_kwh", "to_battery_kwh", "from_battery_kwh",
    "sold_kwh", "curtailed_kwh",
]


def _detail(day: str = "2026-06-15", **flows) -> pd.DataFrame:
    """A synthetic flow table: pass any action column as a 24-value list.

    Prices are a flat 1.0 SEK/kWh buy and 0.5 sell, so the money
    assertions below are readable by eye.
    """
    index = pd.date_range(pd.Timestamp(day, tz=TZ), periods=24, freq="h", tz=TZ)
    data = {col: [0.0] * 24 for col in FLOW_COLS}
    data.update({k: list(v) for k, v in flows.items()})
    frame = pd.DataFrame(data, index=index)
    frame["buy_price_sek_per_kwh"] = 1.0
    frame["sell_price_sek_per_kwh"] = 0.5
    return frame


def _hours(action_values: dict, n: int = 24) -> list[float]:
    """Sparse spec -> a 24-value list: {10: 2.0, 11: 2.0} -> zeros but those."""
    out = [0.0] * n
    for hour, value in action_values.items():
        out[hour] = value
    return out


def _only(plan, action):
    matching = [s for s in plan.steps if s.action == action]
    assert len(matching) == 1, f"expected exactly one {action} step, got {plan.steps}"
    return matching[0]


# -- empty and degenerate ------------------------------------------------------

def test_empty_detail_gives_an_empty_plan_not_an_error():
    # "tomorrow's prices aren't published yet" is a normal afternoon state
    plan = build_day_plan(_detail().iloc[:0])
    assert plan.steps == ()
    assert plan.absent == ACTION_ORDER
    assert all(v == 0.0 for v in plan.totals.values())


def test_an_all_zero_day_produces_no_steps_and_reports_everything_absent():
    """A dark winter day with no surplus never charges, so it never
    discharges. Measured: 25 of 365 days of the committed year. The honest
    message is the finding, so the caller needs `absent` to say it."""
    plan = build_day_plan(_detail(), grid_charge_reason="no_later_hours")
    assert plan.steps == ()
    assert plan.absent == ACTION_ORDER
    assert plan.grid_charge_reason == "no_later_hours"


def test_a_night_only_frame_does_not_raise():
    """Regression guard. The natural pandas spelling of "which action
    dominates this hour", DataFrame.where(cond).idxmax(axis=1), raises
    ValueError on a row where nothing qualifies -- i.e. every night hour,
    i.e. every day. This module must stay clear of that."""
    build_day_plan(_detail(from_battery_kwh=_hours({})))  # must not raise


def test_every_reason_code_has_customer_facing_wording():
    from src.battery import GRID_CHARGE_REASONS
    assert set(GRID_CHARGE_EXPLANATION) == set(GRID_CHARGE_REASONS)
    # every explanation except the "it charged" no-op must be a real sentence
    for code, text in GRID_CHARGE_EXPLANATION.items():
        if code != "charged":
            assert text.endswith("."), code


# -- thresholds ----------------------------------------------------------------

def test_an_hour_at_eleven_percent_of_the_days_peak_is_kept():
    values = _hours({12: 10.0, 13: 1.1})  # 11% of the peak
    step = _only(build_day_plan(_detail(from_battery_kwh=values)), "use_battery")
    assert step.hours == 2
    assert step.kwh == pytest.approx(11.1)


def test_an_hour_at_nine_percent_of_the_days_peak_is_dropped():
    values = _hours({12: 10.0, 13: 0.9})  # 9% -- noise, not a plan step
    step = _only(build_day_plan(_detail(from_battery_kwh=values)), "use_battery")
    assert step.hours == 1
    assert step.kwh == pytest.approx(10.0)


def test_the_absolute_floor_drops_a_day_that_only_ever_moved_a_trickle():
    """A purely relative threshold would keep an hour that is 100% of its
    own peak even if that peak is 0.05 kWh."""
    plan = build_day_plan(_detail(from_battery_kwh=_hours({12: 0.05})))
    assert plan.steps == ()
    assert "use_battery" in plan.absent


def test_the_threshold_is_per_action_not_day_wide():
    """Measured on the committed year: a day-wide threshold let a large
    sell peak raise the bar until a real grid charge vanished, on 3 days.
    Both actions must be judged on their own scale."""
    plan = build_day_plan(_detail(
        sold_kwh=_hours({13: 40.0, 14: 40.0}),        # a big day for selling
        grid_charge_kwh=_hours({3: 0.6, 4: 0.6}),     # small, but real
    ))
    assert _only(plan, "grid_charge").kwh == pytest.approx(1.2)
    assert _only(plan, "sell").kwh == pytest.approx(80.0)


# -- run merging ---------------------------------------------------------------

def test_contiguous_hours_merge_into_one_range():
    values = _hours({17: 2.0, 18: 2.0, 19: 2.0, 20: 2.0})
    step = _only(build_day_plan(_detail(from_battery_kwh=values)), "use_battery")
    assert step.hours == 4
    assert f"{step.start:%H:%M}" == "17:00"
    assert f"{step.end:%H:%M}" == "21:00"  # exclusive


def test_a_single_quiet_hour_does_not_break_a_run():
    assert MAX_GAP_HOURS == 1
    values = _hours({17: 2.0, 18: 2.0, 20: 2.0})  # 19 is quiet
    step = _only(build_day_plan(_detail(from_battery_kwh=values)), "use_battery")
    assert step.hours == 4  # 17,18,19,20 -- the quiet hour is inside the range
    assert step.kwh == pytest.approx(6.0)


def test_a_two_hour_gap_does_break_a_run():
    """Measured: tolerating 2 merged two sell runs across an intervening
    curtail step, which then reads as selling and discarding at once."""
    values = _hours({10: 2.0, 13: 5.0, 14: 5.0})
    step = _only(build_day_plan(_detail(from_battery_kwh=values)), "use_battery")
    assert step.kwh == pytest.approx(10.0)  # the later, bigger run
    assert step.extra_hours == 1
    assert step.extra_kwh == pytest.approx(2.0)


def test_only_the_biggest_run_is_named_and_the_rest_is_reported_as_extra():
    values = _hours({6: 1.0, 9: 3.0, 10: 3.0, 14: 0.5})
    step = _only(build_day_plan(_detail(from_battery_kwh=values)), "use_battery")
    assert step.kwh == pytest.approx(6.0)
    # nothing is lost: the named run plus the extra equals the day
    assert step.kwh + step.extra_kwh == pytest.approx(sum(values))


def test_steps_come_back_in_reading_order():
    plan = build_day_plan(_detail(
        from_battery_kwh=_hours({18: 3.0}),
        grid_charge_kwh=_hours({3: 3.0}),
        sold_kwh=_hours({13: 3.0}),
    ))
    assert [s.action for s in plan.steps] == ["grid_charge", "use_battery", "sell"]


# -- money ---------------------------------------------------------------------

def test_grid_charging_costs_money_and_is_signed_positive():
    step = _only(build_day_plan(_detail(grid_charge_kwh=_hours({3: 4.0}))), "grid_charge")
    assert step.sek == pytest.approx(4.0)  # 4 kWh x 1.0 buy


def test_running_the_house_off_the_battery_is_signed_negative():
    step = _only(build_day_plan(_detail(from_battery_kwh=_hours({18: 4.0}))), "use_battery")
    assert step.sek == pytest.approx(-4.0)  # avoided 4 kWh x 1.0 buy


def test_selling_earns_the_sell_price_not_the_buy_price():
    step = _only(build_day_plan(_detail(sold_kwh=_hours({13: 4.0}))), "sell")
    assert step.sek == pytest.approx(-2.0)  # 4 kWh x 0.5 sell, NOT 4.0


def test_storing_solar_books_no_money_in_that_hour():
    """It pays off later, when the battery discharges. Booking it here as
    well would count the same kWh twice."""
    step = _only(build_day_plan(_detail(to_battery_kwh=_hours({12: 5.0}))), "store_solar")
    assert step.sek == 0.0


def test_curtailed_power_books_no_money():
    step = _only(build_day_plan(_detail(curtailed_kwh=_hours({13: 5.0}))), "curtail")
    assert step.sek == 0.0


def test_step_money_reconciles_against_the_simulations_own_flows():
    """The test that replaced calc.window_cost. Every step's SEK must be
    re-derivable from the detail frame's realised flows times its realised
    prices -- so the plan can never invent money the simulation did not
    book, and can never price a window at a power the battery never ran
    at."""
    index = pd.date_range(pd.Timestamp("2026-11-10", tz=TZ), periods=24, freq="h", tz=TZ)
    frame = pd.DataFrame({
        "production_kwh": [max(0.0, 8.0 * (1 - ((h - 12) / 6) ** 2)) for h in range(24)],
        "consumption_kwh": [2.0] * 24,
        "SEK_per_kWh": [0.05] * 6 + [0.6] * 10 + [3.0] * 5 + [0.6] * 3,
    }, index=index)
    detail = simulate(frame, 10.0)
    plan = build_day_plan(detail)
    assert plan.steps, "fixture must actually produce steps or this proves nothing"

    for step in plan.steps:
        rows = detail.loc[step.start : step.end - pd.Timedelta(hours=1)]
        if step.action == "grid_charge":
            expected = (rows["grid_charge_kwh"] * rows["buy_price_sek_per_kwh"]).sum()
        elif step.action == "use_battery":
            expected = -(rows["from_battery_kwh"] * rows["buy_price_sek_per_kwh"]).sum()
        elif step.action == "sell":
            expected = -(rows["sold_kwh"] * rows["sell_price_sek_per_kwh"]).sum()
        else:
            expected = 0.0
        assert step.sek == pytest.approx(float(expected)), step.action


# -- hour labels and DST -------------------------------------------------------

def test_a_range_ending_at_midnight_reads_as_24_00():
    # 00:00 of the next day would read as the start of the day, not its end
    values = _hours({22: 2.0, 23: 2.0})
    step = _only(build_day_plan(_detail(from_battery_kwh=values)), "use_battery")
    assert format_hour_range(step) == "22:00–24:00 · 2 h"


def test_fall_back_night_four_real_hours_span_three_wall_clock_hours():
    """2025-10-26 has 02:00 twice. A run across it is four real hours but
    looks like three on a clock, and the hour count is what makes that
    visible instead of silently wrong."""
    index = pd.date_range(
        pd.Timestamp("2025-10-26", tz=TZ),
        pd.Timestamp("2025-10-27", tz=TZ), freq="h", tz=TZ, inclusive="left",
    )
    assert len(index) == 25
    frame = pd.DataFrame({c: [0.0] * 25 for c in FLOW_COLS}, index=index)
    frame["buy_price_sek_per_kwh"] = 1.0
    frame["sell_price_sek_per_kwh"] = 0.5
    frame.iloc[1:5, frame.columns.get_loc("from_battery_kwh")] = 2.0

    step = _only(build_day_plan(frame), "use_battery")
    assert step.hours == 4
    assert step.end - step.start == pd.Timedelta(hours=4)  # four REAL hours
    assert format_hour_range(step) == "01:00–04:00 · 4 h"   # three on the clock


def test_spring_forward_night_three_real_hours_span_four_wall_clock_hours():
    """2026-03-29 has no 02:00 at all -- the mirror image."""
    index = pd.date_range(
        pd.Timestamp("2026-03-29", tz=TZ),
        pd.Timestamp("2026-03-30", tz=TZ), freq="h", tz=TZ, inclusive="left",
    )
    assert len(index) == 23
    frame = pd.DataFrame({c: [0.0] * 23 for c in FLOW_COLS}, index=index)
    frame["buy_price_sek_per_kwh"] = 1.0
    frame["sell_price_sek_per_kwh"] = 0.5
    frame.iloc[1:4, frame.columns.get_loc("from_battery_kwh")] = 2.0

    step = _only(build_day_plan(frame), "use_battery")
    assert step.hours == 3
    assert step.end - step.start == pd.Timedelta(hours=3)
    assert format_hour_range(step) == "01:00–05:00 · 3 h"  # four on the clock


def test_describe_step_reads_as_a_sentence_with_money():
    step = _only(build_day_plan(_detail(from_battery_kwh=_hours({18: 4.0}))), "use_battery")
    line = describe_step(step)
    assert "18:00–19:00" in line
    assert "run the house off the battery" in line
    assert "avoids 4 SEK" in line


def test_describe_step_says_earns_for_selling_and_costs_for_grid_charging():
    sell = _only(build_day_plan(_detail(sold_kwh=_hours({13: 4.0}))), "sell")
    charge = _only(build_day_plan(_detail(grid_charge_kwh=_hours({3: 4.0}))), "grid_charge")
    assert "earns 2 SEK" in describe_step(sell)
    assert "costs 4 SEK" in describe_step(charge)


# -- real days from the committed cache (no network) ---------------------------

@lru_cache(maxsize=2)
def _cached_year(orientation_slug="south_t40", kwp=10.0, annual_kwh=20000.0):
    """Load the committed year once per session -- it is 1101 CSV files, and
    several tests below want it. Safe to share: simulate() copies its input."""
    def load(directory, column):
        frames = []
        for path in sorted(directory.glob("*.csv")):
            df = pd.read_csv(path, index_col=0, parse_dates=True)
            df.index = df.index.tz_convert(TZ)
            frames.append(df[[column]])
        out = pd.concat(frames).sort_index()
        return out[~out.index.duplicated(keep="first")][column]

    spot = load(CACHE / "prices" / "SE3", "SEK_per_kWh")
    irradiance = load(CACHE / "solar" / orientation_slug, "irradiance_w_m2")
    production = irradiance / 1000.0 * kwp * SYSTEM_LOSS_FACTOR
    frame, _ = build_frame(production, spot.to_frame("SEK_per_kWh"), annual_kwh)
    return frame


def _real_day_plan(day: date, capacity=10.0):
    frame = _cached_year()
    detail = simulate(frame, capacity)  # continuous, so the battery enters the day correctly
    surplus = (frame["production_kwh"] - frame["consumption_kwh"]).clip(lower=0)
    reasons = grid_charge_plan(buy_price(frame["SEK_per_kWh"]), surplus, capacity).reasons
    return build_day_plan(detail[detail.index.date == day], reasons.get(day))


@pytest.mark.parametrize("day", [date(2026, 10, 2)])
def test_a_real_grid_charging_day_produces_the_briefs_example_shape(day):
    """CLAUDE.md's example is "charge from the grid 02-05 ... use the
    battery 17-20": a cheap-hours charge followed by an expensive-hours
    discharge that is worth more than it cost."""
    plan = _real_day_plan(day)
    charge = _only(plan, "grid_charge")
    use = _only(plan, "use_battery")
    assert plan.grid_charge_reason == "charged"
    assert charge.sek > 0 and use.sek < 0
    assert abs(use.sek) > charge.sek  # it has to be worth doing
    assert charge.start < use.start   # and in that order


def test_a_real_midwinter_day_is_honest_about_doing_nothing():
    plan = _real_day_plan(date(2025, 12, 25))
    assert plan.steps == ()
    assert plan.grid_charge_reason in {"no_later_hours", "spread_too_small"}
    assert GRID_CHARGE_EXPLANATION[plan.grid_charge_reason]


def test_capacity_zero_reports_no_battery_but_still_sells():
    plan = _real_day_plan(date(2026, 6, 15), capacity=0.0)
    assert plan.grid_charge_reason == "no_battery"
    assert {s.action for s in plan.steps} <= {"sell", "curtail"}
    assert _only(plan, "sell").kwh > 0


def test_no_real_day_produces_an_unreadable_wall_of_steps():
    """The cap of one step per action is what keeps this true. Measured
    over the committed year: 2.5 steps a day on average, never above 4."""
    frame = _cached_year()
    detail = simulate(frame, 10.0)
    surplus = (frame["production_kwh"] - frame["consumption_kwh"]).clip(lower=0)
    reasons = grid_charge_plan(buy_price(frame["SEK_per_kWh"]), surplus, 10.0).reasons

    counts = []
    for day, rows in detail.groupby(detail.index.date):
        counts.append(len(build_day_plan(rows, reasons.get(day)).steps))
    assert max(counts) <= len(ACTION_ORDER)
    assert sum(counts) / len(counts) < 4
