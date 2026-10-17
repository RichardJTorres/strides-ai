"""Builds a single-activity text block for chat attachments.

Used when the athlete explicitly attaches one activity to a chat turn (from
the composer's activity picker, or the Activities panel's "Discuss in chat"
bridge). Distinct from the terse per-row training log in coach.py: this is
the full detail for exactly one activity, including Deep Dive and notes,
sent only for the turn it's attached to.
"""

from .db.models import LIFT_TYPES, RUN_TYPES, Activity
from .units import DEFAULT_UNIT_SYSTEM, UnitSystem, format_speed_from_pace


def _format_duration(seconds: int | None) -> str | None:
    if seconds is None:
        return None
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m{s:02d}s" if h else f"{m}m{s:02d}s"


def _measured(activity: dict, field: str, units: UnitSystem) -> str | None:
    m = Activity.measure_field(activity, field, units)
    return m.formatted if m else None


def _cardio_stats_line(activity: dict, units: UnitSystem) -> str:
    sport = activity.get("sport_type") or ""
    is_run = sport in RUN_TYPES
    parts = []
    distance = _measured(activity, "distance_m", units)
    if distance:
        parts.append(f"Distance: {distance}")
    duration = _format_duration(activity.get("moving_time_s"))
    if duration:
        parts.append(f"Duration: {duration}")
    pace_speed = (
        _measured(activity, "avg_pace_s_per_km", units)
        if is_run
        else format_speed_from_pace(activity.get("avg_pace_s_per_km"), units, empty="")
    )
    if pace_speed:
        parts.append(f"{'Pace' if is_run else 'Speed'}: {pace_speed}")
    if activity.get("avg_hr") is not None:
        parts.append(f"Avg HR: {round(activity['avg_hr'])} bpm")
    if activity.get("max_hr") is not None:
        parts.append(f"Max HR: {activity['max_hr']} bpm")
    elevation = _measured(activity, "elevation_gain_m", units)
    if elevation:
        parts.append(f"Elevation gain: {elevation}")
    return " | ".join(parts) if parts else "No stats recorded."


def _lifting_stats_line(activity: dict, units: UnitSystem) -> str:
    parts = []
    duration = _format_duration(activity.get("moving_time_s"))
    if duration:
        parts.append(f"Duration: {duration}")
    if activity.get("total_sets") is not None:
        parts.append(f"Sets: {activity['total_sets']}")
    volume = _measured(activity, "total_volume_kg", units)
    if volume:
        parts.append(f"Volume: {volume}")
    return " | ".join(parts) if parts else "No stats recorded."


def _computed_metrics_line(activity: dict, units: UnitSystem) -> str | None:
    parts = []
    if activity.get("cardiac_decoupling_pct") is not None:
        parts.append(f"cardiac decoupling {activity['cardiac_decoupling_pct']:.1f}%")
    if activity.get("effort_efficiency_score") is not None:
        parts.append(f"effort efficiency {activity['effort_efficiency_score']:.0f}/100")
    pace_fade = _measured(activity, "pace_fade_s_per_km", units)
    if pace_fade:
        parts.append(f"pace fade {pace_fade}")
    if activity.get("avg_cadence") is not None:
        parts.append(f"cadence {activity['avg_cadence']:.0f}")
    climb = _measured(activity, "climb_m_per_km", units)
    if climb:
        parts.append(f"climbing ratio {climb}")
    zone_parts = [
        f"Z{z} {activity[f'hr_zone_{z}_pct']:.0f}%"
        for z in range(1, 6)
        if activity.get(f"hr_zone_{z}_pct") is not None
    ]
    if zone_parts:
        parts.append("HR zones " + " ".join(zone_parts))
    if activity.get("suffer_score_mismatch_flag"):
        parts.append("HR data may be unreliable (suffer score mismatch)")
    return "; ".join(parts) if parts else None


def build_activity_card(activity: dict, units: UnitSystem = DEFAULT_UNIT_SYSTEM) -> str:
    """
    Format one activity's full detail — stats, computed metrics, rule-based
    analysis, Deep Dive report, and athlete notes — as a text block suitable
    for a chat attachment, in ``units``. Every field is independently optional; a field
    with no data is described as missing rather than omitted silently.
    """
    name = activity.get("name") or "Untitled"
    date = activity.get("date") or "unknown date"
    sport = activity.get("sport_type") or ""
    is_lift = sport in LIFT_TYPES or (not sport and activity.get("exercises_json"))

    lines = [f"## Attached Activity: {name} ({date})"]
    if sport:
        lines.append(f"Sport: {sport}")

    lines.append(
        _lifting_stats_line(activity, units) if is_lift else _cardio_stats_line(activity, units)
    )

    from .analysis import render_analysis_summary

    summary = render_analysis_summary(activity, units)
    if summary:
        lines.append(f"Analysis: {summary}")
    elif activity.get("analysis_status") and activity["analysis_status"] != "done":
        lines.append(f"Analysis status: {activity['analysis_status']}.")
    else:
        lines.append("Analysis: not yet analyzed.")

    metrics_line = _computed_metrics_line(activity, units)
    if metrics_line:
        lines.append(f"Computed metrics: {metrics_line}.")

    if activity.get("user_notes"):
        lines.append(f"Athlete notes: {activity['user_notes']}")

    if activity.get("deep_dive_report"):
        lines.append("Deep dive analysis:\n" + activity["deep_dive_report"])
    else:
        lines.append("Deep dive analysis: not yet run for this activity.")

    return "\n".join(lines)
