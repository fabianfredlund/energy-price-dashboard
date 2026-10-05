"""Tests for src/consumption.py -- the villa load-profile assumption.

The important property is the normalisation anchor: a full year must land
on the advisor's entered annual kWh, while a *shorter* period must draw
its seasonally-correct share rather than the whole year's electricity.
"""

import pandas as pd
import pytest

from src.consumption import (
    DAILY_SHAPE,
    MONTHLY_FACTORS,
    consumption_profile,
    hourly_weights,
)


def _hours(start: str, periods: int) -> pd.DatetimeIndex:
    return pd.date_range(start, periods=periods, freq="h", tz="Europe/Stockholm")


def _year_2026() -> pd.DatetimeIndex:
    return pd.date_range(
        "2026-01-01", "2027-01-01", freq="h", tz="Europe/Stockholm", inclusive="left"
    )


# -- shape sanity --------------------------------------------------------------

def test_daily_shape_has_24_values_averaging_one():
    # approx, not ==: these are decimal constants, and float addition of
    # twelve/twenty-four of them lands a few ulps off an exact 1.0 mean
    assert len(DAILY_SHAPE) == 24
    assert sum(DAILY_SHAPE) / 24 == pytest.approx(1.0)


def test_monthly_factors_have_12_values_averaging_one():
    assert len(MONTHLY_FACTORS) == 12
    assert sum(MONTHLY_FACTORS) / 12 == pytest.approx(1.0)


def test_daily_shape_peaks_in_the_morning_and_evening():
    # the shape is the whole point: these peaks are what solar misses
    assert DAILY_SHAPE[7] > DAILY_SHAPE[12]  # breakfast beats midday
    assert DAILY_SHAPE[18] > DAILY_SHAPE[12]  # evening beats midday
    assert DAILY_SHAPE[3] == min(DAILY_SHAPE)  # night trough


def test_winter_months_are_heavier_than_summer_months():
    assert MONTHLY_FACTORS[0] > MONTHLY_FACTORS[6]  # Jan > Jul
    assert MONTHLY_FACTORS[6] == min(MONTHLY_FACTORS)


# -- hourly_weights ------------------------------------------------------------

def test_hourly_weights_is_daily_shape_times_monthly_factor():
    idx = _hours("2026-01-15 07:00", 1)
    assert hourly_weights(idx).iloc[0] == DAILY_SHAPE[7] * MONTHLY_FACTORS[0]


def test_hourly_weights_empty_index_returns_empty():
    assert hourly_weights(_hours("2026-01-01", 0)).empty


# -- consumption_profile -------------------------------------------------------

def test_full_year_sums_to_the_entered_annual_kwh():
    # not exact: the DST hours March loses and October gains sit in months
    # with different factors, so allow a fraction of a percent
    total = consumption_profile(_year_2026(), 20000.0).sum()
    assert total == pytest.approx(20000.0, rel=0.005)


def test_a_winter_week_draws_more_than_a_summer_week():
    jan = consumption_profile(_hours("2026-01-12", 168), 20000.0).sum()
    jul = consumption_profile(_hours("2026-07-13", 168), 20000.0).sum()
    assert jan > jul * 2  # heating dominates


def test_a_short_period_is_not_billed_a_whole_year():
    # the bug the reference-year anchor exists to prevent: scaling to the
    # index sum would make any period, however short, total annual_kwh
    week = consumption_profile(_hours("2026-01-12", 168), 20000.0).sum()
    assert week < 1000.0
    # and it should be in the right ballpark for a heavy winter week
    assert week > 300.0


def test_single_day_is_roughly_a_days_worth():
    day = consumption_profile(_hours("2026-04-15", 24), 20000.0).sum()
    assert 20000.0 / 365 * 0.5 < day < 20000.0 / 365 * 1.5


def test_zero_annual_consumption_is_all_zero_not_an_error():
    assert (consumption_profile(_hours("2026-01-01", 24), 0.0) == 0.0).all()


def test_empty_index_returns_empty_series():
    assert consumption_profile(_hours("2026-01-01", 0), 20000.0).empty


def test_profile_is_never_negative():
    assert (consumption_profile(_year_2026(), 20000.0) >= 0).all()
