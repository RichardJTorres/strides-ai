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
    dist_unit_label,
    elev_unit_label,
    kg_to_weight,
    m_to_distance,
    m_to_elevation,
    pace_unit_label,
    s_per_km_to_pace_seconds,
    s_per_km_to_speed,
    speed_unit_label,
    weight_unit_label,
)

# ── System prompts ─────────────────────────────────────────────────────────────

RUNNING_SYSTEM_PROMPT = """\
You are an experienced, data-driven running coach with access to the athlete's \
complete Strava training log. Your role is to:

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

The athlete's complete training log is included below. Treat it as ground \
truth for all data-related questions.

**Memory:** Use the save_memory tool proactively whenever the athlete mentions \
goals, upcoming races, injuries, preferences, or any key context that should \
persist across sessions.\
"""

CYCLING_SYSTEM_PROMPT = """\
You are an experienced, data-driven cycling coach with access to the athlete's \
complete Strava training log. Your role is to:

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

The athlete's complete training log is included below. Treat it as ground \
truth for all data-related questions.

**Memory:** Use the save_memory tool proactively whenever the athlete mentions \
goals, upcoming events, injuries, preferences, or any key context that should \
persist across sessions.\
"""

HYBRID_SYSTEM_PROMPT = """\
You are an experienced, data-driven multisport coach with access to the athlete's \
complete Strava training log covering both running and cycling. Your role is to:

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

The athlete's complete training log is included below. Treat it as ground \
truth for all data-related questions.

**Memory:** Use the save_memory tool proactively whenever the athlete mentions \
goals, upcoming events, injuries, preferences, or any key context that should \
persist across sessions.\
"""

LIFTING_SYSTEM_PROMPT = """\
You are an experienced, data-driven strength and conditioning coach with access to the athlete's \
complete HEVY training log. Your role is to:

- Analyse training volume, intensity, and progression from the data provided.
- Answer questions about specific sessions, weekly volume, and strength progress.
- Give evidence-based coaching advice: programming, progressive overload, recovery, \
injury prevention, deload timing, and exercise selection.
- Be concise but thorough. When referencing specific sessions, cite the date and \
key metrics (exercises, volume, RPE, estimated 1RM).
- When estimating 1-rep maxes, use the Epley formula (weight × (1 + reps/30)) and \
note it is an estimate.

The athlete's complete training log is included below. Treat it as ground \
truth for all data-related questions.

**Memory:** Use the save_memory tool proactively whenever the athlete mentions \
goals, upcoming competitions, injuries, preferences, or any key context that should \
persist across sessions.\
"""


# ── Training log format helpers ────────────────────────────────────────────────


def _format_pace(s_per_km: float | None, units: str = "metric") -> str:
    s = s_per_km_to_pace_seconds(s_per_km, units)
    if s is None:
        return "—"
    mins = int(s // 60)
    secs = int(s % 60)
    return f"{mins}:{secs:02d}/{dist_unit_label(units)}"


def _format_speed(s_per_km: float | None, units: str = "metric") -> str:
    v = s_per_km_to_speed(s_per_km, units)
    if v is None:
        return "—"
    return f"{v:.1f}{speed_unit_label(units)}"


def _format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "—"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m{s:02d}s"
    return f"{m}m{s:02d}s"


def _format_distance(distance_m: float | None, units: str) -> str:
    v = m_to_distance(distance_m, units)
    return f"{v:8.2f}" if v is not None else "    —   "


def _format_elevation(elevation_m: float | None, units: str) -> str:
    v = m_to_elevation(elevation_m, units)
    if v is None:
        return "—"
    return f"{v:.0f}"


def _format_volume(volume_kg: float | None, units: str) -> str:
    v = kg_to_weight(volume_kg, units)
    if v is None:
        return "—"
    return f"{v:.0f}"


# ── Per-mode log row formatters ────────────────────────────────────────────────


def _running_log_row(r: dict, units: str = "metric") -> str:
    analysis = (r.get("analysis_summary") or "")[:60]
    return (
        f"{r['date'] or '?':10s} | "
        f"{(r['name'] or '')[:30]:30s} | "
        f"{_format_distance(r['distance_m'], units):8s} | "
        f"{_format_duration(r['moving_time_s']):8s} | "
        f"{_format_pace(r['avg_pace_s_per_km'], units):8s} | "
        f"{r['avg_hr'] or '—':6} | "
        f"{r['max_hr'] or '—':6} | "
        f"{r['avg_cadence'] or '—':12} | "
        f"{_format_elevation(r['elevation_gain_m'], units):7} | "
        f"{r['suffer_score'] or '—':6} | "
        f"{r['perceived_exertion'] or '—':3} | "
        f"{analysis}"
    )


def _cycling_log_row(r: dict, units: str = "metric") -> str:
    analysis = (r.get("analysis_summary") or "")[:60]
    return (
        f"{r['date'] or '?':10s} | "
        f"{(r['name'] or '')[:30]:30s} | "
        f"{_format_distance(r['distance_m'], units):8s} | "
        f"{_format_duration(r['moving_time_s']):8s} | "
        f"{_format_speed(r['avg_pace_s_per_km'], units):8s} | "
        f"{r['avg_hr'] or '—':6} | "
        f"{r['max_hr'] or '—':6} | "
        f"{r['avg_cadence'] or '—':12} | "
        f"{_format_elevation(r['elevation_gain_m'], units):7} | "
        f"{r['suffer_score'] or '—':6} | "
        f"{r['perceived_exertion'] or '—':3} | "
        f"{analysis}"
    )


def _hybrid_log_row(r: dict, units: str = "metric") -> str:
    sport = r["sport_type"] or ""
    is_run = sport in RUN_TYPES
    pace_speed = (
        _format_pace(r["avg_pace_s_per_km"], units)
        if is_run
        else _format_speed(r["avg_pace_s_per_km"], units)
    )
    analysis = (r.get("analysis_summary") or "")[:60]
    return (
        f"{r['date'] or '?':10s} | "
        f"{sport[:10]:10s} | "
        f"{(r['name'] or '')[:30]:30s} | "
        f"{_format_distance(r['distance_m'], units):8s} | "
        f"{_format_duration(r['moving_time_s']):8s} | "
        f"{pace_speed:11s} | "
        f"{r['avg_hr'] or '—':6} | "
        f"{r['max_hr'] or '—':6} | "
        f"{r['avg_cadence'] or '—':7} | "
        f"{_format_elevation(r['elevation_gain_m'], units):7} | "
        f"{r['suffer_score'] or '—':6} | "
        f"{r['perceived_exertion'] or '—':3} | "
        f"{analysis}"
    )


def _lifting_log_row(r: dict, units: str = "metric") -> str:
    analysis = (r.get("analysis_summary") or "")[:60]
    return (
        f"{r['date'] or '?':10s} | "
        f"{(r['name'] or '')[:30]:30s} | "
        f"{_format_duration(r['moving_time_s']):8s} | "
        f"{r['total_sets'] or '—':4} | "
        f"{_format_volume(r['total_volume_kg'], units):10} | "
        f"{r['perceived_exertion'] or '—':3} | "
        f"{analysis}"
    )


def _make_cardio_total(label: str) -> Callable[[list[dict], str], str]:
    def total(rows: list[dict], units: str = "metric") -> str:
        total_dist = sum(m_to_distance(r["distance_m"] or 0, units) or 0 for r in rows)
        return f"Total: {len(rows)} {label}, {total_dist:.1f} {dist_unit_label(units)}"

    return total


def _lifting_log_total(rows: list[dict], units: str = "metric") -> str:
    total_volume = sum(kg_to_weight(r["total_volume_kg"] or 0, units) or 0 for r in rows)
    return (
        f"Total: {len(rows)} sessions, "
        f"{total_volume:.0f} {weight_unit_label(units)} cumulative volume"
    )


# ── Per-mode log header builders ──────────────────────────────────────────────


def _running_header(units: str = "metric") -> str:
    return (
        f"DATE       | NAME                           | DIST({dist_unit_label(units)})  | "
        f"DURATION | PACE     | AVG HR | MAX HR | CADENCE(spm) | "
        f"ELEV({elev_unit_label(units)}) | SUFFER | RPE | ANALYSIS"
    )


def _cycling_header(units: str = "metric") -> str:
    return (
        f"DATE       | NAME                           | DIST({dist_unit_label(units)})  | "
        f"DURATION | SPEED    | AVG HR | MAX HR | CADENCE(rpm) | "
        f"ELEV({elev_unit_label(units)}) | SUFFER | RPE | ANALYSIS"
    )


def _hybrid_header(units: str = "metric") -> str:
    return (
        f"DATE       | TYPE       | NAME                           | DIST({dist_unit_label(units)})  | "
        f"DURATION | PACE/SPEED  | AVG HR | MAX HR | CADENCE | "
        f"ELEV({elev_unit_label(units)}) | SUFFER | RPE | ANALYSIS"
    )


def _lifting_header(units: str = "metric") -> str:
    return (
        f"DATE       | NAME                           | DURATION | SETS | "
        f"VOLUME({weight_unit_label(units)}) | RPE | ANALYSIS"
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
    log_header: Callable[[str], str]  # column header row for training log; takes units
    log_sep_len: int  # length of the separator line
    format_log_row: Callable[[dict, str], str]  # row formatter; takes units
    format_log_total: Callable[[list[dict], str], str]  # totals line; takes units
    profile_section_keys: list[str]  # ordered section keys for profile_to_text


MODES: dict[str, ModeConfig] = {
    "running": ModeConfig(
        name="running",
        sport_types=RUN_TYPES,
        system_prompt=RUNNING_SYSTEM_PROMPT,
        has_analysis=True,
        hidden_tabs=frozenset(),
        activity_label="runs",
        log_header=_running_header,
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
        log_header=_cycling_header,
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
        log_header=_hybrid_header,
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
        log_header=_lifting_header,
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
