"""Unit registry: the single place that knows how to convert and label measurements.

All measurements are stored in SI-based canonical units (see ``Quantity``). Display code never
does its own arithmetic — it asks this module (or a model's ``measurement()`` helper, which
delegates here) for a value in the athlete's chosen ``UnitSystem``.

Adding a new kind of measurement means adding one ``Quantity`` member and one ``_SPECS`` row.
The frontend mirror lives in ``web/src/units.ts``; ``tests/fixtures/unit_cases.json`` keeps the
two in sync.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

METERS_PER_MILE = 1609.344
FEET_PER_METER = 3.28084
POUNDS_PER_KG = 2.20462
FL_OZ_PER_ML = 0.033814
CM_PER_INCH = 2.54
KM_PER_MILE = METERS_PER_MILE / 1000


class UnitSystem(str, Enum):
    METRIC = "metric"
    IMPERIAL = "imperial"

    @classmethod
    def parse(cls, value: "str | UnitSystem | None") -> "UnitSystem":
        """Lenient parse: accepts the enum values plus the legacy chart params ("km"/"miles").
        Anything unrecognised falls back to the default."""
        if isinstance(value, UnitSystem):
            return value
        if not isinstance(value, str):
            return DEFAULT_UNIT_SYSTEM
        v = value.strip().lower()
        if v in ("imperial", "miles", "mi"):
            return cls.IMPERIAL
        if v in ("metric", "km"):
            return cls.METRIC
        return DEFAULT_UNIT_SYSTEM


DEFAULT_UNIT_SYSTEM = UnitSystem.METRIC


class Quantity(str, Enum):
    """A kind of measurement, named by its canonical stored unit."""

    DISTANCE = "distance"  # meters
    ELEVATION = "elevation"  # meters
    PACE = "pace"  # seconds per km
    SPEED = "speed"  # meters per second
    PACE_DELTA = "pace_delta"  # seconds per km (difference between two paces)
    CLIMB_RATE = "climb_rate"  # meters gained per km
    MASS = "mass"  # kilograms
    VOLUME = "volume"  # milliliters (fluid intake)
    HEIGHT = "height"  # centimeters (body height; imperial is shown as feet + inches)


@dataclass(frozen=True)
class UnitSpec:
    label: str  # short label shown after the number ("km", "/mi", "ft")
    factor: float  # display value = canonical value * factor
    decimals: int


_SPECS: dict[Quantity, dict[UnitSystem, UnitSpec]] = {
    Quantity.DISTANCE: {
        UnitSystem.METRIC: UnitSpec("km", 0.001, 2),
        UnitSystem.IMPERIAL: UnitSpec("mi", 1 / METERS_PER_MILE, 2),
    },
    Quantity.ELEVATION: {
        UnitSystem.METRIC: UnitSpec("m", 1.0, 0),
        UnitSystem.IMPERIAL: UnitSpec("ft", FEET_PER_METER, 0),
    },
    Quantity.PACE: {
        UnitSystem.METRIC: UnitSpec("/km", 1.0, 0),
        UnitSystem.IMPERIAL: UnitSpec("/mi", KM_PER_MILE, 0),
    },
    Quantity.SPEED: {
        UnitSystem.METRIC: UnitSpec("km/h", 3.6, 1),
        UnitSystem.IMPERIAL: UnitSpec("mph", 3600 / METERS_PER_MILE, 1),
    },
    Quantity.PACE_DELTA: {
        UnitSystem.METRIC: UnitSpec("s/km", 1.0, 0),
        UnitSystem.IMPERIAL: UnitSpec("s/mi", KM_PER_MILE, 0),
    },
    Quantity.CLIMB_RATE: {
        UnitSystem.METRIC: UnitSpec("m/km", 1.0, 0),
        UnitSystem.IMPERIAL: UnitSpec("ft/mi", FEET_PER_METER * KM_PER_MILE, 0),
    },
    Quantity.MASS: {
        UnitSystem.METRIC: UnitSpec("kg", 1.0, 0),
        UnitSystem.IMPERIAL: UnitSpec("lb", POUNDS_PER_KG, 0),
    },
    Quantity.VOLUME: {
        UnitSystem.METRIC: UnitSpec("ml", 1.0, 0),
        UnitSystem.IMPERIAL: UnitSpec("fl oz", FL_OZ_PER_ML, 0),
    },
    Quantity.HEIGHT: {
        UnitSystem.METRIC: UnitSpec("cm", 1.0, 0),
        UnitSystem.IMPERIAL: UnitSpec("in", 1 / CM_PER_INCH, 0),
    },
}


def spec(qty: Quantity, system: UnitSystem) -> UnitSpec:
    return _SPECS[qty][UnitSystem.parse(system)]


def unit_label(qty: Quantity, system: UnitSystem) -> str:
    return spec(qty, system).label


def convert(value: float | None, qty: Quantity, system: UnitSystem) -> float | None:
    """Canonical (SI) value -> display value in ``system``."""
    if value is None:
        return None
    return value * spec(qty, system).factor


def to_si(value: float | None, qty: Quantity, system: UnitSystem) -> float | None:
    """Display value in ``system`` -> canonical (SI) value. Used for user/LLM input."""
    if value is None:
        return None
    return value / spec(qty, system).factor


def speed_from_pace(s_per_km: float | None) -> float | None:
    """Stored pace (s/km) -> canonical speed (m/s). Cycling activities store pace too."""
    if s_per_km is None or s_per_km <= 0:
        return None
    return 1000 / s_per_km


def _clock(seconds: float) -> str:
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins}:{secs:02d}"


def format_value(
    value: float | None,
    qty: Quantity,
    system: UnitSystem,
    *,
    decimals: int | None = None,
    empty: str = "—",
    with_label: bool = True,
) -> str:
    """Canonical value -> display string, e.g. ``"6.21 mi"``, ``"9:39/mi"``, ``"+12 s/km"``."""
    s = spec(qty, system)
    shown = convert(value, qty, system)
    if shown is None:
        return empty
    if qty is Quantity.HEIGHT and s.label == "in":
        feet, inches = feet_inches(value)
        return f"{feet}' {inches}\"" if with_label else f"{feet}'{inches}"
    if qty is Quantity.PACE:
        return _clock(shown) + (s.label if with_label else "")
    d = s.decimals if decimals is None else decimals
    signed = "+" if qty is Quantity.PACE_DELTA else ""
    number = f"{shown:{signed}.{d}f}"
    return f"{number} {s.label}" if with_label else number


def feet_inches(cm: float) -> tuple[int, int]:
    """Body height in cm -> whole (feet, inches), rounded to the nearest inch."""
    total = round(cm / CM_PER_INCH)
    return total // 12, total % 12


def format_speed_from_pace(s_per_km: float | None, system: UnitSystem, *, empty: str = "—") -> str:
    return format_value(speed_from_pace(s_per_km), Quantity.SPEED, system, empty=empty)


@dataclass(frozen=True)
class Measurement:
    value: float  # in the requested system
    unit: str
    formatted: str


def measure(
    value: float | None, qty: Quantity, system: UnitSystem, *, scale: float = 1.0
) -> Measurement | None:
    """Build a Measurement from a stored value. ``scale`` converts a stored column that isn't
    in the canonical unit (e.g. ``TrainingPlan.distance_km`` uses scale=1000 to reach meters)."""
    if value is None:
        return None
    si = value * scale
    return Measurement(
        value=convert(si, qty, system),
        unit=unit_label(qty, system),
        formatted=format_value(si, qty, system),
    )


def describe_for_prompt(system: UnitSystem) -> str:
    """Human-readable list of the units in ``system``, for the coach's system prompt."""
    system = UnitSystem.parse(system)
    if system is UnitSystem.IMPERIAL:
        return "miles, min/mi pace, mph, feet, pounds (lb), and fluid ounces (fl oz)"
    return "kilometers, min/km pace, km/h, meters, kilograms (kg), and milliliters (ml)"
