"""Household consumption profile — a stated assumption, not measured data.

There is no open data for an individual villa's hourly consumption, so the
advisor enters an annual kWh figure and this module spreads it over the
hours using a typical shape: a daily curve with morning and evening peaks,
scaled by monthly factors that are heavier in winter (Swedish villas are
largely electrically heated).

Every number here is an assumption and is shown in the UI's Assumptions
expander. The shape matters more than the absolute numbers: what drives
the whole analysis is *when* the household uses power relative to when the
sun shines and when power is expensive.

Normalisation is deliberately anchored to a reference year, not to the
period being simulated. Scaling the weights so they sum to the annual
figure *over whatever index is passed* would bill a full year's
electricity across a one-week simulation, and Sprint 7's "Tomorrow" view
is a single day. Anchoring to a fixed reference-year total means a week in
January correctly draws more than a week in July, and a full year lands on
the entered figure.
"""

import pandas as pd

# Relative weights by hour of day (mean 1.0). Night trough, a sharp
# breakfast peak, a dip while the house is empty, then the big evening peak
# when people cook, shower and charge things.
# TODO: Fabian verifies against a real load profile if one is available.
DAILY_SHAPE: tuple[float, ...] = (
    0.70, 0.65, 0.62, 0.60, 0.62, 0.70,  # 00-05
    0.95, 1.35, 1.40, 1.15, 1.00, 0.95,  # 06-11
    0.92, 0.90, 0.92, 1.00, 1.20, 1.45,  # 12-17
    1.50, 1.40, 1.25, 1.10, 0.95, 0.72,  # 18-23
)

# Relative weights by month (mean 1.0). Winter:summer ratio ~2.6, which is
# in the right range for a heat-pump-heated villa in western Sweden.
# TODO: Fabian verifies.
MONTHLY_FACTORS: tuple[float, ...] = (
    1.45, 1.40, 1.25, 1.00, 0.75, 0.60,  # Jan-Jun
    0.55, 0.60, 0.75, 1.00, 1.25, 1.40,  # Jul-Dec
)

# Sum of hourly weights over a plain 365-day year. Computed once here so
# the scale factor never depends on the period being simulated.
REFERENCE_YEAR_WEIGHT_SUM: float = sum(
    sum(DAILY_SHAPE) * MONTHLY_FACTORS[month - 1] * days
    for month, days in enumerate(
        [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31], start=1
    )
)


def hourly_weights(index: pd.DatetimeIndex) -> pd.Series:
    """Relative consumption weight per hour: daily shape x monthly factor.

    Unitless and un-normalised -- `consumption_profile` turns these into
    kWh.
    """
    if len(index) == 0:
        return pd.Series(dtype="float64", index=index)
    daily = pd.Series([DAILY_SHAPE[h] for h in index.hour], index=index)
    monthly = pd.Series([MONTHLY_FACTORS[m - 1] for m in index.month], index=index)
    return daily * monthly


def consumption_profile(index: pd.DatetimeIndex, annual_kwh: float) -> pd.Series:
    """Estimated household consumption in kWh for each hour in `index`.

    A full year sums to `annual_kwh` within a fraction of a percent (the
    residual is a DST artefact: the hour March loses and the hour October
    gains sit in months with different factors). Shorter periods sum to
    their seasonally-correct share, which is the point of anchoring to a
    reference year rather than to the index.

    annual_kwh=0 gives an all-zero series -- a legitimate "no load" case,
    not an error.
    """
    weights = hourly_weights(index)
    if weights.empty:
        return weights
    return weights * (annual_kwh / REFERENCE_YEAR_WEIGHT_SUM)
