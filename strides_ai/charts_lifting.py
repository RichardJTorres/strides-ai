"""Chart data computation for lifting (HEVY) sessions.

Mirrors the patterns in ``charts_data.py`` (ISO-week bucketing, 4-week trailing
rolling averages, current-week flag) but operates on weightlifting metrics:

  - weekly_volume: kg lifted per ISO week
  - weekly_sessions: number of sessions per ISO week
  - one_rm_progression: per-exercise estimated 1RM over time
  - muscle_group_sets: stacked working-set count per primary muscle group per week
  - rpe_trend: per-session avg RPE over time, with rolling average

All functions accept a list of activity dicts (DB rows). Sessions without
``total_volume_kg`` or ``exercises_json`` are silently skipped where the metric
isn't computable.
"""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Iterator

from .hevy_analysis import estimate_1rm

log = logging.getLogger(__name__)


# ── JSON helpers ──────────────────────────────────────────────────────────────


def _parse_exercises(exercises_json: str | None) -> list[dict]:
    if not exercises_json:
        return []
    try:
        data = json.loads(exercises_json)
    except (json.JSONDecodeError, TypeError):
        log.warning("could not parse exercises_json")
        return []
    return data if isinstance(data, list) else []


def _working_sets(ex: dict) -> list[dict]:
    return [s for s in ex.get("sets", []) if s.get("type") != "warmup"]


def _resolve_muscle(ex: dict, template_muscle_map: dict[str, str] | None) -> str:
    """Best-effort primary muscle group lookup for an exercise.

    HEVY workouts only carry ``exercise_template_id``; the muscle group lives
    on the template. We prefer the cached template map, then fall back to any
    inline ``primary_muscle_group`` field, then ``"Unknown"``.
    """
    if template_muscle_map:
        tid = ex.get("exercise_template_id")
        if tid and tid in template_muscle_map:
            return template_muscle_map[tid]
    return ex.get("primary_muscle_group") or "Unknown"


def _iter_working_sets(
    activity: dict, template_muscle_map: dict[str, str] | None = None
) -> Iterator[tuple[str, str, dict]]:
    """Yield (exercise_title, primary_muscle, set_dict) for every working set."""
    for ex in _parse_exercises(activity.get("exercises_json")):
        title = ex.get("title", "Unknown")
        muscle = _resolve_muscle(ex, template_muscle_map)
        for s in _working_sets(ex):
            yield title, muscle, s


def _avg_rpe_from_exercises(exercises_json: str | None) -> float | None:
    """Average RPE across all working sets in a session, or None if none recorded."""
    rpes: list[float] = []
    for ex in _parse_exercises(exercises_json):
        for s in _working_sets(ex):
            rpe = s.get("rpe")
            if rpe is not None:
                try:
                    rpes.append(float(rpe))
                except (TypeError, ValueError):
                    continue
    return round(sum(rpes) / len(rpes), 2) if rpes else None


# ── Week bucketing ────────────────────────────────────────────────────────────


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _fill_weeks(first: date, last: date) -> list[date]:
    """Return every Monday from ``first`` (inclusive) to ``last`` (inclusive)."""
    weeks: list[date] = []
    w = first
    while w <= last:
        weeks.append(w)
        w += timedelta(weeks=1)
    return weeks


def _rolling_avg(values: list[float], window: int = 4) -> list[float]:
    out = []
    for i in range(len(values)):
        slice_ = values[max(0, i - (window - 1)) : i + 1]
        out.append(sum(slice_) / len(slice_))
    return out


# ── Weekly volume ─────────────────────────────────────────────────────────────


def compute_weekly_volume(activities: list[dict]) -> list[dict]:
    """Sum total_volume_kg per ISO week with 4-week trailing rolling average."""
    weekly: dict[date, float] = defaultdict(float)
    for act in activities:
        if not act.get("date") or not act.get("total_volume_kg"):
            continue
        weekly[_week_start(date.fromisoformat(act["date"]))] += float(act["total_volume_kg"])

    if not weekly:
        return []

    today = date.today()
    current_week = _week_start(today)
    weeks = _fill_weeks(min(weekly), current_week)
    values = [weekly.get(w, 0.0) for w in weeks]
    rolling = _rolling_avg(values, 4)

    return [
        {
            "week": w.isoformat(),
            "value": round(v, 2),
            "rolling_avg": round(r, 2),
            "is_current": w == current_week,
        }
        for w, v, r in zip(weeks, values, rolling)
    ]


# ── Weekly sessions ───────────────────────────────────────────────────────────


def compute_weekly_sessions(activities: list[dict]) -> list[dict]:
    """Count sessions per ISO week with 4-week rolling average."""
    weekly: dict[date, int] = defaultdict(int)
    for act in activities:
        if not act.get("date"):
            continue
        weekly[_week_start(date.fromisoformat(act["date"]))] += 1

    if not weekly:
        return []

    today = date.today()
    current_week = _week_start(today)
    weeks = _fill_weeks(min(weekly), current_week)
    values = [float(weekly.get(w, 0)) for w in weeks]
    rolling = _rolling_avg(values, 4)

    return [
        {
            "week": w.isoformat(),
            "value": int(v),
            "rolling_avg": round(r, 2),
            "is_current": w == current_week,
        }
        for w, v, r in zip(weeks, values, rolling)
    ]


# ── 1RM progression ───────────────────────────────────────────────────────────


def compute_one_rm_progression(activities: list[dict], top_n: int = 6) -> dict:
    """Per-exercise estimated 1RM time series.

    Returns ``{"series": {exercise_title: [{date, one_rm_kg}, ...]}, "exercises": [titles]}``.

    ``top_n`` keeps the exercises with the most working sets across the dataset
    so the chart auto-surfaces the lifts the athlete actually trains. Sets with
    reps > 12 are dropped by ``estimate_1rm``.
    """
    set_counts: Counter[str] = Counter()
    daily_max: dict[str, dict[date, float]] = defaultdict(dict)

    for act in activities:
        d_str = act.get("date")
        if not d_str:
            continue
        try:
            d = date.fromisoformat(d_str)
        except ValueError:
            continue
        for title, _muscle, s in _iter_working_sets(act):
            set_counts[title] += 1
            weight = s.get("weight_kg") or 0.0
            reps = s.get("reps") or 0
            one_rm = estimate_1rm(float(weight), int(reps))
            if one_rm is None:
                continue
            existing = daily_max[title].get(d)
            if existing is None or one_rm > existing:
                daily_max[title][d] = one_rm

    top_titles = [t for t, _ in set_counts.most_common(top_n) if daily_max.get(t)]
    series: dict[str, list[dict]] = {}
    for title in top_titles:
        points = [
            {"date": d.isoformat(), "one_rm_kg": round(v, 1)}
            for d, v in sorted(daily_max[title].items())
        ]
        if points:
            series[title] = points

    return {"series": series, "exercises": list(series.keys())}


# ── Muscle group sets per week ────────────────────────────────────────────────


def compute_muscle_group_sets_per_week(
    activities: list[dict],
    template_muscle_map: dict[str, str] | None = None,
) -> dict:
    """Stacked working-set counts per primary muscle group per ISO week.

    Returns ``{"weeks": [{week, "Chest": n, "Back": n, ...}, ...], "categories": [...]}``.
    Muscle groups are ordered by total volume across all weeks, descending.

    ``template_muscle_map`` lets the caller pass a cached HEVY exercise-template
    catalogue (``{exercise_template_id: primary_muscle_group}``) so muscle data
    can be resolved even though the workout payload only carries template ids.
    """
    weekly: dict[date, Counter[str]] = defaultdict(Counter)
    totals: Counter[str] = Counter()

    for act in activities:
        d_str = act.get("date")
        if not d_str:
            continue
        try:
            week = _week_start(date.fromisoformat(d_str))
        except ValueError:
            continue
        for _title, muscle, _s in _iter_working_sets(act, template_muscle_map):
            weekly[week][muscle] += 1
            totals[muscle] += 1

    if not weekly:
        return {"weeks": [], "categories": []}

    today = date.today()
    current_week = _week_start(today)
    weeks = _fill_weeks(min(weekly), current_week)
    categories = [m for m, _ in totals.most_common()]

    rows = []
    for w in weeks:
        row: dict = {"week": w.isoformat(), "is_current": w == current_week}
        bucket = weekly.get(w, Counter())
        for cat in categories:
            row[cat] = int(bucket.get(cat, 0))
        rows.append(row)

    return {"weeks": rows, "categories": categories}


# ── RPE trend ─────────────────────────────────────────────────────────────────


def compute_rpe_trend(activities: list[dict]) -> list[dict]:
    """Per-session avg RPE over time, with 4-session rolling average.

    Falls back to per-set average from ``exercises_json`` when ``perceived_exertion``
    is not set on the row. Sessions with no RPE data at all are skipped.
    """
    points: list[dict] = []
    for act in activities:
        d_str = act.get("date")
        if not d_str:
            continue
        rpe = act.get("perceived_exertion")
        if rpe is None:
            rpe = _avg_rpe_from_exercises(act.get("exercises_json"))
        if rpe is None:
            continue
        try:
            rpe_val = float(rpe)
        except (TypeError, ValueError):
            continue
        points.append({"date": d_str, "rpe": round(rpe_val, 2)})

    points.sort(key=lambda p: p["date"])
    rolling = _rolling_avg([p["rpe"] for p in points], 4)
    for p, r in zip(points, rolling):
        p["rolling_avg"] = round(r, 2)
    return points


# ── Combined ──────────────────────────────────────────────────────────────────


def get_chart_data(
    activities: list[dict],
    template_muscle_map: dict[str, str] | None = None,
) -> dict:
    acts = [dict(a) for a in activities]
    return {
        "weekly_volume": compute_weekly_volume(acts),
        "weekly_sessions": compute_weekly_sessions(acts),
        "one_rm_progression": compute_one_rm_progression(acts),
        "muscle_group_sets": compute_muscle_group_sets_per_week(acts, template_muscle_map),
        "rpe_trend": compute_rpe_trend(acts),
    }
