"""Coaching system prompt assembly and history utilities."""

import sqlite3
from datetime import datetime, timedelta

from . import compliance, db
from .db.models import TrainingPlan
from .memory_context import memories_section
from .modes import MODES
from .training_state import build_training_state, render_for_prompt
from .units import (
    DEFAULT_UNIT_SYSTEM,
    Quantity,
    UnitSystem,
    convert,
    describe_for_prompt,
    unit_label,
)

RECALL_MESSAGES = 40
# Number of most-recent activities always pinned in the system prompt each turn.
# Older activities are represented by deterministic aggregates only.
RECENT_ACTIVITIES_IN_SYSTEM = 30
# How far ahead planned workouts are surfaced, wide enough to cover a multi-week
# training block the coach is asked to generate or regenerate.
PLANNED_WORKOUTS_WINDOW_DAYS = 60
# How far back to look when summarizing plan-vs-actual compliance for the coach (today inclusive).
COMPLIANCE_WINDOW_DAYS = 14

VOICE_INSTRUCTIONS: dict[str, str] = {
    "supportive": (
        "## Coaching Voice\n"
        "Communicate with warmth and encouragement. Celebrate every win, no matter how small. "
        "Emphasise progress over performance. Frame setbacks constructively and use inclusive, "
        "affirming language throughout."
    ),
    "motivational": (
        "## Coaching Voice\n"
        "Be high-energy and inspirational. Push the athlete toward their goals with genuine excitement. "
        "Use strong, vivid language. Remind them why they started and what they're capable of. "
        "Keep the energy up throughout every response."
    ),
    "technical": (
        "## Coaching Voice\n"
        "Be analytical and data-driven. Lean into metrics, zones, ratios, and trends. "
        "Minimise small talk — get to the numbers quickly. Use precise terminology "
        "(e.g. lactate threshold, progressive overload, HR zone distribution). "
        "Support every recommendation with data from the training log."
    ),
    "aggressive": (
        "## Coaching Voice\n"
        "Be direct and demanding. No sugarcoating — if the data shows underperformance, say so. "
        "Push harder. Keep responses concise and action-oriented. "
        "Focus on results, not feelings."
    ),
    "beginner_friendly": (
        "## Coaching Voice\n"
        "Be patient and educational. Avoid jargon — explain any technical terms you use. "
        "Break advice into simple, concrete steps. Reassure the athlete that progress takes time "
        "and that consistency matters more than perfection. Prioritise clarity over brevity."
    ),
    "conversational": (
        "## Coaching Voice\n"
        "Be casual and relaxed, like talking to a training buddy. Keep formality low. "
        "Use natural, colloquial language and feel free to be a bit chatty. "
        "Make the athlete feel like they're having a conversation, not receiving a lecture."
    ),
}


# ── build_system section helpers ──────────────────────────────────────────────


def _voice_section(coach_voice: str) -> str:
    block = VOICE_INSTRUCTIONS.get(coach_voice, "")
    if not block and coach_voice:
        block = f"## Coaching Voice\n{coach_voice}"
    return block


def _datetime_section() -> str:
    now = datetime.now().astimezone()
    day_str = now.strftime("%A, %B %-d, %Y")
    time_str = now.strftime("%-I:%M %p %Z")
    return (
        f"## Current Date & Time\n"
        f"Today is {day_str} at {time_str}. "
        "Use this to reason about training timing, upcoming workouts, recovery windows, "
        "and time elapsed since past activities. "
        "Do not mention the date or time in responses unless directly relevant to the athlete's question."
    )


def units_section(units: UnitSystem) -> str:
    units = UnitSystem.parse(units)
    return (
        f"## Units\n"
        f"The athlete uses the {units.value.upper()} system. Use {describe_for_prompt(units)} "
        "in every reply. All data in this prompt is already in these units. "
        "Earlier messages in this conversation may use a different unit system; treat those "
        "numbers as historical and do not let them change the units you reply in. "
        "When calling update_training_plan, set distance_unit and elevation_unit to the units "
        "you are using."
    )


def _memories_section(memories: list[dict]) -> str:
    return memories_section(memories)


def _compliance_section(activities: list[dict], units: UnitSystem = DEFAULT_UNIT_SYSTEM) -> str:
    today = datetime.now().date()
    start = today - timedelta(days=COMPLIANCE_WINDOW_DAYS)
    planned = compliance.planned_workouts_from_rows(
        db.get_training_plan(start.isoformat(), today.isoformat())
    )
    acts = compliance.compliance_activities_from_rows(activities)
    days = compliance.compute_range_compliance(planned, acts, today, units)
    summary = compliance.summarize_compliance(days)
    if summary.total_scored == 0:
        return ""
    lines = [
        f"Last {COMPLIANCE_WINDOW_DAYS} days: {summary.completed} completed, "
        f"{summary.modified} modified, {summary.missed} missed "
        f"({summary.unscored} unscored, {summary.upcoming} upcoming)."
    ]
    if summary.consistency_pct is not None:
        lines.append(
            f"Consistency (did something on plan days): {summary.consistency_pct}% · "
            f"On-target (hit the planned distance): {summary.on_target_pct}%"
        )
    flagged = [
        d
        for d in days
        if d.status in (compliance.ComplianceStatus.MISSED, compliance.ComplianceStatus.MODIFIED)
    ]
    if flagged:
        lines.append("Flagged days:")
        lines.extend(
            f"  - {d.date.isoformat()} ({d.workout_type}): {d.status.value} — {d.note}"
            for d in flagged
        )
    return "## Plan-vs-Actual Compliance\n" + "\n".join(lines)


def _training_state_section(
    activities: list[dict], mode: str, units: UnitSystem = DEFAULT_UNIT_SYSTEM
) -> str:
    """Load, projected load of the planned calendar, weekly ramp and plan conflicts — computed by
    training_state.py so the coach, the dashboard and plan edits all use the same numbers."""
    if mode == "lifting":
        return ""
    cfg = MODES.get(mode, MODES["running"])
    rows = [
        a for a in activities if cfg.sport_types is None or a.get("sport_type") in cfg.sport_types
    ]
    today = datetime.now().date()
    plan_rows, prefs = db.get_training_plan(), db.get_calendar_prefs()
    state = build_training_state(rows, plan_rows, prefs, mode, units, today)
    text = render_for_prompt(state, units)
    readout = _dashboard_readout(rows, plan_rows, prefs, mode, units, today)
    return f"{text}\n\n{readout}" if readout else text


def _dashboard_readout(rows, plan_rows, prefs, mode, units, today) -> str:
    """The athlete's Analytics insights card, when it is still fresh, so the coach and the
    dashboard give consistent advice. Stale or missing readouts are omitted, never guessed."""
    import json

    from .insights import digest_fingerprint

    raw = db.get_setting(f"charts_insights:{mode}:{UnitSystem.parse(units).value}")
    try:
        cached = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        return ""
    if not cached or cached.get("fingerprint") != digest_fingerprint(
        rows, mode, units, today, plan_rows, prefs
    ):
        return ""
    report = cached.get("report") or {}
    lines = [f"Dashboard readout (status: {report.get('status')}): {report.get('headline', '')}"]
    lines += [f"  - Recommended: {r['action']}" for r in report.get("recommendations", [])]
    return "\n".join(lines)


def _upcoming_workouts_section(units: UnitSystem = DEFAULT_UNIT_SYSTEM) -> str:
    upcoming = db.get_upcoming_planned_workouts(days=PLANNED_WORKOUTS_WINDOW_DAYS)
    if not upcoming:
        return ""
    header = "Date       | Type             | Distance  | Duration | Intensity"
    sep = "-" * 66
    rows = []
    for w in upcoming:
        m = TrainingPlan.measure_field(w, "distance_km", units) if w.get("distance_km") else None
        dist = m.formatted if m else "—"
        dur = f"{w['duration_min']} min" if w.get("duration_min") else "—"
        rows.append(
            f"{w['date']:10s} | {(w['workout_type'] or '')[:16]:16s} | {dist:9s} | {dur:8s} | {w.get('intensity') or '—'}"
        )
    return (
        f"## Upcoming Planned Workouts (next {PLANNED_WORKOUTS_WINDOW_DAYS} days)\n"
        + header
        + "\n"
        + sep
        + "\n"
        + "\n".join(rows)
    )


def _calendar_prefs_section() -> str:
    prefs = db.get_calendar_prefs()
    today = datetime.now().date().isoformat()
    races = sorted(
        (r for r in prefs.get("races", []) if r.get("date", "") >= today), key=lambda r: r["date"]
    )
    blocked = sorted(d for d in prefs.get("blocked_days", []) if d >= today)
    if not races and not blocked:
        return ""
    lines = []
    if races:
        lines.append("Upcoming races:")
        lines.extend(f"  - {r['date']}: {r.get('name', 'Race')}" for r in races)
    if blocked:
        lines.append("Blocked-out days (do not schedule workouts on these dates):")
        lines.extend(f"  - {d}" for d in blocked)
    return "## Calendar Constraints\n" + "\n".join(lines)


def _analysis_guide_section(cfg, recent: list, units: UnitSystem = DEFAULT_UNIT_SYSTEM) -> str:
    if not cfg.has_analysis or not any(a.get("analysis_summary") for a in recent):
        return ""
    return (
        "## Analysis Metrics Guide\n"
        "The ANALYSIS column in the training log contains auto-generated summaries. "
        "Treat all metrics as equally important inputs — no single metric defines a run.\n"
        "- **HR zones**: Z1=recovery, Z2=aerobic base, Z3=tempo, Z4=threshold, Z5=VO2max; "
        "Z1/Z2 time builds aerobic base, high Z4/Z5 indicates intensity work\n"
        "- **Effort efficiency score**: 0–100, normalized vs athlete's full history; "
        "higher = more efficient pace for a given HR; tracks fitness trends over time\n"
        f"- **Pace fade**: {unit_label(Quantity.PACE_DELTA, units)} change in final third vs "
        "first third; "
        "positive = slowing (fatigue or poor pacing), negative = negative split (strong finish)\n"
        "- **Cardiac decoupling %**: HR drift relative to pace; <5% = well-coupled, "
        "5–10% = moderate drift, >10% = high drift; most meaningful for steady aerobic runs"
    )


def _recent_activities_section(
    recent: list, mode: str, units: UnitSystem = DEFAULT_UNIT_SYSTEM
) -> str:
    log = build_training_log(recent, mode, units)
    return f"## Recent Activities (last {RECENT_ACTIVITIES_IN_SYSTEM})\n\n```\n{log}\n```"


# ── Public API ────────────────────────────────────────────────────────────────


def build_system(
    profile: str,
    memories: list[dict],
    mode: str = "running",
    activities: list | None = None,
    coach_voice: str = "",
    units: UnitSystem = DEFAULT_UNIT_SYSTEM,
) -> str:
    cfg = MODES.get(mode, MODES["running"])
    # Pin only the most recent activities every turn (cheap, always survives truncation).
    # Older activities are represented by deterministic aggregates only.
    recent = (activities or [])[:RECENT_ACTIVITIES_IN_SYSTEM]

    from .budget import ContextPrompt

    mandatory = "\n\n".join(
        [
            cfg.system_prompt,
            units_section(units),
            _datetime_section(),
            "Older activity details are excluded. Use only included details and labeled aggregates. "
            "Context sections and periods absent from this request are omitted, not evidence of no training.",
        ]
    )
    sections = [
        f"## Recent Activities\nACTIVITY {build_training_log([a], mode, units)}" for a in recent
    ]
    periods = [(str(a.get("date") or "unknown")[:10],) for a in recent]
    if not recent:
        sections.append("## Recent Activities\nNo activities found.")
        periods.append(())
    older = (activities or [])[RECENT_ACTIVITIES_IN_SYSTEM:]
    summary = older_activity_summary(older, units=units)
    if summary:
        sections.append(summary)
        dates = [str(a.get("date") or "unknown")[:10] for a in older]
        periods.append((min(dates), max(dates)))
    for extra in (
        _compliance_section(activities or [], units),
        _analysis_guide_section(cfg, recent, units),
    ):
        if extra:
            sections.append(extra)
            periods.append(())
    return ContextPrompt(
        mandatory,
        [
            profile,
            _memories_section(memories),
            _calendar_prefs_section(),
            _upcoming_workouts_section(units),
            _training_state_section(activities or [], mode, units),
            _voice_section(coach_voice),
        ],
        sections,
        periods,
    )


def build_training_log(
    rows: list[sqlite3.Row], mode: str = "running", units: UnitSystem = DEFAULT_UNIT_SYSTEM
) -> str:
    if not rows:
        return "No activities found."
    cfg = MODES.get(mode, MODES["running"])

    # When activities span multiple sport types, use the hybrid formatter
    # (it has a TYPE column and handles mixed pace/speed/duration display).
    if cfg.sport_types is not None:  # hybrid already uses its own formatter
        types_present = {(r.get("sport_type") or "") for r in rows}
        if not types_present.issubset(cfg.sport_types):
            cfg = MODES["hybrid"]

    sep = "-" * cfg.log_sep_len
    lines = [cfg.log_header(units), sep]
    for r in reversed(rows):
        lines.append(cfg.format_log_row(r, units))
    lines.append(sep)
    lines.append(cfg.format_log_total(rows, units))
    return "\n".join(lines)


def build_initial_history(
    activities: list, prior_messages: list[dict], mode: str = "running"
) -> list[dict]:
    """Recall persisted messages without seeding or duplicating activity data."""
    return [{"role": m["role"], "content": m["content"]} for m in prior_messages[-RECALL_MESSAGES:]]


def older_activity_summary(
    activities: list[dict], today=None, units: UnitSystem = DEFAULT_UNIT_SYSTEM
) -> str:
    """Exact disjoint aggregates, bounded to 12 weeks, 24 months and one older bucket per sport."""
    from collections import defaultdict
    from datetime import date

    today = today or date.today()
    week_start = today - timedelta(days=today.weekday())
    cutoff = week_start - timedelta(weeks=12)
    month_cutoff = today.year * 12 + today.month - 24
    buckets = defaultdict(list)
    unknown = 0
    for a in activities:
        try:
            day = date.fromisoformat(str(a.get("date", ""))[:10])
        except ValueError:
            unknown += 1
            continue
        sport = (a.get("sport_type") or "").lower()
        kind = (
            "strength"
            if any(x in sport for x in ("weight", "strength", "workout"))
            else (
                "cycling"
                if any(x in sport for x in ("ride", "cycl"))
                else "running" if "run" in sport else "other"
            )
        )
        if day > today:
            period = "future (coarsened)"
        elif day >= cutoff:
            period = "week " + (day - timedelta(days=day.weekday())).isoformat()
        elif day.year * 12 + day.month >= month_cutoff:
            period = "month " + day.strftime("%Y-%m")
        else:
            period = "earlier (coarsened)"
        buckets[(period, kind)].append((day, a))
    if not buckets and not unknown:
        return ""
    lines = [
        "## Older Activities (summarized; individual details excluded)",
        "Totals cover summarized records only; recent records may share these periods. "
        "Weekly totals cover preceding 12 weeks; older months and coarsened earlier periods follow.",
    ]
    for (period, kind), rows in sorted(buckets.items()):
        dates = [d for d, _ in rows]

        def total(field):
            return sum(a.get(field) or 0 for _, a in rows)

        def total_in(field, qty):
            return f"{unit_label(qty, units)}={convert(total(field), qty, units):.2f}"

        lines.append(
            f"{period} | {kind} | {min(dates)}..{max(dates)} | count={len(rows)} | "
            f"distance_{total_in('distance_m', Quantity.DISTANCE)} | "
            f'minutes={total("moving_time_s")/60:.1f} | '
            f"elevation_{total_in('elevation_gain_m', Quantity.ELEVATION)} | "
            f'sets={total("total_sets")} | volume_{total_in("total_volume_kg", Quantity.MASS)}'
        )
    if unknown:
        lines.append(f"Omitted: {unknown} activities with missing or invalid dates.")
    return "\n".join(lines)
