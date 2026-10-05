"""Day-granularity CSV cache shared by src/prices.py and src/solar.py.

Stores one file per (subdir, key, day), e.g.
data/cache/prices/SE3/2026-08-15.csv or
data/cache/solar/south_t40/2026-08-15.csv.

Always written/read in UTC: every row in a cached day shares one offset,
which avoids the two real DST-transition dates (2025-10-26, 2026-03-29)
putting mixed-offset rows in the same file -- the same reason _parse_day
(src/prices.py) resamples in UTC before converting to Europe/Stockholm.
Callers convert back to Europe/Stockholm after reading.

Both read and write are best-effort: a missing or corrupt cache file is
just "no fallback available" (returns None), and a write failure (e.g. a
read-only filesystem) is swallowed rather than breaking an otherwise-
successful live fetch. The cache is a fallback, never a source of truth.
"""

from pathlib import Path

import pandas as pd

DEFAULT_CACHE_ROOT = Path(__file__).resolve().parent.parent / "data" / "cache"


def cache_path(cache_root: Path, subdir: str, key: str, day) -> Path:
    return cache_root / subdir / str(key) / f"{day.isoformat()}.csv"


def read_day_cache(cache_root: Path, subdir: str, key: str, day, columns: list[str]) -> pd.DataFrame | None:
    path = cache_path(cache_root, subdir, key, day)
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        df.index = df.index.tz_convert("Europe/Stockholm")
        return df[columns]
    except Exception:
        return None


def write_day_cache(cache_root: Path, subdir: str, key: str, day, df: pd.DataFrame) -> None:
    path = cache_path(cache_root, subdir, key, day)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        df.tz_convert("UTC").to_csv(path)
    except OSError:
        pass
