"""Fetch and parse hourly air temperature from SMHI Open Data (metobs API).

Station 71420 "Göteborg A" (central Gothenburg, long-running, active).
Parameter 1 = hourly instantaneous air temperature (°C) -- SMHI's metobs
API has no true hourly *mean* (parameter 2 is a *daily* mean), so
instantaneous hourly readings are the finest grain available and are what
this module treats as "the hourly temperature series".

Two-step fetch (per SMHI's API design, confirmed live):
  1. GET .../parameter/1/station/{id}/period/{period}.json
     -> metadata incl. data[0].link, which points at the actual values
  2. GET <that link>
     -> {station, parameter, period, value: [{date: epoch_ms_utc,
        value: "14.0", quality: "G"}, ...]}

Period selection (Sprint 1, confirmed live against station 71420):
'corrected-archive' (quality-controlled) covers ages >=~94 days as of
2026-10-03 (through 2026-07-01); 'latest-months' (provisional) covers
ages <=~130 days (from 2026-05-26) -- confirmed overlap, no gap. A single
age threshold would put the cut on the wrong side of that boundary (e.g.
age 70 is newer than archive's cutoff but older than a naive "60 days"
split, so an exclusive rule would route it to archive-only and silently
get back a payload missing that date -- a successful-but-empty response
looks identical to "no data here"). _pick_periods() instead uses two
deliberately-overlapping bands and tries both periods whenever a date
could plausibly be in either; two HTTP calls total (never per-day) makes
that double-fetch cheap insurance rather than waste.

A day absent from an otherwise-successful period payload is a benign
sensor gap -- same semantics as src/prices.py's confirmed-404 (absent,
not failed, no cache fallback attempted). A day whose covering period(s)
actually failed to fetch (network error, bad station/period) falls back
to src/cache.py's day-granularity CSV cache if a snapshot exists, same as
prices.py -- this replaces Sprint 0's raise_for_status()-propagates-
uncaught placeholder (see SPRINTLOG.md).

Format gotcha discovered live while building this: 'latest-months' (and
the other rolling periods) offer a JSON data link, but 'corrected-archive'
only offers a semicolon-delimited CSV link (Swedish headers, a variable-
length station/parameter/position preamble before the real 'Datum;Tid
(UTC);...' header row, times given directly in UTC rather than epoch-ms,
and ragged row widths -- early rows carry extra trailing metadata columns
later rows don't have). _fetch_period() tries the JSON link first and
falls back to parsing the CSV when no JSON link is offered, so it isn't
hardcoded to "corrected-archive is special" -- it degrades the same way
for any period that turns out to be CSV-only.
"""

import io
import time
from datetime import date, timedelta
from pathlib import Path
from typing import NamedTuple

import pandas as pd
import requests

from src.cache import DEFAULT_CACHE_ROOT, read_day_cache, write_day_cache

BASE_URL = "https://opendata-download-metobs.smhi.se/api"
PARAMETER = 1
DEFAULT_STATION = 71420
REQUEST_TIMEOUT = 10
MAX_RETRIES = 2
RETRY_BACKOFF_SECONDS = 1.5

ARCHIVE_MIN_AGE_DAYS = 60  # try corrected-archive once a date is at least this old
LATEST_MONTHS_MAX_AGE_DAYS = 150  # try latest-months up to at least this old

WEATHER_COLUMNS = ["temperature_c", "quality"]


class WeatherFetchResult(NamedTuple):
    df: pd.DataFrame
    failed_days: list[date]
    fallback_days: list[date]


def _date_range(start_date: date, end_date: date) -> list[date]:
    days = []
    day = start_date
    while day <= end_date:
        days.append(day)
        day += timedelta(days=1)
    return days


def _pick_periods(start_date: date, end_date: date, today: date | None = None) -> list[str]:
    """See module docstring for the boundary this straddles."""
    today = today or date.today()
    periods = []
    if (today - start_date).days >= ARCHIVE_MIN_AGE_DAYS:
        periods.append("corrected-archive")
    if (today - end_date).days <= LATEST_MONTHS_MAX_AGE_DAYS:
        periods.append("latest-months")
    return periods or ["latest-months"]


def _get_with_retries(url: str) -> tuple[requests.Response | None, bool]:
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        except requests.RequestException:
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS)
                continue
            return None, True

        if resp.status_code != 200:
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS)
                continue
            return None, True

        return resp, False

    return None, True


def _get_json_with_retries(url: str) -> tuple[dict | None, bool]:
    resp, failed = _get_with_retries(url)
    if failed:
        return None, True
    return resp.json(), False


def _get_text_with_retries(url: str) -> tuple[str | None, bool]:
    resp, failed = _get_with_retries(url)
    if failed:
        return None, True
    return resp.content.decode("utf-8-sig"), False


def _parse_payload(payload: dict) -> pd.DataFrame:
    """Pure: SMHI data.json payload -> tz-aware hourly DataFrame."""
    df = pd.DataFrame(payload["value"])
    if df.empty:
        return pd.DataFrame(columns=WEATHER_COLUMNS)
    df["timestamp"] = pd.to_datetime(df["date"], unit="ms", utc=True).dt.tz_convert(
        "Europe/Stockholm"
    )
    df["temperature_c"] = df["value"].astype(float)
    return df.set_index("timestamp")[WEATHER_COLUMNS].sort_index()


def _parse_archive_csv(text: str) -> pd.DataFrame:
    """Pure: corrected-archive's semicolon-delimited CSV -> tz-aware hourly
    DataFrame. See module docstring for the format gotchas this works
    around (variable-length preamble, UTC times, ragged row widths)."""
    lines = text.splitlines()
    header_idx = next(i for i, line in enumerate(lines) if line.startswith("Datum;"))
    data_text = "\n".join(lines[header_idx:])
    raw = pd.read_csv(
        io.StringIO(data_text),
        sep=";",
        usecols=[0, 1, 2, 3],
        names=["date", "time", "temperature_c", "quality"],
        header=0,
    )
    if raw.empty:
        return pd.DataFrame(columns=WEATHER_COLUMNS)
    timestamp = pd.to_datetime(raw["date"] + " " + raw["time"], utc=True).dt.tz_convert(
        "Europe/Stockholm"
    )
    raw["temperature_c"] = raw["temperature_c"].astype(float)
    return raw.set_index(timestamp)[WEATHER_COLUMNS].sort_index()


def _fetch_period(period: str, station_id: int) -> tuple[pd.DataFrame | None, bool]:
    """I/O: fetch one SMHI period's full payload, parsed.

    Returns (df, failed), mirroring src/prices.py's _fetch_day contract.
    There's no SMHI equivalent of a confirmed-empty 404 here -- any
    unrecoverable failure (bad station, renamed period, network error) is
    reported as failed=True so the caller can fall back to cache. Tries
    the JSON data link first; if the period only offers CSV (confirmed
    live: 'corrected-archive' does), falls back to the CSV parser.
    """
    meta_url = (
        f"{BASE_URL}/version/latest/parameter/{PARAMETER}"
        f"/station/{station_id}/period/{period}.json"
    )
    meta, failed = _get_json_with_retries(meta_url)
    if failed:
        return None, True
    try:
        links = meta["data"][0]["link"]
    except (KeyError, IndexError):
        return None, True

    json_link = next((link["href"] for link in links if link["type"] == "application/json"), None)
    if json_link is not None:
        payload, failed = _get_json_with_retries(json_link)
        if failed:
            return None, True
        return _parse_payload(payload), False

    csv_link = next((link["href"] for link in links if link["type"] == "text/plain"), None)
    if csv_link is None:
        return None, True
    text, failed = _get_text_with_retries(csv_link)
    if failed:
        return None, True
    return _parse_archive_csv(text), False


def _slice_to_range(df: pd.DataFrame, start_date: date, end_date: date) -> pd.DataFrame:
    if df.empty:
        return df
    start_ts = pd.Timestamp(start_date, tz="Europe/Stockholm")
    end_ts = pd.Timestamp(end_date, tz="Europe/Stockholm") + pd.Timedelta(days=1)
    return df.loc[(df.index >= start_ts) & (df.index < end_ts)]


def fetch_temperature(
    start_date: date,
    end_date: date,
    station_id: int = DEFAULT_STATION,
    cache_root: Path = DEFAULT_CACHE_ROOT,
) -> WeatherFetchResult:
    """Fetch hourly instantaneous air temperature for [start_date, end_date].

    Returns a WeatherFetchResult(df, failed_days, fallback_days) -- same
    shape and semantics as src/prices.py's fetch_prices.
    """
    periods = _pick_periods(start_date, end_date)
    frames = []
    failed_periods = set()
    for period in periods:
        period_df, failed = _fetch_period(period, station_id)
        if failed:
            failed_periods.add(period)
        elif period_df is not None and not period_df.empty:
            frames.append(period_df)

    if frames:
        combined = pd.concat(frames).sort_index()
        combined = combined[~combined.index.duplicated(keep="first")]
    else:
        combined = pd.DataFrame(columns=WEATHER_COLUMNS)
    sliced = _slice_to_range(combined, start_date, end_date)

    frames_out = []
    failed_days = []
    fallback_days = []
    for day in _date_range(start_date, end_date):
        day_df = _slice_to_range(sliced, day, day)
        if not day_df.empty:
            frames_out.append(day_df)
            write_day_cache(cache_root, "weather", str(station_id), day, day_df)
        else:
            day_periods = set(_pick_periods(day, day))
            if day_periods & failed_periods:
                cached = read_day_cache(cache_root, "weather", str(station_id), day, WEATHER_COLUMNS)
                if cached is not None:
                    frames_out.append(cached)
                    fallback_days.append(day)
                else:
                    failed_days.append(day)
            # else: benign gap in a successful payload, no fallback attempted

    if not frames_out:
        df = pd.DataFrame(columns=WEATHER_COLUMNS)
    else:
        df = pd.concat(frames_out).sort_index()
    return WeatherFetchResult(df, failed_days, fallback_days)
