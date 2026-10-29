"""Structured (ERG-style) cycling workouts: validation, rendering and Zwift .zwo export.

Pure functions, no DB access. A structure is ``{"blocks": [...]}`` with intensities as fractions
of FTP (0.75 = 75%), the same convention as Zwift's .zwo files, so no FTP value is needed here:

    {"kind": "warmup" | "cooldown" | "ramp", "duration_s", "from_pct", "to_pct"}
    {"kind": "steady", "duration_s", "pct"}
    {"kind": "intervals", "repeat", "on_s", "on_pct", "off_s", "off_pct"}
    {"kind": "freeride", "duration_s"}

``normalize_structure`` is the only way a structure should enter storage: LLM output is
untrusted, so bad blocks are dropped (never raised on) and values are clamped.
"""

import json
import re
import xml.etree.ElementTree as ET

from .compliance import RIDE_WORKOUT_TYPES

MIN_PCT, MAX_PCT = 0.30, 2.00
MIN_SECONDS, MAX_SECONDS = 10, 4 * 3600
MAX_REPEAT = 50
MAX_BLOCKS = 40
MAX_TOTAL_SECONDS = 6 * 3600

_RAMP_KINDS = ("warmup", "cooldown", "ramp")

# Prompt-facing description of the contract, shared by plan generation and the coach prompt.
STRUCTURE_PROMPT = (
    '"structure" (object, optional, cycling workouts only) — intensities are fractions of FTP '
    "(0.75 = 75%). Shape: "
    '{"blocks": [{"kind": "warmup"|"cooldown"|"ramp", "duration_s": int, "from_pct": number, '
    '"to_pct": number}, {"kind": "steady", "duration_s": int, "pct": number}, '
    '{"kind": "intervals", "repeat": int, "on_s": int, "on_pct": number, "off_s": int, '
    '"off_pct": number}, {"kind": "freeride", "duration_s": int}]}. '
    "Open with a warmup and close with a cooldown. When present, duration_min is derived from it."
)


# JSON Schema for the tool-calling backends (Claude / OpenAI / Ollama; Gemini mirrors it).
WORKOUT_STRUCTURE_SCHEMA = {
    "type": "object",
    "description": (
        "Optional structured workout for cycling types (intensities are fractions of FTP, "
        "0.75 = 75%). Overwriting a day without `structure` removes any existing one."
    ),
    "properties": {
        "blocks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["warmup", "cooldown", "ramp", "steady", "intervals", "freeride"],
                    },
                    "duration_s": {
                        "type": "integer",
                        "description": "warmup/cooldown/ramp/steady/freeride",
                    },
                    "from_pct": {"type": "number", "description": "warmup/cooldown/ramp start"},
                    "to_pct": {"type": "number", "description": "warmup/cooldown/ramp end"},
                    "pct": {"type": "number", "description": "steady"},
                    "repeat": {"type": "integer", "description": "intervals"},
                    "on_s": {"type": "integer"},
                    "on_pct": {"type": "number"},
                    "off_s": {"type": "integer"},
                    "off_pct": {"type": "number"},
                },
                "required": ["kind"],
            },
        }
    },
    "required": ["blocks"],
}

# Ride terrain bands (m of gain per km), mirroring CLIMB_TIERS.ride in web/src/pages/activityLabels.ts.
INDOOR_RIDE_GUIDANCE = (
    "Indoor Rides (e.g. Zwift) have simulated climbing: always give an Indoor Ride both `distance` "
    "and `elevation`, chosen to hit a deliberate climb ratio so the athlete can pick a matching "
    "route. Ride climb ratio bands: flat under 5 m/km (26 ft/mi), rolling 5-12 m/km (26-63 ft/mi), "
    "hilly 12-25 m/km (63-132 ft/mi), mountainous 25+ m/km (132+ ft/mi). Name the target ratio in "
    "the description. Prefer a `structure` for Indoor Rides with intervals or targeted efforts."
)


def _num(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        n = float(value)
    except ValueError:
        return None
    return n if n == n and abs(n) != float("inf") else None


def _pct(value) -> float | None:
    n = _num(value)
    return None if n is None else round(min(MAX_PCT, max(MIN_PCT, n)), 2)


def _secs(value) -> int | None:
    n = _num(value)
    return None if n is None else int(min(MAX_SECONDS, max(MIN_SECONDS, round(n))))


def _normalize_block(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    kind = raw.get("kind")
    if kind in _RAMP_KINDS:
        duration, lo, hi = (
            _secs(raw.get("duration_s")),
            _pct(raw.get("from_pct")),
            _pct(raw.get("to_pct")),
        )
        if None in (duration, lo, hi):
            return None
        return {"kind": kind, "duration_s": duration, "from_pct": lo, "to_pct": hi}
    if kind == "steady":
        duration, pct = _secs(raw.get("duration_s")), _pct(raw.get("pct"))
        if None in (duration, pct):
            return None
        return {"kind": "steady", "duration_s": duration, "pct": pct}
    if kind == "intervals":
        repeat = _num(raw.get("repeat"))
        on_s, on_pct = _secs(raw.get("on_s")), _pct(raw.get("on_pct"))
        off_s, off_pct = _secs(raw.get("off_s")), _pct(raw.get("off_pct"))
        if repeat is None or None in (on_s, on_pct, off_s, off_pct):
            return None
        return {
            "kind": "intervals",
            "repeat": int(min(MAX_REPEAT, max(1, round(repeat)))),
            "on_s": on_s,
            "on_pct": on_pct,
            "off_s": off_s,
            "off_pct": off_pct,
        }
    if kind == "freeride":
        duration = _secs(raw.get("duration_s"))
        return None if duration is None else {"kind": "freeride", "duration_s": duration}
    return None


def _block_seconds(block: dict) -> int:
    if block["kind"] == "intervals":
        return block["repeat"] * (block["on_s"] + block["off_s"])
    return block["duration_s"]


def total_seconds(structure: dict | None) -> int:
    return sum(_block_seconds(b) for b in (structure or {}).get("blocks", []))


def normalize_structure(raw) -> dict | None:
    """Validate untrusted structure (dict, JSON string or None). Returns None if nothing valid."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    blocks_in = raw.get("blocks") if isinstance(raw, dict) else None
    if not isinstance(blocks_in, list):
        return None
    blocks: list[dict] = []
    total = 0
    for item in blocks_in:
        block = _normalize_block(item)
        if block is None:
            continue
        seconds = _block_seconds(block)
        if len(blocks) >= MAX_BLOCKS or total + seconds > MAX_TOTAL_SECONDS:
            break
        blocks.append(block)
        total += seconds
    return {"blocks": blocks} if blocks else None


def structure_for_type(workout_type: str | None, raw) -> dict | None:
    """Normalized structure, or None when the workout type can't carry one (non-cycling)."""
    if workout_type not in RIDE_WORKOUT_TYPES:
        return None
    return normalize_structure(raw)


def structure_from_json(text: str | None) -> dict | None:
    return normalize_structure(text) if text else None


def structure_to_json(structure: dict | None) -> str | None:
    """Storage form: None for no structure, never "null" / "[]" / "{}"."""
    return json.dumps(structure, separators=(",", ":")) if structure else None


def _clock(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


def _percent(fraction: float) -> str:
    return f"{round(fraction * 100)}%"


def render_text(structure: dict | None) -> str:
    parts = []
    for b in (structure or {}).get("blocks", []):
        kind = b["kind"]
        if kind in _RAMP_KINDS:
            parts.append(
                f"{_clock(b['duration_s'])} {kind} {round(b['from_pct'] * 100)}→{_percent(b['to_pct'])}"
            )
        elif kind == "steady":
            parts.append(f"{_clock(b['duration_s'])} @ {_percent(b['pct'])}")
        elif kind == "intervals":
            parts.append(
                f"{b['repeat']}×({_clock(b['on_s'])} @ {_percent(b['on_pct'])}, "
                f"{_clock(b['off_s'])} @ {_percent(b['off_pct'])})"
            )
        else:
            parts.append(f"{_clock(b['duration_s'])} free ride")
    return " · ".join(parts)


def to_zwo(structure: dict, name: str, description: str | None = None) -> str:
    """Zwift workout file (.zwo) for a normalized structure."""
    root = ET.Element("workout_file")
    ET.SubElement(root, "author").text = "Strides AI"
    ET.SubElement(root, "name").text = name
    ET.SubElement(root, "description").text = description or ""
    ET.SubElement(root, "sportType").text = "bike"
    ET.SubElement(root, "tags")
    workout = ET.SubElement(root, "workout")
    for b in structure["blocks"]:
        kind = b["kind"]
        if kind in _RAMP_KINDS:
            tag = {"warmup": "Warmup", "cooldown": "Cooldown", "ramp": "Ramp"}[kind]
            ET.SubElement(
                workout,
                tag,
                Duration=str(b["duration_s"]),
                PowerLow=str(b["from_pct"]),
                PowerHigh=str(b["to_pct"]),
            )
        elif kind == "steady":
            ET.SubElement(
                workout, "SteadyState", Duration=str(b["duration_s"]), Power=str(b["pct"])
            )
        elif kind == "intervals":
            ET.SubElement(
                workout,
                "IntervalsT",
                Repeat=str(b["repeat"]),
                OnDuration=str(b["on_s"]),
                OffDuration=str(b["off_s"]),
                OnPower=str(b["on_pct"]),
                OffPower=str(b["off_pct"]),
            )
        else:
            ET.SubElement(workout, "FreeRide", Duration=str(b["duration_s"]), FlatRoad="1")
    ET.indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")


def zwo_filename(date: str, name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower() or "workout"
    return f"{date}-{slug}.zwo"
