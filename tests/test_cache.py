"""Tests for src/cache.py's day-granularity CSV cache."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from src.cache import cache_path, read_day_cache, write_day_cache

STOCKHOLM = ZoneInfo("Europe/Stockholm")


def _hourly_df(utc_start: datetime, count: int, columns: list[str]) -> pd.DataFrame:
    index = pd.DatetimeIndex(
        [utc_start + timedelta(hours=i) for i in range(count)], tz=timezone.utc
    ).tz_convert("Europe/Stockholm")
    data = {col: [float(i) + 0.1 * j for i in range(count)] for j, col in enumerate(columns)}
    return pd.DataFrame(data, index=index)


def test_write_then_read_round_trip(cache_root):
    columns = ["SEK_per_kWh", "EUR_per_kWh", "EXR"]
    day = date(2026, 8, 15)
    df = _hourly_df(datetime(2026, 8, 14, 22, 0, tzinfo=timezone.utc), 24, columns)

    write_day_cache(cache_root, "prices", "SE3", day, df)
    result = read_day_cache(cache_root, "prices", "SE3", day, columns)

    assert result is not None
    assert len(result) == 24
    assert str(result.index.tzinfo) == "Europe/Stockholm"
    pd.testing.assert_frame_equal(result, df[columns], check_freq=False)


def test_write_then_read_round_trip_dst_transition_day(cache_root):
    # 2025-10-26 fall-back: 25 real hours once resampled to hourly.
    columns = ["SEK_per_kWh", "EUR_per_kWh", "EXR"]
    day = date(2025, 10, 26)
    df = _hourly_df(datetime(2025, 10, 25, 22, 0, tzinfo=timezone.utc), 25, columns)

    write_day_cache(cache_root, "prices", "SE3", day, df)
    result = read_day_cache(cache_root, "prices", "SE3", day, columns)

    assert result is not None
    assert len(result) == 25


def test_read_missing_file_returns_none(cache_root):
    result = read_day_cache(cache_root, "prices", "SE3", date(2026, 1, 1), ["SEK_per_kWh"])
    assert result is None


def test_read_corrupt_file_returns_none(cache_root):
    path = cache_path(cache_root, "prices", "SE3", date(2026, 1, 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("this is not valid csv data for our schema\x00\x01")

    result = read_day_cache(cache_root, "prices", "SE3", date(2026, 1, 1), ["SEK_per_kWh"])
    assert result is None


def test_write_failure_is_swallowed(monkeypatch, cache_root):
    def fail_mkdir(self, parents=False, exist_ok=False):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(Path, "mkdir", fail_mkdir)

    df = _hourly_df(datetime(2026, 1, 1, tzinfo=timezone.utc), 1, ["SEK_per_kWh"])
    write_day_cache(cache_root, "prices", "SE3", date(2026, 1, 1), df)  # must not raise
