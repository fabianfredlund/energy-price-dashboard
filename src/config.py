"""Structural constants, and the **defaults** for every editable assumption.

Two kinds of thing live here.

1. **Structure** — the price area, the location, the azimuth convention. Not
   negotiable at runtime, so they are plain constants.
2. **Assumptions** — every number an advisor might be asked to justify. These
   are *defaults only*. The UI makes them editable, and the current values
   travel in a `Settings` object. Nothing in `src/` outside this module may read
   an assumption directly: a function that did would silently ignore the user's
   edit, which is this design's characteristic failure.

Each assumption carries its own source and "last updated" date **in the same
tuple as its value**, so the two cannot drift apart, and a `verified` flag so the
UI can mark what nobody has checked yet.
"""

from datetime import date
from typing import NamedTuple

# --- Structure -------------------------------------------------------------

PRICE_AREA = "SE3"  # Gothenburg region; fixed since the Sprint 5 pivot
LATITUDE = 57.71
LONGITUDE = 11.97

# Open-Meteo azimuth convention, verified live against the API during the
# Sprint 5 spike by curve shape (not assumed): east peaks in the morning,
# west peaks in the evening.
AZIMUTH_SOUTH = 0
AZIMUTH_EAST = -90
AZIMUTH_WEST = 90


class Orientation(NamedTuple):
    slug: str  # filesystem-safe, used in cache keys
    azimuths: tuple[int, ...]  # averaged -> an east-west roof is half the array each way


ORIENTATIONS: dict[str, Orientation] = {
    "South": Orientation("south", (AZIMUTH_SOUTH,)),
    "East–West": Orientation("eastwest", (AZIMUTH_EAST, AZIMUTH_WEST)),
}
DEFAULT_ORIENTATION = "South"

# --- The window ------------------------------------------------------------
# Three full years, FIXED rather than rolling, so every figure is identical
# across the written report, the screenshots and the pitch video. Moving it is
# a deliberate edit, not something that happens quietly on the first of a month.
WINDOW_START = date(2023, 10, 1)
WINDOW_END = date(2026, 9, 30)
WINDOW_LABEL = "Oct 2023 – Sep 2026"

# The battery sizes the model sweeps to answer "should they, and how big".
BATTERY_SIZES_KWH: tuple[int, ...] = (0, 5, 10, 15)


# --- Assumptions -----------------------------------------------------------

class Assumption(NamedTuple):
    value: float
    unit: str
    label: str
    updated: date
    source: str
    verified: bool  # False -> the UI shows a warning sign


_TODAY = date(2026, 10, 6)

ASSUMPTIONS: dict[str, Assumption] = {
    # -- prices --
    "vat_rate": Assumption(
        0.25, "", "VAT applied to the spot price of bought electricity",
        _TODAY, "Standard Swedish VAT rate", True,
    ),
    "surcharge_sek_per_kwh": Assumption(
        0.68, "SEK/kWh",
        "Surcharge per bought kWh (energy tax + grid transfer, incl. VAT)",
        _TODAY,
        "Energy tax 45 öre/kWh incl. VAT (2026) + Göteborg Energi Nät villa "
        "transfer fee 23 öre/kWh incl. VAT. Transfer fee varies by grid operator "
        "and by housing type (apartments pay more) — check the customer's bill.",
        False,
    ),
    # -- lifetimes --
    "solar_lifetime_years": Assumption(
        25, "years", "Expected life of the solar installation",
        _TODAY, "Industry convention; panel performance warranties typically run "
        "25 years. Not independently sourced.", False,
    ),
    "battery_lifetime_years": Assumption(
        10, "years", "Battery warranty — the horizon the recommendation uses",
        _TODAY,
        "10 years is the most common home-battery warranty in Sweden (range "
        "5–10; quality units 10–15). Warranties typically guarantee 60–80% of "
        "original capacity at expiry.", True,
    ),
    "battery_service_life_years": Assumption(
        15, "years", "Expected service life — used only to qualify a 'No'",
        _TODAY,
        "Expected service life runs 15–25 years, longer than the warranty. 15 is "
        "the conservative end. This NEVER drives the recommendation; it only "
        "lets the card say a battery that misses on warranty would pay off on "
        "likely real life.", True,
    ),
    # -- green technology deduction --
    "green_tech_solar_rate": Assumption(
        0.15, "", "Green technology deduction, solar (labour and material)",
        _TODAY, "Skattereduktion för grön teknik, 2026 rate", True,
    ),
    "green_tech_battery_rate": Assumption(
        0.50, "", "Green technology deduction, battery storage",
        _TODAY, "Skattereduktion för grön teknik, 2026 rate", True,
    ),
    "green_tech_cap_per_owner_sek": Assumption(
        50000, "SEK", "Deduction cap, per owner per year",
        _TODAY,
        "50 000 SEK per person per year, combined across all green technology. "
        "Doubling it requires joint ownership of the home AND a split invoice — "
        "two adults living there is not enough.", True,
    ),
    # -- production --
    "system_loss_factor": Assumption(
        0.85, "", "System losses (inverter, cabling, soiling, temperature)",
        date(2026, 10, 5), "The figure named in the project brief. Not "
        "independently sourced.", False,
    ),
    "panel_tilt_deg": Assumption(
        40, "°", "Roof pitch",
        date(2026, 10, 5), "Typical Swedish villa roof pitch. Not independently "
        "sourced, and it is a per-customer fact rather than a constant.", False,
    ),
    # -- battery behaviour --
    "round_trip_efficiency": Assumption(
        0.90, "", "Battery round trip, booked entirely on discharge",
        date(2026, 10, 5), "\"Put 10 kWh in, get 9 kWh back\" — a figure an "
        "advisor can say out loud. Not independently sourced.", False,
    ),
    "battery_max_power_fraction": Assumption(
        0.5, "", "Max charge/discharge per hour, as a fraction of capacity",
        date(2026, 10, 5), "A full charge takes two hours. Not independently "
        "sourced.", False,
    ),
    "grid_charge_min_margin_sek_per_kwh": Assumption(
        0.10, "SEK/kWh", "Minimum saving before charging the battery from the grid",
        date(2026, 10, 5), "Additive, not a percentage: at a negative price a "
        "percentage margin lowers the bar instead of raising it. Not "
        "independently sourced.", False,
    ),
    # -- disclosed but NOT modelled --
    "effektavgift_sek_per_kw": Assumption(
        49, "SEK/kW", "Capacity charge — excluded from the calculation",
        _TODAY,
        "Göteborg Energi Nät charges 49 kr per kW, on the mean of the month's "
        "three highest hourly averages. This is exactly where a battery earns, "
        "and it is NOT modelled — which is part of why payback looks long.",
        False,
    ),
}

#: Structural, NOT editable, despite also appearing in ASSUMPTIONS above:
#: the tilt is baked into the cache key (`south_t40`), so changing it at
#: runtime would silently read a snapshot taken at a different angle.
#: Derived from the table so the two cannot drift. A customer with a
#: different roof pitch needs a re-fetch, not a widget.
PANEL_TILT_DEG = int(ASSUMPTIONS["panel_tilt_deg"].value)


# --- Input defaults --------------------------------------------------------
# What the five inputs start at. Sourced where a source exists, because the
# default decides what the screen says before anyone touches a control.

DEFAULT_ANNUAL_CONSUMPTION_KWH = 20000
DEFAULT_KWP = 10

#: Installed price before any deduction. Research (Oct 2026) puts a complete
#: villa installation at 15 000–20 000 SEK per kWp, ~17 000 typical; a 10 kW
#: system is commonly quoted at 150 000–200 000 SEK. Replace with Kustsol's own
#: figure when available.
DEFAULT_SYSTEM_PRICE_SEK_PER_KWP = 17000
DEFAULT_SYSTEM_PRICE_SEK = DEFAULT_SYSTEM_PRICE_SEK_PER_KWP * DEFAULT_KWP

#: Installed price per kWh before any deduction. Research (Oct 2026) puts home
#: batteries at 6 000–7 500 SEK/kWh, ~7 000 typical; a 10 kWh battery is
#: commonly quoted around 70 000 SEK.
#:
#: This is the single most load-bearing unverified number in the project: it
#: decides the battery Yes/No on its own. Break-even for a 10-year payback is
#: roughly 3 200–3 500 SEK/kWh without the deduction.
DEFAULT_BATTERY_PRICE_SEK_PER_KWH = 7000


# --- The current values ----------------------------------------------------

class Settings(NamedTuple):
    """The assumption values a calculation actually runs with.

    Built from `ASSUMPTIONS` by `Settings.defaults()` and then overridden by
    the UI's widgets. Everything in `src/` takes one of these (or its fields)
    as a **required** argument rather than reading `ASSUMPTIONS` directly, so a
    user's edit can never be silently ignored.
    """

    vat_rate: float
    surcharge_sek_per_kwh: float
    solar_lifetime_years: int
    battery_lifetime_years: int
    battery_service_life_years: int
    green_tech_enabled: bool
    green_tech_owners: int
    green_tech_solar_rate: float
    green_tech_battery_rate: float
    green_tech_cap_per_owner_sek: float
    system_loss_factor: float
    round_trip_efficiency: float
    battery_max_power_fraction: float
    grid_charge_min_margin_sek_per_kwh: float

    @classmethod
    def defaults(cls, **overrides) -> "Settings":
        """The only place that reads `ASSUMPTIONS`."""
        values = {
            name: ASSUMPTIONS[name].value
            for name in cls._fields
            if name in ASSUMPTIONS
        }
        values["green_tech_enabled"] = False  # off by default, per the brief
        values["green_tech_owners"] = 1
        values.update(overrides)
        return cls(**values)
