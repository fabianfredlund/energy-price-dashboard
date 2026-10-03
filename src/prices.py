"""Fetch and parse SE-area day-ahead spot electricity prices from elprisetjustnu.se.

API: https://www.elprisetjustnu.se/api/v1/prices/{YYYY}/{MM}-{DD}_{AREA}.json
One static JSON file per day per price area, no API key.

Key points confirmed by live requests against the API (see SPRINTLOG.md,
Sprint 0, for the full story):

- Timestamps are Europe/Stockholm LOCAL time with a per-record UTC offset
  (+01:00 winter / +02:00 summer DST) -- NOT a fixed +01:00 as the docs
  page states. Parsed via utc=True, resampled in UTC, and only converted
  to Europe/Stockholm afterwards, so DST transitions (a repeated local
  hour on fall-back, a skipped one on spring-forward) never create
  ambiguity.
- Resolution changed from hourly (24 entries/day) to 15-min (96/day) on
  2025-10-01. Rather than branch on entry count, every day is resampled to
  hourly mean unconditionally -- resample("1h").mean() is a no-op on data
  that's already hourly, including DST-transition days with 23 or 25
  hourly entries, so one code path handles both regimes correctly.
- A day with no data returns HTTP 404 with a small error-shaped JSON body,
  not a price array. Only a 404 means "confirmed no data, skip" -- a
  timeout or 5xx is a transient failure, gets retried, and if it still
  fails is reported back to the caller rather than silently dropped.
- Units: returned as SEK_per_kWh / EUR_per_kWh / EXR, exactly as the API
  gives them. Conversion to öre/kWh for display is left to the caller
  (app.py) -- this module stays a plain unit-preserving fetch+parse layer.

Sprint 1 additions (see SPRINTLOG.md): each day's fetch loop runs through
a small thread pool (network I/O only -- the day-fetch calls -- bookkeeping
stays sequential afterwards, so there's no shared-mutable-state race to
reason about), per CLAUDE.md's "fetch day files politely: small thread
pool, timeouts, retries" rule. A successful fetch is written through to
src/cache.py's day-granularity CSV cache; a transient failure (not a
confirmed 404) falls back to that cache if a snapshot exists.
"""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from typing import NamedTuple

import pandas as pd
import requests

from src.cache import DEFAULT_CACHE_ROOT, read_day_cache, write_day_cache

BASE_URL = "https://www.elprisetjustnu.se/api/v1/prices"
VALID_AREAS = {"SE1", "SE2", "SE3", "SE4"}
REQUEST_TIMEOUT = 10
MAX_RETRIES = 2
RETRY_BACKOFF_SECONDS = 1.5
MAX_WORKERS = 4

PRICE_COLUMNS = ["SEK_per_kWh", "EUR_per_kWh", "EXR"]


class PriceFetchResult(NamedTuple):
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


def _day_url(day: date, area: str) -> str:
    return f"{BASE_URL}/{day.year}/{day.month:02d}-{day.day:02d}_{area}.json"


def _fetch_day(day: date, area: str) -> tuple[list | None, bool]:
    """I/O: fetch one day's raw records.

    Returns (records, failed):
    - (records, False) on success.
    - (None, False) if the API confirms there is no data for this day
      (HTTP 404) -- a normal, expected condition, not an error.
    - (None, True) if the day could not be fetched after retries (timeout,
      connection error, or a non-404 error status) -- a day that should
      exist but couldn't be confirmed either way.
    """
    url = _day_url(day, area)
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        except requests.RequestException:
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS)
                continue
            return None, True

        if resp.status_code == 404:
            return None, False
        if resp.status_code != 200:
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS)
                continue
            return None, True

        return resp.json(), False

    return None, True


def _parse_day(records: list) -> pd.DataFrame:
    """Pure: raw day records -> tz-aware hourly DataFrame (Europe/Stockholm).

    Resamples to hourly mean while the index is still in UTC (unambiguous
    and monotonic across DST transitions), then converts to Europe/Stockholm
    for the caller. A no-op on data that's already hourly.
    """
    df = pd.DataFrame(records)
    df["time_start"] = pd.to_datetime(df["time_start"], utc=True)
    df = df.set_index("time_start").sort_index()[PRICE_COLUMNS]
    hourly_utc = df.resample("1h").mean()
    return hourly_utc.tz_convert("Europe/Stockholm")


def fetch_prices(
    start_date: date,
    end_date: date,
    area: str = "SE3",
    cache_root: Path = DEFAULT_CACHE_ROOT,
) -> PriceFetchResult:
    """Fetch SE-area spot prices for [start_date, end_date] inclusive.

    Returns a PriceFetchResult(df, failed_days, fallback_days):
    - df: hourly DataFrame indexed by tz-aware Europe/Stockholm timestamps,
      columns SEK_per_kWh / EUR_per_kWh / EXR. Days confirmed to have no
      published data (404) are simply absent -- compare len(df) against
      expected row counts to detect these gaps.
    - failed_days: days that could not be fetched live AND had no cached
      snapshot to fall back to. Never silently merged into the "no data"
      case -- the caller should surface these.
    - fallback_days: days that could not be fetched live but were served
      from the offline cache instead -- degraded, but recovered.
    """
    if area not in VALID_AREAS:
        raise ValueError(f"area must be one of {VALID_AREAS}, got {area!r}")

    days = _date_range(start_date, end_date)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        fetch_results = list(pool.map(lambda d: _fetch_day(d, area), days))

    frames = []
    failed_days = []
    fallback_days = []
    for day, (records, failed) in zip(days, fetch_results):
        if records:
            day_df = _parse_day(records)
            frames.append(day_df)
            write_day_cache(cache_root, "prices", area, day, day_df)
        elif failed:
            cached = read_day_cache(cache_root, "prices", area, day, PRICE_COLUMNS)
            if cached is not None:
                frames.append(cached)
                fallback_days.append(day)
            else:
                failed_days.append(day)
        # else: confirmed 404 -- day is absent, no fallback attempted

    if not frames:
        df = pd.DataFrame(columns=PRICE_COLUMNS)
    else:
        df = pd.concat(frames).sort_index()
    return PriceFetchResult(df, failed_days, fallback_days)
