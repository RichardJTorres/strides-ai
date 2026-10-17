"""Central registry of coaching mode configuration.

Each ModeConfig instance captures everything mode-specific:
  - Which sport types to filter activities by
  - The LLM system prompt
  - Training log formatting (header, row, totals)
  - Which profile sections to render
  - UI metadata (hidden tabs, activity label)

Adding a new mode means adding one ModeConfig entry to MODES.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .db.models import CYCLE_TYPES, LIFT_TYPES, RUN_TYPES
from .units import (
    DEFAULT_UNIT_SYSTEM,
    Quantity,
    UnitSystem,
    convert,
    format_speed_from_pace,
    format_value,
    unit_label,
)

# ── System prompts ─────────────────────────────────────────────────────────────

RUNNING_SYSTEM_PROMPT = """\
You are an experienced, data-driven running coach with access to the athlete's \
provided recent activity details and historical aggregates. Your role is to:

- Analyse training load, trends, and patterns from the data provided.
- Answer questions about specific workouts, weekly/monthly volume, and progress.
- Give evidence-based coaching advice: pacing, recovery, race preparation, \
injury prevention, and periodisation.
- Be concise but thorough. When referencing specific runs, cite the date and \
key metrics (distance, pace, HR).
- When advising on nutrition for a run, suggest a concrete sample loadout \
(e.g. "2 gels, 1 granola bar, 500 ml electrolytes"). If the athlete has listed \
preferred snacks in their profile, choose from those; otherwise use sensible \
defaults based on run distance and intensity.

- The provided context may include multiple types of activities (runs, walks, rides, \
strength sessions, etc.) so you can assess total training load, cross-training, \
and recovery. Your coaching focus and advice remains on running.

Only the included recent activities and labeled historical aggregates are available. \
Do not claim access to individual excluded workouts.

**Memory:** Use the save_memory tool proactively whenever the athlete mentions \
goals, upcoming races, injuries, preferences, or any key context that should \
persist across sessions.\
"""

CYCLING_SYSTEM_PROMPT = """\
You are an experienced, data-driven cycling coach with access to the athlete's \
provided recent activity details and historical aggregates. Your role is to:

- Analyse training load, trends, and patterns from cycling data provided.
- Answer questions about specific rides, weekly/monthly volume, and progress.
- Give evidence-based coaching advice: pacing, power, recovery, race preparation, \
injury prevention, and periodisation for cyclists.
- Be concise but thorough. When referencing specific rides, cite the date and \
key metrics (distance, speed, HR).
- When advising on nutrition for a ride, suggest a concrete sample loadout \
(e.g. "2 gels, 1 energy bar, 750 ml electrolytes"). If the athlete has listed \
preferred snacks in their profile, choose from those; otherwise use sensible \
defaults based on ride duration and intensity.

- The provided context may include multiple types of activities (rides, runs, walks, \
strength sessions, etc.) so you can assess total training load and recovery. \
Your coaching focus and advice remains on cycling.

Only the included recent activities and labeled historical aggregates are available. \
Do not claim access to individual excluded workouts.

**Memory:** Use the save_memory tool proactively whenever the athlete mentions \
goals, upcoming events, injuries, preferences, or any key context that should \
persist across sessions.\
"""

HYBRID_SYSTEM_PROMPT = """\
You are an experienced, data-driven multisport coach with access to the athlete's \
provided recent activity details and historical aggregates for running and cycling. Your role is to:

- Analyse training load, trends, and patterns across all sport types.
- Answer questions about specific workouts, weekly/monthly volume, and progress.
- Give evidence-based coaching advice covering both running and cycling: \
pacing, recovery, race preparation, injury prevention, and periodisation.
- Be concise but thorough. When referencing specific activities, cite the date, \
sport type, and key metrics.
- When advising on nutrition for any activity, suggest a concrete sample loadout \
(e.g. "2 gels, 1 granola bar, 500 ml electrolytes"). If the athlete has listed \
preferred snacks in their profile, choose from those; otherwise use sensible \
defaults based on activity duration and intensity.

Only the included recent activities and labeled historical aggregates are available. \
Do not claim access to individual excluded workouts.

**Memory:** Use the save_memory tool proactively whenever the athlete mentions \
goals, upcoming events, injuries, preferences, or any key context that should \
persist across sessions.\
"""

LIFTING_SYSTEM_PROMPT = """\
You are an experienced, data-driven strength and conditioning coach with access to the athlete's \
provided recent strength activity details and historical aggregates. Your role is to:

- Analyse training volume, intensity, and progression from the data provided.
- Answer questions about specific sessions, weekly volume, and strength progress.
- Give evidence-based coaching advice: programming, progressive overload, recovery, \
injury prevention, deload timing, and exercise selection.
- Be concise but thorough. When referencing specific sessions, cite the date and \
key metrics (exercises, volume, RPE, estimated 1RM).
- When estimating 1-rep maxes, use the Epley formula (weight × (1 + reps/30)) and \
note it is an estimate.

- The provided context may include multiple types of activities (strength sessions, \
runs, walks, rides, etc.) so you can assess total training load and recovery. \
Your coaching focus and advice remains on strength training.

Only the included recent activities and labeled historical aggregates are available. \
Do not claim access to individual excluded workouts.

**Memory:** Use the save_memory tool proactively whenever the athlete mentions \
goals, upcoming competitions, injuries, preferences, or any key context that should \
persist across sessions.\
"""


# ── Training log format helpers ────────────────────────────────────────────────


def _format_pace(s_per_km: float | None, units: UnitSystem = DEFAULT_UNIT_SYSTEM) -> str:
    return format_value(s_per_km, Quantity.PACE, units)


def _format_speed(s_per_km: float | None, units: UnitSystem = DEFAULT_UNIT_SYSTEM) -> str:
    return format_speed_from_pace(s_per_km, units)


def _num(value: float | None, qty: Quantity, units: UnitSystem, decimals: int) -> str:
    """Bare converted number for a fixed-width log column (unit lives in the header)."""
    shown = convert(value, qty, units)
    return "—" if shown is None else f"{shown:.{decimals}f}"


def _summary(r: dict, units: UnitSystem) -> str:
    from .analysis import render_analysis_summary

    return (render_analysis_summary(r, units) or "")[:60]


def _format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "—"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m{s:02d}s"
    return f"{m}m{s:02d}s"


# ── Per-mode log row formatters ────────────────────────────────────────────────


def _running_log_row(r: dict, units: UnitSystem = DEFAULT_UNIT_SYSTEM) -> str:
    dist = _num(r["distance_m"] or 0, Quantity.DISTANCE, units, 2)
    analysis = _summary(r, units)
    return (
        f"{r['date'] or '?':10s} | "
        f"{(r['name'] or '')[:30]:30s} | "
        f"{dist:>8} | "
        f"{_format_duration(r['moving_time_s']):8s} | "
        f"{_format_pace(r['avg_pace_s_per_km'], units):8s} | "
        f"{r['avg_hr'] or '—':6} | "
        f"{r['max_hr'] or '—':6} | "
        f"{r['avg_cadence'] or '—':12} | "
        f"{_num(r['elevation_gain_m'], Quantity.ELEVATION, units, 0):>7} | "
        f"{r['suffer_score'] or '—':6} | "
        f"{r['perceived_exertion'] or '—':3} | "
        f"{analysis}"
    )


def _cycling_log_row(r: dict, units: UnitSystem = DEFAULT_UNIT_SYSTEM) -> str:
    dist = _num(r["distance_m"] or 0, Quantity.DISTANCE, units, 2)
    analysis = _summary(r, units)
    return (
        f"{r['date'] or '?':10s} | "
        f"{(r['name'] or '')[:30]:30s} | "
        f"{dist:>8} | "
        f"{_format_duration(r['moving_time_s']):8s} | "
        f"{_format_speed(r['avg_pace_s_per_km'], units):9s} | "
        f"{r['avg_hr'] or '—':6} | "
        f"{r['max_hr'] or '—':6} | "
        f"{r['avg_cadence'] or '—':12} | "
        f"{_num(r['elevation_gain_m'], Quantity.ELEVATION, units, 0):>7} | "
        f"{r['suffer_score'] or '—':6} | "
        f"{r['perceived_exertion'] or '—':3} | "
        f"{analysis}"
    )


def _hybrid_log_row(r: dict, units: UnitSystem = DEFAULT_UNIT_SYSTEM) -> str:
    dist = _num(r["distance_m"] or 0, Quantity.DISTANCE, units, 2)
    sport = r["sport_type"] or ""
    is_run = sport in RUN_TYPES
    pace_speed = (
        _format_pace(r["avg_pace_s_per_km"], units)
        if is_run
        else _format_speed(r["avg_pace_s_per_km"], units)
    )
    analysis = _summary(r, units)
    return (
        f"{r['date'] or '?':10s} | "
        f"{sport[:10]:10s} | "
        f"{(r['name'] or '')[:30]:30s} | "
        f"{dist:>8} | "
        f"{_format_duration(r['moving_time_s']):8s} | "
        f"{pace_speed:11s} | "
        f"{r['avg_hr'] or '—':6} | "
        f"{r['max_hr'] or '—':6} | "
        f"{r['avg_cadence'] or '—':7} | "
        f"{_num(r['elevation_gain_m'], Quantity.ELEVATION, units, 0):>7} | "
        f"{r['suffer_score'] or '—':6} | "
        f"{r['perceived_exertion'] or '—':3} | "
        f"{analysis}"
    )


def _lifting_log_row(r: dict, units: UnitSystem = DEFAULT_UNIT_SYSTEM) -> str:
    analysis = _summary(r, units)
    return (
        f"{r['date'] or '?':10s} | "
        f"{(r['name'] or '')[:30]:30s} | "
        f"{_format_duration(r['moving_time_s']):8s} | "
        f"{r['total_sets'] or '—':4} | "
        f"{_num(r['total_volume_kg'], Quantity.MASS, units, 0):>10} | "
        f"{r['perceived_exertion'] or '—':3} | "
        f"{analysis}"
    )


def _make_cardio_total(label: str) -> Callable[[list[dict], UnitSystem], str]:
    def total(rows: list[dict], units: UnitSystem = DEFAULT_UNIT_SYSTEM) -> str:
        total_m = sum((r["distance_m"] or 0) for r in rows)
        return f"Total: {len(rows)} {label}, {format_value(total_m, Quantity.DISTANCE, units, decimals=1)}"

    return total


def _lifting_log_total(rows: list[dict], units: UnitSystem = DEFAULT_UNIT_SYSTEM) -> str:
    total_volume = sum((r["total_volume_kg"] or 0) for r in rows)
    return (
        f"Total: {len(rows)} sessions, "
        f"{format_value(total_volume, Quantity.MASS, units)} cumulative volume"
    )


# ── ModeConfig ─────────────────────────────────────────────────────────────────


@dataclass
class ModeConfig:
    name: str
    sport_types: frozenset[str] | None  # None = no filter (all activities, used by hybrid)
    system_prompt: str
    has_analysis: bool  # whether to inject the cardio metrics guide
    hidden_tabs: frozenset[str]  # frontend tabs to hide for this mode
    activity_label: str  # "runs", "rides", "sessions", "activities"
    log_header_template: str  # column header row; {dist}/{elev}/{mass} are unit placeholders
    log_sep_len: int  # length of the separator line
    format_log_row: Callable[[dict, UnitSystem], str]
    format_log_total: Callable[[list[dict], UnitSystem], str]
    profile_section_keys: list[str]  # ordered section keys for profile_to_text

    def log_header(self, units: UnitSystem = DEFAULT_UNIT_SYSTEM) -> str:
        return self.log_header_template.format(
            dist=f"DIST({unit_label(Quantity.DISTANCE, units)})",
            elev=f"ELEV({unit_label(Quantity.ELEVATION, units)})",
            mass=f"VOLUME({unit_label(Quantity.MASS, units)})",
        )


MODES: dict[str, ModeConfig] = {
    "running": ModeConfig(
        name="running",
        sport_types=RUN_TYPES,
        system_prompt=RUNNING_SYSTEM_PROMPT,
        has_analysis=True,
        hidden_tabs=frozenset(),
        activity_label="runs",
        log_header_template=(
            "DATE       | NAME                           | {dist:8} | DURATION | PACE     "
            "| AVG HR | MAX HR | CADENCE(spm) | {elev:7} | SUFFER | RPE | ANALYSIS"
        ),
        log_sep_len=200,
        format_log_row=_running_log_row,
        format_log_total=_make_cardio_total("runs"),
        profile_section_keys=[
            "personal",
            "running_background",
            "personal_bests",
            "goals",
            "injuries_and_health",
            "gear",
            "nutrition_snacks",
            "other_notes",
        ],
    ),
    "cycling": ModeConfig(
        name="cycling",
        sport_types=CYCLE_TYPES,
        system_prompt=CYCLING_SYSTEM_PROMPT,
        has_analysis=True,
        hidden_tabs=frozenset(),
        activity_label="rides",
        log_header_template=(
            "DATE       | NAME                           | {dist:8} | DURATION | SPEED     "
            "| AVG HR | MAX HR | CADENCE(rpm) | {elev:7} | SUFFER | RPE | ANALYSIS"
        ),
        log_sep_len=200,
        format_log_row=_cycling_log_row,
        format_log_total=_make_cardio_total("rides"),
        profile_section_keys=[
            "personal",
            "cycling_background",
            "cycling_bests",
            "goals",
            "injuries_and_health",
            "gear",
            "nutrition_snacks",
            "other_notes",
        ],
    ),
    "hybrid": ModeConfig(
        name="hybrid",
        sport_types=None,
        system_prompt=HYBRID_SYSTEM_PROMPT,
        has_analysis=True,
        hidden_tabs=frozenset(),
        activity_label="activities",
        log_header_template=(
            "DATE       | TYPE       | NAME                           | {dist:8} | DURATION "
            "| PACE/SPEED  | AVG HR | MAX HR | CADENCE | {elev:7} | SUFFER | RPE | ANALYSIS"
        ),
        log_sep_len=215,
        format_log_row=_hybrid_log_row,
        format_log_total=_make_cardio_total("activities"),
        profile_section_keys=[
            "personal",
            "running_background",
            "running_bests",
            "cycling_background",
            "cycling_bests",
            "goals",
            "injuries_and_health",
            "gear",
            "nutrition_snacks",
            "other_notes",
        ],
    ),
    "lifting": ModeConfig(
        name="lifting",
        sport_types=LIFT_TYPES,
        system_prompt=LIFTING_SYSTEM_PROMPT,
        has_analysis=False,
        hidden_tabs=frozenset({"calendar"}),
        activity_label="sessions",
        log_header_template=(
            "DATE       | NAME                           | DURATION | SETS | {mass:10} | RPE | ANALYSIS"
        ),
        log_sep_len=140,
        format_log_row=_lifting_log_row,
        format_log_total=_lifting_log_total,
        profile_section_keys=[
            "personal",
            "lifting_background",
            "lifting_bests",
            "goals",
            "injuries_and_health",
            "equipment",
            "nutrition_snacks",
            "other_notes",
        ],
    ),
}
