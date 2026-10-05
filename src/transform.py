"""Resampling, aggregation, and price colour categorization.

Pure functions only: DataFrame in, DataFrame out. No fetching, no caching,
no Streamlit, no unit conversion (öre/kWh conversion is app.py's job).
"""

from typing import NamedTuple

import pandas as pd

CATEGORY_ORDER = ["Cheap", "Normal", "Expensive", "Spike"]


def resample_daily_mean(df: pd.DataFrame, columns: list[str] | None = None) -> pd.DataFrame:
    """Hourly tz-aware DataFrame -> one row per Europe/Stockholm calendar day.

    `columns` must be passed explicitly for a frame carrying any non-numeric
    column -- resample().mean() raises TypeError on a mixed frame, it does
    not silently skip the non-numeric column.

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


class PriceKPIs(NamedTuple):
    avg_price: float
    cheapest_time: pd.Timestamp
    cheapest_price: float
    priciest_time: pd.Timestamp
    priciest_price: float
    daily_spread: float


def price_kpis(df: pd.DataFrame, price_col: str) -> PriceKPIs | None:
    """Summary stats for the KPI cards. Always call with the TRUE hourly
    frame, never resample_daily_mean's output -- "cheapest hour" and
    daily_spread lose their meaning on daily-aggregated rows.

    Returns None for an empty df (idxmin/idxmax raise ValueError on an
    empty Series) -- caller shows a message instead of a KPI row.

    daily_spread = mean over calendar days actually present of (that
    day's max price - that day's min price) -- the average gap between
    each day's high and low.
    """
    if df.empty:
        return None
    s = df[price_col]
    daily = s.groupby(s.index.date).agg(["max", "min"])
    return PriceKPIs(
        avg_price=float(s.mean()),
        cheapest_time=s.idxmin(),
        cheapest_price=float(s.min()),
        priciest_time=s.idxmax(),
        priciest_price=float(s.max()),
        daily_spread=float((daily["max"] - daily["min"]).mean()),
    )


def hourly_month_means(df: pd.DataFrame, price_col: str) -> pd.DataFrame:
    """Long-form mean price per (month, hour) across the period -- up to
    12*24=288 rows, one per month x hour-of-day combination actually
    present (fewer for a short range). month: 1=January..12=December
    (pandas' own .month convention). Feed straight into
    categorize_by_price(result, price_col) unmodified -- the up-to-288
    cells become the population for its relative quantiles.

    Month x hour replaced v1's weekday x hour in the pivot: the sales
    story is seasonal, not weekly. What the advisor needs to show is that
    the expensive cells cluster on winter mornings and evenings while
    solar production peaks at summer midday -- a weekday axis averages
    that contrast away, because January and July land in the same cell.

    Gotcha: grouping by df.index.month/df.index.hour directly and
    calling reset_index() produces unnamed level_0/level_1 columns --
    the Index objects must be .rename()d first.
    """
    if df.empty:
        return pd.DataFrame(columns=["month", "hour", price_col])
    month = df.index.month.rename("month")
    hour = df.index.hour.rename("hour")
    return df.groupby([month, hour])[price_col].mean().reset_index()


# The four destinations of every produced kWh, in descending order of
# value to the customer: avoided buy price, avoided buy price later,
# earned roughly spot, earned nothing. Matches the production side of
# battery.py's energy-balance invariant.
PRODUCTION_SPLIT_LABELS = {
    "own_use_kwh": "Own use",
    "to_battery_kwh": "To battery",
    "sold_kwh": "Sold",
    "curtailed_kwh": "Curtailed",
}


def production_split(detail: pd.DataFrame) -> pd.Series:
    """Yearly kWh per destination, for the "where does the solar power
    go" donut. Index: the plain-language labels, in value order.

    By battery.py's per-hour invariant
    (`production = own_use + to_battery + sold + curtailed`) these four
    sum to total production, so the donut is a true part-to-whole and the
    caller can label its centre with the total rather than recomputing
    it. Empty frame -> four zeros, so the caller branches on the total
    rather than on a missing index.
    """
    if detail.empty:
        return pd.Series(
            {label: 0.0 for label in PRODUCTION_SPLIT_LABELS.values()}, dtype="float64"
        )
    return pd.Series(
        {label: float(detail[col].sum()) for col, label in PRODUCTION_SPLIT_LABELS.items()},
        dtype="float64",
    )
