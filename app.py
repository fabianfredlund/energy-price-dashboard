"""Sprint 2: History and Plan ahead modes, the three required interactions
(date range, price area + compare, temperature overlay), and colour-coded
prices. KPI cards, the heatmap, and the production planner are Sprint 3."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from src.prices import VALID_AREAS, fetch_prices
from src.transform import CATEGORY_ORDER, categorize_by_price, resample_daily_mean
from src.weather import fetch_temperature

STOCKHOLM = ZoneInfo("Europe/Stockholm")
HOURLY_BAR_MAX_DAYS = 31

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
TEMPERATURE_COLOR = "#2a78d6"
LEGEND_CAPTION = "Green = cheap, grey = normal, orange = expensive, red = price spike (top 10%)."

st.set_page_config(page_title="Energy Price Dashboard", layout="wide")
st.title("Energy Price Dashboard")


def _now_stockholm() -> datetime:
    return datetime.now(STOCKHOLM)


@st.cache_data(ttl=3600)
def _cached_fetch_prices_history(start, end, area):
    return fetch_prices(start, end, area)


@st.cache_data(ttl=600)  # short TTL: "is tomorrow published yet" can flip within a session
def _cached_fetch_prices_planahead(start, end, area):
    return fetch_prices(start, end, area)


@st.cache_data(ttl=3600)
def _cached_fetch_temperature(start, end):
    return fetch_temperature(start, end)


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


def _build_price_figure(price_df, price_col, temp_df=None, now_marker=None):
    """One figure with price bars on top; when temperature is shown, a second
    panel below sharing the same time axis (never a secondary y-axis on the
    same panel -- the dataviz skill treats dual-axis charts as the #1 chart
    mistake, since the visual alignment between two independent y-scales is
    arbitrary and can look like a correlation that isn't really there)."""
    show_temp = temp_df is not None and not temp_df.empty
    if show_temp:
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

    if show_temp:
        fig.add_trace(
            go.Scatter(
                x=temp_df.index, y=temp_df["temperature_c"], name="Temperature (°C)",
                mode="lines", line=dict(color=TEMPERATURE_COLOR, width=2),
                hovertemplate="%{x|%Y-%m-%d %H:%M}<br>%{y:.1f} °C<extra></extra>",
            ),
            row=2, col=1,
        )

    if now_marker is not None:
        fig.add_vline(x=now_marker, line_dash="dot", line_color="#52514e",
                       annotation_text="Now", row=1, col=1)

    fig.update_layout(template="plotly_white", bargap=0.1, showlegend=True)
    fig.update_yaxes(gridcolor="#e1e0d9", title_text="öre/kWh", row=1, col=1)
    if show_temp:
        fig.update_yaxes(gridcolor="#e1e0d9", title_text="°C", row=2, col=1)
    return fig


def _render_price_chart(prices_df, area_label, weather_df, span_days, now_marker=None):
    prices_df = prices_df.assign(ore_per_kWh=prices_df["SEK_per_kWh"] * 100)
    temp_df = weather_df if weather_df is not None and not weather_df.empty else None

    if span_days > HOURLY_BAR_MAX_DAYS:
        price_rows = categorize_by_price(
            resample_daily_mean(prices_df, columns=["ore_per_kWh"]), "ore_per_kWh"
        )
        if temp_df is not None:
            temp_df = resample_daily_mean(temp_df, columns=["temperature_c"])
    else:
        price_rows = categorize_by_price(prices_df, "ore_per_kWh")

    if price_rows.empty:
        st.info(f"No price data for {area_label} in the selected range.")
        return

    st.subheader(area_label)
    fig = _build_price_figure(price_rows, "ore_per_kWh", temp_df, now_marker)
    st.plotly_chart(fig, use_container_width=True)
    caption = LEGEND_CAPTION
    if temp_df is not None:
        caption += " Temperature is observed (not forecast), shown as a separate panel on the same timeline."
    st.caption(caption)


col_area, col_compare, col_temp = st.columns(3)
with col_area:
    area = st.selectbox("Price area", sorted(VALID_AREAS), index=sorted(VALID_AREAS).index("SE3"))
with col_compare:
    compare_on = st.checkbox("Compare with another area")
    compare_area = (
        st.selectbox("Compare against", [a for a in sorted(VALID_AREAS) if a != area])
        if compare_on
        else None
    )
with col_temp:
    show_temp = st.checkbox("Show temperature overlay")

tab_history, tab_plan = st.tabs(["History", "Plan ahead"])

with tab_history:
    today = _now_stockholm().date()
    date_range = st.date_input(
        "Date range",
        value=(date(2026, 8, 1), date(2026, 8, 31)),
        max_value=today,
    )
    if len(date_range) != 2:
        st.info("Pick an end date to see the chart.")
    else:
        start, end = sorted(date_range)
        span_days = (end - start).days + 1

        weather_df = None
        if show_temp:
            try:
                weather_df, w_failed, w_fallback = _cached_fetch_temperature(start, end)
                _render_fallback_notices(w_fallback, w_failed)
            except Exception:
                st.error("Temperature data unavailable right now; showing prices only.")

        for a in [area] + ([compare_area] if compare_area else []):
            prices_df, p_failed, p_fallback = _cached_fetch_prices_history(start, end, a)
            _render_fallback_notices(p_fallback, p_failed)
            _render_price_chart(prices_df, a, weather_df, span_days)

with tab_plan:
    now = _now_stockholm()
    today, tomorrow = now.date(), now.date() + timedelta(days=1)
    now_marker = pd.Timestamp(now).floor("h") + pd.Timedelta(minutes=30)

    weather_df = None
    if show_temp:
        try:
            weather_df, w_failed, w_fallback = _cached_fetch_temperature(today, tomorrow)
            _render_fallback_notices(w_fallback, w_failed)
        except Exception:
            st.error("Temperature data unavailable right now; showing prices only.")

    for a in [area] + ([compare_area] if compare_area else []):
        prices_df, p_failed, p_fallback = _cached_fetch_prices_planahead(today, tomorrow, a)
        _render_fallback_notices(p_fallback, p_failed)

        tomorrow_present = not prices_df.empty and (prices_df.index.date == tomorrow).any()
        if not tomorrow_present:
            if tomorrow in p_failed:
                st.warning(f"{a}: tomorrow's prices could not be fetched and have no cached fallback.")
            else:
                st.info(f"{a}: tomorrow's prices aren't published yet (usually by ~13:00). Showing today only.")

        _render_price_chart(prices_df, a, weather_df, span_days=2, now_marker=now_marker)

st.caption(
    "Elpriser tillhandahålls av [Elpriset just nu.se](https://www.elprisetjustnu.se). "
    "Spot prices only — excludes VAT, energy tax, grid fees and supplier margin."
)
