"""Tests for src/solar.py -- Open-Meteo irradiance fetch, the production
formula, east-west averaging, and the cache fallback path.

Mirrors the mocked-response style of v1's test_weather.py; the fetch
tests never touch the network or the committed cache (they monkeypatch
requests.get and take cache_root=tmp_path from conftest.py).
"""

from datetime import date, datetime, timedelta, timezone

import pandas as pd
import requests

from src.cache import read_day_cache, write_day_cache
from src.config import PANEL_TILT_DEG
from src.solar import (
    IRRADIANCE_VAR,
    PRODUCTION_COLUMN,
    SOLAR_COLUMNS,
    _cache_key,
    _combine_azimuths,
    _parse_hourly,
    _slice_to_range,
    fetch_irradiance,
    production_kwh,
)


def _utc_times(start: datetime, count: int) -> list[str]:
    """Naive ISO strings in UTC -- exactly what Open-Meteo returns when
    asked for timezone=UTC."""
    return [(start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(count)]


def _payload(times: list[str], values: list) -> dict:
    return {"hourly": {"time": times, IRRADIANCE_VAR: values}}


def _irradiance_df(start_utc: datetime, values: list[float]) -> pd.DataFrame:
    index = pd.DatetimeIndex(
        [start_utc + timedelta(hours=i) for i in range(len(values))], tz=timezone.utc
    ).tz_convert("Europe/Stockholm")
    return pd.DataFrame({"irradiance_w_m2": values}, index=index)


# -- _parse_hourly -------------------------------------------------------------

def test_parse_hourly_converts_utc_to_stockholm():
    payload = _payload(_utc_times(datetime(2026, 6, 15, 10, 0), 2), [500.0, 600.0])
    df = _parse_hourly(payload)
    assert list(df.columns) == SOLAR_COLUMNS
    assert str(df.index.tzinfo) == "Europe/Stockholm"
    # 10:00 UTC in June is 12:00 Stockholm (CEST, +02:00)
    assert df.index[0].hour == 12
    assert df["irradiance_w_m2"].iloc[1] == 600.0


def test_parse_hourly_spring_forward_day_skips_the_nonexistent_hour():
    # Regression test for the trap found during the Sprint 5 spike:
    # asking Open-Meteo for timezone=Europe/Stockholm returns a literal
    # 2026-03-29T02:00, an hour that does not exist in Stockholm.
    # Parsing UTC and converting ourselves produces the real local jump
    # 01:00 CET -> 03:00 CEST instead.
    payload = _payload(_utc_times(datetime(2026, 3, 29, 0, 0), 3), [1.0, 2.0, 3.0])
    df = _parse_hourly(payload)
    local_hours = [ts.hour for ts in df.index]
    assert local_hours == [1, 3, 4]
    assert 2 not in local_hours


def test_parse_hourly_drops_nulls_rather_than_zeroing_them():
    payload = _payload(_utc_times(datetime(2026, 6, 15, 10, 0), 3), [500.0, None, 600.0])
    df = _parse_hourly(payload)
    assert len(df) == 2
    assert 0.0 not in df["irradiance_w_m2"].tolist()


def test_parse_hourly_empty_payload_returns_empty_frame():
    assert _parse_hourly({}).empty
    assert list(_parse_hourly({}).columns) == SOLAR_COLUMNS
    assert _parse_hourly(_payload([], [])).empty


# -- production_kwh ------------------------------------------------------------

def test_production_kwh_formula():
    df = _irradiance_df(datetime(2026, 6, 15, 10, 0, tzinfo=timezone.utc), [1000.0, 500.0])
    out = production_kwh(df, kwp=10.0, loss=0.85)
    # 1000 W/m2 is standard test conditions -> full rated output x loss
    assert out[PRODUCTION_COLUMN].iloc[0] == 10.0 * 0.85
    assert out[PRODUCTION_COLUMN].iloc[1] == 10.0 * 0.85 * 0.5


def test_production_kwh_zero_system_size_is_all_zero_not_an_error():
    df = _irradiance_df(datetime(2026, 6, 15, 10, 0, tzinfo=timezone.utc), [1000.0, 500.0])
    out = production_kwh(df, kwp=0.0)
    assert (out[PRODUCTION_COLUMN] == 0.0).all()


def test_production_kwh_night_hours_produce_nothing():
    df = _irradiance_df(datetime(2026, 1, 15, 0, 0, tzinfo=timezone.utc), [0.0, 0.0])
    out = production_kwh(df, kwp=10.0)
    assert (out[PRODUCTION_COLUMN] == 0.0).all()


def test_production_kwh_empty_frame_keeps_the_column():
    out = production_kwh(pd.DataFrame(columns=SOLAR_COLUMNS), kwp=10.0)
    assert out.empty
    assert PRODUCTION_COLUMN in out.columns


# -- east-west averaging / cache keying ----------------------------------------

def test_combine_azimuths_single_orientation_passes_through():
    df = _irradiance_df(datetime(2026, 6, 15, 10, 0, tzinfo=timezone.utc), [500.0])
    assert _combine_azimuths([df])["irradiance_w_m2"].iloc[0] == 500.0


def test_combine_azimuths_east_west_is_the_mean_of_both_surfaces():
    start = datetime(2026, 6, 15, 10, 0, tzinfo=timezone.utc)
    east = _irradiance_df(start, [800.0, 200.0])
    west = _irradiance_df(start, [200.0, 800.0])
    combined = _combine_azimuths([east, west])
    assert combined["irradiance_w_m2"].tolist() == [500.0, 500.0]


def test_combine_azimuths_empty_returns_empty():
    assert _combine_azimuths([]).empty


# -- _slice_to_range across DST ------------------------------------------------

def _three_days_around_spring_forward() -> pd.DataFrame:
    idx = pd.date_range(
        "2026-03-27 23:00", "2026-03-31 00:00", freq="h", tz="UTC"
    ).tz_convert("Europe/Stockholm")
    return pd.DataFrame({"irradiance_w_m2": range(len(idx))}, index=idx)


def test_slice_to_range_spring_forward_day_has_23_hours_on_one_date():
    # Regression test: Timedelta(days=1) is 24 *absolute* hours, so the
    # 23-hour day returned 24 rows spilling into 2026-03-30.
    df = _three_days_around_spring_forward()
    day = _slice_to_range(df, date(2026, 3, 29), date(2026, 3, 29))
    assert len(day) == 23
    assert {ts.date() for ts in day.index} == {date(2026, 3, 29)}


def test_slice_to_range_consecutive_days_do_not_overlap():
    # The same bug duplicated 2026-03-30 00:00 when days were concatenated,
    # which would have corrupted any year-long frame.
    df = _three_days_around_spring_forward()
    days = [
        _slice_to_range(df, d, d)
        for d in (date(2026, 3, 28), date(2026, 3, 29), date(2026, 3, 30))
    ]
    combined = pd.concat(days)
    assert not combined.index.has_duplicates
    assert [len(d) for d in days] == [24, 23, 24]


def test_cache_key_separates_orientations_and_encodes_tilt():
    south, east_west = _cache_key("South"), _cache_key("East–West")
    assert south != east_west
    assert str(PANEL_TILT_DEG) in south


# -- fetch_irradiance: write-through, fallback, failure -------------------------

class _FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _successful_get(payload):
    def fake_get(url, params=None, timeout=None):
        return _FakeResponse(200, payload)

    return fake_get


def test_fetch_irradiance_writes_through_to_cache(monkeypatch, cache_root):
    day = date(2026, 6, 15)
    # cover the padded request window; the fetcher slices back to the local day
    payload = _payload(_utc_times(datetime(2026, 6, 14, 0, 0), 72), [100.0] * 72)
    monkeypatch.setattr(requests, "get", _successful_get(payload))

    result = fetch_irradiance(day, day, "South", cache_root=cache_root)

    assert result.failed_days == []
    assert result.fallback_days == []
    assert len(result.df) == 24  # one Stockholm day
    cached = read_day_cache(cache_root, "solar", _cache_key("South"), day, SOLAR_COLUMNS)
    assert cached is not None and len(cached) == 24


def test_fetch_irradiance_falls_back_to_cache_on_failure(monkeypatch, cache_root):
    day = date(2026, 6, 15)
    seeded = _irradiance_df(datetime(2026, 6, 14, 22, 0, tzinfo=timezone.utc), [42.0] * 24)
    write_day_cache(cache_root, "solar", _cache_key("South"), day, seeded)

    monkeypatch.setattr(requests, "get", lambda url, params=None, timeout=None: _FakeResponse(503))
    monkeypatch.setattr("src.solar.time.sleep", lambda s: None)

    result = fetch_irradiance(day, day, "South", cache_root=cache_root)

    assert result.fallback_days == [day]
    assert result.failed_days == []
    assert len(result.df) == 24


def test_fetch_irradiance_failure_without_cache_reports_failed_days(monkeypatch, cache_root):
    day = date(2026, 6, 15)
    monkeypatch.setattr(requests, "get", lambda url, params=None, timeout=None: _FakeResponse(503))
    monkeypatch.setattr("src.solar.time.sleep", lambda s: None)

    result = fetch_irradiance(day, day, "South", cache_root=cache_root)  # must not raise

    assert result.failed_days == [day]
    assert result.fallback_days == []
    assert result.df.empty


def test_fetch_irradiance_south_cache_is_not_served_for_east_west(monkeypatch, cache_root):
    # The orientation-keyed cache guard: a seeded South snapshot must not
    # satisfy an East-West request that fails.
    day = date(2026, 6, 15)
    seeded = _irradiance_df(datetime(2026, 6, 14, 22, 0, tzinfo=timezone.utc), [42.0] * 24)
    write_day_cache(cache_root, "solar", _cache_key("South"), day, seeded)

    monkeypatch.setattr(requests, "get", lambda url, params=None, timeout=None: _FakeResponse(503))
    monkeypatch.setattr("src.solar.time.sleep", lambda s: None)

    result = fetch_irradiance(day, day, "East–West", cache_root=cache_root)

    assert result.fallback_days == []
    assert result.failed_days == [day]
