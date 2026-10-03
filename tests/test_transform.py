"""Tests for src/transform.py -- colour categorization and daily
aggregation, including the gotchas caught during Sprint 2 planning (pd.cut
breaking on identical prices, resample().mean() breaking on a non-numeric
column, resample("1D") inserting a phantom row for a fully-missing day)."""

from datetime import datetime, timedelta, timezone

import pandas as pd

from src.transform import (
    categorize_by_price,
    hourly_weekday_means,
    price_kpis,
    resample_daily_mean,
    typical_hour_of_day,
)


def _hourly_price_df(utc_start: datetime, prices: list[float]) -> pd.DataFrame:
    index = pd.DatetimeIndex(
        [utc_start + timedelta(hours=i) for i in range(len(prices))], tz=timezone.utc
    ).tz_convert("Europe/Stockholm")
    return pd.DataFrame({"ore_per_kWh": prices}, index=index)


# -- categorize_by_price ------------------------------------------------------

def test_categorize_by_price_empty_dataframe_returns_category_column():
    df = pd.DataFrame({"ore_per_kWh": []})
    result = categorize_by_price(df, "ore_per_kWh")
    assert len(result) == 0
    assert "category" in result.columns


def test_categorize_by_price_single_row_is_cheap():
    df = _hourly_price_df(datetime(2026, 1, 1, tzinfo=timezone.utc), [42.0])
    result = categorize_by_price(df, "ore_per_kWh")
    assert result["category"].tolist() == ["Cheap"]


def test_categorize_by_price_all_identical_prices_are_all_cheap():
    df = _hourly_price_df(datetime(2026, 1, 1, tzinfo=timezone.utc), [50.0] * 10)
    result = categorize_by_price(df, "ore_per_kWh")  # must not raise (pd.cut would)
    assert (result["category"] == "Cheap").all()


def test_categorize_by_price_exercises_all_four_categories():
    prices = [float(i) for i in range(1, 11)]  # 1..10
    df = _hourly_price_df(datetime(2026, 1, 1, tzinfo=timezone.utc), prices)
    result = categorize_by_price(df, "ore_per_kWh")
    assert set(result["category"]) == {"Cheap", "Normal", "Expensive", "Spike"}
    # cheapest and most expensive land at the expected ends
    assert result["category"].iloc[0] == "Cheap"
    assert result["category"].iloc[-1] == "Spike"


def test_categorize_by_price_boundary_is_inclusive_at_each_cutoff():
    prices = [float(i) for i in range(1, 11)]
    df = _hourly_price_df(datetime(2026, 1, 1, tzinfo=timezone.utc), prices)
    p33, p67, p90 = df["ore_per_kWh"].quantile([0.33, 0.67, 0.90])
    result = categorize_by_price(df, "ore_per_kWh")
    for price, category in zip(prices, result["category"]):
        if price <= p33:
            assert category == "Cheap"
        elif price <= p67:
            assert category == "Normal"
        elif price <= p90:
            assert category == "Expensive"
        else:
            assert category == "Spike"


def test_categorize_by_price_works_on_daily_aggregated_rows():
    # daily means, not hourly -- the function shouldn't care about granularity
    index = pd.date_range("2026-01-01", periods=5, freq="D", tz="Europe/Stockholm")
    df = pd.DataFrame({"ore_per_kWh": [10.0, 20.0, 30.0, 40.0, 100.0]}, index=index)
    result = categorize_by_price(df, "ore_per_kWh")
    assert result["category"].iloc[-1] == "Spike"
    assert result["category"].iloc[0] == "Cheap"


def test_categorize_by_price_preserves_other_columns_and_row_count():
    df = _hourly_price_df(datetime(2026, 1, 1, tzinfo=timezone.utc), [1.0, 2.0, 3.0])
    df["EXR"] = 11.0
    result = categorize_by_price(df, "ore_per_kWh")
    assert len(result) == len(df)
    assert "EXR" in result.columns
    assert list(result["EXR"]) == [11.0, 11.0, 11.0]


# -- resample_daily_mean -------------------------------------------------------

def test_resample_daily_mean_basic_two_full_days():
    # Stockholm midnight on 2026-01-01 (winter, +01:00) == 2025-12-31 23:00 UTC
    # -- not literal UTC midnight, the same offset test_prices.py's fixtures
    # already account for.
    df = _hourly_price_df(datetime(2025, 12, 31, 23, 0, tzinfo=timezone.utc), [10.0] * 24 + [20.0] * 24)
    result = resample_daily_mean(df, columns=["ore_per_kWh"])
    assert len(result) == 2
    assert result["ore_per_kWh"].tolist() == [10.0, 20.0]


def test_resample_daily_mean_drops_fully_missing_day_gap():
    # day 1 present, day 2 fully absent (a confirmed-404 gap), day 3 present
    day1 = _hourly_price_df(datetime(2025, 12, 31, 23, 0, tzinfo=timezone.utc), [10.0] * 24)
    day3 = _hourly_price_df(datetime(2026, 1, 2, 23, 0, tzinfo=timezone.utc), [30.0] * 24)
    df = pd.concat([day1, day3])
    result = resample_daily_mean(df, columns=["ore_per_kWh"])
    assert len(result) == 2  # not 3 -- no phantom NaN row for the missing middle day
    assert result["ore_per_kWh"].tolist() == [10.0, 30.0]


def test_resample_daily_mean_keeps_partial_day_mean():
    # only 12 of 24 hours present for the one day
    df = _hourly_price_df(datetime(2025, 12, 31, 23, 0, tzinfo=timezone.utc), [10.0] * 12)
    result = resample_daily_mean(df, columns=["ore_per_kWh"])
    assert len(result) == 1
    assert result["ore_per_kWh"].iloc[0] == 10.0


def test_resample_daily_mean_handles_dst_transition_day():
    # 2025-10-26 fall-back: 25 real hours once resampled hourly upstream;
    # resampling to daily must still collapse it to exactly one row.
    df = _hourly_price_df(datetime(2025, 10, 25, 22, 0, tzinfo=timezone.utc), [15.0] * 25)
    result = resample_daily_mean(df, columns=["ore_per_kWh"])
    assert len(result) == 1


def test_resample_daily_mean_empty_input_returns_empty():
    df = pd.DataFrame({"ore_per_kWh": []})
    result = resample_daily_mean(df, columns=["ore_per_kWh"])
    assert len(result) == 0


def test_resample_daily_mean_requires_explicit_columns_for_non_numeric_frame():
    # regression test: resample().mean() on a frame including a string
    # column (e.g. weather_df's `quality`) raises unless `columns` pins it
    # down to the numeric column(s) only.
    index = pd.date_range("2026-01-01", periods=24, freq="h", tz="Europe/Stockholm")
    df = pd.DataFrame({"temperature_c": [1.0] * 24, "quality": ["G"] * 24}, index=index)
    result = resample_daily_mean(df, columns=["temperature_c"])  # must not raise
    assert len(result) == 1
    assert list(result.columns) == ["temperature_c"]


# -- price_kpis ------------------------------------------------------

def test_price_kpis_empty_returns_none():
    df = pd.DataFrame({"ore_per_kWh": []})
    assert price_kpis(df, "ore_per_kWh") is None


def test_price_kpis_single_row():
    df = _hourly_price_df(datetime(2026, 1, 14, 23, 0, tzinfo=timezone.utc), [42.0])
    kpis = price_kpis(df, "ore_per_kWh")
    assert kpis.avg_price == 42.0
    assert kpis.cheapest_price == 42.0
    assert kpis.priciest_price == 42.0
    assert kpis.daily_spread == 0.0


def test_price_kpis_multi_day_known_values():
    # Stockholm midnight on 2026-01-14 (winter, +01:00) == 2026-01-13 23:00 UTC
    day1 = [10.0] * 24  # flat day: max - min = 0
    day2 = [5.0] + [15.0] * 22 + [25.0]  # max=25, min=5 -> spread 20
    prices = day1 + day2
    df = _hourly_price_df(datetime(2026, 1, 13, 23, 0, tzinfo=timezone.utc), prices)
    kpis = price_kpis(df, "ore_per_kWh")
    assert kpis.avg_price == sum(prices) / len(prices)
    assert kpis.cheapest_price == 5.0
    assert kpis.priciest_price == 25.0
    assert kpis.daily_spread == 10.0  # mean of [0, 20]


# -- hourly_weekday_means ------------------------------------------------------

def test_hourly_weekday_means_empty_returns_empty_with_columns():
    df = pd.DataFrame({"ore_per_kWh": []})
    result = hourly_weekday_means(df, "ore_per_kWh")
    assert list(result.columns) == ["weekday", "hour", "ore_per_kWh"]
    assert len(result) == 0


def test_hourly_weekday_means_column_names_and_feeds_categorize_by_price():
    df = _hourly_price_df(
        datetime(2026, 1, 13, 23, 0, tzinfo=timezone.utc), [10.0] * 24 + [20.0] * 24
    )
    result = hourly_weekday_means(df, "ore_per_kWh")
    assert list(result.columns) == ["weekday", "hour", "ore_per_kWh"]
    assert len(result) == 48  # two distinct weekdays x 24 distinct hours, no overlap

    categorized = categorize_by_price(result, "ore_per_kWh")  # must not raise
    assert "category" in categorized.columns


# -- typical_hour_of_day ------------------------------------------------------

def test_typical_hour_of_day_empty_returns_empty_series():
    df = pd.DataFrame({"ore_per_kWh": []})
    result = typical_hour_of_day(df, "ore_per_kWh")
    assert len(result) == 0


def test_typical_hour_of_day_multi_day_known_means():
    day1 = [10.0] * 24
    day2 = [30.0] * 24
    df = _hourly_price_df(datetime(2026, 1, 13, 23, 0, tzinfo=timezone.utc), day1 + day2)
    result = typical_hour_of_day(df, "ore_per_kWh")
    assert len(result) == 24
    assert list(result.index) == list(range(24))
    assert (result == 20.0).all()  # each hour-of-day: mean(10, 30) == 20
