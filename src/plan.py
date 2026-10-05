"""Turn one simulated day into a plan a homeowner can follow.

CLAUDE.md's target: "Charge from the grid 02-05, store solar 11-14, use
the battery 17-20". This module takes `battery.simulate`'s hourly flow
table and reduces it to a handful of ordered steps.

**Why this is not in battery.py.** That module is physics and economics,
pinned by the energy-balance invariant. Everything here is *presentation*:
which flows are big enough to mention, how adjacent hours merge into a
range, what to call them. Those are judgement calls that will change the
first time a real advisor reads the screen and says "that's not how I'd
put it" -- and when they do, no tested physics should be anywhere near the
edit.

**This module never computes money.** Every SEK figure is summed from the
detail frame's own realised flows times its own realised prices, so a step
can never claim a saving the simulation did not book. The reconciliation
test in tests/test_plan.py pins that.
"""

from typing import NamedTuple

import pandas as pd

#: Actions in the order they read as a day: fill the battery, then empty
#: it, then what happened to the leftovers.
ACTION_ORDER = ("grid_charge", "store_solar", "use_battery", "sell", "curtail")

#: Which detail column each action is measured by.
ACTION_COLUMN = {
    "grid_charge": "grid_charge_kwh",
    "store_solar": "to_battery_kwh",
    "use_battery": "from_battery_kwh",
    "sell": "sold_kwh",
    "curtail": "curtailed_kwh",
}

#: Plain language for the advisor to read aloud. Deliberately verbs, and
#: deliberately about the house rather than the equipment.
ACTION_LABEL = {
    "grid_charge": "Charge the battery from the grid",
    "store_solar": "Store solar power in the battery",
    "use_battery": "Run the house off the battery",
    "sell": "Sell the surplus",
    "curtail": "Throw surplus away (price below zero)",
}

#: An hour counts toward a step if it moved at least this much energy...
MIN_PLAN_KWH = 0.1
#: ...or at least this fraction of that action's biggest hour that day.
#: Per-action, not day-wide: a big sell peak would otherwise raise the bar
#: so far that a real but modest grid charge disappears (measured: that
#: happened on 3 days of the committed year).
PEAK_FRACTION = 0.10
#: A single quiet hour inside a run does not break it. Measured: a
#: tolerance of 2 merges two separate sell runs across an intervening
#: curtail step, which then reads as selling and discarding at once.
MAX_GAP_HOURS = 1

#: Why rule 4 declined, in words a customer can hear. Keyed by
#: battery.GRID_CHARGE_REASONS.
GRID_CHARGE_EXPLANATION = {
    "charged": "",
    "no_battery": "No battery selected, so there is nothing to charge.",
    "solar_fills_it": (
        "No grid charging needed — the roof is expected to make more than the "
        "battery holds, so the sun fills it for free. We only top up from the "
        "grid what the sun isn't going to give you."
    ),
    "no_later_hours": (
        "No grid charging: the cheapest hours fall at the very end of the day, "
        "with no expensive hours left afterwards to use the stored power in."
    ),
    "spread_too_small": (
        "No grid charging — the cheap hours aren't cheap enough to be worth the "
        "energy lost charging and discharging."
    ),
    "window_does_not_fit": (
        "No grid charging: the battery is too large to fill within this day's "
        "cheap hours."
    ),
}


class PlanStep(NamedTuple):
    action: str
    start: pd.Timestamp
    end: pd.Timestamp  # EXCLUSIVE -- the hour after the last one in the run
    hours: int  # priced hours inside the range, which on a DST day != wall-clock span
    kwh: float
    sek: float  # signed: positive = paid out, negative = earned or avoided
    extra_hours: int  # qualifying hours of this action outside the reported range
    extra_kwh: float


class DayPlan(NamedTuple):
    steps: tuple
    totals: dict  # action -> the day's total kWh, whether or not it made a step
    absent: tuple  # actions that did not happen at all today
    grid_charge_reason: str | None


def _qualifying_mask(values: pd.Series) -> pd.Series:
    """Which hours are worth mentioning for one action."""
    peak = float(values.max()) if len(values) else 0.0
    threshold = max(MIN_PLAN_KWH, peak * PEAK_FRACTION)
    return values >= threshold


def _runs(mask: pd.Series) -> list[tuple[int, int]]:
    """Consecutive qualifying stretches as [start, end) *positions*.

    Positional, never hour arithmetic: that is what makes the 23- and
    25-hour DST days come out right, since "the next hour" is the next row
    regardless of what the wall clock did. Tolerates a gap of up to
    MAX_GAP_HOURS non-qualifying hours inside a run.
    """
    positions = [i for i, flag in enumerate(mask.tolist()) if flag]
    if not positions:
        return []
    runs = []
    run_start = prev = positions[0]
    for pos in positions[1:]:
        if pos - prev - 1 > MAX_GAP_HOURS:
            runs.append((run_start, prev + 1))
            run_start = pos
        prev = pos
    runs.append((run_start, prev + 1))
    return runs


def _step_money(detail: pd.DataFrame, action: str, rows: pd.DataFrame) -> float:
    """SEK for one step, summed from realised flows x realised prices.

    Signed so the UI never has to know which way round an action goes:
    positive is money leaving the household, negative is money earned or
    not spent.

    `store_solar` and `curtail` are deliberately 0.0 -- no cash moves in
    that hour. Storing solar pays off later, when the battery discharges,
    and claiming it twice would double-count; curtailed power earns
    nothing by definition.
    """
    if action == "grid_charge":
        return float((rows["grid_charge_kwh"] * rows["buy_price_sek_per_kwh"]).sum())
    if action == "use_battery":
        # avoided cost: the grid power this hour did not need to buy
        return -float((rows["from_battery_kwh"] * rows["buy_price_sek_per_kwh"]).sum())
    if action == "sell":
        return -float((rows["sold_kwh"] * rows["sell_price_sek_per_kwh"]).sum())
    return 0.0


def build_day_plan(detail: pd.DataFrame, grid_charge_reason: str | None = None) -> DayPlan:
    """One day's flow table -> ordered plan steps.

    `detail` must be exactly one local calendar day of
    `battery.simulate`'s output. Pass the day's `grid_charge_reason` from
    `battery.grid_charge_plan` so the UI can explain an absent grid-charge
    step instead of leaving a hole.

    **One step per action** -- its largest run -- with any further
    qualifying hours reported as `extra_hours`/`extra_kwh`. A day where
    the battery discharges in four separate stretches would otherwise
    produce an eight-step wall of text that nobody reads aloud. Measured
    over the committed year: 2.5 steps a day, never more than 4.

    An empty frame gives an empty plan, not an error: "no prices published
    for tomorrow yet" is a normal afternoon condition.
    """
    if detail.empty:
        return DayPlan((), {a: 0.0 for a in ACTION_ORDER}, ACTION_ORDER, grid_charge_reason)

    totals = {a: float(detail[ACTION_COLUMN[a]].sum()) for a in ACTION_ORDER}
    steps = []
    absent = []

    for action in ACTION_ORDER:
        values = detail[ACTION_COLUMN[action]]
        if totals[action] < MIN_PLAN_KWH:
            absent.append(action)
            continue

        runs = _runs(_qualifying_mask(values))
        if not runs:
            absent.append(action)
            continue

        # the run that moved the most energy is the one worth naming
        scored = [(float(values.iloc[s:e].sum()), s, e) for s, e in runs]
        kwh, start_pos, end_pos = max(scored)
        rows = detail.iloc[start_pos:end_pos]
        other = sum(k for k, s, e in scored if (s, e) != (start_pos, end_pos))
        other_hours = sum(
            int(_qualifying_mask(values).iloc[s:e].sum())
            for k, s, e in scored
            if (s, e) != (start_pos, end_pos)
        )

        steps.append(PlanStep(
            action=action,
            start=rows.index[0],
            # exclusive end: the hour after the last row, so a range that
            # runs to the end of the day reads as "...-24:00"
            end=rows.index[-1] + pd.Timedelta(hours=1),
            hours=len(rows),
            kwh=kwh,
            sek=_step_money(detail, action, rows),
            extra_hours=other_hours,
            extra_kwh=other,
        ))

    steps.sort(key=lambda s: (ACTION_ORDER.index(s.action), s.start))
    return DayPlan(tuple(steps), totals, tuple(absent), grid_charge_reason)


def format_hour_range(step: PlanStep) -> str:
    """A clock interval with explicit minutes, plus the hour count.

    `"17:00-21:00"`, not CLAUDE.md's illustrative `"17-20"`: Swedish price
    apps label an hour by its start, so "17-20" reads as either three
    hours or four, and this is exactly the line a customer screenshots.

    The hour count is not decoration -- it is the DST disambiguator. A
    four-hour run across the repeated 02:00 on fall-back night renders
    "01:00-04:00 · 4 h": three wall-clock hours, four real ones. Printing
    the count makes that visible instead of silently wrong.
    """
    end_label = "24:00" if step.end.hour == 0 else f"{step.end:%H:%M}"
    return f"{step.start:%H:%M}–{end_label} · {step.hours} h"


def describe_step(step: PlanStep) -> str:
    """One line an advisor can read aloud, money included where money moved."""
    line = f"**{format_hour_range(step)}** — {ACTION_LABEL[step.action].lower()}"
    line += f", {step.kwh:.1f} kWh"
    if step.sek > 0.005:
        line += f" (costs {step.sek:.0f} SEK)"
    elif step.sek < -0.005:
        verb = "earns" if step.action == "sell" else "avoids"
        line += f" ({verb} {abs(step.sek):.0f} SEK)"
    if step.extra_hours:
        line += f" — plus {step.extra_kwh:.1f} kWh over another {step.extra_hours} h"
    return line
