"""Fetch tilted solar irradiance from Open-Meteo and turn it into an
estimated hourly production series. Replaces v1's src/weather.py.

Two endpoints, identical parameter names (verified live in the Sprint 5
spike):
  - archive:  https://archive-api.open-meteo.com/v1/archive   (history,
    reaches to ~2 days before today)
  - forecast: https://api.open-meteo.com/v1/forecast          (tomorrow)
Both take `tilt` + `azimuth` and return `global_tilted_irradiance` in
W/m², hourly.

Azimuth convention, verified by curve shape rather than assumed:
-90 = East (peaks ~06:00), 0 = South, +90 = West (peaks ~18:00).
An East-West roof is modelled as half the array each way, i.e. the mean
of the -90 and +90 series against the full kWp.

Two deliberate design points:

1. **Always request timezone=UTC and convert to Europe/Stockholm here.**
   Asking Open-Meteo for timezone=Europe/Stockholm returns naive local
   strings that include wall-clock times which don't exist: verified
   live, 2026-03-29 (EU spring-forward) came back with 24 hours
   including "02:00", an hour Stockholm skips entirely. Localizing that
   raises NonExistentTimeError. Parsing UTC and converting afterwards is
   the same rule src/prices.py has followed since Sprint 0, and it makes
   the 23- and 25-hour DST days come out right for free. Because a UTC
   day is not a Stockholm day, the request is padded by a day on each
   side and then sliced back to the local range.

2. **The cache stores irradiance, not production.** Irradiance is
   independent of system size, so the advisor can move the kWp slider
   without refetching anything; production_kwh() applies kWp and losses
   afterwards. The cache key includes orientation and tilt, so a
   south-facing snapshot can never be served for an east-west roof.
"""

import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import NamedTuple
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from src.cache import DEFAULT_CACHE_ROOT, read_day_cache, write_day_cache
from src.config import (
    DEFAULT_ORIENTATION,
    LATITUDE,
    LONGITUDE,
    ORIENTATIONS,
    PANEL_TILT_DEG,
)

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
IRRADIANCE_VAR = "global_tilted_irradiance"

REQUEST_TIMEOUT = 15
MAX_RETRIES = 2
RETRY_BACKOFF_SECONDS = 1.5

SOLAR_COLUMNS = ["irradiance_w_m2"]
PRODUCTION_COLUMN = "production_kwh"


class SolarFetchResult(NamedTuple):
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


def _cache_key(orientation_name: str) -> str:
    """Orientation + tilt, so snapshots for different roofs never collide."""
    return f"{ORIENTATIONS[orientation_name].slug}_t{PANEL_TILT_DEG}"


def _get_json_with_retries(url: str, params: dict) -> tuple[dict | None, bool]:
    """Returns (payload, failed). Mirrors the retry contract used by
    src/prices.py's _fetch_day and v1's weather fetcher."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
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

        return resp.json(), False

    return None, True


def _parse_hourly(payload: dict) -> pd.DataFrame:
    """Pure: Open-Meteo payload -> tz-aware hourly irradiance DataFrame.

    Timestamps are parsed as UTC then converted to Europe/Stockholm (see
    the module docstring). Null readings are dropped rather than coerced
    to zero -- a missing hour is absent, not an hour with no sun, the
    same distinction src/prices.py draws for missing price days.
    """
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    values = hourly.get(IRRADIANCE_VAR) or []
    if not times or not values:
        return pd.DataFrame(columns=SOLAR_COLUMNS)

    df = pd.DataFrame({"timestamp": times, "irradiance_w_m2": values})
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert(
        "Europe/Stockholm"
    )
    df = df.dropna(subset=["irradiance_w_m2"])
    if df.empty:
        return pd.DataFrame(columns=SOLAR_COLUMNS)
    df["irradiance_w_m2"] = df["irradiance_w_m2"].astype(float)
    return df.set_index("timestamp")[SOLAR_COLUMNS].sort_index()


def _base_params(azimuth: int) -> dict:
    return {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "hourly": IRRADIANCE_VAR,
        "tilt": PANEL_TILT_DEG,
        "azimuth": azimuth,
        "timezone": "UTC",
    }


def _fetch_one_azimuth(
    azimuth: int, start_date: date, end_date: date, forecast: bool
) -> tuple[pd.DataFrame | None, bool]:
    """One API call for one panel azimuth. Returns (df, failed).

    The requested window is padded a day either side because a UTC day is
    not a Stockholm day; the caller slices back to the local range.
    """
    params = _base_params(azimuth)
    if forecast:
        params |= {"past_days": 1, "forecast_days": 3}
        url = FORECAST_URL
    else:
        params |= {
            "start_date": (start_date - timedelta(days=1)).isoformat(),
            "end_date": (end_date + timedelta(days=1)).isoformat(),
        }
        url = ARCHIVE_URL

    payload, failed = _get_json_with_retries(url, params)
    if failed or payload is None:
        return None, True
    return _parse_hourly(payload), False


def _combine_azimuths(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Mean irradiance across the roof's azimuths -- for East-West this is
    half the array facing each way, which is exactly the average of the
    two surfaces' irradiance applied to the full kWp."""
    if not frames:
        return pd.DataFrame(columns=SOLAR_COLUMNS)
    if len(frames) == 1:
        return frames[0]
    combined = pd.concat(frames)
    return combined.groupby(combined.index).mean().sort_index()


def _slice_to_range(df: pd.DataFrame, start_date: date, end_date: date) -> pd.DataFrame:
    """Local-calendar slice, end-exclusive at the next calendar midnight.

    Uses DateOffset, not Timedelta: `Timedelta(days=1)` is 24 *absolute*
    hours, which on the spring-forward day lands at 01:00 the next
    morning -- so a 23-hour day would return 24 rows spilling into the
    next date, and concatenating consecutive days duplicated an hour.
    DateOffset moves to the next calendar midnight whatever the day's
    length. (Found in Sprint 6 while building the first year-long frame;
    it would have corrupted two days a year.)
    """
    if df.empty:
        return df
    start_ts = pd.Timestamp(start_date, tz="Europe/Stockholm")
    end_ts = pd.Timestamp(end_date, tz="Europe/Stockholm") + pd.DateOffset(days=1)
    return df.loc[(df.index >= start_ts) & (df.index < end_ts)]


def _settled_cache(cache_root: Path, key: str, days: list, today: date) -> dict | None:
    """Every requested day, read from the snapshot, or None if any is missing.

    A past day's irradiance is as settled as a past day's spot price: it is
    measurement, and it does not change. So for a window wholly in the past
    the API need not be consulted at all, which is what makes the app work
    on a bad hotel wifi, keeps a Community Cloud cold start independent of
    Open-Meteo being up, and keeps the test suite off the network.

    All-or-nothing on purpose: a partial hit would still need the API call
    for the rest, and one call answers the whole range anyway, so there is
    nothing to gain from a partial read and a gap to miss by trying.
    """
    out = {}
    for day in days:
        if day >= today:
            return None
        cached = read_day_cache(cache_root, "solar", key, day, SOLAR_COLUMNS)
        if cached is None or cached.empty:
            return None
        out[day] = cached
    return out


def _fetch(
    start_date: date,
    end_date: date,
    orientation: str,
    cache_root: Path,
    forecast: bool,
    today: date | None = None,
) -> SolarFetchResult:
    """Shared body for the archive and forecast fetchers.

    A failed call makes every day in the range a fallback candidate: unlike
    the per-day price API, Open-Meteo answers the whole range in one call,
    so there is no per-day success/failure to distinguish. A day missing
    from an otherwise-successful payload is a benign gap -- absent, not
    failed, and no fallback attempted (the same distinction src/prices.py
    draws between a confirmed-404 day and an unreachable one).

    A range entirely before `today` with a complete snapshot is served from
    that snapshot and makes no request -- see `_settled_cache`. Such a hit
    is the *primary* source, so it is reported as neither failed nor
    fallback.
    """
    key = _cache_key(orientation)
    days = _date_range(start_date, end_date)

    if not forecast:
        settled = _settled_cache(cache_root, key, days, today or _today_stockholm())
        if settled is not None:
            return SolarFetchResult(
                pd.concat(settled.values()).sort_index(), [], []
            )

    frames, call_failed = [], False
    for azimuth in ORIENTATIONS[orientation].azimuths:
        df, failed = _fetch_one_azimuth(azimuth, start_date, end_date, forecast)
        if failed:
            call_failed = True
            break
        if df is not None and not df.empty:
            frames.append(df)

    sliced = _slice_to_range(_combine_azimuths(frames), start_date, end_date)

    frames_out, failed_days, fallback_days = [], [], []
    for day in days:
        day_df = _slice_to_range(sliced, day, day)
        if not day_df.empty:
            frames_out.append(day_df)
            write_day_cache(cache_root, "solar", key, day, day_df)
        elif call_failed:
            cached = read_day_cache(cache_root, "solar", key, day, SOLAR_COLUMNS)
            if cached is not None:
                frames_out.append(cached)
                fallback_days.append(day)
            else:
                failed_days.append(day)
        # else: benign gap in a successful payload

    df = pd.concat(frames_out).sort_index() if frames_out else pd.DataFrame(columns=SOLAR_COLUMNS)
    return SolarFetchResult(df, failed_days, fallback_days)


def _today_stockholm() -> date:
    return datetime.now(ZoneInfo("Europe/Stockholm")).date()


def fetch_irradiance(
    start_date: date,
    end_date: date,
    orientation: str = DEFAULT_ORIENTATION,
    cache_root: Path = DEFAULT_CACHE_ROOT,
    today: date | None = None,
) -> SolarFetchResult:
    """Historical hourly tilted irradiance for [start_date, end_date].

    Same (df, failed_days, fallback_days) shape as src/prices.py's
    fetch_prices, so app.py's fallback notices work unchanged.
    """
    return _fetch(start_date, end_date, orientation, cache_root, forecast=False, today=today)


def fetch_irradiance_forecast(
    start_date: date,
    end_date: date,
    orientation: str = DEFAULT_ORIENTATION,
    cache_root: Path = DEFAULT_CACHE_ROOT,
) -> SolarFetchResult:
    """Forecast hourly tilted irradiance, for today/tomorrow."""
    return _fetch(start_date, end_date, orientation, cache_root, forecast=True)


def production_kwh(
    irradiance_df: pd.DataFrame, kwp: float, *, loss: float
) -> pd.DataFrame:
    """Pure: add a `production_kwh` column from irradiance and system size.

    CLAUDE.md's model: kWp x (W/m^2 / 1000) x loss. Each row is one hour,
    so kW x 1h is kWh directly. 1000 W/m^2 is standard test conditions,
    i.e. the irradiance at which a system produces its rated kWp.

    kwp=0 (or an empty frame) gives a well-formed all-zero / empty result
    rather than an error -- "no system" is a legitimate scenario, not a
    failure.
    """
    out = irradiance_df.copy()
    if out.empty:
        out[PRODUCTION_COLUMN] = pd.Series(dtype="float64")
        return out
    out[PRODUCTION_COLUMN] = out["irradiance_w_m2"] / 1000.0 * kwp * loss
    return out
