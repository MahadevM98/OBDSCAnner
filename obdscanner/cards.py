"""
Analysis cards for the Honda Accord 8th gen 2.4L.

Each card pairs an automatic analyzer (from analysis.py) with the reference
thresholds and the list of likely causes a technician would check, so the
Analysis tab can show a self-contained "what it is / what's normal / what to
look at" panel per system. Layout follows the spec in the project `NEw` file.

The Honda-specific card is special: enhanced parameters (VTEC, VTC angle,
knock, transmission temperature) are not part of generic OBD-II, so it reads
manufacturer Mode 22 data live — see honda.py. Those values are EXPERIMENTAL
and ECU/model dependent.
"""

from __future__ import annotations

from collections import namedtuple

from . import analysis as an

Card = namedtuple("Card", "title analyzer reference causes")

CARDS = [
    Card(
        "Fuel Trim Analyzer",
        an.analyze_fuel_trim,
        ["Normal:  -10% to +10%",
         "Warning: ±10% to ±20%",
         "Fault:   greater than ±20%"],
        ["Vacuum leak", "Fuel pump / pressure",
         "Injector issue", "MAF or O2 sensor issue"],
    ),
    Card(
        "Catalytic Converter Analyzer",
        an.analyze_catalyst,
        ["Inputs: O2 B1S1, O2 B1S2, fuel trims, engine load",
         "Healthy: downstream O2 steady while upstream swings"],
        ["Cat efficiency degraded", "Cat possibly restricted",
         "O2 sensor issue"],
    ),
    Card(
        "Ignition Analyzer",
        an.analyze_ignition_timing,
        ["Watch: timing advance at cruise, timing pull under load"],
        ["Excessive knock retard", "Poor fuel quality",
         "Ignition / knock sensor fault"],
    ),
    Card(
        "MAP Sensor Analyzer",
        an.analyze_map,
        ["Warm idle:      25-40 kPa",
         "2500 rpm no load: lower than idle",
         "Wide open throttle: ~95-100 kPa (near atmospheric)"],
        ["Vacuum leak", "Intake / exhaust restriction",
         "MAP sensor fault"],
    ),
    Card(
        "Cooling System Analyzer",
        an.analyze_cooling,
        ["Operating temp: 80-98°C",
         "Thermostat opens ~90°C",
         "Above 105°C = overheating"],
        ["Thermostat stuck open", "Overheating / low coolant",
         "Fan or water-pump fault"],
    ),
]


def render(card: Card, snap: dict) -> dict:
    """Run a card's analyzer on a snapshot and bundle it with its reference."""
    finding = card.analyzer(snap)
    return {
        "title": card.title,
        "status": finding.status,
        "detail": finding.detail,
        "reference": card.reference,
        "causes": card.causes,
    }


def render_all(snap: dict) -> list[dict]:
    return [render(c, snap) for c in CARDS]


def honda_card(enhanced: list) -> dict:
    """Build the Honda-specific card from a list of (name, value, unit) read
    via Mode 22. Empty list -> 'not available' (the common real-world case)."""
    if enhanced:
        detail = "Enhanced parameters read (EXPERIMENTAL — verify per model):"
        lines = [f"{name}: {value} {unit}".strip() for name, value, unit in enhanced]
        status = an.NORMAL
    else:
        detail = ("No Honda enhanced data returned. These parameters are "
                  "manufacturer-specific (Mode 22) and depend on the ECU and "
                  "adapter; many clones cannot read them.")
        lines = ["VTEC status", "VTC cam angle", "Knock count / retard",
                 "Transmission fluid temperature"]
        status = an.UNKNOWN
    return {
        "title": "Honda-Specific Data (experimental)",
        "status": status,
        "detail": detail,
        "reference": lines,
        "causes": [],
    }
