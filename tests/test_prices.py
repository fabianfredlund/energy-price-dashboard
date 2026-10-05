"""Smoke tests for src/prices.py -- locking in the DST-offset and
404-vs-failed behavior discovered by trial and error against the live
API during Sprint 0 (see SPRINTLOG.md).

The DST-transition fixtures are built by walking real, evenly-spaced UTC
instants and converting each to Europe/Stockholm for display (via
zoneinfo, using the system's real tz database) -- the same construction
the real API itself uses, confirmed by fetching 2025-10-26 and 2026-03-29
live: a repeated local hour on fall-back, a skipped one on spring-forward.
"""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
import requests

from src.cache import read_day_cache, write_day_cache
from src.prices import (
    PRICE_COLUMNS,
    _expected_hours,
    _fetch_day,
    _parse_day,
    fetch_prices,
)

STOCKHOLM = ZoneInfo("Europe/Stockholm")

# Every fetch_prices test pins `today` explicitly. Two reasons: a day
# before today is now served straight from the cache without touching the
# API, which changes what these tests are asserting; and their fixture
# dates are "in the past" only because of the wall clock, so without this
# they would quietly change behaviour as time passes.
TEST_TODAY = date(2026, 1, 1)


def _quarter_hour_records(utc_start: datetime, count: int) -> list[dict]:
    records = []
    for i in range(count):
        start_utc = utc_start + timedelta(minutes=15 * i)
        end_utc = start_utc + timedelta(minutes=15)
        records.append(
            {
                "SEK_per_kWh": round(0.5 + i * 0.001, 5),
                "EUR_per_kWh": round(0.05 + i * 0.0001, 5),
                "EXR": 11.0,
                "time_start": start_utc.astimezone(STOCKHOLM).isoformat(),
                "time_end": end_utc.astimezone(STOCKHOLM).isoformat(),
            }
        )
    return records


def _hourly_records(utc_start: datetime, count: int) -> list[dict]:
    records = []
    for i in range(count):
        start_utc = utc_start + timedelta(hours=i)
        end_utc = start_utc + timedelta(hours=1)
        records.append(
            {
                "SEK_per_kWh": round(0.5 + i * 0.01, 5),
                "EUR_per_kWh": round(0.05 + i * 0.001, 5),
                "EXR": 11.0,
                "time_start": start_utc.astimezone(STOCKHOLM).isoformat(),
                "time_end": end_utc.astimezone(STOCKHOLM).isoformat(),
            }
        )
    return records


def test_parse_day_resamples_96_quarter_hours_to_24_hourly_rows():
    utc_start = datetime(2026, 7, 14, 22, 0, tzinfo=timezone.utc)  # summer, ordinary day
    df = _parse_day(_quarter_hour_records(utc_start, 96))
    assert len(df) == 24


def test_parse_day_handles_24_hourly_entries_unchanged():
    utc_start = datetime(2026, 1, 14, 23, 0, tzinfo=timezone.utc)  # winter, ordinary day
    df = _parse_day(_hourly_records(utc_start, 24))
    assert len(df) == 24


def test_timestamps_preserve_seasonal_offset():
    winter = _parse_day(_hourly_records(datetime(2026, 1, 14, 23, 0, tzinfo=timezone.utc), 1))
    summer = _parse_day(_quarter_hour_records(datetime(2026, 7, 14, 22, 0, tzinfo=timezone.utc), 4))

    assert winter.index[0].tz_convert("UTC") == datetime(2026, 1, 14, 23, 0, tzinfo=timezone.utc)
    assert str(winter.index[0].tzinfo) == "Europe/Stockholm"
    assert winter.index[0].utcoffset() == timedelta(hours=1)

    assert summer.index[0].tz_convert("UTC") == datetime(2026, 7, 14, 22, 0, tzinfo=timezone.utc)
    assert summer.index[0].utcoffset() == timedelta(hours=2)


def test_parse_day_fall_back_dst_transition_2025_10_26():
    # 2025-10-26T00:00:00+02:00 local == 2025-10-25T22:00:00Z. The day has
    # 25 real hours (a repeated local 02:00 hour) -> 100 quarter-hour
    # entries at 15-min resolution (confirmed live: the real API returns
    # exactly 100 entries for this date).
    utc_start = datetime(2025, 10, 25, 22, 0, tzinfo=timezone.utc)
    df = _parse_day(_quarter_hour_records(utc_start, 100))
    assert len(df) == 25


def test_parse_day_spring_forward_dst_transition_2026_03_29():
    # 2026-03-29T00:00:00+01:00 local == 2026-03-28T23:00:00Z. The day has
    # 23 real hours (a skipped local 02:00-03:00 hour) -> 92 quarter-hour
    # entries (confirmed live: the real API returns exactly 92 entries).
    utc_start = datetime(2026, 3, 28, 23, 0, tzinfo=timezone.utc)
    df = _parse_day(_quarter_hour_records(utc_start, 92))
    assert len(df) == 23


class _FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_fetch_day_returns_confirmed_no_data_on_404(monkeypatch):
    calls = []

    def fake_get(url, timeout):
        calls.append(url)
        return _FakeResponse(404)

    monkeypatch.setattr(requests, "get", fake_get)
    records, failed = _fetch_day(datetime(2099, 1, 1).date(), "SE3")

    assert records is None
    assert failed is False
    assert len(calls) == 1  # a confirmed 404 is not retried


def test_fetch_day_returns_failed_after_exhausting_retries_on_timeout(monkeypatch):
    calls = []

    def fake_get(url, timeout):
        calls.append(url)
        raise requests.Timeout("simulated timeout")

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr("src.prices.time.sleep", lambda seconds: None)
    records, failed = _fetch_day(datetime(2026, 1, 1).date(), "SE3")

    assert records is None
    assert failed is True
    assert len(calls) == 3  # MAX_RETRIES=2 -> 3 attempts total


def test_fetch_day_returns_failed_after_exhausting_retries_on_5xx(monkeypatch):
    calls = []

    def fake_get(url, timeout):
        calls.append(url)
        return _FakeResponse(503)

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr("src.prices.time.sleep", lambda seconds: None)
    records, failed = _fetch_day(datetime(2026, 1, 1).date(), "SE3")

    assert records is None
    assert failed is True
    assert len(calls) == 3


def test_fetch_prices_transient_failure_falls_back_to_cache(monkeypatch, cache_root):
    day = date(2026, 1, 15)
    cached_df = _parse_day(_hourly_records(datetime(2026, 1, 14, 23, 0, tzinfo=timezone.utc), 24))
    write_day_cache(cache_root, "prices", "SE3", day, cached_df)

    monkeypatch.setattr(requests, "get", lambda url, timeout: _FakeResponse(503))
    monkeypatch.setattr("src.prices.time.sleep", lambda seconds: None)

    result = fetch_prices(day, day, "SE3", cache_root=cache_root, today=TEST_TODAY)

    assert result.fallback_days == [day]
    assert result.failed_days == []
    assert len(result.df) == 24


def test_fetch_prices_confirmed_404_does_not_read_cache(monkeypatch, cache_root):
    day = date(2026, 1, 16)
    cached_df = _parse_day(_hourly_records(datetime(2026, 1, 15, 23, 0, tzinfo=timezone.utc), 24))
    write_day_cache(cache_root, "prices", "SE3", day, cached_df)

    monkeypatch.setattr(requests, "get", lambda url, timeout: _FakeResponse(404))

    result = fetch_prices(day, day, "SE3", cache_root=cache_root, today=TEST_TODAY)

    assert result.failed_days == []
    assert result.fallback_days == []
    assert len(result.df) == 0  # confirmed-no-data day is absent; cache not consulted


def test_fetch_prices_successful_fetch_writes_through_cache(monkeypatch, cache_root):
    day = date(2026, 1, 17)
    records = _hourly_records(datetime(2026, 1, 16, 23, 0, tzinfo=timezone.utc), 24)

    monkeypatch.setattr(requests, "get", lambda url, timeout: _FakeResponse(200, records))

    result = fetch_prices(day, day, "SE3", cache_root=cache_root, today=TEST_TODAY)

    assert len(result.df) == 24
    cached = read_day_cache(cache_root, "prices", "SE3", day, PRICE_COLUMNS)
    assert cached is not None
    assert len(cached) == 24


def test_fetch_prices_single_day_range(monkeypatch, cache_root):
    day = date(2026, 1, 18)
    records = _hourly_records(datetime(2026, 1, 17, 23, 0, tzinfo=timezone.utc), 24)

    monkeypatch.setattr(requests, "get", lambda url, timeout: _FakeResponse(200, records))

    result = fetch_prices(day, day, "SE3", cache_root=cache_root, today=TEST_TODAY)

    assert len(result.df) == 24
    assert result.failed_days == []
    assert result.fallback_days == []


def test_fetch_prices_empty_reversed_range_returns_no_error(monkeypatch, cache_root):
    def fake_get(url, timeout):
        raise AssertionError("should not be called for an empty date range")

    monkeypatch.setattr(requests, "get", fake_get)

    result = fetch_prices(
        date(2026, 1, 20), date(2026, 1, 10), "SE3",
        cache_root=cache_root, today=TEST_TODAY,
    )

    assert len(result.df) == 0
    assert result.failed_days == []
    assert result.fallback_days == []
    assert list(result.df.columns) == PRICE_COLUMNS


# -- settled-day cache fast path (Sprint 8) ------------------------------------

def _no_network(monkeypatch):
    """Any HTTP call becomes a hard failure, so "didn't touch the API" is
    asserted rather than inferred from a timing measurement."""
    def fake_get(url, timeout):
        raise AssertionError(f"the API must not be consulted for a settled day: {url}")
    monkeypatch.setattr(requests, "get", fake_get)


def test_settled_day_with_a_valid_snapshot_makes_no_request(monkeypatch, cache_root):
    day = date(2026, 1, 15)
    cached_df = _parse_day(_hourly_records(datetime(2026, 1, 14, 23, 0, tzinfo=timezone.utc), 24))
    write_day_cache(cache_root, "prices", "SE3", day, cached_df)
    _no_network(monkeypatch)

    result = fetch_prices(day, day, "SE3", cache_root=cache_root, today=date(2026, 1, 16))

    assert len(result.df) == 24
    # a settled hit is the PRIMARY source, not a degraded one -- it must not
    # trigger the UI's "served from the offline cache" notice
    assert result.fallback_days == []
    assert result.failed_days == []


def test_today_and_tomorrow_are_never_served_from_cache(monkeypatch, cache_root):
    """Tomorrow's prices publish mid-afternoon, so "is tomorrow published
    yet" must always be answered live."""
    today = date(2026, 1, 15)
    for day in (today, today + timedelta(days=1)):
        cached_df = _parse_day(
            _hourly_records(datetime(2026, 1, 14, 23, 0, tzinfo=timezone.utc), 24)
        )
        write_day_cache(cache_root, "prices", "SE3", day, cached_df)

    calls = []
    monkeypatch.setattr(
        requests, "get",
        lambda url, timeout: calls.append(url) or _FakeResponse(404),
    )

    fetch_prices(today, today + timedelta(days=1), "SE3", cache_root=cache_root, today=today)

    assert len(calls) == 2  # both days went to the API despite having snapshots


def test_truncated_snapshot_falls_through_to_the_network(monkeypatch, cache_root):
    """A half-written snapshot would otherwise be served forever, since
    this path never consults the API to notice it is short."""
    day = date(2026, 1, 15)
    short = _parse_day(_hourly_records(datetime(2026, 1, 14, 23, 0, tzinfo=timezone.utc), 10))
    write_day_cache(cache_root, "prices", "SE3", day, short)

    full = _hourly_records(datetime(2026, 1, 14, 23, 0, tzinfo=timezone.utc), 24)
    monkeypatch.setattr(requests, "get", lambda url, timeout: _FakeResponse(200, full))

    result = fetch_prices(day, day, "SE3", cache_root=cache_root, today=date(2026, 1, 16))

    assert len(result.df) == 24  # the network answer, not the 10-row snapshot


def test_cache_first_output_matches_a_live_fetch(monkeypatch, cache_root):
    """The fast path must return the same frame as the slow one.

    Two deliberate loosenings, both verified to be metadata rather than
    data:

    - `atol`, not `.equals()`: the CSV round trip through the cache
      perturbs floats by ~4e-16, so `.equals()` is False even when
      nothing is wrong.
    - `check_freq=False`: a freshly resampled single-day frame carries
      `index.freq = <Hour>` while one read back from CSV carries None.
      Irrelevant in practice -- `pd.concat` drops freq, so every
      multi-day call (i.e. every real one) already has None on both
      paths.
    """
    day = date(2026, 1, 15)
    records = _hourly_records(datetime(2026, 1, 14, 23, 0, tzinfo=timezone.utc), 24)
    monkeypatch.setattr(requests, "get", lambda url, timeout: _FakeResponse(200, records))

    live = fetch_prices(day, day, "SE3", cache_root=cache_root, today=day).df  # writes through
    _no_network(monkeypatch)
    cached = fetch_prices(day, day, "SE3", cache_root=cache_root, today=day + timedelta(days=1)).df

    pd.testing.assert_frame_equal(live, cached, atol=1e-12, check_freq=False)


@pytest.mark.parametrize("day,expected", [
    (date(2026, 3, 29), 23),   # spring forward: 02:00 does not exist
    (date(2025, 10, 26), 25),  # fall back: 02:00 happens twice
    (date(2026, 1, 15), 24),
])
def test_expected_hours_counts_dst_days_from_the_zone(day, expected):
    # a hardcoded 24 would reject both DST days' snapshots every year
    assert _expected_hours(day) == expected
