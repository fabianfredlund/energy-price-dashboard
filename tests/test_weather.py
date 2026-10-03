"""Smoke tests for src/weather.py -- parsing, period selection (including
the band that exposed a single-threshold bug during planning), and the
cache-fallback behavior that replaces Sprint 0's raise_for_status()
placeholder."""

from datetime import date, datetime, timezone

import pandas as pd
import requests

from src.cache import read_day_cache, write_day_cache
from src.weather import (
    WEATHER_COLUMNS,
    _fetch_period,
    _parse_archive_csv,
    _parse_payload,
    _pick_periods,
    fetch_temperature,
)


def test_parse_payload_converts_epoch_ms_and_casts_float():
    payload = {
        "value": [
            {"date": 1691000000000, "value": "14.0", "quality": "G"},
            {"date": 1691003600000, "value": "13.5", "quality": "G"},
        ]
    }

    df = _parse_payload(payload)

    assert len(df) == 2
    assert df["temperature_c"].dtype.kind == "f"
    assert df["temperature_c"].iloc[0] == 14.0
    assert str(df.index.tzinfo) == "Europe/Stockholm"
    assert df.index[0].tz_convert("UTC") == datetime.fromtimestamp(
        1691000000000 / 1000, tz=timezone.utc
    )


def test_parse_payload_handles_empty_value_list():
    df = _parse_payload({"value": []})
    assert len(df) == 0
    assert list(df.columns) == ["temperature_c", "quality"]


def test_parse_archive_csv_handles_real_format():
    # Trimmed real sample from corrected-archive's data.csv (confirmed
    # live): a variable-length preamble before the real 'Datum;...'
    # header, a UTF-8 BOM, UTC times, and ragged row widths -- the first
    # few data rows carry extra trailing metadata columns later rows
    # don't have. This regression-tests a real bug found during Sprint 1
    # manual verification: corrected-archive only offers a CSV link, not
    # JSON, and naively assuming JSON silently classified every
    # corrected-archive-only day as failed.
    text = (
        "﻿Stationsnamn;Stationsnummer;Stationsnät;Mäthöjd (meter över marken)\n"
        "Göteborg A;71420;SMHIs stationsnät;2.0\n"
        "\n"
        "Parameternamn;Beskrivning;Enhet\n"
        "Lufttemperatur;momentanvärde, 1 gång/tim;celsius\n"
        "\n"
        "Tidsperiod (fr.o.m);Tidsperiod (t.o.m);Höjd (meter över havet);Latitud (decimalgrader);Longitud (decimalgrader)\n"
        "1999-03-01 00:00:00;2026-10-01 19:20:11;3.038;57.7156;11.9924\n"
        "\n"
        "Datum;Tid (UTC);Lufttemperatur;Kvalitet;;Tidsutsnitt:\n"
        "2026-01-10;00:00:00;-4.1;G;;Kvalitetskontrollerade historiska data\n"
        "2026-01-10;01:00:00;-4.5;G;;Tidsperiod (fr.o.m.) = 1999-03-01\n"
        "2026-01-10;02:00:00;-5.2;G\n"
    )

    df = _parse_archive_csv(text)

    assert len(df) == 3
    assert list(df.columns) == WEATHER_COLUMNS
    assert df["temperature_c"].iloc[0] == -4.1
    assert str(df.index.tzinfo) == "Europe/Stockholm"
    # 2026-01-10 00:00 UTC == 01:00 CET (winter, +01:00)
    assert df.index[0].tz_convert("UTC") == pd.Timestamp("2026-01-10 00:00:00", tz="UTC")


# -- _pick_periods: the overlap band is where a single threshold would have
# silently dropped data (see module docstring / SPRINTLOG.md). All three
# cases pinned against today=2026-10-03.

def test_pick_periods_recent_range_uses_latest_months_only():
    assert _pick_periods(date(2026, 9, 1), date(2026, 9, 30), today=date(2026, 10, 3)) == [
        "latest-months"
    ]


def test_pick_periods_old_range_uses_corrected_archive_only():
    assert _pick_periods(date(2026, 1, 1), date(2026, 1, 31), today=date(2026, 10, 3)) == [
        "corrected-archive"
    ]


def test_pick_periods_range_spanning_overlap_band_uses_both():
    # ages 75/44 -- exactly the band (60-150) where a naive single
    # threshold misclassified dates that only latest-months actually has.
    assert _pick_periods(date(2026, 7, 20), date(2026, 8, 20), today=date(2026, 10, 3)) == [
        "corrected-archive",
        "latest-months",
    ]


class _FakeResponse:
    def __init__(self, status_code, payload=None, text=None):
        self.status_code = status_code
        self._payload = payload
        self.content = text.encode("utf-8") if text is not None else b""

    def json(self):
        return self._payload


def _single_row_df(day: date, temperature_c: float) -> pd.DataFrame:
    return pd.DataFrame(
        {"temperature_c": [temperature_c], "quality": ["G"]},
        index=pd.DatetimeIndex([pd.Timestamp(day, tz="Europe/Stockholm")]),
    )


def test_fetch_period_falls_back_to_csv_when_no_json_link_offered(monkeypatch):
    # Regression test for the real bug: corrected-archive's metadata only
    # lists a text/plain link, never application/json.
    meta_payload = {
        "data": [
            {
                "link": [
                    {"href": "https://example/data.csv", "type": "text/plain"},
                ]
            }
        ]
    }
    csv_text = "Datum;Tid (UTC);Lufttemperatur;Kvalitet\n2026-01-10;00:00:00;-4.1;G\n"

    def fake_get(url, timeout):
        if url.endswith(".json"):
            return _FakeResponse(200, payload=meta_payload)
        return _FakeResponse(200, text=csv_text)

    monkeypatch.setattr(requests, "get", fake_get)

    df, failed = _fetch_period("corrected-archive", 71420)

    assert failed is False
    assert len(df) == 1
    assert df["temperature_c"].iloc[0] == -4.1


def test_fetch_temperature_transient_failure_falls_back_to_cache(monkeypatch, cache_root):
    day = date(2026, 1, 15)
    monkeypatch.setattr("src.weather._pick_periods", lambda *a, **k: ["latest-months"])
    write_day_cache(cache_root, "weather", "71420", day, _single_row_df(day, 1.0))

    monkeypatch.setattr(requests, "get", lambda url, timeout: _FakeResponse(503))
    monkeypatch.setattr("src.weather.time.sleep", lambda seconds: None)

    result = fetch_temperature(day, day, cache_root=cache_root)

    assert result.fallback_days == [day]
    assert result.failed_days == []
    assert len(result.df) == 1


def test_benign_gap_in_successful_payload_is_not_a_failure(monkeypatch, cache_root):
    monkeypatch.setattr("src.weather._pick_periods", lambda *a, **k: ["latest-months"])
    present_day = date(2026, 1, 15)
    missing_day = date(2026, 1, 16)

    monkeypatch.setattr(
        "src.weather._fetch_period",
        lambda period, station_id: (_single_row_df(present_day, 2.0), False),
    )

    result = fetch_temperature(present_day, missing_day, cache_root=cache_root)

    assert missing_day not in result.failed_days
    assert missing_day not in result.fallback_days
    assert len(result.df) == 1


def test_fetch_temperature_all_periods_fail_no_cache_returns_failed_days(monkeypatch, cache_root):
    day = date(2026, 1, 20)
    monkeypatch.setattr("src.weather._pick_periods", lambda *a, **k: ["latest-months"])
    monkeypatch.setattr(requests, "get", lambda url, timeout: _FakeResponse(500))
    monkeypatch.setattr("src.weather.time.sleep", lambda seconds: None)

    result = fetch_temperature(day, day, cache_root=cache_root)  # must not raise

    assert result.failed_days == [day]
    assert result.fallback_days == []
    assert len(result.df) == 0


def test_fetch_temperature_successful_fetch_writes_through_cache(monkeypatch, cache_root):
    day = date(2026, 1, 21)
    monkeypatch.setattr("src.weather._pick_periods", lambda *a, **k: ["latest-months"])
    monkeypatch.setattr(
        "src.weather._fetch_period",
        lambda period, station_id: (_single_row_df(day, 5.0), False),
    )

    result = fetch_temperature(day, day, cache_root=cache_root)

    assert len(result.df) == 1
    cached = read_day_cache(cache_root, "weather", "71420", day, WEATHER_COLUMNS)
    assert cached is not None
    assert len(cached) == 1
