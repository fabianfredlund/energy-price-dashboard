"""Sprint 5 (pivot spike): SE3 spot prices with real solar production
overlaid, replacing v1's temperature overlay.

Still carrying v1's production-units planner -- Sprint 7 replaces that
with the advisor's customer inputs (consumption, kWp, orientation,
battery), so this is deliberately a transitional, half-pivoted page.
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from src.calc import plan_unit, planner_totals, yearly_saving_estimate
from src.config import (
    DEFAULT_ORIENTATION,
    PANEL_TILT_DEG,
    PRICE_AREA,
    SPIKE_DEFAULT_KWP,
    SYSTEM_LOSS_FACTOR,
)
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
    hourly_weekday_means,
    price_kpis,
    resample_daily_mean,
    typical_hour_of_day,
)

STOCKHOLM = ZoneInfo("Europe/Stockholm")
HOURLY_BAR_MAX_DAYS = 31
WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# A summer week, so the point of the whole pivot is visible on first load:
# production peaks at midday, prices peak morning and evening.
DEFAULT_RANGE = (date(2026, 6, 15), date(2026, 6, 21))

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

st.set_page_config(page_title="Solar Advisor", layout="wide")
st.title("Solar Advisor")
st.caption(f"Spot prices for {PRICE_AREA} (Gothenburg region).")


def _now_stockholm() -> datetime:
    return datetime.now(STOCKHOLM)


@st.cache_data(ttl=3600)
def _cached_fetch_prices_history(start, end, area):
    return fetch_prices(start, end, area)


@st.cache_data(ttl=600)  # short TTL: "is tomorrow published yet" can flip within a session
def _cached_fetch_prices_planahead(start, end, area):
    return fetch_prices(start, end, area)


@st.cache_data(ttl=3600)
def _cached_fetch_irradiance(start, end, orientation):
    return fetch_irradiance(start, end, orientation)


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


def _render_kpi_cards(prices_df, price_col):
    kpis = price_kpis(prices_df, price_col)
    if kpis is None:
        st.info("Not enough data to compute KPIs for this range.")
        return
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Average price", f"{kpis.avg_price:.1f} öre/kWh")
    c2.metric(
        "Cheapest hour", f"{kpis.cheapest_price:.1f} öre/kWh",
        kpis.cheapest_time.strftime("%Y-%m-%d %H:%M"),
    )
    c3.metric(
        "Most expensive hour", f"{kpis.priciest_price:.1f} öre/kWh",
        kpis.priciest_time.strftime("%Y-%m-%d %H:%M"),
    )
    c4.metric("Avg daily spread", f"{kpis.daily_spread:.1f} öre/kWh")
    st.caption(
        "Daily spread is the average gap between each day's highest and lowest price — "
        "a bigger gap means more to gain from shifting load within the day."
    )


def _render_heatmap(prices_df, price_col):
    long_form = hourly_weekday_means(prices_df, price_col)
    if long_form.empty:
        st.info("Not enough data to build the hour × weekday heatmap for this range.")
        return
    coded = categorize_by_price(long_form, price_col)
    code_map = {cat: i for i, cat in enumerate(CATEGORY_ORDER)}
    coded["code"] = coded["category"].map(code_map)

    price_grid = coded.pivot(index="weekday", columns="hour", values=price_col).reindex(
        index=range(7), columns=range(24)
    )
    code_grid = coded.pivot(index="weekday", columns="hour", values="code").reindex(
        index=range(7), columns=range(24)
    )

    n = len(CATEGORY_ORDER)
    colorscale = []
    for i, cat in enumerate(CATEGORY_ORDER):
        colorscale += [[i / n, CATEGORY_COLORS[cat]], [(i + 1) / n, CATEGORY_COLORS[cat]]]

    fig = go.Figure(
        go.Heatmap(
            z=code_grid.values,
            x=[f"{h:02d}" for h in range(24)],
            y=WEEKDAY_LABELS,
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
    fig.update_layout(template="plotly_white", title="Average price by hour and weekday")
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "Darker/warmer cells are the consistently pricier hour-weekday combinations across "
        "the selected period — use this to spot a weekly pattern, not a single day's prices. "
        + LEGEND_CAPTION
    )


def _render_price_chart(prices_df, title, solar_df, span_days, now_marker=None, show_insight=False):
    prices_df = prices_df.assign(ore_per_kWh=prices_df["SEK_per_kWh"] * 100)
    prod_df = solar_df if solar_df is not None and not solar_df.empty else None

    if span_days > HOURLY_BAR_MAX_DAYS:
        price_rows = categorize_by_price(
            resample_daily_mean(prices_df, columns=["ore_per_kWh"]), "ore_per_kWh"
        )
        if prod_df is not None:
            # a daily *sum*, not a mean: production is energy, and a day's
            # total kWh is the number an advisor actually quotes
            prod_df = prod_df[[PRODUCTION_COLUMN]].resample("1D").sum()
    else:
        price_rows = categorize_by_price(prices_df, "ore_per_kWh")

    if price_rows.empty:
        st.info("No price data for the selected range.")
        return

    st.subheader(title)

    if show_insight:
        _render_kpi_cards(prices_df, "ore_per_kWh")

    fig = _build_price_figure(price_rows, "ore_per_kWh", prod_df, now_marker)
    st.plotly_chart(fig, use_container_width=True)
    caption = LEGEND_CAPTION
    if prod_df is not None:
        caption += (
            f" Solar production is an estimate for a {SPIKE_DEFAULT_KWP:.0f} kWp"
            f" {DEFAULT_ORIENTATION.lower()}-facing system at {PANEL_TILT_DEG}° tilt"
            f" ({SYSTEM_LOSS_FACTOR:.0%} of theoretical, to cover inverter and other losses)."
        )
    st.caption(caption)

    if show_insight:
        _render_heatmap(prices_df, "ore_per_kWh")


def _render_planner(units_df, prices, position_labels, usual_pos_fn, wrap, caption):
    active = units_df[
        units_df["active"].fillna(False) & (units_df["name"].astype(str).str.strip() != "")
    ]
    if active.empty:
        st.info("No active production units — add one above or switch a unit on.")
        return

    plans, lines = [], []
    for _, row in active.iterrows():
        hours = int(row["hours"]) if pd.notna(row["hours"]) else 0
        power_kw = float(row["power_kw"]) if pd.notna(row["power_kw"]) else 0.0
        usual_pos = usual_pos_fn(row["usual_start"]) if pd.notna(row["usual_start"]) else None
        plan = plan_unit(prices, hours, power_kw, usual_pos, wrap=wrap)
        plans.append(plan)

        if not plan.fits:
            lines.append(f"**{row['name']}**: run length ({hours}h) doesn't fit the available priced hours.")
            continue
        label = position_labels[plan.recommended_start] if plan.recommended_start is not None else "—"
        lines.append(f"Start **{row['name']}** at {label} — est. cost {plan.recommended_cost:.1f} öre.")
        if usual_pos is None and pd.notna(row["usual_start"]):
            lines.append(f"  ↳ usual start for {row['name']} isn't within the priced window — no comparison available.")

    for line in lines:
        st.write(line)

    totals = planner_totals(plans)
    yearly = yearly_saving_estimate(totals.total_saving)

    c1, c2, c3 = st.columns(3)
    c1.metric("Total energy", f"{totals.total_energy_kwh:.1f} kWh")
    c2.metric(
        "Total cost (recommended)", f"{totals.total_recommended_cost:.1f} öre",
        f"saved {totals.total_saving:.1f} öre vs usual",
    )
    c3.metric("Yearly saving (est.)", f"{yearly / 100:,.0f} SEK")
    st.caption(
        caption + " Yearly figure assumes one run per day; not a forecast. "
        "Grid/capacity charges are not modelled — spot price only."
    )


DEFAULT_UNITS = pd.DataFrame({
    "name": ["Induction furnace", "Compressor line"],
    "power_kw": [120.0, 45.0],
    "hours": [4, 3],
    "usual_start": [time(6, 0), time(22, 0)],
    "active": [True, True],
})

st.subheader("Production units")
st.caption("Add your flexible loads here — used by the planner in both tabs below.")
units_df = st.data_editor(
    DEFAULT_UNITS,
    key="units_editor",
    num_rows="dynamic",
    hide_index=True,
    column_config={
        "name": st.column_config.TextColumn("Name", required=True),
        "power_kw": st.column_config.NumberColumn("Power (kW)", min_value=0.0, step=1.0),
        "hours": st.column_config.NumberColumn("Run length (h)", min_value=1, step=1, format="%d"),
        "usual_start": st.column_config.TimeColumn("Usual start", format="HH:mm", step=3600),
        "active": st.column_config.CheckboxColumn("Active"),
    },
)

show_solar = st.checkbox("Show solar production", value=True)

tab_history, tab_plan = st.tabs(["History", "Plan ahead"])

with tab_history:
    today = _now_stockholm().date()
    date_range = st.date_input("Date range", value=DEFAULT_RANGE, max_value=today)
    if len(date_range) != 2:
        st.info("Pick an end date to see the chart.")
    else:
        start, end = sorted(date_range)
        span_days = (end - start).days + 1

        solar_df = None
        if show_solar:
            try:
                irradiance, s_failed, s_fallback = _cached_fetch_irradiance(
                    start, end, DEFAULT_ORIENTATION
                )
                _render_fallback_notices(s_fallback, s_failed)
                solar_df = production_kwh(irradiance, SPIKE_DEFAULT_KWP)
            except Exception:
                st.error("Solar data unavailable right now; showing prices only.")

        prices_df, p_failed, p_fallback = _cached_fetch_prices_history(start, end, PRICE_AREA)
        _render_fallback_notices(p_fallback, p_failed)
        _render_price_chart(
            prices_df, f"{PRICE_AREA} — prices and solar production", solar_df,
            span_days, show_insight=True,
        )

        hourly_ore = prices_df.assign(ore=prices_df["SEK_per_kWh"] * 100)
        typical = typical_hour_of_day(hourly_ore, "ore")
        if typical.empty:
            st.info("Not enough data to build a typical-day profile for the planner.")
        else:
            typical_prices = typical.tolist()
            typical_labels = [f"{h:02d}:00" for h in typical.index]

            def _typical_usual_pos(t, _index=list(typical.index)):
                return _index.index(t.hour) if t.hour in _index else None

            _render_planner(
                units_df, typical_prices, typical_labels, _typical_usual_pos, wrap=True,
                caption="History: typical savings based on the selected period's average "
                        "price per hour of day — not a prediction.",
            )

with tab_plan:
    now = _now_stockholm()
    today, tomorrow = now.date(), now.date() + timedelta(days=1)
    now_marker = pd.Timestamp(now).floor("h") + pd.Timedelta(minutes=30)

    solar_df = None
    if show_solar:
        try:
            irradiance, s_failed, s_fallback = _cached_fetch_irradiance_forecast(
                today, tomorrow, DEFAULT_ORIENTATION
            )
            _render_fallback_notices(s_fallback, s_failed)
            solar_df = production_kwh(irradiance, SPIKE_DEFAULT_KWP)
        except Exception:
            st.error("Solar forecast unavailable right now; showing prices only.")

    prices_df, p_failed, p_fallback = _cached_fetch_prices_planahead(today, tomorrow, PRICE_AREA)
    _render_fallback_notices(p_fallback, p_failed)

    tomorrow_present = not prices_df.empty and (prices_df.index.date == tomorrow).any()
    if not tomorrow_present:
        if tomorrow in p_failed:
            st.warning("Tomorrow's prices could not be fetched and have no cached fallback.")
        else:
            st.info("Tomorrow's prices aren't published yet (usually by ~13:00). Showing today only.")

    _render_price_chart(
        prices_df, f"{PRICE_AREA} — today and tomorrow", solar_df,
        span_days=2, now_marker=now_marker,
    )

    now_floor = pd.Timestamp(now).floor("h")
    remaining = prices_df[prices_df.index >= now_floor].assign(
        ore=lambda d: d["SEK_per_kWh"] * 100
    )
    if remaining.empty:
        st.info("No remaining priced hours today to plan against.")
    else:
        remaining_prices = remaining["ore"].tolist()
        remaining_labels = [t.strftime("%Y-%m-%d %H:%M") for t in remaining.index]

        def _remaining_usual_pos(t):
            # Floor to the hour (ignore minutes) -- the priced series is
            # hourly, so any usual_start with non-zero minutes would never
            # match an exact timestamp. Try today's occurrence of that hour
            # first, then tomorrow's, matching how a "usual start time"
            # actually recurs day to day.
            for day_offset in (0, 1):
                day = (now_floor + pd.Timedelta(days=day_offset)).date()
                candidate = pd.Timestamp.combine(day, time(t.hour, 0)).tz_localize(STOCKHOLM)
                if candidate in remaining.index:
                    return remaining.index.get_loc(candidate)
            return None

        _render_planner(
            units_df, remaining_prices, remaining_labels, _remaining_usual_pos, wrap=False,
            caption="Plan ahead: based on actual published prices from now onward.",
        )

st.caption(
    "Elpriser tillhandahålls av [Elpriset just nu.se](https://www.elprisetjustnu.se). "
    "Weather data by [Open-Meteo.com](https://open-meteo.com). "
    "Spot prices only — excludes VAT, energy tax, grid fees and supplier margin."
)
