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

# --- Spike-only default ----------------------------------------------------
# Sprint 7 replaces this with the advisor's kWp slider; until then the
# overlay needs some system size to render a production line at all.
SPIKE_DEFAULT_KWP = 10.0
