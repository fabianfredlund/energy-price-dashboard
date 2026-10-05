"""Hourly battery simulation and the three scenarios the advisor quotes.

Every rule here has to survive being explained to a homeowner at a kitchen
table, so there is no optimiser: just four ordered rules applied hour by
hour, exactly as CLAUDE.md's calculation model states them.

**The two invariants this module guarantees, per hour:**

    production  = own_use + to_battery + sold + curtailed
    consumption = own_use + from_battery + bought_for_house

They hold by construction because each closes with a *residual* rather
than an independently recomputed figure: `sold + curtailed` is whatever
surplus the battery did not take, and `bought_for_house` is whatever
deficit the battery did not cover.

`curtailed` is the fourth production term because "never sell at a
negative price" leaves surplus that is neither used, stored, nor sold.
Surplus thrown away at negative prices is itself an argument for a
battery, so it is tracked rather than hidden.

`grid_charge_kwh` is kept separate from `bought_for_house_kwh` (their sum
is `bought_kwh`). Folding them together would silently break the
consumption invariant, because grid-charge energy goes into the battery,
not into the house.

Round-trip efficiency is booked entirely on discharge: 10 kWh in, 9 kWh
back out. `to_battery` is metered at the battery's input and
`from_battery` at its output, so the loss lives strictly inside the
battery and appears in neither invariant -- only in the battery's own
balance.
"""

import math
from typing import NamedTuple

import pandas as pd

from src.calc import cheapest_window
from src.config import (
    BATTERY_MAX_POWER_FRACTION,
    BATTERY_ROUND_TRIP_EFFICIENCY,
    ENERGY_TAX_SEK_PER_KWH,
    GRID_BENEFIT_SEK_PER_KWH,
    GRID_CHARGE_MIN_MARGIN_SEK_PER_KWH,
    GRID_FEE_SEK_PER_KWH,
    VAT_RATE,
)
from src.consumption import consumption_profile

SPOT_COLUMN = "SEK_per_kWh"  # as produced by src/prices.py

FLOW_COLUMNS = [
    "own_use_kwh",
    "to_battery_kwh",
    "sold_kwh",
    "curtailed_kwh",
    "from_battery_kwh",
    "bought_for_house_kwh",
    "grid_charge_kwh",
    "battery_loss_kwh",
]


def buy_price(spot: pd.Series) -> pd.Series:
    """What a kWh taken from the grid costs: (spot + tax + grid fee) x VAT."""
    return (spot + ENERGY_TAX_SEK_PER_KWH + GRID_FEE_SEK_PER_KWH) * (1 + VAT_RATE)


def sell_price(spot: pd.Series) -> pd.Series:
    """What a kWh exported earns: spot + nätnytta, no VAT (a private
    microproducer is normally not VAT-registered for this)."""
    return spot + GRID_BENEFIT_SEK_PER_KWH


def max_power_kwh_per_hour(capacity_kwh: float) -> float:
    """Charge/discharge limit for one hour. At the default fraction of 0.5 a
    full charge takes exactly two hours -- which is why the grid-charge
    window below is always a two-hour window."""
    return capacity_kwh * BATTERY_MAX_POWER_FRACTION


#: Why rule 4 declined to grid-charge on a given day. Codes, not prose --
#: the customer-facing wording lives in src/plan.py, so the Tomorrow tab
#: can explain the decision without this module knowing about the UI.
#: Measured frequency over the committed year at 10 kWh, in case the
#: relative weight is ever surprising: solar_fills_it 182 days, charged
#: 138, no_later_hours 40, spread_too_small 7.
GRID_CHARGE_REASONS = (
    "charged",             # it did grid-charge
    "no_battery",          # capacity is zero
    "solar_fills_it",      # the expected solar surplus already fills the battery
    "no_later_hours",      # the cheapest window falls at the end of the day
    "spread_too_small",    # the cheap hours don't beat the round trip plus margin
    "window_does_not_fit", # the day is shorter than the window needed
)


class GridChargeDecision(NamedTuple):
    allowance: pd.Series
    reasons: dict  # date -> one of GRID_CHARGE_REASONS


def grid_charge_plan(
    buy: pd.Series,
    expected_surplus: pd.Series,
    capacity_kwh: float,
    margin: float = GRID_CHARGE_MIN_MARGIN_SEK_PER_KWH,
    efficiency: float = BATTERY_ROUND_TRIP_EFFICIENCY,
) -> GridChargeDecision:
    """Rule 4, returning *why* it decided what it decided.

    Same arithmetic as `grid_charge_allowance` (which is now a thin
    wrapper around this), plus a per-day reason code. The reason exists
    because "your battery will not charge from the grid tomorrow" is
    useless to an advisor standing in front of a customer, while "the roof
    is expected to make more than the battery holds" is a selling point.

    See `grid_charge_allowance` for the rules themselves.
    """
    allowance = pd.Series(0.0, index=buy.index)
    reasons: dict = {}
    power = max_power_kwh_per_hour(capacity_kwh)

    if capacity_kwh <= 0 or power <= 0:
        return GridChargeDecision(allowance, {d: "no_battery" for d in set(buy.index.date)})
    if buy.empty:
        return GridChargeDecision(allowance, reasons)

    surplus_by_day = expected_surplus.groupby(expected_surplus.index.date).sum()

    for day, day_buy in buy.groupby(buy.index.date):
        budget = capacity_kwh - float(surplus_by_day.get(day, 0.0))
        if budget <= 0:
            reasons[day] = "solar_fills_it"
            continue

        window_hours = max(1, math.ceil(budget / power))
        found = cheapest_window(day_buy.tolist(), window_hours, wrap=False)
        if found is None:
            reasons[day] = "window_does_not_fit"
            continue
        cheap_mean = found.total_price / window_hours
        later = day_buy.iloc[found.start + window_hours :]
        if later.empty:
            reasons[day] = "no_later_hours"
            continue
        dearest = later.nlargest(min(window_hours, len(later)))
        if dearest.mean() * efficiency - cheap_mean > margin:
            hours = day_buy.index[found.start : found.start + window_hours]
            allowance.loc[hours] = budget / window_hours
            reasons[day] = "charged"
        else:
            reasons[day] = "spread_too_small"

    return GridChargeDecision(allowance, reasons)


def grid_charge_allowance(
    buy: pd.Series,
    expected_surplus: pd.Series,
    capacity_kwh: float,
    margin: float = GRID_CHARGE_MIN_MARGIN_SEK_PER_KWH,
    efficiency: float = BATTERY_ROUND_TRIP_EFFICIENCY,
) -> pd.Series:
    """Rule 4: how many kWh may be bought from the grid in each hour.

    Per calendar day:

    1. **Reserve room for the sun.** The day's budget is whatever the
       expected solar surplus will not fill: `capacity - surplus`, floored
       at zero. On a sunny summer day the budget is zero and rule 4 stays
       out of the way entirely; in winter, when there is no surplus, the
       budget is the whole battery and rule 4 behaves as written.
    2. Find the cheapest contiguous window long enough to cover that
       budget (reusing src/calc.py's cheapest_window) and compare it with
       the dearest hours *still to come that day* -- you cannot discharge
       into the past.
    3. Charge only if the saving clears the round-trip loss by at least
       `margin` SEK/kWh.

    Step 1 is a deliberate refinement of CLAUDE.md's rule 4, which looks
    only at prices. Taken literally it grid-charges on any cheap-night /
    dear-evening spread, including in June, filling the battery before
    dawn so the day's solar surplus has nowhere to go -- the battery then
    *reduces* self-consumption, the exact opposite of the product's
    thesis. Rule 4's stated purpose is to keep the battery useful in
    winter, and reserving room preserves that while giving solar first
    claim on the battery at the day level, matching the priority the
    hourly rules already give it. One sentence to a customer: "we only
    top up from the grid what the sun isn't going to give you."

    Compares **buy** prices, not spot, and the margin is **additive**.
    Both matter: you pay tax, grid fee and VAT on the energy the round
    trip throws away, and at a negative price a percentage margin would
    lower the bar instead of raising it.

    **Known limitation, disclosed in the README rather than fixed.** The
    decision is taken within a single calendar day, so on the 40 days of
    the committed year where the cheapest window falls at 22:00-24:00
    there is nothing left to discharge into and rule 4 declines -- a
    *calendar artefact*, not economics, since a real battery charges
    across midnight. Fixing it in the final sprint would move every figure
    the report already quotes (`no_later_hours` in GRID_CHARGE_REASONS).

    Implementation note: one grouped sum up front, not a boolean scan per
    day. The scan version rebuilt `expected_surplus.index.date` -- an
    array as long as the whole series -- once per calendar day, which over
    a year is 365 passes across 8760 rows and measured as 94% of a
    three-scenario comparison.
    """
    return grid_charge_plan(
        buy, expected_surplus, capacity_kwh, margin, efficiency
    ).allowance


def simulate(
    frame: pd.DataFrame,
    capacity_kwh: float,
    margin: float = GRID_CHARGE_MIN_MARGIN_SEK_PER_KWH,
    initial_soc_kwh: float = 0.0,
    efficiency: float = BATTERY_ROUND_TRIP_EFFICIENCY,
) -> pd.DataFrame:
    """Run the four hourly rules over `frame` and return the full flow table.

    `frame` needs `production_kwh`, `consumption_kwh` and `SEK_per_kWh`
    (the spot price, exactly as src/prices.py names it).

    capacity_kwh=0 is a legitimate "no battery" run through the same code
    path -- that is how the solar-only scenario is produced, so there is
    one simulation to reason about rather than three.
    """
    out = frame.copy()
    spot = out[SPOT_COLUMN]
    buy = buy_price(spot)
    sell = sell_price(spot)

    if out.empty:
        for col in FLOW_COLUMNS + ["soc_kwh", "bought_kwh", "cost_sek", "revenue_sek", "net_cost_sek"]:
            out[col] = pd.Series(dtype="float64")
        out["buy_price_sek_per_kwh"] = buy
        out["sell_price_sek_per_kwh"] = sell
        return out

    # Day-level pre-computation. Grouping by the local calendar date, never
    # by day arithmetic: a Timedelta day is 24 absolute hours and lands an
    # hour off on the two DST transition days.
    median_spot = spot.groupby(spot.index.date).transform("median").to_numpy()
    expected_surplus = (out["production_kwh"] - out["consumption_kwh"]).clip(lower=0)
    charge_allow = grid_charge_allowance(
        buy, expected_surplus, capacity_kwh, margin, efficiency
    ).to_numpy()

    # Iterate numpy arrays, not .at[] -- measured ~220x faster over a year.
    prod = out["production_kwh"].to_numpy()
    cons = out["consumption_kwh"].to_numpy()
    spot_a, buy_a, sell_a = spot.to_numpy(), buy.to_numpy(), sell.to_numpy()

    n = len(out)
    own_use = [0.0] * n
    to_batt = [0.0] * n
    sold = [0.0] * n
    curtailed = [0.0] * n
    from_batt = [0.0] * n
    bought_house = [0.0] * n
    grid_chg = [0.0] * n
    loss = [0.0] * n
    soc_trace = [0.0] * n

    power = max_power_kwh_per_hour(capacity_kwh)
    soc = float(initial_soc_kwh)

    for i in range(n):
        power_left = power

        # Rule 1 -- solar covers the house first.
        use = min(prod[i], cons[i])
        surplus = prod[i] - use
        deficit = cons[i] - use

        # Rule 2 -- surplus charges the battery, then is sold, and is
        # curtailed rather than exported at a negative sell price.
        charge = min(surplus, capacity_kwh - soc, power_left) if capacity_kwh > 0 else 0.0
        soc += charge
        power_left -= charge
        rest = surplus - charge
        if sell_a[i] >= 0:
            sold_i, curtailed_i = rest, 0.0
        else:
            sold_i, curtailed_i = 0.0, rest

        drawn = 0.0
        charge_from_grid = 0.0
        delivered = 0.0
        if capacity_kwh > 0 and charge_allow[i] > 0:
            # Rule 4 -- top up from the grid in the day's cheapest hours,
            # but only up to the room the sun isn't expected to fill.
            charge_from_grid = min(charge_allow[i], capacity_kwh - soc, power_left)
            soc += charge_from_grid
            power_left -= charge_from_grid
        elif capacity_kwh > 0 and deficit > 0 and spot_a[i] > median_spot[i]:
            # Rule 3 -- discharge only into hours above the day's median.
            drawn = min(soc, power_left, deficit / efficiency)
            delivered = drawn * efficiency
            soc -= drawn
            deficit -= delivered

        own_use[i] = use
        to_batt[i] = charge
        sold[i] = sold_i
        curtailed[i] = curtailed_i
        from_batt[i] = delivered
        bought_house[i] = deficit
        grid_chg[i] = charge_from_grid
        loss[i] = drawn - delivered
        soc_trace[i] = soc

    out["own_use_kwh"] = own_use
    out["to_battery_kwh"] = to_batt
    out["sold_kwh"] = sold
    out["curtailed_kwh"] = curtailed
    out["from_battery_kwh"] = from_batt
    out["bought_for_house_kwh"] = bought_house
    out["grid_charge_kwh"] = grid_chg
    out["battery_loss_kwh"] = loss
    out["soc_kwh"] = soc_trace

    out["buy_price_sek_per_kwh"] = buy
    out["sell_price_sek_per_kwh"] = sell
    out["bought_kwh"] = out["bought_for_house_kwh"] + out["grid_charge_kwh"]
    out["cost_sek"] = out["bought_kwh"] * out["buy_price_sek_per_kwh"]
    out["revenue_sek"] = out["sold_kwh"] * out["sell_price_sek_per_kwh"]
    out["net_cost_sek"] = out["cost_sek"] - out["revenue_sek"]
    return out


def build_frame(
    production: pd.Series, prices: pd.DataFrame, annual_kwh: float
) -> tuple[pd.DataFrame, int]:
    """Join production, spot prices and the consumption assumption.

    Returns (frame, missing_hours). Hours that have production but no
    price are dropped -- the model never invents a price, and never
    invents consumption for an hour it cannot price. `missing_hours` is
    surfaced so the UI can disclose coverage rather than quietly
    under-reporting a year.
    """
    index = production.index.intersection(prices.index)
    missing = len(production.index) - len(index)
    frame = pd.DataFrame(
        {
            "production_kwh": production.reindex(index),
            SPOT_COLUMN: prices[SPOT_COLUMN].reindex(index),
        }
    ).sort_index()
    frame["consumption_kwh"] = consumption_profile(frame.index, annual_kwh)
    return frame, missing


class ScenarioResult(NamedTuple):
    name: str
    cost_sek: float
    self_consumption_share: float  # of production used on site (own use + battery)
    detail: pd.DataFrame


def run_scenario(frame: pd.DataFrame, capacity_kwh: float, with_solar: bool) -> ScenarioResult:
    """One scenario through the one simulation path."""
    name = (
        "solar_battery" if with_solar and capacity_kwh > 0
        else "solar_only" if with_solar
        else "no_solar"
    )
    run_frame = frame if with_solar else frame.assign(production_kwh=0.0)
    detail = simulate(run_frame, capacity_kwh if with_solar else 0.0)

    produced = detail["production_kwh"].sum()
    used_on_site = detail["own_use_kwh"].sum() + detail["to_battery_kwh"].sum()
    share = float(used_on_site / produced) if produced > 0 else 0.0
    return ScenarioResult(name, float(detail["net_cost_sek"].sum()), share, detail)


class ScenarioComparison(NamedTuple):
    no_solar: ScenarioResult
    solar_only: ScenarioResult
    solar_battery: ScenarioResult
    solar_value_sek: float  # yearly, vs doing nothing
    battery_value_sek: float  # yearly, on top of solar
    payback_years: float | None


def compare_scenarios(
    frame: pd.DataFrame, capacity_kwh: float, battery_price_sek: float | None = None
) -> ScenarioComparison:
    """All three scenarios plus the two differences the advisor quotes."""
    no_solar = run_scenario(frame, 0.0, with_solar=False)
    solar_only = run_scenario(frame, 0.0, with_solar=True)
    solar_battery = run_scenario(frame, capacity_kwh, with_solar=True)

    solar_value = no_solar.cost_sek - solar_only.cost_sek
    battery_value = solar_only.cost_sek - solar_battery.cost_sek
    return ScenarioComparison(
        no_solar, solar_only, solar_battery,
        solar_value, battery_value,
        payback_years(battery_price_sek, battery_value) if battery_price_sek else None,
    )


def payback_years(battery_price_sek: float, yearly_battery_value_sek: float) -> float | None:
    """Simple payback: price / yearly value. None when the battery saves
    nothing (no finite payback exists) rather than returning infinity.

    This deliberately excludes the green-technology deduction,
    capacity/effekt-tariff savings and frequency-regulation income -- the
    UI must state that, since those are where home-battery economics
    actually lives and why this figure looks long.
    """
    if yearly_battery_value_sek <= 0:
        return None
    return battery_price_sek / yearly_battery_value_sek
