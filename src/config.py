"""Constants and stated assumptions for the Solar Advisor dashboard.

Everything an advisor might be asked to justify in a customer meeting
lives here, in one place, so the Assumptions expander in the UI can show
the same numbers the calculations use.

Sprint 5 scope: only the constants the solar spike actually needs.
Sprint 6 adds the price/tax/grid and battery constants.

TODO: Fabian verifies the values marked below before these numbers go in
front of a real customer.
"""

from typing import NamedTuple

# --- Price area ------------------------------------------------------------
# v2 is fixed to SE3 (Gothenburg region) -- the area dropdown and the
# area comparison from v1 were removed in the pivot.
PRICE_AREA = "SE3"

# --- Location (Gothenburg) -------------------------------------------------
LATITUDE = 57.71
LONGITUDE = 11.97

# --- Panel geometry --------------------------------------------------------
# Tilt is a fixed, documented assumption rather than a sixth advisor input
# (the input set is consumption / kWp / orientation / battery / battery price).
# TODO: Fabian verifies -- 40 deg is a typical Swedish villa roof pitch.
PANEL_TILT_DEG = 40

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

# --- System losses ---------------------------------------------------------
# Covers inverter losses, cabling, soiling, temperature derating.
# TODO: Fabian verifies -- 0.85 is the figure named in CLAUDE.md.
SYSTEM_LOSS_FACTOR = 0.85

# --- Advisor input default -------------------------------------------------
# Where the kWp slider starts. 10 kWp is a common villa system size, so the
# first thing an advisor sees is a plausible customer rather than a stub.
# TODO: Fabian verifies against Kustsol's actual typical installation.
DEFAULT_KWP = 10.0

# --- Buy and sell price components (SEK per kWh) ---------------------------
# buy  = (spot + energy tax + grid fee) * (1 + VAT)
# sell = spot + grid benefit            (no VAT: a private microproducer is
#                                        normally not VAT-registered for this)
#
# TODO: Fabian verifies all four against the customer's actual contract and
# grid operator -- these drive every SEK figure the advisor quotes.
ENERGY_TAX_SEK_PER_KWH = 0.36  # 36 öre excl VAT (45 öre incl) for 2026
GRID_FEE_SEK_PER_KWH = 0.27  # variable transmission, ~33.75 öre incl VAT
VAT_RATE = 0.25  # applies to the whole bill, including the energy tax itself
GRID_BENEFIT_SEK_PER_KWH = 0.05  # nätnytta -- PLACEHOLDER, not yet sourced

# Deliberately NOT modelled: the fixed annual grid charge (~175 kr/ampere of
# main fuse). It does not change with solar or a battery, so it cancels out of
# every scenario difference. Worth knowing that capacity/effekt tariffs live
# here, which is one reason the payback figure below looks conservative.

# --- Battery ---------------------------------------------------------------
# The round trip is booked entirely on discharge, so the rule an advisor says
# out loud is "put 10 kWh in, get 9 kWh back".
BATTERY_ROUND_TRIP_EFFICIENCY = 0.90
# Max charge/discharge in one hour = capacity x this. At 0.5 a full charge
# takes exactly two hours, which is why the grid-charge window search below
# is always a 2-hour window.
BATTERY_MAX_POWER_FRACTION = 0.5
# Grid charging must beat the round-trip loss by at least this much per kWh.
# Additive, not a percentage: at a negative cheap price a percentage margin
# would lower the bar instead of raising it.
# TODO: Fabian verifies against the real cached year.
GRID_CHARGE_MIN_MARGIN_SEK_PER_KWH = 0.10

# --- Advisor input defaults ------------------------------------------------
# TODO: Fabian verifies -- starting points for the Sprint 7 input panel.
DEFAULT_ANNUAL_CONSUMPTION_KWH = 20000.0  # electrically heated villa
DEFAULT_BATTERY_KWH = 10.0
DEFAULT_BATTERY_PRICE_SEK = 75000.0  # installed, before any deduction

# Payback deliberately excludes the green-technology deduction,
# capacity/effekt-tariff savings and frequency-regulation income -- the three
# places Swedish home-battery economics actually lives. The UI must say so,
# because they are why an honest payback figure looks long.
