"""Sprint 0 spike: fetch one month of SE3 spot prices and Gothenburg
temperature, print shapes, render one chart. No widgets/interactions yet."""

from datetime import date

import plotly.express as px
import streamlit as st

from src.prices import fetch_prices
from src.weather import fetch_temperature

st.set_page_config(page_title="Energy Price Dashboard — Spike", layout="wide")
st.title("Energy Price Dashboard — Sprint 0 spike")

START, END, AREA = date(2026, 8, 1), date(2026, 8, 31), "SE3"


@st.cache_data(ttl=3600)
def _cached_fetch_prices(start, end, area):
    return fetch_prices(start, end, area)


@st.cache_data(ttl=3600)
def _cached_fetch_temperature(start, end):
    return fetch_temperature(start, end)


with st.spinner(f"Fetching {AREA} spot prices, {START} to {END}..."):
    prices_df, failed_days = _cached_fetch_prices(START, END, AREA)

with st.spinner("Fetching Gothenburg temperature..."):
    weather_df = _cached_fetch_temperature(START, END)

st.subheader("Data shapes")
expected_hours = ((END - START).days + 1) * 24
st.write(
    f"Prices ({AREA}): {prices_df.shape} — expected ~{expected_hours} hourly "
    f"rows for a full month"
)
st.write(f"Temperature (Göteborg A, station 71420): {weather_df.shape}")
if failed_days:
    st.warning(
        f"{len(failed_days)} day(s) could not be fetched after retries "
        f"(not the same as confirmed-no-data): {failed_days}"
    )
else:
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
    "Sprint 0 spike — prices shown in SEK/kWh as returned by the API "
    "(öre/kWh conversion deferred to the display layer). No offline "
    "cache/fallback yet — see Sprint 1."
)
