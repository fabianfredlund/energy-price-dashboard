"""Tests for src/transform.py -- colour categorization and daily
aggregation, including the gotchas caught during Sprint 2 planning (pd.cut
breaking on identical prices, resample().mean() breaking on a non-numeric
column, resample("1D") inserting a phantom row for a fully-missing day)."""

from datetime import datetime, timedelta, timezone

import pandas as pd

from src.transform import (
    categorize_by_price,
    hourly_month_means,
    price_kpis,
    production_split,
    resample_daily_mean,
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
    # column raises unless `columns` pins it down to the numeric one(s).
    index = pd.date_range("2026-01-01", periods=24, freq="h", tz="Europe/Stockholm")
    df = pd.DataFrame({"irradiance_w_m2": [1.0] * 24, "quality": ["G"] * 24}, index=index)
    result = resample_daily_mean(df, columns=["irradiance_w_m2"])  # must not raise
    assert len(result) == 1
    assert list(result.columns) == ["irradiance_w_m2"]


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


# -- hourly_month_means --------------------------------------------------------

def test_hourly_month_means_empty_returns_empty_with_columns():
    df = pd.DataFrame({"ore_per_kWh": []})
    result = hourly_month_means(df, "ore_per_kWh")
    assert list(result.columns) == ["month", "hour", "ore_per_kWh"]
    assert len(result) == 0


def test_hourly_month_means_column_names_and_feeds_categorize_by_price():
    # the .rename() gotcha: grouping on the Index objects without renaming
    # them yields level_0/level_1 and the pivot below would KeyError
    #
    # 22:00 UTC on the 30th, not 23:00 on the 31st: Stockholm winter
    # midnight is UTC 23:00 the *previous* day, so a 31 Jan 23:00 UTC start
    # puts all 48 hours inside February and the fixture spans one month.
    df = _hourly_price_df(
        datetime(2026, 1, 30, 23, 0, tzinfo=timezone.utc), [10.0] * 24 + [20.0] * 24
    )
    result = hourly_month_means(df, "ore_per_kWh")
    assert set(result["month"]) == {1, 2}
    assert list(result.columns) == ["month", "hour", "ore_per_kWh"]
    assert len(result) == 48  # Jan and Feb x 24 distinct hours, no overlap

    categorized = categorize_by_price(result, "ore_per_kWh")  # must not raise
    assert "category" in categorized.columns


def test_hourly_month_means_averages_the_same_hour_across_days_of_a_month():
    # two consecutive January days at different prices: each (1, hour)
    # cell is the mean of the two
    df = _hourly_price_df(
        datetime(2026, 1, 13, 23, 0, tzinfo=timezone.utc), [10.0] * 24 + [30.0] * 24
    )
    result = hourly_month_means(df, "ore_per_kWh")
    assert len(result) == 24  # one month x 24 hours
    assert (result["month"] == 1).all()
    assert (result["ore_per_kWh"] == 20.0).all()


def test_hourly_month_means_full_year_pivots_to_a_complete_12x24_grid():
    # the real shape the heatmap gets: every cell populated, so no NaN
    # gaps appear in the rendered grid
    index = pd.date_range(
        "2026-01-01", "2027-01-01", freq="h", tz="Europe/Stockholm", inclusive="left"
    )
    df = pd.DataFrame({"ore_per_kWh": range(len(index))}, index=index, dtype="float64")
    result = hourly_month_means(df, "ore_per_kWh")
    assert len(result) == 288

    grid = result.pivot(index="month", columns="hour", values="ore_per_kWh").reindex(
        index=range(1, 13), columns=range(24)
    )
    assert grid.shape == (12, 24)
    assert grid.isna().sum().sum() == 0


def test_hourly_month_means_handles_the_25_hour_fall_back_day():
    # 2025-10-26 has local 02:00 twice. Grouping by hour must average both
    # readings rather than raise or drop one.
    df = _hourly_price_df(
        datetime(2025, 10, 25, 22, 0, tzinfo=timezone.utc),
        [0.0, 0.0, 10.0, 30.0] + [0.0] * 21,  # positions 2 and 3 are both local 02:00
    )
    assert len(df) == 25
    assert (df.index.hour == 2).sum() == 2  # the duplicated wall-clock hour

    result = hourly_month_means(df, "ore_per_kWh")
    assert len(result) == 24  # 25 rows collapse to 24 distinct hours
    hour_2 = result.loc[result["hour"] == 2, "ore_per_kWh"]
    assert hour_2.iloc[0] == 20.0  # mean(10, 30), both 02:00 readings


# -- production_split ----------------------------------------------------------

def _detail(own, batt, sold, curtailed) -> pd.DataFrame:
    return pd.DataFrame({
        "own_use_kwh": own,
        "to_battery_kwh": batt,
        "sold_kwh": sold,
        "curtailed_kwh": curtailed,
    })


def test_production_split_empty_detail_returns_four_zeros():
    result = production_split(pd.DataFrame())
    assert list(result.index) == ["Own use", "To battery", "Sold", "Curtailed"]
    assert (result == 0.0).all()


def test_production_split_sums_each_destination_in_value_order():
    result = production_split(_detail([1.0, 2.0], [0.5, 0.5], [3.0, 1.0], [0.0, 0.25]))
    assert list(result.index) == ["Own use", "To battery", "Sold", "Curtailed"]
    assert result["Own use"] == 3.0
    assert result["To battery"] == 1.0
    assert result["Sold"] == 4.0
    assert result["Curtailed"] == 0.25


def test_production_split_total_equals_production_so_the_donut_is_part_to_whole():
    # the donut labels its centre with this total, so it must equal what
    # battery.py's production-side invariant says was produced
    detail = _detail([1.0, 2.0], [0.5, 0.5], [3.0, 1.0], [0.0, 0.25])
    detail["production_kwh"] = (
        detail["own_use_kwh"] + detail["to_battery_kwh"]
        + detail["sold_kwh"] + detail["curtailed_kwh"]
    )
    assert production_split(detail).sum() == detail["production_kwh"].sum()


def test_production_split_zero_production_is_all_zero_not_an_error():
    # a winter week with no sun: a legitimate result, not a missing value
    result = production_split(_detail([0.0] * 3, [0.0] * 3, [0.0] * 3, [0.0] * 3))
    assert (result == 0.0).all()
    assert result.sum() == 0.0
