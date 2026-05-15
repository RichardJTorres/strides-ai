"""Athlete profile — stored per-mode in the database."""

import copy

from .modes import MODES

# ── Per-mode default field schemas ────────────────────────────────────────────

RUNNING_DEFAULTS: dict = {
    "personal": {
        "name": "",
        "gender": "",
        "date_of_birth": "",
        "height": "",
        "weight": "",
        "max_hr": "",
    },
    "running_background": {
        "running_since": "",
        "weekly_volume": "",
        "running_focus": "",
        "background": "",
    },
    "personal_bests": {
        "5k": "",
        "10k": "",
        "half_marathon": "",
        "marathon": "",
    },
    "goals": "",
    "injuries_and_health": "",
    "gear": "",
    "nutrition_snacks": [],
    "other_notes": "",
    "coach_voice": "",
}

CYCLING_DEFAULTS: dict = {
    "personal": {
        "name": "",
        "gender": "",
        "date_of_birth": "",
        "height": "",
        "weight": "",
        "max_hr": "",
    },
    "cycling_background": {
        "cycling_since": "",
        "weekly_distance": "",
        "cycling_focus": "",
        "background": "",
    },
    "cycling_bests": {
        "ftp": "",
        "fastest_century": "",
        "fastest_gran_fondo": "",
        "other": "",
    },
    "goals": "",
    "injuries_and_health": "",
    "gear": "",
    "nutrition_snacks": [],
    "other_notes": "",
    "coach_voice": "",
}

HYBRID_DEFAULTS: dict = {
    "personal": {
        "name": "",
        "gender": "",
        "date_of_birth": "",
        "height": "",
        "weight": "",
        "max_hr": "",
    },
    "running_background": {
        "running_since": "",
        "weekly_run_volume": "",
        "background": "",
    },
    "cycling_background": {
        "cycling_since": "",
        "weekly_ride_distance": "",
        "background": "",
    },
    "running_bests": {
        "5k": "",
        "10k": "",
        "half_marathon": "",
        "marathon": "",
    },
    "cycling_bests": {
        "ftp": "",
        "fastest_century": "",
        "fastest_gran_fondo": "",
        "other": "",
    },
    "goals": "",
    "injuries_and_health": "",
    "gear": "",
    "nutrition_snacks": [],
    "other_notes": "",
    "coach_voice": "",
}

LIFTING_DEFAULTS: dict = {
    "personal": {
        "name": "",
        "gender": "",
        "date_of_birth": "",
        "height": "",
        "weight": "",
    },
    "lifting_background": {
        "lifting_since": "",
        "sessions_per_week": "",
        "training_style": "",  # e.g. powerlifting, bodybuilding, general strength
        "background": "",
    },
    "lifting_bests": {
        "squat_1rm": "",
        "deadlift_1rm": "",
        "bench_press_1rm": "",
        "overhead_press_1rm": "",
        "other": "",
    },
    "goals": "",
    "injuries_and_health": "",
    "equipment": "",  # home gym, commercial gym, etc.
    "nutrition_snacks": [],
    "other_notes": "",
    "coach_voice": "",
    "weight_unit": "kg",
}

_DEFAULTS = {
    "running": RUNNING_DEFAULTS,
    "cycling": CYCLING_DEFAULTS,
    "hybrid": HYBRID_DEFAULTS,
    "lifting": LIFTING_DEFAULTS,
}


def get_default_fields(mode: str) -> dict:
    return copy.deepcopy(_DEFAULTS.get(mode, RUNNING_DEFAULTS))


# ── Text formatting for LLM system prompt ─────────────────────────────────────


def _v(val: object) -> str:
    return str(val).strip() if val else ""


def _section(title: str, lines: list[str]) -> str:
    body = "\n".join(line for line in lines if line)
    return f"### {title}\n{body}" if body else ""


# ── Per-section renderers ──────────────────────────────────────────────────────


def _render_personal(fields: dict) -> str:
    p = fields.get("personal", {})
    lines = [
        f"Name: {_v(p.get('name'))}" if _v(p.get("name")) else "",
        f"Gender: {_v(p.get('gender'))}" if _v(p.get("gender")) else "",
        f"Date of birth: {_v(p.get('date_of_birth'))}" if _v(p.get("date_of_birth")) else "",
        f"Height: {_v(p.get('height'))}" if _v(p.get("height")) else "",
        f"Weight: {_v(p.get('weight'))}" if _v(p.get("weight")) else "",
        f"Max heart rate: {_v(p.get('max_hr'))} bpm" if _v(p.get("max_hr")) else "",
    ]
    return _section("Personal", lines)


_RUNNING_FOCUS_LABELS = {
    "fitness": "Fitness & General Health",
    "road_racing": "Road Racing (5K – Marathon)",
    "marathon": "Marathon Training",
    "trail": "Trail Running",
    "ultra": "Ultra Running",
    "track": "Track & Speed",
    "beginner": "Beginner / Return to Running",
    "multi_sport": "Multi-Sport / Triathlon",
}


def _render_running_background(fields: dict) -> str:
    rb = fields.get("running_background", {})
    weekly = _v(rb.get("weekly_volume") or rb.get("weekly_run_volume"))
    focus_key = _v(rb.get("running_focus"))
    focus_label = _RUNNING_FOCUS_LABELS.get(focus_key, focus_key)
    lines = [
        f"Running since: {_v(rb.get('running_since'))}" if _v(rb.get("running_since")) else "",
        f"Weekly volume: {weekly}" if weekly else "",
        f"Running focus: {focus_label}" if focus_key else "",
        f"Background: {_v(rb.get('background'))}" if _v(rb.get("background")) else "",
    ]
    return _section("Running Background", lines)


def _render_personal_bests(fields: dict) -> str:
    pbs = fields.get("personal_bests", {})
    lines = [
        f"5K: {_v(pbs.get('5k'))}" if _v(pbs.get("5k")) else "",
        f"10K: {_v(pbs.get('10k'))}" if _v(pbs.get("10k")) else "",
        f"Half marathon: {_v(pbs.get('half_marathon'))}" if _v(pbs.get("half_marathon")) else "",
        f"Marathon: {_v(pbs.get('marathon'))}" if _v(pbs.get("marathon")) else "",
    ]
    return _section("Running Personal Bests", lines)


def _render_running_bests(fields: dict) -> str:
    pbs = fields.get("running_bests", {})
    lines = [
        f"5K: {_v(pbs.get('5k'))}" if _v(pbs.get("5k")) else "",
        f"10K: {_v(pbs.get('10k'))}" if _v(pbs.get("10k")) else "",
        f"Half marathon: {_v(pbs.get('half_marathon'))}" if _v(pbs.get("half_marathon")) else "",
        f"Marathon: {_v(pbs.get('marathon'))}" if _v(pbs.get("marathon")) else "",
    ]
    return _section("Running Personal Bests", lines)


_CYCLING_FOCUS_LABELS = {
    "fitness": "Fitness & General Health",
    "road_racing": "Road Racing / Criteriums",
    "gran_fondo": "Gran Fondo / Sportive",
    "time_trial": "Time Trial",
    "mountain_biking": "Mountain Biking",
    "gravel": "Gravel & Adventure",
    "triathlon": "Triathlon / Multi-Sport",
    "beginner": "Beginner / Return to Cycling",
}

_LIFTING_STYLE_LABELS = {
    "general_strength": "General Strength",
    "powerlifting": "Powerlifting",
    "bodybuilding": "Bodybuilding / Hypertrophy",
    "olympic": "Olympic Weightlifting",
    "crossfit": "CrossFit / Functional Fitness",
    "calisthenics": "Calisthenics / Bodyweight",
    "athletic": "Athletic Performance",
    "beginner": "Beginner / Getting Started",
}


def _render_cycling_background(fields: dict) -> str:
    cb = fields.get("cycling_background", {})
    weekly = _v(cb.get("weekly_distance") or cb.get("weekly_ride_distance"))
    focus_key = _v(cb.get("cycling_focus"))
    focus_label = _CYCLING_FOCUS_LABELS.get(focus_key, focus_key)
    lines = [
        f"Cycling since: {_v(cb.get('cycling_since'))}" if _v(cb.get("cycling_since")) else "",
        f"Weekly distance: {weekly}" if weekly else "",
        f"Cycling focus: {focus_label}" if focus_key else "",
        f"Background: {_v(cb.get('background'))}" if _v(cb.get("background")) else "",
    ]
    return _section("Cycling Background", lines)


def _render_cycling_bests(fields: dict) -> str:
    cyb = fields.get("cycling_bests", {})
    lines = [
        f"FTP: {_v(cyb.get('ftp'))}" if _v(cyb.get("ftp")) else "",
        (
            f"Fastest century: {_v(cyb.get('fastest_century'))}"
            if _v(cyb.get("fastest_century"))
            else ""
        ),
        (
            f"Fastest gran fondo: {_v(cyb.get('fastest_gran_fondo'))}"
            if _v(cyb.get("fastest_gran_fondo"))
            else ""
        ),
        f"Other: {_v(cyb.get('other'))}" if _v(cyb.get("other")) else "",
    ]
    return _section("Cycling Bests", lines)


def _render_lifting_background(fields: dict) -> str:
    lb = fields.get("lifting_background", {})
    style_key = _v(lb.get("training_style"))
    style_label = _LIFTING_STYLE_LABELS.get(style_key, style_key)
    lines = [
        f"Lifting since: {_v(lb.get('lifting_since'))}" if _v(lb.get("lifting_since")) else "",
        (
            f"Sessions per week: {_v(lb.get('sessions_per_week'))}"
            if _v(lb.get("sessions_per_week"))
            else ""
        ),
        f"Training style: {style_label}" if style_key else "",
        f"Background: {_v(lb.get('background'))}" if _v(lb.get("background")) else "",
    ]
    return _section("Lifting Background", lines)


def _render_lifting_bests(fields: dict) -> str:
    lbests = fields.get("lifting_bests", {})
    lines = [
        f"Squat 1RM: {_v(lbests.get('squat_1rm'))}" if _v(lbests.get("squat_1rm")) else "",
        f"Deadlift 1RM: {_v(lbests.get('deadlift_1rm'))}" if _v(lbests.get("deadlift_1rm")) else "",
        (
            f"Bench press 1RM: {_v(lbests.get('bench_press_1rm'))}"
            if _v(lbests.get("bench_press_1rm"))
            else ""
        ),
        (
            f"Overhead press 1RM: {_v(lbests.get('overhead_press_1rm'))}"
            if _v(lbests.get("overhead_press_1rm"))
            else ""
        ),
        f"Other: {_v(lbests.get('other'))}" if _v(lbests.get("other")) else "",
    ]
    return _section("Lifting Bests", lines)


def _render_simple(key: str, title: str) -> "Callable[[dict], str]":
    def render(fields: dict) -> str:
        val = _v(fields.get(key))
        return f"### {title}\n{val}" if val else ""

    return render


def _render_nutrition(fields: dict) -> str:
    snacks = fields.get("nutrition_snacks", [])
    if isinstance(snacks, list):
        items = [s.strip() for s in snacks if str(s).strip()]
    else:
        items = [s.strip() for s in str(snacks).splitlines() if s.strip()]
    if not items:
        return ""
    bullet_list = "\n".join(f"- {s}" for s in items)
    return f"### Preferred Nutrition & Snacks\n{bullet_list}"


# Callable import for type hint in _render_simple
from typing import Callable  # noqa: E402

_SECTION_RENDERERS: dict[str, Callable[[dict], str]] = {
    "personal": _render_personal,
    "running_background": _render_running_background,
    "personal_bests": _render_personal_bests,
    "running_bests": _render_running_bests,
    "cycling_background": _render_cycling_background,
    "cycling_bests": _render_cycling_bests,
    "lifting_background": _render_lifting_background,
    "lifting_bests": _render_lifting_bests,
    "goals": _render_simple("goals", "Goals"),
    "injuries_and_health": _render_simple("injuries_and_health", "Injuries & Health"),
    "gear": _render_simple("gear", "Gear"),
    "equipment": _render_simple("equipment", "Equipment"),
    "nutrition_snacks": _render_nutrition,
    "other_notes": _render_simple("other_notes", "Other Notes"),
}


def profile_to_text(fields: dict | None, mode: str) -> str:
    """Convert a profile fields dict to readable text for the system prompt.

    Only non-empty fields are emitted. Returns "" if fields is None or all blank.
    """
    if not fields:
        return ""

    cfg = MODES.get(mode, MODES["running"])
    sections: list[str] = []
    for key in cfg.profile_section_keys:
        renderer = _SECTION_RENDERERS.get(key)
        if renderer:
            rendered = renderer(fields)
            if rendered:
                sections.append(rendered)

    if not sections:
        return ""

    return "## Athlete Profile\n\n" + "\n\n".join(sections)
