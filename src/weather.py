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

Period choice: 'latest-months' (rolling ~4 months, provisional/uncorrected)
is enough for a spike fetching one recent month. Sprint 1+ must branch to
'corrected-archive' for older/arbitrary ranges, and verify the two periods
overlap with no gap -- _pick_period() is a placeholder seam for that, not
a real implementation yet (see SPRINTLOG.md open questions).

A failure here (bad station id, renamed period, network error) is not a
confirmed/expected condition the way a 404 is for elprisetjustnu's daily
price files -- it's treated as a real bug and allowed to raise, rather
than being silently swallowed. app.py does not yet catch this (see
SPRINTLOG.md open questions).
"""

from datetime import date

import pandas as pd
import requests

BASE_URL = "https://opendata-download-metobs.smhi.se/api"
PARAMETER = 1
DEFAULT_STATION = 71420
REQUEST_TIMEOUT = 10

WEATHER_COLUMNS = ["temperature_c", "quality"]


def _pick_period(start_date: date, end_date: date) -> str:
    """Spike-level placeholder. See module docstring."""
    return "latest-months"


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


def fetch_temperature(
    start_date: date, end_date: date, station_id: int = DEFAULT_STATION
) -> pd.DataFrame:
    """Fetch hourly instantaneous air temperature for [start_date, end_date].

    Returns a DataFrame indexed by tz-aware Europe/Stockholm timestamps,
    columns temperature_c / quality.
    """
    period = _pick_period(start_date, end_date)

    meta_url = (
        f"{BASE_URL}/version/latest/parameter/{PARAMETER}"
        f"/station/{station_id}/period/{period}.json"
    )
    meta = requests.get(meta_url, timeout=REQUEST_TIMEOUT)
    meta.raise_for_status()
    links = meta.json()["data"][0]["link"]
    data_url = next(link["href"] for link in links if link["type"] == "application/json")

    resp = requests.get(data_url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    df = _parse_payload(resp.json())

    start_ts = pd.Timestamp(start_date, tz="Europe/Stockholm")
    end_ts = pd.Timestamp(end_date, tz="Europe/Stockholm") + pd.Timedelta(days=1)
    return df.loc[(df.index >= start_ts) & (df.index < end_ts)]
