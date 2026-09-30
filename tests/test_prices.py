"""Smoke tests for src/prices.py -- locking in the DST-offset and
404-vs-failed behavior discovered by trial and error against the live
API during Sprint 0 (see SPRINTLOG.md).

The DST-transition fixtures are built by walking real, evenly-spaced UTC
instants and converting each to Europe/Stockholm for display (via
zoneinfo, using the system's real tz database) -- the same construction
the real API itself uses, confirmed by fetching 2025-10-26 and 2026-03-29
live: a repeated local hour on fall-back, a skipped one on spring-forward.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from src.prices import _fetch_day, _parse_day

STOCKHOLM = ZoneInfo("Europe/Stockholm")


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
