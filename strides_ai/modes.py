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
- Use metric units (km, min/km) unless the athlete asks otherwise.
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
- Use metric units (km, km/h) unless the athlete asks otherwise.
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
- Use metric units unless the athlete asks otherwise.
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
- Use metric units (kg) unless the athlete asks otherwise.
- When estimating 1-rep maxes, use the Epley formula (weight × (1 + reps/30)) and \
note it is an estimate.

The athlete's complete training log is included below. Treat it as ground \
truth for all data-related questions.

**Memory:** Use the save_memory tool proactively whenever the athlete mentions \
goals, upcoming competitions, injuries, preferences, or any key context that should \
persist across sessions.\
"""


# ── Training log format helpers ────────────────────────────────────────────────


def _format_pace(s_per_km: float | None) -> str:
    if s_per_km is None:
        return "—"
    mins = int(s_per_km // 60)
    secs = int(s_per_km % 60)
    return f"{mins}:{secs:02d}/km"


def _format_speed(s_per_km: float | None) -> str:
    if s_per_km is None or s_per_km <= 0:
        return "—"
    kph = 3600 / s_per_km
    return f"{kph:.1f}km/h"


def _format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "—"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m{s:02d}s"
    return f"{m}m{s:02d}s"


# ── Per-mode log row formatters ────────────────────────────────────────────────


def _running_log_row(r: dict) -> str:
    dist_km = (r["distance_m"] or 0) / 1000
    analysis = (r.get("analysis_summary") or "")[:60]
    return (
        f"{r['date'] or '?':10s} | "
        f"{(r['name'] or '')[:30]:30s} | "
        f"{dist_km:8.2f} | "
        f"{_format_duration(r['moving_time_s']):8s} | "
        f"{_format_pace(r['avg_pace_s_per_km']):8s} | "
        f"{r['avg_hr'] or '—':6} | "
        f"{r['max_hr'] or '—':6} | "
        f"{r['avg_cadence'] or '—':12} | "
        f"{r['elevation_gain_m'] or '—':7} | "
        f"{r['suffer_score'] or '—':6} | "
        f"{r['perceived_exertion'] or '—':3} | "
        f"{analysis}"
    )


def _cycling_log_row(r: dict) -> str:
    dist_km = (r["distance_m"] or 0) / 1000
    analysis = (r.get("analysis_summary") or "")[:60]
    return (
        f"{r['date'] or '?':10s} | "
        f"{(r['name'] or '')[:30]:30s} | "
        f"{dist_km:8.2f} | "
        f"{_format_duration(r['moving_time_s']):8s} | "
        f"{_format_speed(r['avg_pace_s_per_km']):8s} | "
        f"{r['avg_hr'] or '—':6} | "
        f"{r['max_hr'] or '—':6} | "
        f"{r['avg_cadence'] or '—':12} | "
        f"{r['elevation_gain_m'] or '—':7} | "
        f"{r['suffer_score'] or '—':6} | "
        f"{r['perceived_exertion'] or '—':3} | "
        f"{analysis}"
    )


def _hybrid_log_row(r: dict) -> str:
    dist_km = (r["distance_m"] or 0) / 1000
    sport = r["sport_type"] or ""
    is_run = sport in RUN_TYPES
    pace_speed = (
        _format_pace(r["avg_pace_s_per_km"]) if is_run else _format_speed(r["avg_pace_s_per_km"])
    )
    analysis = (r.get("analysis_summary") or "")[:60]
    return (
        f"{r['date'] or '?':10s} | "
        f"{sport[:10]:10s} | "
        f"{(r['name'] or '')[:30]:30s} | "
        f"{dist_km:8.2f} | "
        f"{_format_duration(r['moving_time_s']):8s} | "
        f"{pace_speed:11s} | "
        f"{r['avg_hr'] or '—':6} | "
        f"{r['max_hr'] or '—':6} | "
        f"{r['avg_cadence'] or '—':7} | "
        f"{r['elevation_gain_m'] or '—':7} | "
        f"{r['suffer_score'] or '—':6} | "
        f"{r['perceived_exertion'] or '—':3} | "
        f"{analysis}"
    )


def _lifting_log_row(r: dict) -> str:
    analysis = (r.get("analysis_summary") or "")[:60]
    return (
        f"{r['date'] or '?':10s} | "
        f"{(r['name'] or '')[:30]:30s} | "
        f"{_format_duration(r['moving_time_s']):8s} | "
        f"{r['total_sets'] or '—':4} | "
        f"{r['total_volume_kg'] or '—':10} | "
        f"{r['perceived_exertion'] or '—':3} | "
        f"{analysis}"
    )


def _make_cardio_total(label: str) -> Callable[[list[dict]], str]:
    def total(rows: list[dict]) -> str:
        total_km = sum((r["distance_m"] or 0) / 1000 for r in rows)
        return f"Total: {len(rows)} {label}, {total_km:.1f} km"

    return total


def _lifting_log_total(rows: list[dict]) -> str:
    total_volume = sum((r["total_volume_kg"] or 0) for r in rows)
    return f"Total: {len(rows)} sessions, {total_volume:.0f} kg cumulative volume"


# ── ModeConfig ─────────────────────────────────────────────────────────────────


@dataclass
class ModeConfig:
    name: str
    sport_types: frozenset[str] | None  # None = no filter (all activities, used by hybrid)
    system_prompt: str
    has_analysis: bool  # whether to inject the cardio metrics guide
    hidden_tabs: frozenset[str]  # frontend tabs to hide for this mode
    activity_label: str  # "runs", "rides", "sessions", "activities"
    log_header: str  # column header row for training log
    log_sep_len: int  # length of the separator line
    format_log_row: Callable[[dict], str]
    format_log_total: Callable[[list[dict]], str]
    profile_section_keys: list[str]  # ordered section keys for profile_to_text


MODES: dict[str, ModeConfig] = {
    "running": ModeConfig(
        name="running",
        sport_types=RUN_TYPES,
        system_prompt=RUNNING_SYSTEM_PROMPT,
        has_analysis=True,
        hidden_tabs=frozenset(),
        activity_label="runs",
        log_header=(
            "DATE       | NAME                           | DIST(km) | DURATION | PACE     "
            "| AVG HR | MAX HR | CADENCE(spm) | ELEV(m) | SUFFER | RPE | ANALYSIS"
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
        log_header=(
            "DATE       | NAME                           | DIST(km) | DURATION | SPEED    "
            "| AVG HR | MAX HR | CADENCE(rpm) | ELEV(m) | SUFFER | RPE | ANALYSIS"
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
        log_header=(
            "DATE       | TYPE       | NAME                           | DIST(km) | DURATION "
            "| PACE/SPEED  | AVG HR | MAX HR | CADENCE | ELEV(m) | SUFFER | RPE | ANALYSIS"
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
        log_header=(
            "DATE       | NAME                           | DURATION | SETS | VOLUME(kg) | RPE | ANALYSIS"
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
