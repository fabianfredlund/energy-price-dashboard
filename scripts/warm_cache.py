"""Refresh the committed offline cache for the window the app shows.

**Why this exists.** `data/cache/` is committed so the app works instantly
and survives an API outage -- in a customer meeting on bad wifi, and on
Streamlit Community Cloud, where the app sleeps and cold-starts for every
new visitor. But the 12-month window rolls forward every day, and Cloud's
filesystem is ephemeral: the app's own write-through is lost on every
restart. So the snapshot decays by roughly one day per day, and only a
commit can heal it.

Run this before the examination, before any demo, and whenever the app
starts reporting fetched days:

    .venv/bin/python scripts/warm_cache.py
    git add data/cache && git commit -m "chore: refresh cached year"

It fetches exactly what the app's default view needs: the same 12-month
window (ending at today - 2 for Open-Meteo's archive lag) plus today and
tomorrow for the Tomorrow tab, for both roof orientations.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import ORIENTATIONS, PRICE_AREA  # noqa: E402
from src.prices import fetch_prices  # noqa: E402
from src.solar import fetch_irradiance, fetch_irradiance_forecast  # noqa: E402

YEAR_DAYS = 365
ARCHIVE_LAG_DAYS = 2


def main() -> int:
    today = date.today()
    end = today - timedelta(days=ARCHIVE_LAG_DAYS)
    start = end - timedelta(days=YEAR_DAYS - 1)
    tomorrow = today + timedelta(days=1)

    print(f"Window: {start} .. {end}  (plus {today} and {tomorrow} for the Tomorrow tab)")

    problems = 0

    # Prices. Passing today=start forces every day to be fetched live
    # rather than served from the snapshot we are trying to refresh.
    print(f"\nSpot prices, {PRICE_AREA} ...")
    result = fetch_prices(start, tomorrow, PRICE_AREA, today=start)
    print(f"  {len(result.df)} rows, {len(result.failed_days)} failed, "
          f"{len(result.fallback_days)} from cache")
    if result.failed_days:
        print(f"  FAILED: {result.failed_days}")
        problems += len(result.failed_days)

    # Irradiance: one request per azimuth series, so this is cheap.
    for name in ORIENTATIONS:
        print(f"\nIrradiance, {name} ...")
        archive = fetch_irradiance(start, end, name)
        forecast = fetch_irradiance_forecast(today, tomorrow, name)
        for label, res in (("archive", archive), ("forecast", forecast)):
            print(f"  {label}: {len(res.df)} rows, {len(res.failed_days)} failed")
            if res.failed_days:
                print(f"  FAILED: {res.failed_days}")
                problems += len(res.failed_days)

    print(
        "\nDone. Now commit the refreshed snapshot:\n"
        "    git add data/cache && git commit -m 'chore: refresh cached year'"
    )
    if problems:
        print(f"\nWARNING: {problems} day(s) could not be fetched; re-run before committing.")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
