"""What-if: the deterministic before/after diff for a hypothetical calendar change.

The athlete builds a change they have not saved ("add a Friday jog", "swap this ride for
intervals"); this module says what it would do to the plan, from the same pure code the coach,
the Calendar and the `update_training_plan` guardrails already read (`training_state`). It
introduces no metric formula of its own: it builds the training state for the saved plan and for
the changed plan and reports where they differ.

Pure: no DB, no LLM, every function takes `today` explicitly. The same inputs always give the same
digest, byte for byte under ``json.dumps(sort_keys=True)``.

Digest contract (everything is JSON-able; hours are the load unit, `ts.LOAD_UNIT`):

* ``changes[]`` — one per operation, in order. ``{ref, op, entry_id, date, day, label, hours,
  scored, counted, reason}``. ``hours`` is the entry's own planned time (None when unknown).
  ``counted`` is False, with a ``reason`` (``past`` | ``beyond_horizon`` | ``not_in_load`` |
  ``no_duration``), when the load model ignores the entry, so a zero delta is never shown without
  its cause. Today counts the larger of what is logged and what is planned, so an entry for today
  can still move nothing once that much is logged: the metrics tell, ``counted`` does not.
* ``metrics[]`` — only values that differ. ``{id, label, before, after, delta, formatted_before,
  formatted_after, formatted_delta}``; None means "not available" (no baseline yet), never zero.
  Ids are stable and unique: ``week.<monday>.volume`` (sum of hours; zero is a real value),
  ``week.<monday>.ramp`` (the ramp against the mean of recent normal weeks, percent; None when there
  is no reference or nothing is planned that week) and ``load.peak_ratio`` (the highest projected
  fatigue/fitness ratio, with ``dates`` for where it falls; context, not a guardrail). A later
  week's ramp can change although its own volume did not, because its reference includes the
  changed week.
* ``violations`` — ``new``: what the change introduces (`training_state.violations_introduced`, the
  guardrails the coach is held to); ``resolved``: conflicts in the saved plan the change removes.
* ``context`` — ``next_race``, ``blocked_days`` inside the horizon, ``typical_week`` (the athlete's
  usual week, from completed weeks, so a hypothetical cannot move it) and ``neighbors``: the
  entries within `NEIGHBOR_DAYS` of any date the change touches, as they would stand after it.
* ``sufficient`` / ``missing`` — load needs `MIN_HISTORY_DAYS` of history. Without it the load
  metrics are left out (``missing`` has ``"load"``) rather than reported as zero; weekly volume,
  a plain sum, is still reported.
"""

from datetime import date, timedelta
from typing import Optional

from . import kinds
from . import training_state as ts
from .compliance import SportGroup, classify_workout_type
from .dates import fmt_day
from .plan_generation import _extract_json_object
from .units import Quantity, UnitSystem, format_value, unit_label

NEIGHBOR_DAYS = 3


def _trim(value: float, decimals: int) -> str:
    return f"{value:.{decimals}f}".rstrip("0").rstrip(".")


def _hours(value: float) -> str:
    return f"{_trim(value, 2)} h"


def _hours_delta(value: float) -> str:
    return f"{'+' if value > 0 else ''}{_trim(value, 2)} h"


def _pct(value: float) -> str:
    return f"{value:+.1f}%"


def _ratio(value: float) -> str:
    return f"{value:.2f}"


def _ratio_delta(value: float) -> str:
    return f"{value:+.2f}"


def _metric(mid: str, label: str, before, after, fmt, fmt_delta, decimals: int, **extra) -> dict:
    delta = None if before is None or after is None else round(after - before, decimals)
    return {
        "id": mid,
        "label": label,
        "before": before,
        "after": after,
        "delta": delta,
        "formatted_before": None if before is None else fmt(before),
        "formatted_after": None if after is None else fmt(after),
        "formatted_delta": None if delta is None else fmt_delta(delta),
        **extra,
    }


def _week_metrics(before: ts.TrainingState, after: ts.TrainingState) -> list[dict]:
    old = {w["week_start"]: w for w in before.weeks}
    new = {w["week_start"]: w for w in after.weeks}
    out: list[dict] = []
    for week in sorted(set(old) | set(new)):
        b, a = old.get(week), new.get(week)
        name = f"Week of {fmt_day(week)}"
        b_vol = None if b is None else b["volume"]
        a_vol = None if a is None else a["volume"]
        if b_vol != a_vol:
            out.append(
                _metric(
                    f"week.{week}.volume",
                    f"{name}: volume",
                    b_vol,
                    a_vol,
                    _hours,
                    _hours_delta,
                    2,
                )
            )
        b_ramp = None if b is None else b["ramp_pct"]
        a_ramp = None if a is None else a["ramp_pct"]
        if b_ramp != a_ramp:
            out.append(
                _metric(
                    f"week.{week}.ramp",
                    f"{name}: ramp vs {ts.REFERENCE_BASIS}",
                    b_ramp,
                    a_ramp,
                    _pct,
                    _pct,
                    1,
                )
            )
    return out


def _peak(state: ts.TrainingState) -> Optional[dict]:
    """The projection day with the highest ratio (the earliest on a tie), or None."""
    points = [p for p in state.projection if p["ratio"] is not None]
    return max(points, key=lambda p: p["ratio"]) if points else None


def _load_metrics(before: ts.TrainingState, after: ts.TrainingState) -> list[dict]:
    b, a = _peak(before), _peak(after)
    if b is None or a is None or b["ratio"] == a["ratio"]:
        return []
    return [
        _metric(
            "load.peak_ratio",
            f"Peak fatigue/fitness ratio, next {ts.DEFAULT_HORIZON_DAYS} days",
            b["ratio"],
            a["ratio"],
            _ratio,
            _ratio_delta,
            3,
            dates={"before": b["date"], "after": a["date"]},
        )
    ]


def _label(row: dict, units: UnitSystem) -> str:
    parts = [row.get("workout_type") or str(row.get("kind") or "entry").capitalize()]
    if row.get("distance_km"):
        parts.append(format_value(row["distance_km"] * 1000, Quantity.DISTANCE, units))
    if row.get("duration_min"):
        parts.append(f"{round(row['duration_min'])} min")
    return ", ".join(parts)


def _is_scored(row: dict) -> bool:
    return (
        row.get("kind", "workout") == "workout"
        and classify_workout_type(row.get("workout_type")) is not SportGroup.UNSCORED
    )


def _describe_changes(
    ops: list[dict], plan_rows: list[dict], mode: Optional[str], today: date, units: UnitSystem
) -> tuple[list[dict], set[date]]:
    """One record per operation, and the dates the operations touch (before and after a move)."""
    by_id = {p["id"]: p for p in plan_rows if p.get("id") is not None}
    out: list[dict] = []
    touched: set[date] = set()
    for n, op in enumerate(ops, start=1):
        single = ts.changes_from_ops([op], plan_rows)
        kind = op.get("op")
        entry_id: Optional[int] = None
        if kind == "create" and single["create"]:
            row = single["create"][0]
        elif kind == "update" and single["update"]:
            patch = single["update"][0]
            entry_id = patch["id"]
            row = {**by_id.get(entry_id, {}), **{k: v for k, v in patch.items() if k != "id"}}
        elif kind == "delete" and single["delete"] and single["delete"][0] in by_id:
            entry_id = single["delete"][0]
            row = by_id[entry_id]
        else:
            # Not something the calendar would do: a delete of an entry that is not there is a
            # no-op there, and anything malformed is refused by the dry run before this runs.
            continue
        row = ts.normalized_plan_row(row)  # a structure decides the duration the label shows
        load = ts.describe_planned_load(row, mode, today)
        out.append(
            {
                "ref": f"change.{n}",
                "op": kind,
                "entry_id": entry_id,
                "date": row.get("date"),
                "day": fmt_day(row.get("date")),
                "label": _label(row, units),
                "hours": None if load["hours"] is None else round(load["hours"], 2),
                "scored": _is_scored(row),
                "counted": load["reason"] is None,
                "reason": load["reason"],
            }
        )
        for d in (row.get("date"), (by_id.get(entry_id) or {}).get("date")):
            try:
                touched.add(date.fromisoformat(d or ""))
            except ValueError:
                pass
    return out, touched


def _neighbors(
    after_rows: list[dict], touched: set[date], updated_ids: set[int], units: UnitSystem
) -> list[dict]:
    out = []
    for r in after_rows:
        try:
            d = date.fromisoformat(r.get("date") or "")
        except ValueError:
            continue
        if not any(abs((d - t).days) <= NEIGHBOR_DAYS for t in touched):
            continue
        out.append(
            {
                "id": r.get("id"),
                "date": d.isoformat(),
                "day": fmt_day(d.isoformat()),
                "kind": r.get("kind"),
                "type": r.get("workout_type"),
                "name": r.get("title") if r.get("kind") == "race" else None,
                "duration_min": r.get("duration_min"),
                "distance": (
                    format_value(r["distance_km"] * 1000, Quantity.DISTANCE, units)
                    if r.get("distance_km")
                    else None
                ),
                "intensity": r.get("intensity"),
                "hypothetical": r.get("id") is None,
                "modified": r.get("id") in updated_ids,
            }
        )
    out.sort(key=lambda n: (n["date"], n["id"] is None, n["id"] or 0, n["type"] or ""))
    return out


def _conflict_key(v: dict) -> tuple:
    return (v["kind"], v["date"])


def build_what_if_digest(
    rows: list[dict],
    plan_rows: list[dict],
    prefs: dict,
    mode: Optional[str],
    units: UnitSystem,
    today: date,
    ops: list[dict],
) -> dict:
    """The digest (see the module docstring) for calendar `ops` applied to `plan_rows`.

    `rows` are the activities of `mode` (as for `build_training_state`), `ops` the create /
    update / delete operations the calendar would run. Nothing is stored.
    """
    changes = ts.changes_from_ops(ops, plan_rows)
    before = ts.build_training_state(rows, plan_rows, prefs, mode, units, today)
    after_rows = ts.apply_changes(plan_rows, changes)
    after = ts.build_training_state(rows, after_rows, prefs, mode, units, today)

    described, touched = _describe_changes(ops, plan_rows, mode, today, units)
    sufficient = after.load["ctl"] is not None
    missing = [] if sufficient else ["load"]
    if before.typical_week is None:
        missing.append("typical_week")

    after_keys = {_conflict_key(v) for v in after.conflicts}
    horizon_end = (today + timedelta(days=ts.DEFAULT_HORIZON_DAYS)).isoformat()
    order = lambda v: (v["date"], v["kind"])  # noqa: E731
    return {
        "as_of": today.isoformat(),
        "mode": mode,
        "unit": ts.LOAD_UNIT,
        "horizon_days": ts.DEFAULT_HORIZON_DAYS,
        "thresholds": after.thresholds,
        "sufficient": sufficient,
        "missing": missing,
        "changes": described,
        "metrics": _week_metrics(before, after) + (_load_metrics(before, after)),
        "violations": {
            "new": sorted(
                (v.to_dict() for v in ts.violations_introduced(before, after, plan_rows, changes)),
                key=order,
            ),
            "resolved": sorted(
                (v for v in before.conflicts if _conflict_key(v) not in after_keys), key=order
            ),
        },
        "context": {
            "next_race": after.constraints["next_race"],
            "blocked_days": [d for d in after.constraints["blocked_days"] if d <= horizon_end],
            "typical_week": before.typical_week,
            "neighbors": _neighbors(
                after_rows, touched, {u["id"] for u in changes["update"]}, units
            ),
        },
    }


# ── the coach's reading of the digest ────────────────────────────────────────────

VERDICTS = ("fine", "caution", "bad")  # least to most severe
MAX_REASONS = 4

WHAT_IF_SYSTEM_PROMPT = f"""\
You are the athlete's coach answering a hypothetical. They have NOT saved the change below; they
want to know whether it is a good idea and whether anything else on their calendar should move.
This is an assessment, not a conversation: no greetings, no questions back.

You are given a digest: computed numbers for the saved plan against the plan with the change (each
metric has an id in square brackets), the guardrails the change trips, the entries around it (with
ids), and the athlete's profile and notes. Interpret the digest. Do NOT recompute numbers and never
invent data. A metric that is absent is unavailable: say nothing about it.

Respond with ONLY a valid JSON object, no prose and no markdown fences. Exactly these keys:
  "verdict"   - "fine" | "caution" | "bad"
  "headline"  - one sentence (max 140 chars) that answers the athlete's question
  "reasons"   - up to {MAX_REASONS} objects {{"text": 1-2 sentences quoting the numbers or entries
                behind it, "metric_ids": [ids from the digest it rests on]}}
  "suggested" - null when the change is fine as it is. Otherwise the COMPLETE alternative change
                set, which REPLACES the athlete's: it must contain their change (adjusted if
                needed) plus anything else that has to move. Shape {{"set": [...], "delete": [ids]}}.
                A "set" item without "id" creates an entry ("date" and "workout_type" required); with
                an "id" from the digest's calendar list it changes only the fields you send.
                Fields: date (YYYY-MM-DD), workout_type (one of: {", ".join(kinds.WORKOUT_TYPES)}),
                description, duration_min (integer), distance + distance_unit ("km" or "mi"),
                elevation + elevation_unit ("m" or "ft"), intensity ("easy", "moderate", "hard").
                Change as little as possible: move or shorten the one session that has to give.

How to judge:
- Ramp, loading-week and run-spike notes are advisory screening, not limits. Off weeks (travel,
  race recovery) are already set aside from the ramp. Moving time measures volume, not intensity or
  mechanical stress; a cycling hour carries far less impact than a running hour, and a single run
  much longer than the athlete's recent longest is the best-evidenced running injury risk.
- Planned Strength counts as load by its duration; logged strength sessions never enter a running or
  cycling baseline, so a planned one can read as a jump against it. Weigh the number against how
  hard the session really is instead of treating it as running volume.
- Judge how the change sits against the neighbouring days: a hard or long session the next day, a
  rest day it removes, a race. A change marked "not counted" did not move the load numbers: judge it
  on the neighbours alone and say it is outside the load model.
- A guardrail violation marked HARD is a rule, not an opinion. Never suggest training on a
  blocked-out day, or on a race day beyond a short easy shakeout.
- Respect the athlete's notes, injuries first.
- The server raises your verdict to match any guardrail violation; do not understate one.\
"""


def _entry_line(n: dict) -> str:
    bits = [n["type"] or n["kind"] or "entry"]
    if n.get("name"):
        bits.append(f"\"{n['name']}\"")
    if n.get("distance"):
        bits.append(n["distance"])
    if n.get("duration_min"):
        bits.append(f"{round(n['duration_min'])} min")
    if n.get("intensity"):
        bits.append(n["intensity"])
    tag = " (proposed)" if n["hypothetical"] else " (changed)" if n["modified"] else ""
    ident = "new" if n["id"] is None else str(n["id"])
    return f"[{ident}] {n['day']}: {', '.join(bits)}{tag}"


def build_what_if_prompt(
    digest: dict,
    question: str,
    profile_text: str = "",
    protected_notes: Optional[list[str]] = None,
    units: UnitSystem = ts.DEFAULT_UNIT_SYSTEM,
) -> str:
    """The user message: the digest as text, the athlete's profile and notes, their question."""
    c = digest["context"]
    sections = [
        f"## Today\n{fmt_day(digest['as_of'])}. Coaching mode: {digest['mode']}. Load is moving "
        f"time in hours. Give any distance in {unit_label(Quantity.DISTANCE, units)} and say so "
        'with "distance_unit".'
    ]
    if profile_text:
        sections.append(f"## Athlete\n{profile_text}")
    if protected_notes:
        sections.append("## Notes to respect\n" + "\n".join(protected_notes))

    changes = []
    for ch in digest["changes"]:
        effect = (
            f"{ch['hours']:g} h of planned load"
            if ch["counted"]
            else f"not counted in load ({ch['reason'].replace('_', ' ')})"
        )
        scored = "" if ch["scored"] else "; never scored against the athlete's activities"
        changes.append(f"[{ch['ref']}] {ch['op']} {ch['day']}: {ch['label']}; {effect}{scored}")
    sections.append("## Proposed change (not saved)\n" + "\n".join(changes))

    metrics = [
        f"[{m['id']}] {m['label']}: {m['formatted_before'] or 'n/a'} -> "
        f"{m['formatted_after'] or 'n/a'}"
        + (f" ({m['formatted_delta']})" if m["formatted_delta"] else "")
        for m in digest["metrics"]
    ] or ["No load metric moves."]
    if "load" in digest["missing"]:
        metrics.append(
            f"Fatigue/fitness load is unavailable (under {ts.MIN_HISTORY_DAYS} days of history)."
        )
    sections.append("## Metrics, saved plan -> with the change\n" + "\n".join(metrics))

    th = digest["thresholds"]
    v = digest["violations"]
    guardrails = [f"- NEW{' HARD' if x['hard'] else ''}: {x['detail']}" for x in v["new"]] + [
        f"- RESOLVED: {x['detail']}" for x in v["resolved"]
    ]
    sections.append(
        f"## Guardrails (screening notes; a ramp above {th['ramp_high']:.0f}% vs recent normal "
        "weeks is high)\n"
        + ("\n".join(guardrails) or "The change introduces and resolves no violation.")
    )

    around = [_entry_line(n) for n in c["neighbors"]] or ["Nothing else within three days."]
    sections.append("## Calendar around the change (ids in brackets)\n" + "\n".join(around))

    context = []
    if c["next_race"]:
        r = c["next_race"]
        context.append(f"Next race: {r['name']} on {fmt_day(r['date'])} ({r['days_out']} days).")
    if c["blocked_days"]:
        context.append("Blocked-out days: " + ", ".join(fmt_day(d) for d in c["blocked_days"]))
    if c["typical_week"]:
        t = c["typical_week"]
        context.append(
            f"A typical week is {t['median']:g} h (range {t['low']:g}-{t['high']:g} h over "
            f"{t['weeks']} weeks)."
        )
    if context:
        sections.append("## Context\n" + "\n".join(context))

    sections.append("## The athlete's question\n" + (question.strip() or "Is this a good idea?"))
    return "\n\n".join(sections)


def verdict_floor(digest: dict) -> str:
    """The least severe verdict the computed guardrails allow: a new hard violation is bad, any
    other new violation at least a caution. A lenient model cannot understate what the rules
    already say."""
    new = digest["violations"]["new"]
    if any(v["hard"] for v in new):
        return "bad"
    return "caution" if new else "fine"


def _clean_ids(raw, valid: set[str]) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [i for i in raw if isinstance(i, str) and i in valid]


def _clean_suggested(raw) -> Optional[dict]:
    """The model's alternative change set in the `update_training_plan` shape, or None. Items are
    left as sent: validating them (and refusing the whole set on one bad item) is the caller's."""
    if not isinstance(raw, dict):
        return None
    sets = raw.get("set") if isinstance(raw.get("set"), list) else []
    deletes = raw.get("delete") if isinstance(raw.get("delete"), list) else []
    return {"set": sets, "delete": deletes} if sets or deletes else None


def parse_what_if_response(text: str, digest: dict) -> dict:
    """The model's JSON as `{verdict, headline, reasons, suggested}`.

    Raises ``json.JSONDecodeError`` / ``TypeError`` when there is no JSON object. An unknown verdict
    becomes "caution"; the verdict is never milder than `verdict_floor`; metric ids the digest does
    not have are dropped from the reasons.
    """
    parsed = _extract_json_object(text)
    if not isinstance(parsed, dict):
        raise TypeError("expected a JSON object")
    verdict = parsed.get("verdict")
    if verdict not in VERDICTS:
        verdict = "caution"
    floor = verdict_floor(digest)
    if VERDICTS.index(floor) > VERDICTS.index(verdict):
        verdict = floor
    valid = {m["id"] for m in digest["metrics"]} | {c["ref"] for c in digest["changes"]}
    reasons = []
    for r in (parsed.get("reasons") or [])[:MAX_REASONS]:
        if isinstance(r, dict) and r.get("text"):
            reasons.append(
                {"text": str(r["text"]), "metric_ids": _clean_ids(r.get("metric_ids"), valid)}
            )
    return {
        "verdict": verdict,
        "headline": str(parsed.get("headline") or "")[:200],
        "reasons": reasons,
        "suggested": _clean_suggested(parsed.get("suggested")),
    }
