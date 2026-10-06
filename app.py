"""Solar Advisor — four answers for an energy advisor in a customer meeting.

1. Is solar worth it for this customer?
2. How long until it pays back, and how much does it save per year?
3. Should they get a battery?
4. If yes, how big?

Everything on screen serves one of those four. The hourly simulation runs
underneath over three full years; the screen shows **conclusions, not data**.

Layout only. Every number comes from a pure function in `src/` — this file
wires widgets to those functions and renders the result. No prose here
restates a figure that lives in `config.py`.
"""

import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from src.battery import build_frame, run_scenario
from src.config import (
    ASSUMPTIONS,
    BATTERY_PRICE_REFERENCE_KWH,
    BATTERY_SIZES_KWH,
    DEFAULT_ANNUAL_CONSUMPTION_KWH,
    DEFAULT_BATTERY_PRICE_SEK,
    DEFAULT_KWP,
    DEFAULT_ORIENTATION,
    DEFAULT_SYSTEM_PRICE_SEK,
    ORIENTATIONS,
    PANEL_TILT_DEG,
    PRICE_AREA,
    WINDOW_END,
    WINDOW_LABEL,
    WINDOW_START,
    Settings,
)
from src.economics import (
    SUMMER_MONTHS,
    WINTER_MONTHS,
    YearlyCosts,
    average_day,
    break_even_year,
    payback_curve,
    recommend,
    year_spans,
    yearly_net_cost,
)
from src.prices import fetch_prices
from src.solar import PRODUCTION_COLUMN, fetch_irradiance, production_kwh

# Two series on the payback curve. Validated with the dataviz skill's
# checker (light surface, --pairs all): all checks pass, CVD ΔE 24.7.
SOLAR_COLOR = "#2a78d6"
BATTERY_COLOR = "#eb6834"
# A two-step ordinal of the same blue for the size chart: the recommended
# bar is darker. A selection state, not value-rank colouring — bar length
# still carries the magnitude. Passes --ordinal.
SIZE_COLOR = "#86b6ef"
SIZE_COLOR_PICKED = "#2a78d6"
# Status-critical red, used for its actual job: a threshold line.
LIMIT_COLOR = "#d03b3b"
PRODUCTION_COLOR = "#eda100"
GRID_COLOR = "#e1e0d9"

st.set_page_config(
    page_title="Solar Advisor",
    page_icon="☀️",
    layout="wide",
    menu_items={
        "about": (
            "**Solar Advisor** — a sales tool for the energy advisors of Kustsol AB, "
            "a **fictional** solar installer in the Gothenburg region.\n\n"
            "Built as a course assignment for Digital Leadership, University of "
            "Gothenburg. Spot prices from elprisetjustnu.se; weather data by "
            "Open-Meteo.com. Household consumption is a modelled assumption, not "
            "measured data. Not financial advice."
        )
    },
)


def _sek(value: float) -> str:
    """SEK with a thin space as the thousands separator, never öre."""
    return f"{value:,.0f} SEK".replace(",", " ")


def _years(value: float | None) -> str:
    return "never" if value is None else f"{value:.0f} years"


def _kwh(value: float) -> str:
    """kWh with a thin-space separator. Separate from _sek so the grouping
    substitution only ever touches the number, never a sentence's commas."""
    return f"{value:,.0f}".replace(",", "\u00a0") + " kWh"


# -- data and computation ------------------------------------------------------
#
# Split exactly on the measured boundary between what forces a re-simulation
# and what is only arithmetic. Editing the system price, the battery price,
# the deduction, the owners or the lifetimes costs milliseconds; editing the
# surcharge, VAT, consumption, kWp or orientation costs a couple of seconds,
# because the surcharge genuinely re-enters the battery's grid-charging rule.
#
# `max_entries` is set on every one: `st.cache_data` pickles, and Community
# Cloud has about a gigabyte. `YearlyCosts` is deliberately a handful of
# floats so it can be cached freely — caching the simulation's detail frames
# would be megabytes per entry for data no element on this page reads.


@st.cache_data(max_entries=2, show_spinner=f"Loading three years of {PRICE_AREA} spot prices…")
def _prices():
    # No arguments: the window is a fixed constant, so there is one answer.
    return fetch_prices(WINDOW_START, WINDOW_END, PRICE_AREA)


@st.cache_data(max_entries=4, show_spinner="Loading three years of Gothenburg sunshine…")
def _irradiance(orientation: str):
    return fetch_irradiance(WINDOW_START, WINDOW_END, orientation)


@st.cache_data(max_entries=8, show_spinner=False)
def _frame(orientation: str, kwp: float, annual_kwh: float, loss: float):
    prices, p_failed, p_fallback = _prices()
    irradiance, s_failed, s_fallback = _irradiance(orientation)
    production = production_kwh(irradiance, kwp, loss=loss)[PRODUCTION_COLUMN]
    frame, missing = build_frame(production, prices, annual_kwh)
    return frame, missing, (p_failed, p_fallback, s_failed, s_fallback)


@st.cache_data(max_entries=16, show_spinner="Simulating three years, hour by hour…")
def _yearly_costs(
    orientation: str, kwp: float, annual_kwh: float, loss: float,
    vat_rate: float, surcharge: float,
    efficiency: float, power_fraction: float, margin: float,
) -> YearlyCosts:
    """The expensive layer. Every argument that changes a simulated flow is
    in the key — including the three battery parameters no widget exposes
    yet, so adding one later cannot silently reuse a stale entry."""
    frame, _, _ = _frame(orientation, kwp, annual_kwh, loss)
    settings = Settings.defaults(
        vat_rate=vat_rate, surcharge_sek_per_kwh=surcharge,
        round_trip_efficiency=efficiency, battery_max_power_fraction=power_fraction,
        grid_charge_min_margin_sek_per_kwh=margin,
    )
    spans = year_spans(WINDOW_START, WINDOW_END)
    years = len(spans)

    no_solar = run_scenario(frame, 0.0, with_solar=False, settings=settings)
    by_size, self_consumption, grid_days = {}, {}, {}
    curtailed = production = 0.0
    for capacity in BATTERY_SIZES_KWH:
        result = run_scenario(frame, float(capacity), with_solar=True, settings=settings)
        by_size[capacity] = yearly_net_cost(result.detail, spans)
        self_consumption[capacity] = result.self_consumption_share
        detail = result.detail
        grid_days[capacity] = int(
            (detail["grid_charge_kwh"].groupby(detail.index.date).sum() > 0).sum()
        )
        if capacity == 0:
            production = float(detail["production_kwh"].sum()) / years
            curtailed = float(detail["curtailed_kwh"].sum()) / years

    return YearlyCosts(
        spans=spans,
        no_solar=yearly_net_cost(no_solar.detail, spans),
        by_size=by_size,
        production_kwh_per_year=production,
        curtailed_kwh_per_year=curtailed,
        self_consumption_by_size=self_consumption,
        grid_charge_days_by_size=grid_days,
    )


@st.cache_data(max_entries=12, show_spinner=False)
def _average_day(orientation: str, kwp: float, annual_kwh: float, loss: float, season: str):
    frame, _, _ = _frame(orientation, kwp, annual_kwh, loss)
    months = {"Summer (Apr–Sep)": SUMMER_MONTHS, "Winter (Oct–Mar)": WINTER_MONTHS}.get(season)
    return average_day(frame, months)


def _render_fallback_notices(fallback_days, failed_days, source: str) -> None:
    if fallback_days:
        st.info(f"{len(fallback_days)} day(s) of {source} came from an older snapshot.")
    if failed_days:
        st.warning(
            f"{len(failed_days)} day(s) of {source} could not be loaded, so the "
            f"figures cover slightly less than three full years."
        )


# -- the assumptions box -------------------------------------------------------

def _provenance(key: str) -> str:
    a = ASSUMPTIONS[key]
    mark = "" if a.verified else "⚠ "
    return f"{mark}{a.source}  \n*Last updated {a.updated:%-d %b %Y}.*"


def _render_assumptions() -> Settings:
    """The editable box. Returns the values every calculation then uses.

    Nothing downstream reads `config` directly, so what is returned here is
    what the whole page is computed from — which is the only way an edit can
    be trusted to take effect.
    """
    defaults = Settings.defaults()
    with st.expander("Assumptions and deductions — every number here is editable"):
        st.caption(
            "Each value shows where it came from and when it was last checked. "
            "⚠ marks one nobody has verified yet."
        )

        st.markdown("**Green technology deduction**")
        enabled = st.checkbox(
            "Apply the green technology deduction", value=False,
            help="Off by default, so the figures above are the conservative case.",
        )
        owners = 1
        if enabled:
            owners = int(st.number_input(
                "Number of owners", min_value=1, max_value=10, value=1, step=1,
                help=_provenance("green_tech_cap_per_owner_sek"),
            ))
            st.caption(
                f"{ASSUMPTIONS['green_tech_solar_rate'].value:.0%} on solar and "
                f"{ASSUMPTIONS['green_tech_battery_rate'].value:.0%} on the battery, "
                f"capped at {_sek(ASSUMPTIONS['green_tech_cap_per_owner_sek'].value * owners)} "
                f"in total. When the cap binds, the panels are deducted first and the "
                f"battery takes what is left."
            )

        st.divider()
        st.markdown("**Price of bought electricity**")
        left, right = st.columns(2)
        surcharge_ore = left.number_input(
            f"Surcharge ({ASSUMPTIONS['surcharge_sek_per_kwh'].unit.replace('SEK', 'öre')})",
            min_value=0.0, max_value=300.0,
            value=float(defaults.surcharge_sek_per_kwh * 100), step=1.0,
            help=_provenance("surcharge_sek_per_kwh"),
        )
        vat_percent = right.number_input(
            "VAT on the spot price (%)", min_value=0.0, max_value=50.0,
            value=float(defaults.vat_rate * 100), step=1.0,
            help=_provenance("vat_rate"),
        )
        st.caption(
            "Buy price = spot × (1 + VAT) + surcharge. Sold power earns the bare "
            "spot price."
        )

        st.divider()
        st.markdown("**Lifetimes**")
        c1, c2, c3 = st.columns(3)
        solar_life = int(c1.number_input(
            "Solar (years)", min_value=5, max_value=40,
            value=int(defaults.solar_lifetime_years), step=1,
            help=_provenance("solar_lifetime_years"),
        ))
        battery_warranty = int(c2.number_input(
            "Battery warranty (years)", min_value=1, max_value=30,
            value=int(defaults.battery_lifetime_years), step=1,
            help=_provenance("battery_lifetime_years"),
        ))
        battery_service_life = int(c3.number_input(
            "Battery service life (years)", min_value=1, max_value=40,
            value=int(defaults.battery_service_life_years), step=1,
            help=_provenance("battery_service_life_years"),
        ))
        st.caption(
            f"**The battery verdict is judged against its service life**, not its "
            f"warranty — a warranty is a manufacturer's defect guarantee, not a "
            f"claim that the battery stops being useful the day it expires. "
            f"Test finding, 2026-10-06: judging against the warranty made every "
            f"realistically-priced battery say 'No'. When a payback relies on the "
            f"battery outliving its warranty, the card says so."
        )

        st.divider()
        st.markdown("**Other battery income**")
        other_income = st.number_input(
            "Grid support services & capacity-charge savings (SEK/year)",
            min_value=0, max_value=20000,
            value=int(defaults.other_battery_income_sek_per_year), step=100,
            help=_provenance("other_battery_income_sek_per_year"),
        )
        st.caption(
            "Covers frequency regulation income (stödtjänster) and capacity-charge "
            "(effektavgift) savings from peak shaving — a real figure from an "
            "aggregator's offer or the customer's grid tariff, added directly to "
            "the battery's yearly saving. Defaults to 0: this tool's hourly "
            "consumption is a modelled assumption, not the customer's real usage, "
            "so it cannot honestly estimate a specific capacity-charge saving on "
            "its own."
        )

        st.divider()
        st.markdown("**Not included in these figures**")
        st.markdown(
            f"- **Capacity charge (effektavgift)** — "
            f"{ASSUMPTIONS['effektavgift_sek_per_kw'].value:.0f} SEK/kW in this grid "
            f"area, charged on the month's three highest hours — and **grid support "
            f"services (stödtjänster)** are not simulated from this tool's own data. "
            f"Enter a real figure above, under 'Other battery income', to include "
            f"them in the payback.\n"
            f"- Panel degradation, and any rise or fall in electricity prices.\n"
            f"- Payback here is simple payback — investment divided by yearly "
            f"saving — **not** a discounted calculation. Over 15–25 years that is "
            f"not a rounding error.\n"
            f"- The **fixed** annual grid charge is excluded on purpose: it does not "
            f"change with solar or a battery, so it cancels out of every comparison.\n"
            f"- Household consumption is a **modelled assumption**, not this "
            f"customer's measured data."
        )

    return Settings.defaults(
        vat_rate=vat_percent / 100,
        surcharge_sek_per_kwh=surcharge_ore / 100,
        solar_lifetime_years=solar_life,
        battery_lifetime_years=battery_warranty,
        battery_service_life_years=battery_service_life,
        other_battery_income_sek_per_year=float(other_income),
        green_tech_enabled=enabled,
        green_tech_owners=owners,
    )


# -- the four elements ---------------------------------------------------------

def _render_answer_cards(rec, settings) -> None:
    left, right = st.columns(2)

    with left, st.container(border=True):
        s = rec.solar
        if rec.solar_worth_it:
            st.markdown(
                f"### :material/check_circle: Solar: **Yes**\n"
                f"Paid back in **{_years(s.payback_years)}**, saving "
                f"**{_sek(s.savings.average)}/year**."
            )
        else:
            st.markdown(
                f"### :material/cancel: Solar: **No**\n"
                f"It would save **{_sek(s.savings.average)}/year**, which covers "
                f"{_sek(s.net_investment_sek)} in **{_years(s.payback_years)}** — "
                f"longer than the panels' {settings.solar_lifetime_years}-year life."
            )
        st.caption(
            f"Range across the three years: {_sek(s.savings.lowest)} to "
            f"{_sek(s.savings.highest)} a year. "
            f"Investment {_sek(s.net_investment_sek)}"
            + (f" after a {_sek(s.deduction_sek)} deduction." if s.deduction_sek else ".")
        )

    with right, st.container(border=True):
        if rec.recommended is not None:
            b = rec.recommended
            st.markdown(
                f"### :material/check_circle: Battery: **Yes, {b.capacity_kwh} kWh**\n"
                f"Paid back in **{_years(b.payback_years)}**, saving a further "
                f"**{_sek(b.savings.average)}/year**."
            )
            if not b.within_warranty:
                st.markdown(
                    f"**But:** that payback happens after the "
                    f"{settings.battery_lifetime_years}-year warranty ends — it "
                    f"relies on the battery lasting into its expected "
                    f"{settings.battery_service_life_years}-year service life."
                )
            st.caption(
                f"Range {_sek(b.savings.lowest)} to {_sek(b.savings.highest)} a year. "
                f"That payback is the battery on its own — what it adds on top of the "
                f"panels, against its own cost."
            )
        else:
            best = rec.best_candidate
            detail = (
                f"The best case is **{best.capacity_kwh} kWh at "
                f"{_years(best.payback_years)}**."
                if best is not None else
                "No size saves enough to pay back at all."
            )
            st.markdown(
                f"### :material/cancel: Battery: **No**\n"
                f"No size pays for itself within its expected "
                f"{settings.battery_service_life_years}-year service life. {detail}"
            )
            if rec.extra_income_to_flip_sek is not None:
                st.markdown(
                    f"**But:** it would pay off with about "
                    f"**{_sek(rec.extra_income_to_flip_sek)}/year** more income — "
                    f"from grid support services or peak shaving — on top of what "
                    f"it already saves. Enter a real figure in 'Other battery "
                    f"income' above if the customer has an offer."
                )
            st.caption(
                "Battery payback is what the battery adds on top of the panels, "
                "against its own cost — not the whole system's payback."
            )


def _render_payback_curve(rec, settings) -> None:
    curve = payback_curve(
        rec,
        solar_lifetime_years=settings.solar_lifetime_years,
        # The service life, not the warranty: that is the horizon the
        # verdict is actually judged against, so the chart's retirement
        # point has to agree with the card or the two would contradict.
        battery_credit_years=settings.battery_service_life_years,
    )
    fig = go.Figure()
    colors = {"Solar only": SOLAR_COLOR}
    series_names = list(dict.fromkeys(curve["series"]))
    for name in series_names:
        if name != "Solar only":
            colors[name] = BATTERY_COLOR

    for name in series_names:
        rows = curve[curve["series"] == name]
        colour = colors[name]
        rgb = tuple(int(colour[i:i + 2], 16) for i in (1, 3, 5))
        # The range is drawn in the series' OWN hue, translucent -- a third
        # colour would claim to be a third thing, and a grey band fails the
        # palette's chroma floor.
        fig.add_trace(go.Scatter(
            x=list(rows["year"]) + list(rows["year"])[::-1],
            y=list(rows["highest"]) + list(rows["lowest"])[::-1],
            fill="toself", fillcolor=f"rgba({rgb[0]},{rgb[1]},{rgb[2]},0.15)",
            line=dict(width=0), hoverinfo="skip", showlegend=False,
        ))
        fig.add_trace(go.Scatter(
            x=rows["year"], y=rows["average"], name=name, mode="lines",
            line=dict(color=colour, width=2),
            hovertemplate="Year %{x}<br>%{y:,.0f} SEK<extra>" + name + "</extra>",
        ))
        crossing = break_even_year(curve, name)
        if crossing is not None:
            fig.add_trace(go.Scatter(
                x=[crossing], y=[0], mode="markers",
                marker=dict(color=colour, size=9),
                showlegend=False,
                hovertemplate=f"Paid back, year {crossing}<extra></extra>",
            ))

    fig.add_hline(y=0, line_dash="dot", line_color="#52514e")
    if rec.recommended is not None or rec.best_candidate is not None:
        fig.add_vline(
            x=settings.battery_service_life_years, line_dash="dot", line_color="#898781",
            annotation_text="Battery end of life", annotation_position="top left",
        )
    fig.update_layout(
        template="plotly_white", title="What it is worth over time",
        xaxis=dict(title="Years from installation", gridcolor=GRID_COLOR),
        yaxis=dict(title="Cumulative saving (SEK)", gridcolor=GRID_COLOR),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(r=140),  # outside annotations clip without this
    )
    st.plotly_chart(fig, width="stretch")

    note = (
        "Each line starts at minus the investment and climbs by the yearly saving; "
        "the shaded band is the best and worst of the three years. Where it crosses "
        "zero is the payback."
    )
    if rec.recommended is not None or rec.best_candidate is not None:
        note += (
            f" The battery stops earning at {settings.battery_service_life_years} years "
            f"(its expected service life) and is not replaced, so from there the two "
            f"lines run parallel — **the gap between them is what the battery was "
            f"worth over its whole life**."
        )
    st.caption(note)


def _render_size_chart(rec, settings) -> None:
    sizes = [s for s in rec.sizes if s.payback_years is not None]
    if not sizes:
        st.info("No battery size saves enough to pay back at any price, so there is "
                "nothing to compare.")
        return

    picked = rec.recommended.capacity_kwh if rec.recommended else None
    fig = go.Figure(go.Bar(
        x=[f"{s.capacity_kwh} kWh" for s in sizes],
        y=[s.payback_years for s in sizes],
        marker=dict(color=[
            SIZE_COLOR_PICKED if s.capacity_kwh == picked else SIZE_COLOR for s in sizes
        ]),
        text=[f"{s.payback_years:.0f} yr" for s in sizes],
        textposition="outside", cliponaxis=False,
        hovertemplate="%{x}<br>pays back in %{y:.1f} years<extra></extra>",
    ))
    # The service life, not the warranty: the line a bar must clear to be
    # "worth it" has to be the same horizon recommend() actually judges
    # pays_back against, or the chart would visually contradict the cards.
    fig.add_hline(
        y=settings.battery_service_life_years, line_dash="dash", line_color=LIMIT_COLOR,
        annotation_text=f"{settings.battery_service_life_years}-year service life",
        annotation_position="top left",
    )
    fig.update_layout(
        template="plotly_white", showlegend=False,
        title="How long each battery size takes to pay for itself",
        xaxis=dict(title=None),
        yaxis=dict(title="Years to pay back", gridcolor=GRID_COLOR),
        margin=dict(r=140, t=70),
    )
    st.plotly_chart(fig, width="stretch")

    missing = [s.capacity_kwh for s in rec.sizes if s.payback_years is None]
    note = (
        "A bar below the red line pays for itself inside its expected service "
        "life; above it, it does not. **0 kWh is not shown — there is nothing to "
        "pay back.**"
    )
    if missing:
        note += f" {', '.join(f'{m} kWh' for m in missing)} saves nothing at all."
    st.caption(note)


def _render_why(orientation: str, kwp: float, annual_kwh: float, loss: float) -> None:
    season = st.selectbox(
        "Season", ["Summer (Apr–Sep)", "Winter (Oct–Mar)", "Full year"], index=0,
    )
    day = _average_day(orientation, kwp, annual_kwh, loss, season)

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08, row_heights=[0.5, 0.5],
    )
    hours = [f"{h:02d}" for h in day["hour"]]
    fig.add_trace(go.Bar(
        x=hours, y=day["ore_per_kwh"], marker_color=SOLAR_COLOR, name="Spot price",
        hovertemplate="%{x}:00<br>%{y:.0f} öre/kWh<extra></extra>",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=hours, y=day["production_kwh"], mode="lines", name="Production",
        line=dict(color=PRODUCTION_COLOR, width=2),
        fill="tozeroy", fillcolor="rgba(237,161,0,0.18)",
        hovertemplate="%{x}:00<br>%{y:.2f} kWh<extra></extra>",
    ), row=2, col=1)

    # The production yellow carries a contrast warning against this surface,
    # so it ships with a visible label rather than relying on the hue alone.
    peak = day.loc[day["production_kwh"].idxmax()]
    fig.add_annotation(
        x=f"{int(peak['hour']):02d}", y=float(peak["production_kwh"]),
        text=f"peak {peak['production_kwh']:.1f} kWh",
        showarrow=True, arrowhead=0, ax=0, ay=-24, row=2, col=1,
    )
    fig.update_layout(
        template="plotly_white", showlegend=False, bargap=0.15,
        title="An average day — when power is dear, and when the roof makes it",
        margin=dict(t=70),
    )
    fig.update_yaxes(title_text="öre/kWh", gridcolor=GRID_COLOR, row=1, col=1)
    fig.update_yaxes(title_text="kWh per hour", gridcolor=GRID_COLOR, row=2, col=1)
    fig.update_xaxes(title_text="Hour of day", row=2, col=1)
    st.plotly_chart(fig, width="stretch")

    cheapest = day.loc[day["ore_per_kwh"].idxmin()]
    dearest = day.loc[day["ore_per_kwh"].idxmax()]
    st.caption(
        f"Production peaks at {int(peak['hour']):02d}:00. The price is at its lowest "
        f"around {int(cheapest['hour']):02d}:00 ({cheapest['ore_per_kwh']:.0f} öre) and "
        f"its highest at {int(dearest['hour']):02d}:00 "
        f"({dearest['ore_per_kwh']:.0f} öre). **That gap is the whole argument:** the "
        f"roof produces when power is cheap, and the house needs it when power is dear. "
        f"Using it yourself avoids the full buy price; selling it earns only the spot "
        f"price. A battery moves power from one to the other. Two panels, one shared "
        f"time axis — never a second y-axis."
    )


# -- the page ------------------------------------------------------------------

st.title("Solar Advisor")
st.caption(
    f"Is solar worth it for this customer — and a battery? Real {PRICE_AREA} spot "
    f"prices and real Gothenburg sunshine, {WINDOW_LABEL}."
)

with st.container(border=True):
    st.markdown("**The customer**")
    c1, c2, c3, c4, c5 = st.columns([1.1, 0.9, 1.1, 1.1, 1.1])
    annual_kwh = float(c1.number_input(
        "Annual consumption (kWh)", min_value=1000, max_value=60000,
        value=DEFAULT_ANNUAL_CONSUMPTION_KWH, step=1000,
        help="From the customer's electricity bill or grid operator.",
    ))
    kwp = float(c2.number_input(
        "System size (kWp)", min_value=2, max_value=30, value=DEFAULT_KWP, step=1,
    ))
    orientation = c3.selectbox(
        "Roof orientation", list(ORIENTATIONS),
        index=list(ORIENTATIONS).index(DEFAULT_ORIENTATION),
    )
    system_price = float(c4.number_input(
        "System price (SEK)", min_value=0, max_value=1000000,
        value=DEFAULT_SYSTEM_PRICE_SEK, step=5000,
        help="Installed, before any deduction.",
    ))
    battery_price_quoted = float(c5.number_input(
        f"Battery price (SEK, for {BATTERY_PRICE_REFERENCE_KWH} kWh)",
        min_value=0, max_value=300000,
        value=DEFAULT_BATTERY_PRICE_SEK, step=5000,
        help=(
            f"Installed price for a {BATTERY_PRICE_REFERENCE_KWH} kWh battery, "
            f"before any deduction — what a quote actually says. Other sizes "
            f"(5, 15 kWh) are priced in proportion, since the app has to compare "
            f"sizes to answer 'how big?'."
        ),
    ))
    # The sweep that answers "how big?" needs a rate to price 0/5/10/15 kWh
    # against each other; the advisor only ever types a quote, never a rate.
    battery_price_per_kwh = battery_price_quoted / BATTERY_PRICE_REFERENCE_KWH

settings = _render_assumptions()

try:
    frame, missing_hours, notices = _frame(
        orientation, kwp, annual_kwh, settings.system_loss_factor
    )
    p_failed, p_fallback, s_failed, s_fallback = notices
    _render_fallback_notices(p_fallback, p_failed, "spot prices")
    _render_fallback_notices(s_fallback, s_failed, "sunshine")
except Exception:
    st.error(
        "Could not load the three years of data this calculation needs. Check the "
        "connection and reload."
    )
    st.stop()

if frame.empty:
    st.warning("No overlapping price and sunshine data for the window.")
    st.stop()
if missing_hours:
    st.info(f"{missing_hours} hour(s) had sunshine data but no price and were left out.")

costs = _yearly_costs(
    orientation, kwp, annual_kwh, settings.system_loss_factor,
    settings.vat_rate, settings.surcharge_sek_per_kwh,
    settings.round_trip_efficiency, settings.battery_max_power_fraction,
    settings.grid_charge_min_margin_sek_per_kwh,
)
rec = recommend(
    costs,
    system_price_sek=system_price,
    battery_price_per_kwh_sek=battery_price_per_kwh,
    settings=settings,
)

_render_answer_cards(rec, settings)
st.caption(
    f"Averages of three full years — {', '.join(s.label for s in costs.spans)} — "
    f"with today's prices and rules applied to all three. The range matters: the "
    f"three years differ a lot, and a single average would claim more certainty "
    f"than the data supports."
)

st.divider()
_render_payback_curve(rec, settings)

st.divider()
_render_size_chart(rec, settings)

st.divider()
st.subheader("Why?")
_render_why(orientation, kwp, annual_kwh, settings.system_loss_factor)

_curtailed_note = (
    f", of which roughly {_kwh(costs.curtailed_kwh_per_year)} is thrown away because "
    f"the price went below zero and there was nowhere to put it — which is itself an "
    f"argument for a battery."
    if costs.curtailed_kwh_per_year >= 1 else "."
)
st.caption(
    f"Over a year this roof makes about {_kwh(costs.production_kwh_per_year)}"
    + _curtailed_note
)

st.caption(
    "Elpriser tillhandahålls av [Elpriset just nu.se](https://www.elprisetjustnu.se). "
    "Weather data by [Open-Meteo.com](https://open-meteo.com). "
    f"Production modelled at {PANEL_TILT_DEG}° tilt. Household consumption is a "
    "modelled assumption, not measured data — see Assumptions. Kustsol AB is a "
    "fictional client; this is a course project and not financial advice."
)
