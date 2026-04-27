"""Central unit conversion module.

Single source of truth for the metric ↔ imperial display switch. All storage
in the app stays canonical SI (metres, kilograms, seconds); these helpers run
at the display layer and inside the LLM prompt builder.

The frontend's ``web/src/units.ts`` mirrors this module 1:1.
"""

from __future__ import annotations

from typing import Literal

Units = Literal["metric", "imperial"]
VALID_UNITS: frozenset[str] = frozenset({"metric", "imperial"})


# ── Constants ─────────────────────────────────────────────────────────────────

M_TO_MI = 0.000621371
M_TO_KM = 0.001
KG_TO_LB = 2.20462
M_TO_FT = 3.28084
S_PER_KM_TO_S_PER_MI = 1.60934


# ── Labels ────────────────────────────────────────────────────────────────────


def dist_unit_label(units: str) -> str:
    return "mi" if units == "imperial" else "km"


def weight_unit_label(units: str) -> str:
    return "lb" if units == "imperial" else "kg"


def elev_unit_label(units: str) -> str:
    return "ft" if units == "imperial" else "m"


def speed_unit_label(units: str) -> str:
    return "mph" if units == "imperial" else "km/h"


def pace_unit_label(units: str) -> str:
    return "min/mi" if units == "imperial" else "min/km"


# ── Numeric conversions ───────────────────────────────────────────────────────


def m_to_distance(m: float | None, units: str) -> float | None:
    if m is None:
        return None
    return m * (M_TO_MI if units == "imperial" else M_TO_KM)


def km_to_distance(km: float | None, units: str) -> float | None:
    if km is None:
        return None
    return (km * 1000.0) * (M_TO_MI if units == "imperial" else M_TO_KM)


def kg_to_weight(kg: float | None, units: str) -> float | None:
    if kg is None:
        return None
    return kg * KG_TO_LB if units == "imperial" else kg


def m_to_elevation(m: float | None, units: str) -> float | None:
    if m is None:
        return None
    return m * M_TO_FT if units == "imperial" else m


def s_per_km_to_pace_seconds(s_per_km: float | None, units: str) -> float | None:
    """Convert seconds/km to seconds per the user's preferred distance unit."""
    if s_per_km is None:
        return None
    return s_per_km * S_PER_KM_TO_S_PER_MI if units == "imperial" else s_per_km


def s_per_km_to_speed(s_per_km: float | None, units: str) -> float | None:
    """Convert seconds/km pace to speed in the user's preferred unit (km/h or mph)."""
    if s_per_km is None or s_per_km <= 0:
        return None
    kph = 3600.0 / s_per_km
    return kph * (M_TO_MI / M_TO_KM) if units == "imperial" else kph


# ── Round-trip helpers (Calendar form input) ─────────────────────────────────


def imperial_input_to_km(value: float | None, units: str) -> float | None:
    """Take user input in their preferred unit and return km for storage."""
    if value is None:
        return None
    if units == "imperial":
        # value is in miles; convert to km
        return value / (M_TO_MI / M_TO_KM)
    return value


def imperial_input_to_m(value: float | None, units: str) -> float | None:
    """Take user input in their preferred elevation unit and return metres."""
    if value is None:
        return None
    if units == "imperial":
        return value / M_TO_FT
    return value


# ── Formatting helpers ────────────────────────────────────────────────────────


def format_distance(m: float | None, units: str, *, precision: int = 2) -> str:
    v = m_to_distance(m, units)
    if v is None:
        return "—"
    return f"{v:.{precision}f}{dist_unit_label(units)}"


def format_pace(s_per_km: float | None, units: str) -> str:
    """Format pace as M:SS/<unit>. Imperial users see s per mile."""
    s = s_per_km_to_pace_seconds(s_per_km, units)
    if s is None:
        return "—"
    mins = int(s // 60)
    secs = int(s % 60)
    return f"{mins}:{secs:02d}/{dist_unit_label(units)}"


def format_speed(s_per_km: float | None, units: str) -> str:
    """Format speed as 'XX.X km/h' or 'XX.X mph'."""
    v = s_per_km_to_speed(s_per_km, units)
    if v is None:
        return "—"
    return f"{v:.1f}{speed_unit_label(units)}"


def format_elevation(m: float | None, units: str, *, precision: int = 0) -> str:
    v = m_to_elevation(m, units)
    if v is None:
        return "—"
    return f"{v:.{precision}f}{elev_unit_label(units)}"


def format_weight(kg: float | None, units: str, *, precision: int = 0) -> str:
    v = kg_to_weight(kg, units)
    if v is None:
        return "—"
    return f"{v:.{precision}f}{weight_unit_label(units)}"


def format_duration(seconds: int | None) -> str:
    """Unit-agnostic; kept here so callers have one place to import all formatters."""
    if seconds is None:
        return "—"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m{s:02d}s"
    return f"{m}m{s:02d}s"


# ── LLM unit instruction ──────────────────────────────────────────────────────


def llm_unit_instruction(mode: str, units: str) -> str:
    """Return the per-mode unit instruction line injected into the system prompt.

    Replaces the hardcoded ``"Use metric units (km, min/km)…"`` line that used
    to live in each mode's base prompt.
    """
    if units == "imperial":
        if mode == "running":
            return "Use imperial units (mi, min/mi) when reporting distances and paces."
        if mode == "cycling":
            return "Use imperial units (mi, mph) when reporting distances and speeds."
        if mode == "lifting":
            return (
                "Use imperial units (lb) when reporting weights, sets, and 1RM estimates. "
                "When estimating 1-rep maxes, still use the Epley formula (weight × (1 + reps/30))."
            )
        # hybrid / default
        return "Use imperial units (mi, min/mi for runs, mph for rides) when reporting metrics."

    # metric
    if mode == "running":
        return "Use metric units (km, min/km) when reporting distances and paces."
    if mode == "cycling":
        return "Use metric units (km, km/h) when reporting distances and speeds."
    if mode == "lifting":
        return (
            "Use metric units (kg) when reporting weights, sets, and 1RM estimates. "
            "When estimating 1-rep maxes, still use the Epley formula (weight × (1 + reps/30))."
        )
    return "Use metric units (km, min/km for runs, km/h for rides) when reporting metrics."
