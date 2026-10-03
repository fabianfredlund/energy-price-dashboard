"""Sprint 1: fetch one month of SE3 spot prices and Gothenburg temperature
through the cached/fallback pipeline, print shapes, render one chart.
No widgets/interactions yet (Sprint 2)."""

from datetime import date

import pandas as pd
import plotly.express as px
import streamlit as st

from src.prices import fetch_prices
from src.weather import fetch_temperature

st.set_page_config(page_title="Energy Price Dashboard", layout="wide")
st.title("Energy Price Dashboard — Sprint 1")

START, END, AREA = date(2026, 8, 1), date(2026, 8, 31), "SE3"


@st.cache_data(ttl=3600)
def _cached_fetch_prices(start, end, area):
    return fetch_prices(start, end, area)


@st.cache_data(ttl=3600)
def _cached_fetch_temperature(start, end):
    return fetch_temperature(start, end)


with st.spinner(f"Fetching {AREA} spot prices, {START} to {END}..."):
    prices_df, price_failed_days, price_fallback_days = _cached_fetch_prices(START, END, AREA)

weather_df = pd.DataFrame()
weather_failed_days: list = []
weather_fallback_days: list = []
with st.spinner("Fetching Gothenburg temperature..."):
    try:
        weather_df, weather_failed_days, weather_fallback_days = _cached_fetch_temperature(
            START, END
        )
    except Exception:
        st.error("Temperature data unavailable right now; showing prices only.")

st.subheader("Data shapes")
expected_hours = ((END - START).days + 1) * 24
st.write(
    f"Prices ({AREA}): {prices_df.shape} — expected ~{expected_hours} hourly "
    f"rows for a full month"
)
st.write(f"Temperature (Göteborg A, station 71420): {weather_df.shape}")

fallback_days = price_fallback_days + weather_fallback_days
if fallback_days:
    st.info(
        f"{len(fallback_days)} day(s) served from the offline cache — "
        f"API was unreachable, used the last cached snapshot."
    )
failed_days = price_failed_days + weather_failed_days
if failed_days:
    st.warning(
        f"{len(failed_days)} day(s) could not be fetched and had no "
        f"cached fallback: {failed_days}"
    )
if not fallback_days and not failed_days:
    st.write("Failed days: 0")

st.dataframe(prices_df.head())
st.dataframe(weather_df.head())

st.subheader(f"{AREA} spot price, {START} to {END}")
fig = px.line(
    prices_df.reset_index(),
    x="time_start",
    y="SEK_per_kWh",
    labels={"time_start": "Time", "SEK_per_kWh": "Price (SEK/kWh)"},
)
st.plotly_chart(fig, use_container_width=True)

st.caption(
    "Prices shown in SEK/kWh as returned by the API (öre/kWh conversion "
    "deferred to the display layer). Falls back to the offline cache in "
    "data/cache/ if the live APIs are unreachable."
)
