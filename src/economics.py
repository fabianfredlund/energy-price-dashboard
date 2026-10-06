"""Three-year aggregation, the deduction, payback, and the two verdicts.

This module turns hourly simulation output into the four answers the
dashboard exists to give: is solar worth it, what does it pay back in and
save per year, should they get a battery, and how big.

Pure functions. No Streamlit, no I/O, and — like `battery.py` — **nothing is
read from `config.py`**. Every assumption arrives as an argument, because the
UI lets the advisor edit them and a value read behind their back would be
silently ignored.

Two conventions worth stating once:

- **Averaging is a plain mean of the per-year totals, with no
  day-normalisation.** One of the three years is a leap year, worth a couple
  of SEK against a year-to-year spread of thousands. Correcting for it would
  move the headline by ~0.01% while requiring an explanation nobody can see
  on screen. `year_spans` asserts each span is a whole year instead, so a
  future window that silently clips fails loudly.
- **The battery's payback is marginal** — battery cost divided by what the
  battery adds on top of solar. It is the only reading that means anything
  against a *battery* lifetime, and the UI has to say so, or an advisor will
  read it as the whole system's payback.
"""

from datetime import date, timedelta
from typing import NamedTuple

import pandas as pd

STOCKHOLM = "Europe/Stockholm"


# -- the window, split into years ---------------------------------------------

class YearSpan(NamedTuple):
    start: date
    end: date  # inclusive
    label: str  # "Oct 2023 – Sep 2024"


def year_spans(start: date, end: date) -> tuple[YearSpan, ...]:
    """Split [start, end] into whole years on the anniversary of `start`.

    Raises if the window is not a whole number of years. That is deliberate:
    a window quietly clipped to 2 years 11 months would still produce a
    plausible-looking average, and nothing on screen would reveal it.
    """
    spans = []
    span_start = start
    while span_start <= end:
        span_end = span_start.replace(year=span_start.year + 1) - timedelta(days=1)
        if span_end > end:
            raise ValueError(
                f"window {start}..{end} is not a whole number of years: "
                f"the final span would run to {span_end}"
            )
        spans.append(YearSpan(
            span_start, span_end,
            f"{span_start:%b %Y} – {span_end:%b %Y}",
        ))
        span_start = span_end + timedelta(days=1)
    if not spans:
        raise ValueError(f"empty window: {start}..{end}")
    return tuple(spans)


def yearly_net_cost(detail: pd.DataFrame, spans: tuple[YearSpan, ...]) -> tuple[float, ...]:
    """Net electricity cost for each span, from one simulation's flow table.

    Slices on tz-aware timestamps rather than day arithmetic -- the window
    contains three spring-forwards and three fall-backs, and a `Timedelta`
    day lands an hour off on each of them.
    """
    totals = []
    for span in spans:
        start_ts = pd.Timestamp(span.start, tz=STOCKHOLM)
        end_ts = pd.Timestamp(span.end, tz=STOCKHOLM) + pd.DateOffset(days=1)
        rows = detail.loc[(detail.index >= start_ts) & (detail.index < end_ts)]
        totals.append(float(rows["net_cost_sek"].sum()))
    return tuple(totals)


# -- savings -------------------------------------------------------------------

class Savings(NamedTuple):
    per_year: tuple[float, ...]

    @property
    def average(self) -> float:
        return sum(self.per_year) / len(self.per_year) if self.per_year else 0.0

    @property
    def lowest(self) -> float:
        return min(self.per_year) if self.per_year else 0.0

    @property
    def highest(self) -> float:
        return max(self.per_year) if self.per_year else 0.0


def savings(baseline: tuple[float, ...], scenario: tuple[float, ...]) -> Savings:
    """What `scenario` saves against `baseline`, year by year."""
    if len(baseline) != len(scenario):
        raise ValueError("baseline and scenario must cover the same years")
    return Savings(tuple(b - s for b, s in zip(baseline, scenario)))


# -- the green technology deduction --------------------------------------------

class Deduction(NamedTuple):
    solar_sek: float
    battery_sek: float
    cap_sek: float
    capped: bool  # True when the cap bit, i.e. the full rates were not granted

    @property
    def total_sek(self) -> float:
        return self.solar_sek + self.battery_sek


def green_tech_deduction(
    system_price_sek: float,
    battery_price_sek: float,
    *,
    enabled: bool,
    owners: int,
    solar_rate: float,
    battery_rate: float,
    cap_per_owner_sek: float,
) -> Deduction:
    """Skattereduktion för grön teknik, with the combined cap applied.

    The cap is per owner per year and **combined** across solar and battery,
    so when it binds something has to give. **Solar is deducted first and the
    battery takes what is left.** Three reasons, in order of how much they
    matter: solar is bought first in reality; it keeps the solar verdict
    stable while the battery sizes are swept, which would otherwise make the
    solar card jump about for reasons the advisor cannot explain; and it is
    the conservative choice for the marginal battery decision.

    Doubling the cap requires joint *ownership* and a split invoice — two
    adults living in the house is not enough — which is why the UI asks for
    owners rather than people.
    """
    if not enabled:
        return Deduction(0.0, 0.0, 0.0, capped=False)

    cap = cap_per_owner_sek * max(1, owners)
    wanted_solar = system_price_sek * solar_rate
    wanted_battery = battery_price_sek * battery_rate

    solar = min(wanted_solar, cap)
    battery = min(wanted_battery, max(0.0, cap - solar))
    capped = (solar + battery) < (wanted_solar + wanted_battery) - 1e-9
    return Deduction(solar, battery, cap, capped)


# -- payback -------------------------------------------------------------------

def payback_years(net_investment_sek: float, average_yearly_saving_sek: float) -> float | None:
    """Simple payback. None when it never pays back, rather than infinity.

    Deliberately not NPV: no discounting, no electricity-price drift, no
    panel degradation. Over 15-25 years that is not a rounding error, and the
    UI says so — but a figure an advisor can derive on a napkin is worth more
    here than a defensible one they cannot explain.
    """
    if average_yearly_saving_sek <= 0:
        return None
    return net_investment_sek / average_yearly_saving_sek


# -- the sweep and the verdicts ------------------------------------------------

class YearlyCosts(NamedTuple):
    """Everything the expensive hourly layer needs to hand to the cheap one.

    Deliberately tiny — a few floats per battery size — so it can be cached
    freely. Caching the simulation's detail frames instead would be megabytes
    per entry for data no screen element reads.
    """
    spans: tuple[YearSpan, ...]
    no_solar: tuple[float, ...]
    by_size: dict  # capacity_kwh -> per-year net cost
    production_kwh_per_year: float
    curtailed_kwh_per_year: float
    self_consumption_by_size: dict
    grid_charge_days_by_size: dict


class SizeResult(NamedTuple):
    capacity_kwh: int
    gross_price_sek: float
    deduction_sek: float
    net_investment_sek: float
    savings: Savings  # vs no-solar for solar; vs solar-only for a battery
    payback_years: float | None
    pays_back: bool  # within the horizon the verdict is judged against (service life)
    within_warranty: bool  # also inside the shorter warranty -- a stronger, lower-risk result.
                            # For solar, which has no separate warranty concept, this mirrors
                            # pays_back.


class Recommendation(NamedTuple):
    solar: SizeResult
    solar_worth_it: bool
    sizes: tuple[SizeResult, ...]  # the battery sizes, excluding 0
    recommended: SizeResult | None  # None => "Battery: No"
    best_candidate: SizeResult | None  # shortest payback even if it does not pay back
    extra_income_to_flip_sek: float | None  # see below; None unless recommended is None


def recommend(
    costs: YearlyCosts,
    *,
    system_price_sek: float,
    battery_price_per_kwh_sek: float,
    settings,
) -> Recommendation:
    """The four answers.

    `settings` is duck-typed (in practice `config.Settings`) and must expose
    the two lifetimes, the service life, the other-income figure, and the
    five green-tech fields.

    Solar is judged against the solar lifetime on the saving versus no solar.

    **Each battery size is judged against its expected service life, not its
    warranty.** Test finding, 2026-10-06: judging against the 10-year warranty
    made every realistically-priced battery say "No" -- including ones that
    comfortably pay for themselves over their real working life. A warranty is
    a manufacturer's guarantee against defects, not a statement that the asset
    stops being useful the day it expires, so it is the wrong yardstick for
    "is this worth it". `within_warranty` still reports the stricter, lower-
    risk result for disclosure -- a battery that pays back inside the warranty
    is a stronger case than one that needs its full expected life to break
    even, and the UI says so either way.

    `settings.other_battery_income_sek_per_year` folds in value streams this
    model cannot honestly derive itself -- grid support services (stödtjänster)
    and capacity-charge savings (effektavgift) both depend on the customer's
    real hourly load, and this tool's consumption profile is a modelled
    assumption, not that. Defaults to 0 (none assumed); an advisor enters a
    real figure from an aggregator offer or the customer's tariff, and it is
    added to every battery size's yearly saving before payback is computed.

    When no size pays back, `extra_income_to_flip_sek` is how much additional
    yearly income (on top of whatever is already entered) the best candidate
    would need to cross into "worth it" -- a concrete number for the
    "what would it take" conversation, rather than a bare "No".
    """
    solar_only_costs = costs.by_size[0]

    def deduction_for(battery_gross: float) -> Deduction:
        return green_tech_deduction(
            system_price_sek, battery_gross,
            enabled=settings.green_tech_enabled,
            owners=settings.green_tech_owners,
            solar_rate=settings.green_tech_solar_rate,
            battery_rate=settings.green_tech_battery_rate,
            cap_per_owner_sek=settings.green_tech_cap_per_owner_sek,
        )

    # -- solar, judged on its own and with no battery in the picture --
    solar_deduction = deduction_for(0.0)
    solar_net = system_price_sek - solar_deduction.solar_sek
    solar_savings = savings(costs.no_solar, solar_only_costs)
    solar_payback = payback_years(solar_net, solar_savings.average)
    solar_worth_it = solar_payback is not None and solar_payback < settings.solar_lifetime_years
    solar = SizeResult(
        0, system_price_sek, solar_deduction.solar_sek, solar_net,
        solar_savings, solar_payback, solar_worth_it, solar_worth_it,
    )

    # -- each battery size, on its marginal saving over solar alone --
    sizes = []
    for capacity in sorted(k for k in costs.by_size if k > 0):
        gross = capacity * battery_price_per_kwh_sek
        deduction = deduction_for(gross)
        net = gross - deduction.battery_sek
        marginal = savings(solar_only_costs, costs.by_size[capacity])
        if settings.other_battery_income_sek_per_year:
            marginal = Savings(tuple(
                v + settings.other_battery_income_sek_per_year for v in marginal.per_year
            ))
        payback = payback_years(net, marginal.average)
        sizes.append(SizeResult(
            capacity, gross, deduction.battery_sek, net, marginal, payback,
            pays_back=payback is not None and payback < settings.battery_service_life_years,
            within_warranty=payback is not None and payback < settings.battery_lifetime_years,
        ))

    paying = [s for s in sizes if s.pays_back]
    with_payback = [s for s in sizes if s.payback_years is not None]
    recommended = min(paying, key=lambda s: s.payback_years) if paying else None
    best_candidate = min(with_payback, key=lambda s: s.payback_years) if with_payback else None

    # The concrete number for "what would it take": how much more yearly
    # income the best candidate needs to cross the service-life horizon.
    # Algebraically non-negative whenever this branch is reached: recommended
    # is None means best_candidate.payback_years >= service_life, which is
    # equivalent to its average saving <= net / service_life (= needed_average
    # below), so needed_average - average is >= 0.
    extra_income_to_flip_sek = None
    if recommended is None and best_candidate is not None:
        needed_average = best_candidate.net_investment_sek / settings.battery_service_life_years
        extra_income_to_flip_sek = max(0.0, needed_average - best_candidate.savings.average)

    return Recommendation(
        solar, solar_worth_it, tuple(sizes), recommended, best_candidate,
        extra_income_to_flip_sek,
    )


# -- the payback curve ---------------------------------------------------------

def payback_curve(
    recommendation: Recommendation,
    *,
    solar_lifetime_years: int,
    battery_credit_years: int,
) -> pd.DataFrame:
    """Cumulative savings per year, long form, for the two series.

    Columns: `year`, `series`, `average`, `lowest`, `highest`.

    **The battery is retired at `battery_credit_years`, not replaced.** From
    that year on, the "solar + battery" series keeps accruing *solar-only*
    savings, so the two lines run to the same horizon and stay a fixed
    distance apart — and that gap is the battery's net lifetime result,
    readable off the chart without arithmetic. Replacing it instead would
    require assuming the price of a battery a decade from now, which nothing
    here knows.

    Pass the battery's **expected service life** here, not its warranty —
    that is the horizon `recommend()` actually judges the battery against, so
    the chart's retirement point has to agree with the card's verdict or the
    two would visibly contradict each other.
    """
    rows = []
    solar = recommendation.solar

    def add(series: str, years: int, invest, step):
        for year in range(years + 1):
            rows.append({
                "year": year,
                "series": series,
                "average": -invest + sum(step(y)[0] for y in range(1, year + 1)),
                "lowest": -invest + sum(step(y)[1] for y in range(1, year + 1)),
                "highest": -invest + sum(step(y)[2] for y in range(1, year + 1)),
            })

    s = solar.savings
    add("Solar only", solar_lifetime_years, solar.net_investment_sek,
        lambda y: (s.average, s.lowest, s.highest))

    battery = recommendation.recommended or recommendation.best_candidate
    if battery is not None:
        b = battery.savings

        def step(year: int):
            if year <= battery_credit_years:
                return (s.average + b.average, s.lowest + b.lowest, s.highest + b.highest)
            return (s.average, s.lowest, s.highest)  # battery retired

        add(
            f"Solar + {battery.capacity_kwh} kWh battery",
            solar_lifetime_years,
            solar.net_investment_sek + battery.net_investment_sek,
            step,
        )

    return pd.DataFrame(rows)


def break_even_year(curve: pd.DataFrame, series: str) -> int | None:
    """First whole year where a series' cumulative average turns positive."""
    rows = curve[(curve["series"] == series) & (curve["average"] >= 0)]
    return int(rows["year"].iloc[0]) if not rows.empty else None


# -- the "why?" chart ----------------------------------------------------------

#: Months counted as summer and winter for the average-day chart. Split so
#: each half is six months; the point is the contrast between them.
SUMMER_MONTHS = (4, 5, 6, 7, 8, 9)
WINTER_MONTHS = (10, 11, 12, 1, 2, 3)


def average_day(frame: pd.DataFrame, months: tuple | None = None) -> pd.DataFrame:
    """Mean production and mean spot price for each hour of the day.

    Returns 24 rows: `hour`, `production_kwh`, `ore_per_kwh`. `months`
    restricts the input; None averages the whole window.

    This is the one chart whose job is explanation rather than conclusion:
    production peaks at midday when the price is at its lowest, and the price
    peaks in the evening when the roof has stopped. Everything else on the
    page is a verdict; this is the reason behind it.

    Averaging deliberately destroys spikes, which is why the result must
    never be re-quantiled into price categories — doing so would label an
    averaged 76 öre hour a "spike" when the true hourly 90th percentile over
    the window is far higher.
    """
    rows = frame if months is None else frame[frame.index.month.isin(months)]
    if rows.empty:
        return pd.DataFrame({"hour": range(24), "production_kwh": 0.0, "ore_per_kwh": 0.0})
    grouped = rows.groupby(rows.index.hour)
    out = pd.DataFrame({
        "production_kwh": grouped["production_kwh"].mean(),
        "ore_per_kwh": grouped["SEK_per_kWh"].mean() * 100,
    })
    return out.reindex(range(24)).fillna(0.0).rename_axis("hour").reset_index()
