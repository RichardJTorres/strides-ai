"""Charts insights: a deterministic training digest plus the prompt/parser for the LLM readout.

All numbers come from `build_digest` (pure, deterministic, `today` explicit). The LLM only
interprets the digest and cites metric ids; the UI renders figures from the digest, so the model
cannot invent or misquote data.

Windows (complete Monday-Sunday weeks, the in-progress week excluded from trend math):
  recent   = the 4 full weeks before the current week
  baseline = the 8 full weeks before that
"""

import hashlib
import json
from collections import defaultdict
from datetime import date, timedelta
from typing import Callable, Optional

from .activity_types import CYCLE_TYPES, RUN_TYPES
from .analytics import cardio
from .analytics.adapters import to_cardio_analytics
from .analytics.aggregation import monday_of
from .analytics.models import CardioAnalyticsActivity
from .compliance import (
    compliance_activities_from_rows,
    compute_range_compliance,
    planned_workouts_from_rows,
    summarize_compliance,
)
from .route_analysis import _strip_json_fences
from .training_state import (
    ACWR_DANGER,
    ACWR_HIGH,
    ACWR_LOW,
    RAMP_ELEVATED,
    RAMP_HIGH,
    TrainingState,
)
from .units import (
    DEFAULT_UNIT_SYSTEM,
    Quantity,
    UnitSystem,
    convert,
    describe_for_prompt,
    format_value,
    unit_label,
)

RECENT_WEEKS = 4
BASELINE_WEEKS = 8
MIN_ACTIVITIES = 6
MIN_ACTIVE_WEEKS = 3
FLAT_PCT = 3.0  # |delta| below this is "flat"
FLAT_PP = 1.0  # same, for percentage-point metrics
COMPLIANCE_LOOKBACK_DAYS = 14
UPCOMING_DAYS = 14

STATUSES = (
    "building",
    "maintaining",
    "peaking",
    "overreaching",
    "recovering",
    "detraining",
    "insufficient_data",
)
TONES = ("positive", "neutral", "warning")
MAX_FINDINGS = 4
MAX_RECOMMENDATIONS = 3


# ── Digest ──────────────────────────────────────────────────────────────────────


def _metric(
    id: str,
    label: str,
    group: str,
    value: Optional[float],
    fmt: Callable[[float], str],
    baseline: Optional[float] = None,
    *,
    pct_points: bool = False,
) -> Optional[dict]:
    """One digest entry, or None when there's no value (never zero-filled)."""
    if value is None:
        return None
    delta = delta_pct = None
    if baseline is not None:
        delta = round(value - baseline, 3)
        if not pct_points and baseline > 0:
            delta_pct = round(100 * (value - baseline) / baseline, 1)
    if delta_pct is not None:
        direction = "flat" if abs(delta_pct) < FLAT_PCT else ("up" if delta_pct > 0 else "down")
    elif delta is not None:
        direction = "flat" if abs(delta) < FLAT_PP else ("up" if delta > 0 else "down")
    else:
        direction = None
    return {
        "id": id,
        "label": label,
        "group": group,
        "value": round(value, 3),
        "formatted": fmt(value),
        "baseline": None if baseline is None else round(baseline, 3),
        "baseline_formatted": None if baseline is None else fmt(baseline),
        "delta": delta,
        "delta_pct": delta_pct,
        "direction": direction,
    }


def _in(a: CardioAnalyticsActivity, start: date, end: date) -> bool:
    """start inclusive, end exclusive."""
    return start <= a.date < end


def _avg(values: list[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def _weekly_avg(acts: list[CardioAnalyticsActivity], getter, start: date, weeks: int) -> float:
    end = start + timedelta(weeks=weeks)
    return sum(getter(a) for a in acts if _in(a, start, end)) / weeks


def _active_days_per_week(acts: list[CardioAnalyticsActivity], start: date, weeks: int) -> float:
    end = start + timedelta(weeks=weeks)
    return len({a.date for a in acts if _in(a, start, end)}) / weeks


def _longest_gap_days(dates: list[date], since: date, today: date) -> int:
    """Longest run of consecutive days with no activity between `since` and `today`."""
    active = sorted({d for d in dates if since <= d <= today})
    points = [since - timedelta(days=1), *active, today + timedelta(days=1)]
    return max((b - a).days - 1 for a, b in zip(points, points[1:]))


def _mean_in_windows(
    points: list[tuple[date, float]], recent: tuple[date, date], base: tuple[date, date]
) -> tuple[Optional[float], Optional[float]]:
    r = [v for d, v in points if recent[0] <= d < recent[1]]
    b = [v for d, v in points if base[0] <= d < base[1]]
    return _avg(r), _avg(b)


def _quality_metrics(
    acts: list[CardioAnalyticsActivity],
    unit: str,
    today: date,
    recent: tuple[date, date],
    base: tuple[date, date],
    units: UnitSystem,
    prefix: str,
    tag: str,
) -> tuple[list[dict], list[str]]:
    """Intensity distribution and efficiency/durability trends for one activity set."""
    out: list[Optional[dict]] = []
    missing: list[str] = []
    pct = lambda v: f"{v:.0f}%"

    zones = cardio.compute_hr_zone_trend(acts, unit, today)
    if zones.available:
        easy, hard = [], []
        for p in zones.data:
            wk = date.fromisoformat(p.week)
            if p.is_current:
                continue
            easy.append((wk, p.values["Z1"] + p.values["Z2"]))
            hard.append((wk, p.values["Z4"] + p.values["Z5"]))
        for key, label, pts in (
            ("easy_share", "Easy (Z1-Z2)", easy),
            ("hard_share", "Hard (Z4-Z5)", hard),
        ):
            r, b = _mean_in_windows(pts, recent, base)
            out.append(
                _metric(
                    f"intensity.{prefix}{key}",
                    f"{tag}{label} time share",
                    "intensity",
                    r,
                    pct,
                    b,
                    pct_points=True,
                )
            )
    else:
        missing.append(f"intensity.{prefix}hr_zones")

    decoupling = cardio.compute_cardiac_decoupling_trend(acts, unit, today)
    if decoupling.available:
        pts = [(date.fromisoformat(p.date), p.value) for p in decoupling.data]
        r, b = _mean_in_windows(pts, recent, base)
        out.append(
            _metric(
                f"efficiency.{prefix}decoupling",
                f"{tag}Cardiac decoupling",
                "efficiency",
                r,
                lambda v: f"{v:.1f}%",
                b,
                pct_points=True,
            )
        )
    else:
        missing.append(f"efficiency.{prefix}decoupling")

    aerobic = cardio.compute_aerobic_efficiency(acts, unit, today)
    if aerobic.available:
        pts = [(date.fromisoformat(p.date), p.value) for p in aerobic.scatter]
        r, b = _mean_in_windows(pts, recent, base)
        out.append(
            _metric(
                f"efficiency.{prefix}aerobic",
                f"{tag}Aerobic efficiency",
                "efficiency",
                r,
                lambda v: f"{v:.2f}",
                b,
            )
        )
    else:
        missing.append(f"efficiency.{prefix}aerobic")

    fade = cardio.compute_pace_fade_trend(acts, unit, today)
    if fade.available:
        pts = [(date.fromisoformat(p.date), p.value) for p in fade.data]
        r, b = _mean_in_windows(pts, recent, base)
        out.append(
            _metric(
                f"efficiency.{prefix}pace_fade",
                f"{tag}Pace fade",
                "efficiency",
                r,
                lambda v: f"{v:+.0f} s/{'mi' if unit == 'miles' else 'km'}",
                b,
                pct_points=True,
            )
        )
    return [m for m in out if m], missing


def build_digest(
    rows: list[dict],
    mode: str,
    units: UnitSystem,
    today: date,
    plan_rows: Optional[list[dict]] = None,
    races: Optional[list[dict]] = None,
    state: Optional[TrainingState] = None,
) -> dict:
    """DB activity rows -> deterministic digest. Same inputs always produce the same output.

    `state` (see training_state.py) adds the forward-looking `plan.*` metrics and the `upcoming`
    context so the readout is written against the calendar, not just the past."""
    units = UnitSystem.parse(units)
    unit = "miles" if units is UnitSystem.IMPERIAL else "km"
    acts = to_cardio_analytics(rows)

    cm = monday_of(today)
    recent = (cm - timedelta(weeks=RECENT_WEEKS), cm)
    base = (recent[0] - timedelta(weeks=BASELINE_WEEKS), recent[0])
    active_weeks = len({monday_of(a.date) for a in acts if a.date < cm})
    sufficient = len(acts) >= MIN_ACTIVITIES and active_weeks >= MIN_ACTIVE_WEEKS

    digest: dict = {
        "mode": mode,
        "unit_system": units.value,
        "as_of": today.isoformat(),
        "windows": {
            "recent": [recent[0].isoformat(), (recent[1] - timedelta(days=1)).isoformat()],
            "baseline": [base[0].isoformat(), (base[1] - timedelta(days=1)).isoformat()],
        },
        "sufficient": sufficient,
        "activity_count": len(acts),
        "metrics": [],
        "flags": [],
        "missing": [],
        "context": {"next_race": None, "compliance": None, "upcoming": None},
    }
    if not sufficient:
        return digest

    dist_u = lambda v: f"{v:.1f} {unit_label(Quantity.DISTANCE, units)}"
    elev_u = lambda v: f"{v:.0f} {unit_label(Quantity.ELEVATION, units)}"
    hours = lambda v: f"{v:.1f} h"
    metrics: list[Optional[dict]] = []

    def dist_of(a):  # distance in the athlete's display unit
        return convert(a.distance_m or 0.0, Quantity.DISTANCE, units)

    def hrs(a):
        return (a.moving_time_s or 0) / 3600.0

    # Volume
    metrics.append(
        _metric(
            "volume.distance",
            "Avg weekly distance",
            "volume",
            _weekly_avg(acts, dist_of, recent[0], RECENT_WEEKS),
            dist_u,
            _weekly_avg(acts, dist_of, base[0], BASELINE_WEEKS),
        )
    )
    metrics.append(
        _metric(
            "volume.time",
            "Avg weekly training time",
            "volume",
            _weekly_avg(acts, hrs, recent[0], RECENT_WEEKS),
            hours,
            _weekly_avg(acts, hrs, base[0], BASELINE_WEEKS),
        )
    )
    last_week = cm - timedelta(weeks=1)
    last_week_dist = _weekly_avg(acts, dist_of, last_week, 1)
    prior_avg = _weekly_avg(acts, dist_of, last_week - timedelta(weeks=RECENT_WEEKS), RECENT_WEEKS)
    ramp = _metric(
        "volume.ramp",
        "Last full week vs prior 4-wk avg",
        "volume",
        last_week_dist,
        dist_u,
        prior_avg if prior_avg > 0 else None,
    )
    metrics.append(ramp)
    metrics.append(
        _metric(
            "volume.freq",
            "Active days per week",
            "volume",
            _active_days_per_week(acts, recent[0], RECENT_WEEKS),
            lambda v: f"{v:.1f}",
            _active_days_per_week(acts, base[0], BASELINE_WEEKS),
        )
    )
    recent_acts = [a for a in acts if _in(a, *recent)]
    if recent_acts:
        longest = max(recent_acts, key=lambda a: a.distance_m or 0.0)
        metrics.append(
            _metric("volume.longest", "Longest session (4 wk)", "volume", dist_of(longest), dist_u)
        )
    gap_start = max(today - timedelta(days=27), min(a.date for a in acts))
    gap = _longest_gap_days([a.date for a in acts], gap_start, today)
    metrics.append(
        _metric("volume.gap", "Longest rest gap (28 d)", "volume", gap, lambda v: f"{v:.0f} d")
    )
    wtd = sum(dist_of(a) for a in acts if cm <= a.date <= today)
    metrics.append(_metric("volume.wtd", "This week so far", "volume", wtd, dist_u))

    if mode == "hybrid":
        for sport, types, tag in (("run", RUN_TYPES, "Run"), ("ride", CYCLE_TYPES, "Ride")):
            sub = [a for a in acts if a.sport_type in types]
            if sub:
                metrics.append(
                    _metric(
                        f"volume.{sport}_distance",
                        f"{tag}: avg weekly distance",
                        "volume",
                        _weekly_avg(sub, dist_of, recent[0], RECENT_WEEKS),
                        dist_u,
                        _weekly_avg(sub, dist_of, base[0], BASELINE_WEEKS),
                    )
                )

    # Load (ATL/CTL are distance-based in the chart unit)
    atl_ctl = cardio.compute_atl_ctl(acts, unit, today)
    if atl_ctl.available and atl_ctl.data:
        by_date = {p.date: p for p in atl_ctl.data}
        latest = atl_ctl.data[-1]
        past = by_date.get((today - timedelta(days=28)).isoformat())
        metrics.append(
            _metric(
                "load.ctl",
                "Fitness (CTL, 42 d)",
                "load",
                latest.ctl,
                dist_u,
                past.ctl if past else None,
            )
        )
        metrics.append(_metric("load.atl", "Fatigue (ATL, 7 d)", "load", latest.atl, dist_u))
        metrics.append(
            _metric(
                "load.acwr",
                "Fatigue / fitness ratio",
                "load",
                latest.ratio,
                lambda v: f"{v:.2f}",
            )
        )
    else:
        digest["missing"].append("load")

    # Intensity / efficiency
    if mode == "hybrid":
        for prefix, types, tag in (("run_", RUN_TYPES, "Run: "), ("ride_", CYCLE_TYPES, "Ride: ")):
            sub = [a for a in acts if a.sport_type in types]
            q, missing = _quality_metrics(sub, unit, today, recent, base, units, prefix, tag)
            metrics.extend(q)
            digest["missing"].extend(missing)
    else:
        q, missing = _quality_metrics(acts, unit, today, recent, base, units, "", "")
        metrics.extend(q)
        digest["missing"].extend(missing)

    # Terrain
    if mode in ("cycling", "hybrid"):
        elev = lambda a: convert(a.elevation_gain_m or 0.0, Quantity.ELEVATION, units)
        metrics.append(
            _metric(
                "terrain.climb",
                "Avg weekly climbing",
                "terrain",
                _weekly_avg(acts, elev, recent[0], RECENT_WEEKS),
                elev_u,
                _weekly_avg(acts, elev, base[0], BASELINE_WEEKS),
            )
        )

    if state is not None:
        metrics.extend(_plan_metrics(state, dist_u))
    digest["metrics"] = [m for m in metrics if m]

    # Context: next race, recent plan compliance
    upcoming = sorted(
        (r for r in (races or []) if (r.get("date") or "") >= today.isoformat()),
        key=lambda r: r["date"],
    )
    if upcoming:
        r = upcoming[0]
        days_out = (date.fromisoformat(r["date"]) - today).days
        digest["context"]["next_race"] = {
            "name": r.get("name") or "Race",
            "date": r["date"],
            "days_out": days_out,
        }

    since = today - timedelta(days=COMPLIANCE_LOOKBACK_DAYS)
    planned = [p for p in planned_workouts_from_rows(plan_rows or []) if since <= p.date <= today]
    if planned:
        days = compute_range_compliance(
            planned, compliance_activities_from_rows(rows), today, units
        )
        s = summarize_compliance(days)
        if s.total_scored:
            digest["context"]["compliance"] = {
                "window_days": COMPLIANCE_LOOKBACK_DAYS,
                "scored": s.total_scored,
                "completed": s.completed,
                "modified": s.modified,
                "missed": s.missed,
                "consistency_pct": s.consistency_pct,
            }

    if state is not None:
        digest["context"]["upcoming"] = _upcoming_context(
            state, plan_rows or [], today, units, dist_u
        )

    digest["flags"] = _flags(digest)
    return digest


def _plan_metrics(state: TrainingState, dist_u: Callable[[float], str]) -> list[Optional[dict]]:
    out: list[Optional[dict]] = []
    ratios = [p["ratio"] for p in state.projection[:UPCOMING_DAYS] if p["ratio"] is not None]
    if ratios:
        out.append(
            _metric(
                "plan.peak_ratio",
                "Peak projected fatigue/fitness ratio (next 14 d, as planned)",
                "plan",
                max(ratios),
                lambda v: f"{v:.2f}",
            )
        )
    nxt = next((w for w in state.weeks if not w["is_current"]), None)
    if nxt and nxt["ramp_pct"] is not None:
        base = nxt["volume"] / (1 + nxt["ramp_pct"] / 100) if nxt["ramp_pct"] > -100 else None
        out.append(
            _metric(
                "plan.next_week",
                f"Planned volume, week of {nxt['week_start']}",
                "plan",
                nxt["volume"],
                dist_u,
                base if base and base > 0 else None,
            )
        )
    return out


def _upcoming_context(
    state: TrainingState,
    plan_rows: list[dict],
    today: date,
    units: UnitSystem,
    dist_u: Callable[[float], str],
) -> dict:
    """What is already on the calendar: the model must work with it, never against it."""
    end = (today + timedelta(days=UPCOMING_DAYS)).isoformat()
    sessions = []
    for p in sorted(plan_rows, key=lambda p: p.get("date") or ""):
        d = p.get("date") or ""
        if not (today.isoformat() <= d <= end):
            continue
        km = p.get("distance_km")
        sessions.append(
            {
                "date": d,
                "workout_type": p.get("workout_type"),
                "distance": dist_u(convert(km * 1000.0, Quantity.DISTANCE, units)) if km else None,
                "intensity": p.get("intensity"),
            }
        )
    c = state.constraints
    return {
        "sessions": sessions,
        "blocked_days": c["blocked_days"],
        "race_dates": [r["date"] for r in c["races"]],
        "weeks": state.weeks,
        "conflicts": state.conflicts,
    }


def _get(digest: dict, metric_id: str) -> Optional[dict]:
    return next((m for m in digest["metrics"] if m["id"] == metric_id), None)


def _flags(digest: dict) -> list[dict]:
    """Rule-based callouts. Thresholds are deliberately simple and testable."""
    flags: list[dict] = []

    def add(id_, severity, text, ids):
        flags.append({"id": id_, "severity": severity, "text": text, "metric_ids": ids})

    ramp = _get(digest, "volume.ramp")
    if ramp and ramp["delta_pct"] is not None:
        if ramp["delta_pct"] > RAMP_HIGH:
            add(
                "ramp_high",
                "warning",
                f"Last full week was {ramp['delta_pct']:+.0f}% vs the prior 4-week average.",
                ["volume.ramp"],
            )
        elif ramp["delta_pct"] > RAMP_ELEVATED:
            add(
                "ramp_elevated",
                "info",
                f"Last full week was {ramp['delta_pct']:+.0f}% vs the prior 4-week average.",
                ["volume.ramp"],
            )

    dist = _get(digest, "volume.distance")
    if dist and dist["delta_pct"] is not None and dist["delta_pct"] <= -25:
        add(
            "volume_drop",
            "info",
            f"4-week volume is {dist['delta_pct']:.0f}% vs the prior 8-week baseline.",
            ["volume.distance"],
        )

    acwr = _get(digest, "load.acwr")
    if acwr:
        if acwr["value"] > ACWR_HIGH:
            add(
                "acwr_high",
                "warning" if acwr["value"] > ACWR_DANGER else "info",
                f"Fatigue/fitness ratio is {acwr['value']:.2f} (>{ACWR_HIGH}).",
                ["load.acwr"],
            )
        elif acwr["value"] < ACWR_LOW:
            add(
                "acwr_low",
                "info",
                f"Fatigue/fitness ratio is {acwr['value']:.2f} (<{ACWR_LOW}): fresh or detraining.",
                ["load.acwr"],
            )

    gap = _get(digest, "volume.gap")
    if gap and gap["value"] >= 7:
        add(
            "long_gap",
            "warning",
            f"{gap['value']:.0f} consecutive days without activity in the last 28.",
            ["volume.gap"],
        )

    for m in digest["metrics"]:
        if m["id"].endswith("decoupling") and m["value"] > 5:
            add(
                "decoupling_high",
                "warning",
                f"{m['label']} averages {m['formatted']} (>5%): aerobic base may be lagging.",
                [m["id"]],
            )
        if m["id"].endswith("easy_share") and m["value"] < 70:
            add(
                "low_easy_share",
                "info",
                f"{m['label']} is {m['formatted']}; most training is above easy intensity.",
                [m["id"]],
            )

    race = digest["context"]["next_race"]
    if race and race["days_out"] <= 21:
        add("race_soon", "info", f"{race['name']} is {race['days_out']} days away.", [])

    up = digest["context"].get("upcoming")
    if up:
        hard = [c for c in up["conflicts"] if c["hard"]]
        if hard:
            add(
                "plan_conflict",
                "warning",
                f"{len(hard)} planned workout(s) sit on blocked-out or race days "
                f"(first: {hard[0]['date']}).",
                [],
            )
        soft = [c for c in up["conflicts"] if c["kind"] in ("ramp_high", "ratio_breach")]
        if soft:
            add("projected_overload", "warning", soft[0]["detail"], ["plan.peak_ratio"])

    comp = digest["context"]["compliance"]
    if comp and comp["consistency_pct"] is not None and comp["consistency_pct"] < 60:
        add(
            "plan_adherence_low",
            "info",
            f"Only {comp['consistency_pct']:.0f}% of scored planned workouts were done in the last {comp['window_days']} days.",
            [],
        )
    return flags


def digest_fingerprint(
    rows: list[dict],
    mode: str,
    units: UnitSystem,
    today: date,
    plan_rows: Optional[list[dict]] = None,
    prefs: Optional[dict] = None,
) -> str:
    """Changes when activities are added, the athlete's units change, the ISO week rolls over, or
    the calendar (planned workouts, races, blocked days) is edited."""
    ids = [r.get("id") or 0 for r in rows]
    dates = [r.get("date") or "" for r in rows]
    iso = today.isocalendar()
    payload = [
        mode,
        UnitSystem.parse(units).value,
        len(rows),
        max(ids, default=0),
        max(dates, default=""),
        iso[0],
        iso[1],
        sorted(
            [p.get("date"), p.get("workout_type"), p.get("distance_km"), p.get("intensity")]
            for p in (plan_rows or [])
        ),
        sorted([r.get("date"), r.get("name")] for r in (prefs or {}).get("races", [])),
        sorted((prefs or {}).get("blocked_days", [])),
    ]
    return hashlib.sha1(json.dumps(payload).encode()).hexdigest()[:16]


# ── Prompt / parser ─────────────────────────────────────────────────────────────

INSIGHTS_SYSTEM_PROMPT = """\
You are a training-data analyst producing a dashboard readout for an endurance athlete.
This is a report, not a conversation: no greetings, no questions, no filler.

You are given a digest of computed metrics: the last 4 full weeks ("recent") against the prior
8 full weeks ("baseline"), each with an id in square brackets, plus rule-based flags and context.
Interpret the digest. Do NOT recompute or restate numbers that are not in it, and never invent data.
If a metric is absent, it is unavailable: say nothing about it.

Respond with ONLY a valid JSON object — no prose, no markdown fences. Exactly these keys:
  "status"          — one of "building", "maintaining", "peaking", "overreaching", "recovering",
                      "detraining", "insufficient_data"
  "headline"        — one sentence (max 140 chars) summarizing current training state
  "findings"        — up to 4 objects: {"title": short label (max 6 words),
                      "detail": 1-2 sentences quoting the specific numbers that support it,
                      "tone": "positive" | "neutral" | "warning",
                      "metric_ids": [ids from the digest this finding rests on]}
                      Prioritize the most notable or surprising datapoints; skip the obvious.
  "recommendations" — up to 3 objects: {"action": concrete imperative with a number or session
                      type where possible, "why": max 15 words, "metric_ids": [..]}
                      Add "date" (YYYY-MM-DD) when the action targets a specific day.
                      Tie advice to the next race or planned-workout adherence when present.

The digest's "Already on the calendar" section lists sessions, blocked-out days and race dates.
Work with it, never against it: never recommend training on a blocked-out day or a race day;
if a planned deload, taper or rest day already delivers the advice, say it is already planned
instead of repeating it; phrase advice relative to the planned sessions ("keep Thursday's
tempo, make Saturday's long run easy") rather than adding new sessions.\
"""


def build_insights_prompt(digest: dict, units: UnitSystem = DEFAULT_UNIT_SYSTEM) -> str:
    w = digest["windows"]
    lines = [
        f"## Digest ({digest['mode']} mode, as of {digest['as_of']})",
        f"recent = {w['recent'][0]} to {w['recent'][1]}; baseline = {w['baseline'][0]} to {w['baseline'][1]}",
        "",
        "## Metrics",
    ]
    for m in digest["metrics"]:
        extra = ""
        if m["baseline_formatted"] is not None:
            extra = f" (baseline {m['baseline_formatted']}"
            if m["delta_pct"] is not None:
                extra += f", {m['delta_pct']:+.0f}%"
            elif m["delta"] is not None:
                extra += f", {m['delta']:+.1f} pts"
            extra += ")"
        lines.append(f"[{m['id']}] {m['label']}: {m['formatted']}{extra}")
    if digest["flags"]:
        lines += ["", "## Flags"]
        lines += [f"- ({f['severity']}) {f['text']}" for f in digest["flags"]]
    ctx = digest["context"]
    ctx_lines = []
    if ctx["next_race"]:
        r = ctx["next_race"]
        ctx_lines.append(f"Next race: {r['name']} on {r['date']} ({r['days_out']} days out)")
    if ctx["compliance"]:
        c = ctx["compliance"]
        ctx_lines.append(
            f"Plan adherence, last {c['window_days']} days: {c['completed']} completed, "
            f"{c['modified']} short of plan, {c['missed']} missed of {c['scored']} scored"
        )
    if ctx_lines:
        lines += ["", "## Context", *ctx_lines]
    up = ctx.get("upcoming")
    if up:
        lines += ["", f"## Already on the calendar (next {UPCOMING_DAYS} days)"]
        if up["sessions"]:
            lines += [
                f"- {x['date']}: {x['workout_type']}"
                + (f", {x['distance']}" if x["distance"] else "")
                + (f", {x['intensity']}" if x["intensity"] else "")
                for x in up["sessions"]
            ]
        else:
            lines.append("- No planned workouts.")
        if up["blocked_days"]:
            lines.append("Blocked-out days: " + ", ".join(up["blocked_days"]))
        if up["race_dates"]:
            lines.append("Race dates: " + ", ".join(up["race_dates"]))
        for w in up["weeks"]:
            ramp = "" if w["ramp_pct"] is None else f" ({w['ramp_pct']:+.0f}% vs prior 4-wk avg)"
            lines.append(f"Week of {w['week_start']}: {w['volume']:.1f} planned{ramp}")
        lines += [f"- Plan issue: {c['detail']}" for c in up["conflicts"]]
    if digest["missing"]:
        lines += ["", "Unavailable (not enough data): " + ", ".join(digest["missing"])]
    lines += ["", f"## Units\nWrite all measurements in {describe_for_prompt(units)}."]
    return "\n".join(lines)


def _clean_date(value) -> Optional[str]:
    try:
        return date.fromisoformat(value).isoformat() if isinstance(value, str) else None
    except ValueError:
        return None


def _clean_ids(ids, valid: set[str]) -> list[str]:
    if not isinstance(ids, list):
        return []
    return [i for i in ids if isinstance(i, str) and i in valid]


def parse_insights_response(text: str, digest: dict) -> dict:
    """Raises json.JSONDecodeError on non-JSON; otherwise normalizes to the documented shape."""
    parsed = json.loads(_strip_json_fences(text))
    if not isinstance(parsed, dict):
        raise json.JSONDecodeError("expected a JSON object", text, 0)
    valid = {m["id"] for m in digest["metrics"]}
    up = (digest.get("context") or {}).get("upcoming") or {}
    forbidden = set(up.get("blocked_days", [])) | set(up.get("race_dates", []))
    status = parsed.get("status")
    findings = []
    for f in (parsed.get("findings") or [])[:MAX_FINDINGS]:
        if not isinstance(f, dict) or not f.get("title"):
            continue
        tone = f.get("tone")
        findings.append(
            {
                "title": str(f["title"]),
                "detail": str(f.get("detail") or ""),
                "tone": tone if tone in TONES else "neutral",
                "metric_ids": _clean_ids(f.get("metric_ids"), valid),
            }
        )
    recs = []
    for r in (parsed.get("recommendations") or [])[:MAX_RECOMMENDATIONS]:
        if not isinstance(r, dict) or not r.get("action"):
            continue
        rec_date = _clean_date(r.get("date"))
        if rec_date and rec_date in forbidden:
            continue  # the model ignored the calendar; drop rather than show a conflict
        recs.append(
            {
                "action": str(r["action"]),
                "why": str(r.get("why") or ""),
                "metric_ids": _clean_ids(r.get("metric_ids"), valid),
                "date": rec_date,
            }
        )
    return {
        "status": status if status in STATUSES else "insufficient_data",
        "headline": str(parsed.get("headline") or "")[:200],
        "findings": findings,
        "recommendations": recs,
    }
