"""Athlete profile — one unified document shared by every coaching mode.

Storage (``profiles`` table, one JSON row per section):
  shared   personal, goals, availability, injuries_and_health, nutrition_snacks,
           other_notes, coach_voice
  running / cycling / lifting
           since, volume, focus, background, bests{...}, gear

A mode only decides which discipline sections the coach sees in full
(``DISCIPLINES_BY_MODE``); the others are summarised under "Also trains".
"""

import copy
from dataclasses import dataclass

from .body_metrics import normalize_personal
from .units import DEFAULT_UNIT_SYSTEM, Quantity, UnitSystem, format_value

SECTIONS = ("shared", "running", "cycling", "lifting")
DISCIPLINE_KEYS = ("running", "cycling", "lifting")

# Disciplines the coach sees in full for each mode, in display order.
DISCIPLINES_BY_MODE: dict[str, tuple[str, ...]] = {
    "running": ("running",),
    "cycling": ("cycling",),
    "hybrid": ("running", "cycling"),
    "lifting": ("lifting",),
}

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_WEEKDAY_LABELS = {
    "mon": "Mon",
    "tue": "Tue",
    "wed": "Wed",
    "thu": "Thu",
    "fri": "Fri",
    "sat": "Sat",
    "sun": "Sun",
}


@dataclass(frozen=True)
class DisciplineSpec:
    title: str
    since_label: str
    volume_label: str
    focus_label: str
    focus_options: dict[str, str]
    bests: tuple[tuple[str, str], ...]  # (key, label)
    gear_label: str


DISCIPLINES: dict[str, DisciplineSpec] = {
    "running": DisciplineSpec(
        title="Running",
        since_label="Running since",
        volume_label="Weekly volume",
        focus_label="Running focus",
        focus_options={
            "fitness": "Fitness & General Health",
            "road_racing": "Road Racing (5K – Marathon)",
            "marathon": "Marathon Training",
            "trail": "Trail Running",
            "ultra": "Ultra Running",
            "track": "Track & Speed",
            "beginner": "Beginner / Return to Running",
            "multi_sport": "Multi-Sport / Triathlon",
        },
        bests=(
            ("5k", "5K"),
            ("10k", "10K"),
            ("half_marathon", "Half marathon"),
            ("marathon", "Marathon"),
        ),
        gear_label="Gear",
    ),
    "cycling": DisciplineSpec(
        title="Cycling",
        since_label="Cycling since",
        volume_label="Weekly distance",
        focus_label="Cycling focus",
        focus_options={
            "fitness": "Fitness & General Health",
            "road_racing": "Road Racing / Criteriums",
            "gran_fondo": "Gran Fondo / Sportive",
            "time_trial": "Time Trial",
            "mountain_biking": "Mountain Biking",
            "gravel": "Gravel & Adventure",
            "triathlon": "Triathlon / Multi-Sport",
            "beginner": "Beginner / Return to Cycling",
        },
        bests=(
            ("ftp", "FTP"),
            ("fastest_century", "Fastest century"),
            ("fastest_gran_fondo", "Fastest gran fondo"),
            ("other", "Other"),
        ),
        gear_label="Gear",
    ),
    "lifting": DisciplineSpec(
        title="Lifting",
        since_label="Lifting since",
        volume_label="Sessions per week",
        focus_label="Training style",
        focus_options={
            "general_strength": "General Strength",
            "powerlifting": "Powerlifting",
            "bodybuilding": "Bodybuilding / Hypertrophy",
            "olympic": "Olympic Weightlifting",
            "crossfit": "CrossFit / Functional Fitness",
            "calisthenics": "Calisthenics / Bodyweight",
            "athletic": "Athletic Performance",
            "beginner": "Beginner / Getting Started",
        },
        bests=(
            ("squat_1rm", "Squat 1RM"),
            ("deadlift_1rm", "Deadlift 1RM"),
            ("bench_press_1rm", "Bench press 1RM"),
            ("overhead_press_1rm", "Overhead press 1RM"),
            ("other", "Other"),
        ),
        gear_label="Equipment",
    ),
}

# ── Defaults ──────────────────────────────────────────────────────────────────

SHARED_DEFAULTS: dict = {
    "personal": {
        "name": "",
        "gender": "",
        "date_of_birth": "",
        "height_cm": None,
        "weight_kg": None,
        "max_hr": None,
    },
    "goals": "",
    "availability": {
        "sessions_per_week": None,
        "preferred_days": [],
        "long_session_day": "",
        "notes": "",
    },
    "injuries_and_health": "",
    "nutrition_snacks": [],
    "other_notes": "",
    "coach_voice": "",
}


def _discipline_defaults(name: str) -> dict:
    return {
        "since": "",
        "volume": "",
        "focus": "",
        "background": "",
        "bests": {key: "" for key, _ in DISCIPLINES[name].bests},
        "gear": "",
    }


def get_default_section(section: str) -> dict:
    if section == "shared":
        return copy.deepcopy(SHARED_DEFAULTS)
    if section in DISCIPLINES:
        return _discipline_defaults(section)
    raise KeyError(section)


def get_default_fields() -> dict:
    """The full unified profile document with every field blank."""
    doc = get_default_section("shared")
    for name in DISCIPLINE_KEYS:
        doc[name] = _discipline_defaults(name)
    return doc


def with_defaults(fields: dict | None) -> dict:
    """Overlay stored ``fields`` onto the blank document (nested dicts merge one level deep)."""
    doc = get_default_fields()
    for key, val in (fields or {}).items():
        base = doc.get(key)
        if isinstance(val, dict) and isinstance(base, dict):
            for sub, subval in val.items():
                if isinstance(subval, dict) and isinstance(base.get(sub), dict):
                    base[sub] = {**base[sub], **subval}
                else:
                    base[sub] = subval
        else:
            doc[key] = val
    return doc


def disciplines_for_mode(mode: str) -> tuple[str, ...]:
    return DISCIPLINES_BY_MODE.get(mode, DISCIPLINES_BY_MODE["running"])


# ── Text formatting for LLM system prompt ─────────────────────────────────────


def _v(val: object) -> str:
    return str(val).strip() if val not in (None, "", [], {}) else ""


def _section(title: str, lines: list[str]) -> str:
    body = "\n".join(line for line in lines if line)
    return f"### {title}\n{body}" if body else ""


def _render_personal(fields: dict, units: UnitSystem) -> str:
    p = normalize_personal(fields.get("personal") or {})
    height, weight = p.get("height_cm"), p.get("weight_kg")
    lines = [
        f"Name: {_v(p.get('name'))}" if _v(p.get("name")) else "",
        f"Gender: {_v(p.get('gender'))}" if _v(p.get("gender")) else "",
        f"Date of birth: {_v(p.get('date_of_birth'))}" if _v(p.get("date_of_birth")) else "",
        f"Height: {format_value(height, Quantity.HEIGHT, units)}" if height else "",
        f"Weight: {format_value(weight, Quantity.MASS, units, decimals=1)}" if weight else "",
        f"Body notes: {_v(p.get('body_notes'))}" if _v(p.get("body_notes")) else "",
        f"Max heart rate: {_v(p.get('max_hr'))} bpm" if _v(p.get("max_hr")) else "",
    ]
    return _section("Personal", lines)


def _render_goals(fields: dict) -> str:
    val = _v(fields.get("goals"))
    return f"### Long-term Goals\n{val}" if val else ""


def _render_availability(fields: dict) -> str:
    a = fields.get("availability") or {}
    days = [d for d in WEEKDAYS if d in (a.get("preferred_days") or [])]
    long_day = _v(a.get("long_session_day"))
    lines = [
        (
            f"Sessions per week: {_v(a.get('sessions_per_week'))}"
            if _v(a.get("sessions_per_week"))
            else ""
        ),
        f"Preferred training days: {', '.join(_WEEKDAY_LABELS[d] for d in days)}" if days else "",
        f"Long session day: {_WEEKDAY_LABELS.get(long_day, long_day)}" if long_day else "",
        f"Notes: {_v(a.get('notes'))}" if _v(a.get("notes")) else "",
    ]
    return _section("Weekly Availability", lines)


def _bests_lines(spec: DisciplineSpec, bests: dict) -> list[str]:
    return [f"{label}: {_v(bests.get(key))}" for key, label in spec.bests if _v(bests.get(key))]


def _focus_label(spec: DisciplineSpec, key: str) -> str:
    return spec.focus_options.get(key, key)


def _render_discipline(name: str, fields: dict) -> list[str]:
    spec, d = DISCIPLINES[name], fields.get(name) or {}
    focus = _v(d.get("focus"))
    background = _section(
        f"{spec.title} Background",
        [
            f"{spec.since_label}: {_v(d.get('since'))}" if _v(d.get("since")) else "",
            f"{spec.volume_label}: {_v(d.get('volume'))}" if _v(d.get("volume")) else "",
            f"{spec.focus_label}: {_focus_label(spec, focus)}" if focus else "",
            f"Background: {_v(d.get('background'))}" if _v(d.get("background")) else "",
        ],
    )
    bests = _section(f"{spec.title} Bests", _bests_lines(spec, d.get("bests") or {}))
    return [s for s in (background, bests) if s]


def _render_gear(active: tuple[str, ...], fields: dict) -> list[str]:
    out = []
    for name in active:
        spec, val = DISCIPLINES[name], _v((fields.get(name) or {}).get("gear"))
        if not val:
            continue
        title = spec.gear_label if len(active) == 1 else f"{spec.title} {spec.gear_label.lower()}"
        out.append(f"### {title}\n{val}")
    return out


def _render_nutrition(fields: dict) -> str:
    snacks = fields.get("nutrition_snacks") or []
    if isinstance(snacks, str):
        snacks = snacks.splitlines()
    items = [str(s).strip() for s in snacks if str(s).strip()]
    if not items:
        return ""
    return "### Preferred Nutrition & Snacks\n" + "\n".join(f"- {s}" for s in items)


def _render_simple(fields: dict, key: str, title: str) -> str:
    val = _v(fields.get(key))
    return f"### {title}\n{val}" if val else ""


def _render_also_trains(active: tuple[str, ...], fields: dict) -> str:
    """One line per discipline the coach isn't focused on but the athlete also trains."""
    lines = []
    for name in DISCIPLINE_KEYS:
        if name in active:
            continue
        spec, d = DISCIPLINES[name], fields.get(name) or {}
        focus = _v(d.get("focus"))
        parts = [
            f"since {_v(d.get('since'))}" if _v(d.get("since")) else "",
            f"{spec.volume_label.lower()}: {_v(d.get('volume'))}" if _v(d.get("volume")) else "",
            _focus_label(spec, focus) if focus else "",
            *_bests_lines(spec, d.get("bests") or {}),
        ]
        parts = [p for p in parts if p]
        if parts:
            lines.append(f"- {spec.title}: " + "; ".join(parts))
    if not lines:
        return ""
    return "### Also Trains (outside this coaching mode)\n" + "\n".join(lines)


def profile_to_text(fields: dict | None, mode: str, units: UnitSystem = DEFAULT_UNIT_SYSTEM) -> str:
    """Render the unified profile for the system prompt, scoped to ``mode``.

    Only non-empty fields are emitted; order is fixed. Returns "" if fields is None or blank.
    """
    if not fields:
        return ""
    active = disciplines_for_mode(mode)
    sections: list[str] = [
        _render_personal(fields, units),
        _render_goals(fields),
        _render_availability(fields),
    ]
    for name in active:
        sections.extend(_render_discipline(name, fields))
    sections.append(_render_simple(fields, "injuries_and_health", "Injuries & Health"))
    sections.extend(_render_gear(active, fields))
    sections.append(_render_nutrition(fields))
    sections.append(_render_simple(fields, "other_notes", "Other Notes"))
    sections.append(_render_also_trains(active, fields))

    sections = [s for s in sections if s]
    if not sections:
        return ""
    return "## Athlete Profile\n\n" + "\n\n".join(sections)


# ── Completeness ──────────────────────────────────────────────────────────────

# (label, weight, getter). Fixed order => deterministic output.


def _shared_checks() -> list[tuple[str, str, int, "callable"]]:
    return [
        (
            "personal.date_of_birth",
            "Date of birth",
            1,
            lambda f: _v(f["personal"].get("date_of_birth")),
        ),
        ("personal.height_cm", "Height", 1, lambda f: _v(f["personal"].get("height_cm"))),
        ("personal.weight_kg", "Weight", 1, lambda f: _v(f["personal"].get("weight_kg"))),
        ("personal.max_hr", "Max heart rate", 2, lambda f: _v(f["personal"].get("max_hr"))),
        ("goals", "Long-term goals", 3, lambda f: _v(f.get("goals"))),
        (
            "availability.sessions_per_week",
            "Sessions per week",
            2,
            lambda f: _v(f["availability"].get("sessions_per_week")),
        ),
        (
            "availability.preferred_days",
            "Preferred training days",
            1,
            lambda f: _v(f["availability"].get("preferred_days")),
        ),
        ("injuries_and_health", "Injuries & health", 2, lambda f: _v(f.get("injuries_and_health"))),
    ]


def _discipline_checks(name: str) -> list[tuple[str, str, int, "callable"]]:
    spec = DISCIPLINES[name]
    return [
        (f"{name}.since", spec.since_label, 1, lambda f, n=name: _v(f[n].get("since"))),
        (f"{name}.volume", spec.volume_label, 2, lambda f, n=name: _v(f[n].get("volume"))),
        (f"{name}.focus", spec.focus_label, 1, lambda f, n=name: _v(f[n].get("focus"))),
        (
            f"{name}.background",
            f"{spec.title} background",
            1,
            lambda f, n=name: _v(f[n].get("background")),
        ),
        (
            f"{name}.bests",
            f"{spec.title} bests",
            2,
            lambda f, n=name: any(_v(x) for x in f[n].get("bests", {}).values()),
        ),
        (f"{name}.gear", spec.gear_label, 1, lambda f, n=name: _v(f[n].get("gear"))),
    ]


def profile_completeness(fields: dict | None, mode: str) -> dict:
    """Weighted completeness of the fields that matter for ``mode``.

    Returns ``{"percent": int, "missing": [{"path", "label", "weight"}]}`` with missing items
    ordered by weight (high first) then by declaration order.
    """
    doc = with_defaults(fields)
    checks = _shared_checks()
    for name in disciplines_for_mode(mode):
        checks.extend(_discipline_checks(name))
    total = sum(w for _, _, w, _ in checks)
    done = 0
    missing = []
    for path, label, weight, getter in checks:
        if getter(doc):
            done += weight
        else:
            missing.append({"path": path, "label": label, "weight": weight})
    missing.sort(key=lambda m: -m["weight"])  # stable: keeps declaration order within a weight
    return {"percent": round(100 * done / total) if total else 100, "missing": missing}


# ── Coach-proposed edits (update_profile tool) ────────────────────────────────

_SHARED_TEXT = {
    "goals": "Long-term goals",
    "injuries_and_health": "Injuries & health",
    "other_notes": "Other notes",
    "availability.notes": "Availability notes",
}
_SHARED_OTHER = {
    "availability.sessions_per_week": "Sessions per week",
    "availability.preferred_days": "Preferred training days",
    "availability.long_session_day": "Long session day",
    "personal.max_hr": "Max heart rate",
    "nutrition_snacks": "Preferred nutrition & snacks",
}


def profile_update_fields() -> dict[str, str]:
    """Every path the coach may propose a change to, mapped to a human label."""
    fields = {**_SHARED_TEXT, **_SHARED_OTHER}
    for name, spec in DISCIPLINES.items():
        fields[f"{name}.since"] = spec.since_label
        fields[f"{name}.volume"] = spec.volume_label
        fields[f"{name}.focus"] = spec.focus_label
        fields[f"{name}.background"] = f"{spec.title} background"
        fields[f"{name}.gear"] = f"{spec.title} {spec.gear_label.lower()}"
        for key, label in spec.bests:
            fields[f"{name}.bests.{key}"] = f"{spec.title} best: {label}"
    return fields


def _get_path(doc: dict, path: list[str]) -> object:
    cur: object = doc
    for part in path:
        cur = cur.get(part) if isinstance(cur, dict) else None
    return cur


def build_profile_proposal(args: dict, current: dict | None) -> dict:
    """Validate an ``update_profile`` tool call and turn it into an un-applied proposal.

    Returns ``{"section", "label", "op", "current", "proposed", "fields"}`` where ``fields`` is
    the exact body to PUT to ``/api/profile/{section}`` to apply it. Raises ``ValueError`` with a
    message the model can act on if the call is not allowed.
    """
    path = _v(args.get("field"))
    allowed = profile_update_fields()
    if path not in allowed:
        raise ValueError(f"Unknown profile field '{path}'. Allowed: {', '.join(sorted(allowed))}")
    op = _v(args.get("op")) or "set"
    if op not in ("set", "append"):
        raise ValueError("op must be 'set' or 'append'")
    raw = args.get("value")
    value = raw.strip() if isinstance(raw, str) else raw
    if value in (None, ""):
        raise ValueError("value is required")

    parts = path.split(".")
    section = parts[0] if parts[0] in DISCIPLINES else "shared"
    inner = parts[1:] if section != "shared" else parts
    doc = with_defaults(current)
    existing = _get_path(doc[section] if section != "shared" else doc, inner)

    if path == "nutrition_snacks":
        items = [s.strip() for s in str(value).replace(";", "\n").splitlines() if s.strip()]
        base = list(existing or [])
        new = (base + [i for i in items if i not in base]) if op == "append" else items
    elif path == "availability.preferred_days":
        days = [d.strip().lower()[:3] for d in str(value).replace(";", ",").split(",") if d.strip()]
        if not days or any(d not in WEEKDAYS for d in days):
            raise ValueError("preferred_days must be weekdays like 'mon, wed, sat'")
        new = [d for d in WEEKDAYS if d in days]
    elif path == "availability.long_session_day":
        day = str(value).strip().lower()[:3]
        if day not in WEEKDAYS:
            raise ValueError("long_session_day must be a weekday")
        new = day
    elif path in ("availability.sessions_per_week", "personal.max_hr"):
        try:
            new = int(str(value).strip().split()[0])
        except (ValueError, IndexError):
            raise ValueError(f"{path} must be a whole number")
        low, high = (0, 21) if path.startswith("availability") else (60, 250)
        if not low <= new <= high:
            raise ValueError(f"{path} must be between {low} and {high}")
    elif parts[-1] == "focus":
        options = DISCIPLINES[section].focus_options
        text = str(value).strip().lower()
        by_label = {label.lower(): k for k, label in options.items()}
        key = (
            text.replace(" ", "_") if text.replace(" ", "_") in options else by_label.get(text, "")
        )
        if key not in options:
            raise ValueError(f"focus must be one of: {', '.join(options)}")
        new = key
    else:
        text = str(value)
        base = _v(existing)
        new = f"{base}\n{text}" if op == "append" and base else text

    # Build the PUT body: {"bests": {"5k": ...}} / {"availability": {...}} / {"goals": ...}.
    fields: dict = {}
    cursor = fields
    for part in inner[:-1]:
        cursor[part] = {}
        cursor = cursor[part]
    cursor[inner[-1]] = new
    if parts[0] in ("availability", "personal"):
        # Nested objects merge server-side, so send only the changed key; sending the whole object
        # would overwrite edits made after this proposal's snapshot (e.g. a second proposal).
        fields = {parts[0]: {inner[-1]: new}}
    return {
        "section": section,
        "label": allowed[path],
        "op": op,
        "current": existing if existing not in (None, "", []) else None,
        "proposed": new,
        "fields": fields,
    }
