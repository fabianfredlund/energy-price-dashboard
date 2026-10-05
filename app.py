"""Solar Advisor — a sales tool for Kustsol's energy advisors.

Tab 1 "Customer calculation" answers CLAUDE.md's five questions for a
made-up customer from the last 12 months of real SE3 prices and real
Gothenburg irradiance. Tab 2 "Tomorrow" makes the battery concrete;
Sprint 8 owns it.

Layout only. Every number comes from a pure function in src/ -- this file
wires widgets to those functions and renders the result.

**Scope rule, stated once and repeated in the UI:** the yearly SEK
figures, the donut, the scenario bars and the heatmap are always computed
over the full 12 months. The date picker zooms the overlay chart and
nothing else. Deriving a "yearly" figure from a hand-picked sunny week
would be indefensible in front of a customer.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from src.battery import build_frame, compare_scenarios
from src.config import (
    BATTERY_MAX_POWER_FRACTION,
    BATTERY_ROUND_TRIP_EFFICIENCY,
    DEFAULT_ANNUAL_CONSUMPTION_KWH,
    DEFAULT_BATTERY_KWH,
    DEFAULT_BATTERY_PRICE_SEK,
    DEFAULT_KWP,
    DEFAULT_ORIENTATION,
    ENERGY_TAX_SEK_PER_KWH,
    GRID_BENEFIT_SEK_PER_KWH,
    GRID_CHARGE_MIN_MARGIN_SEK_PER_KWH,
    GRID_FEE_SEK_PER_KWH,
    ORIENTATIONS,
    PANEL_TILT_DEG,
    PRICE_AREA,
    SYSTEM_LOSS_FACTOR,
    VAT_RATE,
)
from src.consumption import MONTHLY_FACTORS
from src.prices import fetch_prices
from src.solar import (
    PRODUCTION_COLUMN,
    fetch_irradiance,
    fetch_irradiance_forecast,
    production_kwh,
)
from src.transform import (
    CATEGORY_ORDER,
    categorize_by_price,
    hourly_month_means,
    production_split,
    resample_daily_mean,
)

STOCKHOLM = ZoneInfo("Europe/Stockholm")
HOURLY_BAR_MAX_DAYS = 31
MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

YEAR_DAYS = 365
# Open-Meteo's archive reaches roughly two days back, so "the last 12
# months" has to end there rather than today, or the most recent days come
# back empty and the year is quietly short.
ARCHIVE_LAG_DAYS = 2

# Cheap/Expensive/Spike reuse the dataviz skill's fixed status palette
# (good/serious/critical); Normal uses the skill's own "Muted" ink, per
# CLAUDE.md's explicit "middle third -> neutral grey" instruction. The
# skill's generic categorical-palette validator isn't the right tool for
# this combination (it expects distinct hues, not one deliberate neutral)
# -- the status palette is separately pre-validated in the skill's own
# reference for exactly this purpose. The borderline contrast/CVD pairs
# documented there are mitigated by secondary encoding already present
# here: Plotly's always-visible legend, the plain-language caption below
# every chart, and the per-bar hover tooltip, so colour is never the only
# signal.
CATEGORY_COLORS = {
    "Cheap": "#0ca30c",
    "Normal": "#898781",
    "Expensive": "#ec835a",
    "Spike": "#d03b3b",
}
PRODUCTION_COLOR = "#eda100"  # solar: the dataviz palette's yellow, distinct from every price category
LEGEND_CAPTION = "Green = cheap, grey = normal, orange = expensive, red = price spike (top 10%)."

# The donut's four destinations are ORDINAL, not categorical: own use ->
# battery -> sold -> curtailed is a strict value ranking (avoids the buy
# price, avoids it later, earns about spot, earns nothing). The dataviz
# skill prescribes a one-hue ramp for that, darkest = most valuable, so
# the reader sees the order in the colour. Two further reasons not to use
# four hues here: the obvious categorical foursome FAILS the skill's
# normal-vision separation gate on the orange/yellow pair (ΔE 13.7 against
# a floor of 15) and a donut compares every slice with every other through
# its legend; and CATEGORY_COLORS above is the reserved status palette,
# which the skill forbids reusing as "series 4".
FLOW_COLORS = {
    "Own use": "#0d366b",
    "To battery": "#1c5cab",
    "Sold": "#3987e5",
    "Curtailed": "#86b6ef",
}
# One hue for the three scenario bars, no legend: bar length already shows
# the progression, and the skill is explicit that colouring nominal bars
# by their value spends the identity channel re-encoding it.
SCENARIO_COLOR = "#2a78d6"
SURFACE = "#fcfcfb"

st.set_page_config(page_title="Solar Advisor", layout="wide")
st.title("Solar Advisor")
st.caption(
    f"Does solar — and a battery — pay off for this customer? "
    f"Real {PRICE_AREA} spot prices and real Gothenburg sunshine."
)


def _now_stockholm() -> datetime:
    return datetime.now(STOCKHOLM)


def _sek(value: float) -> str:
    """SEK with a thin space as the thousands separator, never öre.

    CLAUDE.md: all money in SEK. Per-kWh *rates* stay in öre/kWh on the
    chart and heatmap, which is the conventional Swedish unit for a rate;
    every total is SEK.
    """
    return f"{value:,.0f} SEK".replace(",", " ")


def _twelve_month_window(today: date) -> tuple[date, date]:
    end = today - timedelta(days=ARCHIVE_LAG_DAYS)
    return end - timedelta(days=YEAR_DAYS - 1), end


def _summer_week(start: date, end: date) -> tuple[date, date]:
    """A week in mid-June inside the window, so the pivot's whole point is
    visible before the advisor touches a control: production peaks at
    midday, exactly when the price bottoms out, while the price peaks in
    the evening when the roof has stopped producing.

    Derived from the window rather than hardcoded -- a fixed date would
    silently fall outside the range as the window rolls forward.
    """
    for year in (end.year, end.year - 1):
        candidate = date(year, 6, 15)
        if start <= candidate and candidate + timedelta(days=6) <= end:
            return candidate, candidate + timedelta(days=6)
    return max(start, end - timedelta(days=6)), end


# -- cached data and computation ----------------------------------------------
#
# Keyed on scalars only (date / str / float / None all hash correctly;
# DataFrames do not). Two things here are load-bearing rather than
# cosmetic:
#
# 1. Prices are keyed WITHOUT orientation. Both orientations are computed
#    for the question-5 comparison, and keying prices together with the
#    orientation would fetch a year of prices twice on first load.
# 2. max_entries is set everywhere. st.cache_data returns a copy, i.e. it
#    pickles, and a ScenarioComparison carries three 8760-row detail
#    frames (~4 MB). The default is unbounded, so a few minutes of slider
#    work would pile up hundreds of MB against Community Cloud's ~1 GB.
#
# Deliberately NO ttl on the two year-long fetchers: the key is the window
# itself, so the cache already invalidates when the window rolls over at
# midnight, and a settled past spot price never changes. A ttl would
# re-issue 365 requests every hour of a working session -- a stall in the
# middle of a customer meeting, and poor citizenship toward a free API.


@st.cache_data(max_entries=2, show_spinner=f"Fetching 12 months of {PRICE_AREA} spot prices…")
def _cached_year_prices(start: date, end: date):
    return fetch_prices(start, end, PRICE_AREA)


@st.cache_data(max_entries=4, show_spinner="Fetching 12 months of Gothenburg sunshine…")
def _cached_year_irradiance(start: date, end: date, orientation: str):
    return fetch_irradiance(start, end, orientation)


@st.cache_data(max_entries=8, show_spinner=False)
def _cached_year_frame(start: date, end: date, orientation: str, kwp: float, annual_kwh: float):
    prices, p_failed, p_fallback = _cached_year_prices(start, end)
    irradiance, s_failed, s_fallback = _cached_year_irradiance(start, end, orientation)
    production = production_kwh(irradiance, kwp)[PRODUCTION_COLUMN]
    frame, missing = build_frame(production, prices, annual_kwh)
    return frame, missing, (p_failed, p_fallback, s_failed, s_fallback)


@st.cache_data(max_entries=8, show_spinner="Simulating the year, hour by hour…")
def _cached_scenarios(start: date, end: date, orientation: str, kwp: float,
                      annual_kwh: float, capacity_kwh: float, battery_price_sek: float | None):
    frame, _, _ = _cached_year_frame(start, end, orientation, kwp, annual_kwh)
    return compare_scenarios(frame, capacity_kwh, battery_price_sek)


@st.cache_data(ttl=600)  # short TTL: "is tomorrow published yet" can flip within a session
def _cached_fetch_prices_tomorrow(start, end, area):
    return fetch_prices(start, end, area)


@st.cache_data(ttl=3600)
def _cached_fetch_irradiance_forecast(start, end, orientation):
    return fetch_irradiance_forecast(start, end, orientation)


def _render_fallback_notices(fallback_days: list, failed_days: list) -> None:
    if fallback_days:
        st.info(
            f"{len(fallback_days)} day(s) served from the offline cache — "
            f"API was unreachable, used the last cached snapshot."
        )
    if failed_days:
        st.warning(
            f"{len(failed_days)} day(s) could not be fetched and had no "
            f"cached fallback: {failed_days}"
        )


def _build_price_figure(price_df, price_col, prod_df=None, now_marker=None):
    """Price bars on top; when solar production is shown, a second panel
    below sharing the same time axis.

    Deliberately NOT a second y-axis on one panel: the dataviz skill
    treats dual-axis as the #1 chart mistake, and here the shared time
    axis is the whole point -- the advisor's pitch is *when* production
    happens versus *when* power is expensive, which you read off the x
    axis, not off two arbitrarily-aligned y scales.
    """
    show_prod = prod_df is not None and not prod_df.empty
    if show_prod:
        fig = make_subplots(
            rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
            row_heights=[0.7, 0.3],
        )
    else:
        fig = make_subplots(rows=1, cols=1)

    for cat in CATEGORY_ORDER:
        subset = price_df[price_df["category"] == cat]
        if subset.empty:
            continue
        fig.add_trace(
            go.Bar(
                x=subset.index, y=subset[price_col], name=cat,
                marker_color=CATEGORY_COLORS[cat],
                hovertemplate=f"%{{x|%Y-%m-%d %H:%M}}<br>%{{y:.1f}} öre/kWh<br>{cat}<extra></extra>",
            ),
            row=1, col=1,
        )

    if show_prod:
        fig.add_trace(
            go.Scatter(
                x=prod_df.index, y=prod_df[PRODUCTION_COLUMN], name="Solar production (kWh)",
                mode="lines", line=dict(color=PRODUCTION_COLOR, width=2),
                fill="tozeroy", fillcolor="rgba(237,161,0,0.15)",
                hovertemplate="%{x|%Y-%m-%d %H:%M}<br>%{y:.2f} kWh<extra></extra>",
            ),
            row=2, col=1,
        )

    if now_marker is not None:
        fig.add_vline(x=now_marker, line_dash="dot", line_color="#52514e",
                       annotation_text="Now", row=1, col=1)

    fig.update_layout(template="plotly_white", bargap=0.1, showlegend=True)
    fig.update_yaxes(gridcolor="#e1e0d9", title_text="öre/kWh", row=1, col=1)
    if show_prod:
        fig.update_yaxes(gridcolor="#e1e0d9", title_text="kWh", row=2, col=1)
    return fig


def _render_heatmap(prices_df, price_col):
    long_form = hourly_month_means(prices_df, price_col)
    if long_form.empty:
        st.info("Not enough data to build the hour × month heatmap for this range.")
        return
    coded = categorize_by_price(long_form, price_col)
    code_map = {cat: i for i, cat in enumerate(CATEGORY_ORDER)}
    coded["code"] = coded["category"].map(code_map)

    price_grid = coded.pivot(index="month", columns="hour", values=price_col).reindex(
        index=range(1, 13), columns=range(24)
    )
    code_grid = coded.pivot(index="month", columns="hour", values="code").reindex(
        index=range(1, 13), columns=range(24)
    )

    n = len(CATEGORY_ORDER)
    colorscale = []
    for i, cat in enumerate(CATEGORY_ORDER):
        colorscale += [[i / n, CATEGORY_COLORS[cat]], [(i + 1) / n, CATEGORY_COLORS[cat]]]

    fig = go.Figure(
        go.Heatmap(
            z=code_grid.values,
            x=[f"{h:02d}" for h in range(24)],
            y=MONTH_LABELS,
            zmin=-0.5, zmax=n - 0.5,
            colorscale=colorscale,
            customdata=price_grid.values,
            hovertemplate="%{y} %{x}:00<br>%{customdata:.1f} öre/kWh<extra></extra>",
            colorbar=dict(
                title="Category", tickmode="array",
                tickvals=list(range(n)), ticktext=CATEGORY_ORDER,
            ),
            xgap=2, ygap=2,
        )
    )
    fig.update_layout(
        template="plotly_white", title="Average price by hour of day and month"
    )
    # Plotly puts the first y value at the bottom, which would stand January
    # at the foot of the chart and read as December-first.
    fig.update_yaxes(autorange="reversed")
    st.plotly_chart(fig, width="stretch")
    st.caption(
        "Each cell is the average price for that hour in that month. Read it for the "
        "season: the expensive cells cluster on winter mornings and evenings, which is "
        "exactly when a roof produces least. " + LEGEND_CAPTION
    )


def _render_overlay_chart(frame, start, end, title, now_marker=None):
    """Price bars with the production line below, over [start, end]."""
    span_days = (end - start).days + 1
    # DateOffset, never Timedelta: 24 absolute hours lands at 01:00 the
    # next morning on the spring-forward day and would drag one row of the
    # following date into the slice.
    start_ts = pd.Timestamp(start, tz=STOCKHOLM)
    end_ts = pd.Timestamp(end, tz=STOCKHOLM) + pd.DateOffset(days=1)
    window = frame.loc[(frame.index >= start_ts) & (frame.index < end_ts)]

    if window.empty:
        st.info("No data for the selected range.")
        return

    prices_df = window.assign(ore_per_kWh=window["SEK_per_kWh"] * 100)
    prod_df = window[[PRODUCTION_COLUMN]]

    if span_days > HOURLY_BAR_MAX_DAYS:
        price_rows = categorize_by_price(
            resample_daily_mean(prices_df, columns=["ore_per_kWh"]), "ore_per_kWh"
        )
        # a daily *sum*, not a mean: production is energy, and a day's
        # total kWh is the number an advisor actually quotes
        prod_df = prod_df.resample("1D").sum()
    else:
        price_rows = categorize_by_price(prices_df, "ore_per_kWh")

    st.subheader(title)
    fig = _build_price_figure(price_rows, "ore_per_kWh", prod_df, now_marker)
    st.plotly_chart(fig, width="stretch")


def _render_donut(detail):
    split = production_split(detail)
    total = float(split.sum())
    if total <= 0:
        st.info("No production in this period, so there is nothing to split.")
        return

    labels = list(split.index)
    fig = go.Figure(
        go.Pie(
            labels=labels, values=split.tolist(), hole=0.55,
            sort=False, direction="clockwise",  # keep the energy-flow order so the ramp reads as a ramp
            marker=dict(
                colors=[FLOW_COLORS[label] for label in labels],
                line=dict(color=SURFACE, width=2),
            ),
            texttemplate="%{label}<br>%{percent}",
            # outside, not inside: the curtailed slice is a fraction of a
            # percent and an inside label would collide with its neighbour
            textposition="outside",
            hovertemplate="%{label}<br>%{value:,.0f} kWh/yr (%{percent})<extra></extra>",
        )
    )
    fig.update_layout(
        template="plotly_white", showlegend=True,
        title="Where the solar power goes (last 12 months)",
        annotations=[dict(text=f"{total:,.0f}<br>kWh/yr", x=0.5, y=0.5,
                          showarrow=False, font=dict(size=16))],
    )
    st.plotly_chart(fig, width="stretch")

    # The curtailed sliver is too small for any arc to show, so the exact
    # numbers go in text as well.
    parts = " · ".join(
        f"{label.lower()} {value:,.0f} kWh ({value / total:.1%})".replace(",", " ")
        for label, value in split.items()
    )
    st.caption(
        f"{parts}. Look at “sold”: that share earns roughly the bare spot price now that "
        f"the 60 öre/kWh tax reduction is gone — it is exactly what a battery moves into "
        f"“own use”, where each kWh instead avoids the full buy price."
    )


def _render_scenario_bars(comparison):
    scenarios = [
        ("No solar", comparison.no_solar),
        ("Solar only", comparison.solar_only),
        ("Solar + battery", comparison.solar_battery),
    ]
    names = [name for name, _ in scenarios]
    costs = [s.cost_sek for _, s in scenarios]

    fig = go.Figure(
        go.Bar(
            x=costs, y=names, orientation="h",
            marker=dict(color=SCENARIO_COLOR),
            text=[_sek(c) for c in costs],
            textposition="outside", cliponaxis=False,
            hovertemplate="%{y}<br>%{x:,.0f} SEK/yr<extra></extra>",
        )
    )
    fig.update_layout(
        template="plotly_white", showlegend=False,
        title="Yearly electricity cost (last 12 months)",
        xaxis=dict(title="SEK per year", gridcolor="#e1e0d9"),
        yaxis=dict(autorange="reversed"),  # "No solar" at the top, so it reads top-down
        margin=dict(r=120),  # room for the outside labels
    )
    st.plotly_chart(fig, width="stretch")
    st.caption(
        "The gap between the first two bars is what the panels are worth; the gap "
        "between the last two is what the battery adds on top."
    )


def _render_assumptions():
    with st.expander("Assumptions — what these numbers rest on"):
        st.markdown(
            f"""
**Production**
- {PANEL_TILT_DEG}° roof pitch, system losses {SYSTEM_LOSS_FACTOR:.0%} of theoretical
  (inverter, cabling, soiling, temperature).
- An east–west roof is modelled as half the array each way (the mean of the
  −90° and +90° irradiance series).
- Irradiance is real measured data for Gothenburg, not a typical year.

**Prices**
- Buy price = (spot + energy tax {ENERGY_TAX_SEK_PER_KWH:.2f} + grid fee
  {GRID_FEE_SEK_PER_KWH:.2f}) × (1 + VAT {VAT_RATE:.0%}).
- Sell price = spot + grid benefit (nätnytta) {GRID_BENEFIT_SEK_PER_KWH:.2f}, no VAT.
- ⚠️ The grid benefit is a **placeholder that has not been sourced yet**, and it
  moves every figure involving exported power. Verify it against the customer's
  grid operator before quoting.
- The **fixed** annual grid charge is excluded on purpose: it does not change with
  solar or a battery, so it cancels out of every comparison above.

**Battery**
- Round trip {BATTERY_ROUND_TRIP_EFFICIENCY:.0%}, booked entirely on discharge —
  "put 10 kWh in, get 9 kWh back".
- Max charge/discharge per hour = capacity × {BATTERY_MAX_POWER_FRACTION}.
- Solar charges the battery first. The grid only tops up what the sun is not
  expected to give, and only when the saving clears the round-trip loss by at
  least {GRID_CHARGE_MIN_MARGIN_SEK_PER_KWH:.2f} SEK/kWh.
- The battery discharges in hours priced above that day's median.

**Consumption — an assumption, not measured data**
- There is no open data for one household's hourly consumption. The annual figure
  entered above is spread over the year using a typical villa shape: morning and
  evening peaks, and winter months roughly
  {MONTHLY_FACTORS[0] / MONTHLY_FACTORS[6]:.1f}× heavier than summer.
- A real customer's own hourly data would replace this and is the single biggest
  improvement available to these numbers.

**Not included in payback**
- The green-technology deduction (*grön teknik*).
- Capacity/effekt-tariff savings.
- Frequency-regulation income (FCR-D and similar).
- The fixed annual grid charge, as above.

These four are where Swedish home-battery economics actually lives — they are why
an honest payback figure looks long.
            """
        )


# -- inputs (shared by both tabs) ---------------------------------------------

today = _now_stockholm().date()
window_start, window_end = _twelve_month_window(today)

with st.container(border=True):
    st.markdown("**The customer**")
    c1, c2, c3, c4, c5 = st.columns([1.2, 1, 1.2, 1, 1.3])
    annual_kwh = c1.number_input(
        "Annual consumption (kWh)", min_value=1000.0, max_value=60000.0,
        value=DEFAULT_ANNUAL_CONSUMPTION_KWH, step=1000.0,
        help="From the customer's electricity bill or grid operator.",
    )
    kwp = c2.slider(
        "System size (kWp)", min_value=2.0, max_value=30.0,
        value=DEFAULT_KWP, step=0.5,
    )
    orientation = c3.selectbox(
        "Roof orientation", list(ORIENTATIONS),
        index=list(ORIENTATIONS).index(DEFAULT_ORIENTATION),
    )
    capacity_kwh = c4.slider(
        "Battery (kWh)", min_value=0.0, max_value=30.0,
        value=DEFAULT_BATTERY_KWH, step=1.0,
        help="0 means no battery — the comparison still shows what one would add.",
    )
    battery_price_input = c5.number_input(
        "Battery price (SEK, optional)", min_value=0.0, max_value=400000.0,
        value=DEFAULT_BATTERY_PRICE_SEK, step=5000.0,
        help="Installed price before any deduction. Leave at 0 to hide payback.",
    )
battery_price = battery_price_input or None

tab_customer, tab_tomorrow = st.tabs(["Customer calculation", "Tomorrow"])

with tab_customer:
    try:
        frame, missing_hours, notices = _cached_year_frame(
            window_start, window_end, orientation, kwp, annual_kwh
        )
        p_failed, p_fallback, s_failed, s_fallback = notices
        _render_fallback_notices(p_fallback, p_failed)
        _render_fallback_notices(s_fallback, s_failed)
    except Exception:
        st.error(
            "Could not load 12 months of data right now. Check the connection and "
            "reload — the figures below need a full year to be honest."
        )
        st.stop()

    if frame.empty:
        st.warning("No overlapping price and sunshine data for the last 12 months.")
        st.stop()

    if missing_hours:
        st.info(
            f"{missing_hours} hour(s) had sunshine data but no price and were left out, "
            f"so the yearly figures cover slightly less than a full year."
        )

    comparison = _cached_scenarios(
        window_start, window_end, orientation, kwp, annual_kwh, capacity_kwh, battery_price
    )

    # --- 1. the four numbers the advisor quotes -----------------------------
    k1, k2, k3, k4 = st.columns(4)
    k1.metric(
        "Value of solar", f"{_sek(comparison.solar_value_sek)}/yr",
        help="Yearly electricity cost without solar, minus the cost with solar only.",
        border=True,
    )
    k2.metric(
        "Value of the battery", f"{_sek(comparison.battery_value_sek)}/yr",
        help="What the battery adds on top of the panels, over the same 12 months.",
        border=True,
    )
    k3.metric(
        "Self-consumption", f"{comparison.solar_battery.self_consumption_share:.0%}",
        help=(
            "Share of production used on site rather than exported. "
            f"Without a battery: {comparison.solar_only.self_consumption_share:.0%}."
        ),
        border=True,
    )
    if battery_price is None:
        payback_value, payback_help = "—", "Enter a battery price to see payback."
    elif comparison.payback_years is None:
        payback_value = "—"
        payback_help = "This battery size saves nothing at these prices, so there is no payback."
    else:
        payback_value = f"{comparison.payback_years:.0f} years"
        payback_help = "Simple payback: price ÷ yearly value. See Assumptions for what is excluded."
    k4.metric("Battery payback", payback_value, help=payback_help, border=True)

    st.caption(
        f"**All yearly figures above cover the full 12 months, "
        f"{window_start:%d %b %Y} – {window_end:%d %b %Y}.** The date picker further down "
        f"zooms the chart only — it never changes these numbers."
    )

    # --- question 5, as one line rather than a second set of controls ------
    other_orientation = next(
        (name for name in ORIENTATIONS if name != orientation), None
    )
    if other_orientation is not None:
        try:
            other = _cached_scenarios(
                window_start, window_end, other_orientation, kwp, annual_kwh,
                capacity_kwh, battery_price,
            )
            other_payback = (
                f", payback {other.payback_years:.0f} years"
                if other.payback_years is not None else ""
            )
            st.caption(
                f"**Roof orientation:** on {'an' if other_orientation[0] in 'AEIOU' else 'a'} "
                f"{other_orientation.lower()} roof the same system is worth "
                f"{_sek(other.solar_value_sek)}/yr and the battery "
                f"{_sek(other.battery_value_sek)}/yr{other_payback}. Orientation usually "
                f"moves the battery's value more than the panels' — a flatter east–west "
                f"curve already matches the household's morning and evening peaks, so less "
                f"has to go through the battery."
            )
        except Exception:
            pass  # the comparison is a nice-to-have; never block the main figures

    st.divider()

    # --- 2. the overlay: when the sun shines vs when power is expensive ----
    picked = st.date_input(
        "Zoom the chart (does not affect the figures above)",
        value=_summer_week(window_start, window_end),
        min_value=window_start, max_value=window_end,
    )
    if len(picked) != 2:
        st.info("Pick an end date to see the chart.")
    else:
        chart_start, chart_end = sorted(picked)
        # the window spans a year boundary, so the start needs its own year
        # whenever the two differ -- "04 Oct – 03 Oct 2026" reads as one year
        start_fmt = "%d %b" if chart_start.year == chart_end.year else "%d %b %Y"
        _render_overlay_chart(
            frame, chart_start, chart_end,
            f"{PRICE_AREA} price and solar production, "
            f"{chart_start.strftime(start_fmt)} – {chart_end:%d %b %Y}",
        )
        st.caption(
            "Look at midday: production peaks when the price is at its lowest, while the "
            "price peaks in the evening when the roof has already stopped. That gap is "
            "what the battery bridges. " + LEGEND_CAPTION
        )

    st.divider()

    # --- 3 and 4. where the power goes, and what each scenario costs -------
    left, right = st.columns(2)
    with left:
        _render_donut(comparison.solar_battery.detail)
    with right:
        _render_scenario_bars(comparison)

    st.divider()

    # --- 5. the seasonal price pattern -------------------------------------
    _render_heatmap(frame.assign(ore_per_kWh=frame["SEK_per_kWh"] * 100), "ore_per_kWh")

    # --- 6. assumptions ----------------------------------------------------
    _render_assumptions()

with tab_tomorrow:
    now = _now_stockholm()
    today_d, tomorrow_d = now.date(), now.date() + timedelta(days=1)
    now_marker = pd.Timestamp(now).floor("h") + pd.Timedelta(minutes=30)

    solar_df = None
    try:
        irradiance, s_failed, s_fallback = _cached_fetch_irradiance_forecast(
            today_d, tomorrow_d, orientation
        )
        _render_fallback_notices(s_fallback, s_failed)
        solar_df = production_kwh(irradiance, kwp)
    except Exception:
        st.error("Solar forecast unavailable right now; showing prices only.")

    prices_df, p_failed, p_fallback = _cached_fetch_prices_tomorrow(
        today_d, tomorrow_d, PRICE_AREA
    )
    _render_fallback_notices(p_fallback, p_failed)

    tomorrow_present = not prices_df.empty and (prices_df.index.date == tomorrow_d).any()
    if not tomorrow_present:
        if tomorrow_d in p_failed:
            st.warning("Tomorrow's prices could not be fetched and have no cached fallback.")
        else:
            st.info("Tomorrow's prices aren't published yet (usually by ~13:00). Showing today only.")

    if prices_df.empty:
        st.info("No published prices for today or tomorrow.")
    else:
        hourly = prices_df.assign(ore_per_kWh=prices_df["SEK_per_kWh"] * 100)
        price_rows = categorize_by_price(hourly, "ore_per_kWh")
        st.subheader(f"{PRICE_AREA} — today and tomorrow")
        fig = _build_price_figure(price_rows, "ore_per_kWh", solar_df, now_marker)
        st.plotly_chart(fig, width="stretch")
        st.caption(
            f"Forecast production for a {kwp:.1f} kWp {orientation.lower()} system. "
            + LEGEND_CAPTION
        )

    st.info(
        "**Coming in Sprint 8:** tomorrow's battery plan in plain language — "
        "when to charge from the grid, when to store solar, and when to run the "
        "house off the battery."
    )

st.caption(
    "Elpriser tillhandahålls av [Elpriset just nu.se](https://www.elprisetjustnu.se). "
    "Weather data by [Open-Meteo.com](https://open-meteo.com). "
    "Consumption is a modelled assumption, not the customer's measured data — "
    "see Assumptions."
)
