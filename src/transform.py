"""Resampling, aggregation, and price colour categorization.

Pure functions only: DataFrame in, DataFrame out. No fetching, no caching,
no Streamlit, no unit conversion (öre/kWh conversion is app.py's job).
"""

import pandas as pd

CATEGORY_ORDER = ["Cheap", "Normal", "Expensive", "Spike"]


def resample_daily_mean(df: pd.DataFrame, columns: list[str] | None = None) -> pd.DataFrame:
    """Hourly tz-aware DataFrame -> one row per Europe/Stockholm calendar day.

    `columns` must be passed explicitly for a frame with non-numeric columns
    (e.g. weather_df's `quality`) -- resample().mean() raises TypeError on a
    mixed frame, it does not silently skip the non-numeric column.

    A day with NO rows at all (a confirmed-404 gap) produces no output row:
    resample("1D") would otherwise insert a NaN row for it, which
    dropna(how="all") removes. A day with SOME but not all hours present
    keeps the mean of whichever hours are present -- a partial-day mean,
    deliberately not treated the same as a full gap.
    """
    if df.empty:
        return df.copy()
    cols = columns or list(df.columns)
    return df[cols].resample("1D").mean().dropna(how="all")


def categorize_by_price(df: pd.DataFrame, price_col: str) -> pd.DataFrame:
    """Add a `category` column (Cheap/Normal/Expensive/Spike) based on
    `price_col`'s OWN quantiles within `df` -- works identically on hourly
    rows or daily-aggregated rows, since it's agnostic to what a row
    represents.

    Boundaries (CLAUDE.md): price <= p33 -> Cheap; p33 < price <= p67 ->
    Normal; p67 < price <= p90 -> Expensive; price > p90 -> Spike.

    Implemented as a boolean-mask cascade, not pd.cut -- pd.cut raises
    ValueError ("Bin edges must be unique") when every price is identical,
    which a single flat-priced day would trigger.

    Edge cases, verified to never raise:
    - Empty df -> empty df, `category` column present (object dtype).
    - Single row, or every row sharing one identical price -> every row is
      "Cheap" (p33/p67/p90 all equal that price; price <= p33 holds for all).
    - A sample small enough that nothing exceeds the interpolated 90th
      percentile -> zero "Spike" rows. Expected: a relative top-10%
      carve-out, not a guarantee a spike always exists in any given sample.
    """
    out = df.copy()
    if out.empty:
        out["category"] = pd.Series(dtype="object")
        return out
    p33, p67, p90 = out[price_col].quantile([0.33, 0.67, 0.90])
    category = pd.Series("Spike", index=out.index, dtype="object")
    category[out[price_col] <= p90] = "Expensive"
    category[out[price_col] <= p67] = "Normal"
    category[out[price_col] <= p33] = "Cheap"
    out["category"] = category
    return out
