"""Fill and verify the committed offline cache for the fixed window.

**Why this exists.** `data/cache/` is committed so the app works instantly
and survives an API outage — in a customer meeting on bad wifi, and on
Streamlit Community Cloud, where the app sleeps and cold-starts for every
new visitor and whose filesystem is ephemeral, so the app's own
write-through is lost on every restart. Only a commit heals it.

The window is **fixed** (`config.WINDOW_START..WINDOW_END`), so unlike the
rolling version this replaces, the cache does not decay day by day. It only
needs filling once, and re-verifying before a demo.

    .venv/bin/python scripts/warm_cache.py            # fill anything missing
    .venv/bin/python scripts/warm_cache.py --refresh  # re-fetch everything live
    .venv/bin/python scripts/warm_cache.py --verify   # check, fetch nothing

    git add data/cache && git commit -m "chore: refresh cached window"
"""

import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.cache import DEFAULT_CACHE_ROOT  # noqa: E402
from src.config import (  # noqa: E402
    ORIENTATIONS,
    PANEL_TILT_DEG,
    PRICE_AREA,
    WINDOW_END,
    WINDOW_LABEL,
    WINDOW_START,
)
from src.prices import fetch_prices  # noqa: E402
from src.solar import fetch_irradiance  # noqa: E402

STOCKHOLM = "Europe/Stockholm"


def _expected_hours(day) -> int:
    """23, 24 or 25 -- computed from the zone, never assumed."""
    start = pd.Timestamp(day, tz=STOCKHOLM)
    return len(pd.date_range(start, start + pd.DateOffset(days=1), freq="h", inclusive="left"))


def _all_days() -> list:
    days, day = [], WINDOW_START
    while day <= WINDOW_END:
        days.append(day)
        day += timedelta(days=1)
    return days


def fill(refresh: bool) -> int:
    today = WINDOW_START if refresh else None  # WINDOW_START => nothing counts as settled
    problems = 0

    print(f"Window: {WINDOW_LABEL}  ({WINDOW_START} .. {WINDOW_END})")
    print(f"\nSpot prices, {PRICE_AREA} ...")
    result = fetch_prices(WINDOW_START, WINDOW_END, PRICE_AREA, today=today)
    print(f"  {len(result.df)} rows, {len(result.failed_days)} failed, "
          f"{len(result.fallback_days)} served from an older snapshot")
    if result.failed_days:
        print(f"  FAILED: {result.failed_days[:10]}{' ...' if len(result.failed_days) > 10 else ''}")
        problems += len(result.failed_days)

    for name in ORIENTATIONS:
        print(f"\nIrradiance, {name} (tilt {PANEL_TILT_DEG}°) ...")
        res = fetch_irradiance(WINDOW_START, WINDOW_END, name)
        print(f"  {len(res.df)} rows, {len(res.failed_days)} failed")
        if res.failed_days:
            print(f"  FAILED: {res.failed_days[:10]}")
            problems += len(res.failed_days)
    return problems


def verify(cache_root: Path = DEFAULT_CACHE_ROOT) -> int:
    """Check the committed cache covers the window, without fetching.

    Asserts the things that would otherwise fail silently: a missing day, a
    short file, the three 23-hour and three 25-hour DST days, the leap day,
    and NaNs.
    """
    days = _all_days()
    failures = []

    def check(directory: Path, column: str, label: str):
        present = {p.stem for p in directory.glob("*.csv")} if directory.exists() else set()
        missing = [d for d in days if d.isoformat() not in present]
        if missing:
            failures.append(f"{label}: {len(missing)} day(s) missing, first {missing[:3]}")
            return
        rows = nan = 0
        wrong = []
        for day in days:
            df = pd.read_csv(directory / f"{day.isoformat()}.csv", index_col=0, parse_dates=True)
            rows += len(df)
            nan += int(df[column].isna().sum())
            if len(df) != _expected_hours(day):
                wrong.append((day, len(df), _expected_hours(day)))
        if wrong:
            failures.append(f"{label}: {len(wrong)} day(s) with the wrong hour count, {wrong[:3]}")
        if nan:
            failures.append(f"{label}: {nan} NaN value(s) in {column}")
        print(f"  {label}: {len(days)} days, {rows} rows, {nan} NaN")

    print(f"Verifying {WINDOW_LABEL} ...")
    check(cache_root / "prices" / PRICE_AREA, "SEK_per_kWh", "prices")
    for name, orientation in ORIENTATIONS.items():
        check(cache_root / "solar" / f"{orientation.slug}_t{PANEL_TILT_DEG}",
              "irradiance_w_m2", f"solar {name}")

    # The days that make a naive implementation wrong
    short = [d for d in days if _expected_hours(d) == 23]
    long_ = [d for d in days if _expected_hours(d) == 25]
    leap = [d for d in days if (d.month, d.day) == (2, 29)]
    print(f"\n  spring-forward (23h): {[str(d) for d in short]}")
    print(f"  fall-back      (25h): {[str(d) for d in long_]}")
    print(f"  leap day            : {[str(d) for d in leap]}")
    if len(short) != 3 or len(long_) != 3:
        failures.append(f"expected 3 of each DST day, found {len(short)} and {len(long_)}")
    if len(leap) != 1:
        failures.append(f"expected exactly 1 leap day, found {len(leap)}")

    if failures:
        print("\nFAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nAll checks passed.")
    return 0


def main(argv: list[str]) -> int:
    if "--verify" in argv:
        return verify()
    problems = fill(refresh="--refresh" in argv)
    print("\nNow verify and commit:")
    print("    .venv/bin/python scripts/warm_cache.py --verify")
    print("    git add data/cache && git commit -m 'chore: refresh cached window'")
    if problems:
        print(f"\nWARNING: {problems} day(s) could not be fetched; re-run before committing.")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
