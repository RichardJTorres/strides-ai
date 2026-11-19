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
  ``week.<monday>.ramp.mean4`` / ``.median8`` (the ramp against each baseline, percent; None when
  that baseline does not exist) and ``load.peak_ratio`` (the highest projected fatigue/fitness
  ratio, with ``dates`` for where it falls). A later week's ramp can change although its own
  volume did not, because its baselines include the changed week.
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

from . import training_state as ts
from .compliance import SportGroup, classify_workout_type
from .dates import fmt_day
from .units import Quantity, UnitSystem, format_value

NEIGHBOR_DAYS = 3
# ramp_comparisons() names its baselines; the digest ids use these short keys.
_RAMP_KEYS = {"4-week average": "mean4", "8-week median": "median8"}
_RAMP_LABELS = {"mean4": "4-week average", "median8": "8-week median"}


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


def _ramps(week: Optional[dict]) -> dict[str, Optional[float]]:
    found = {
        _RAMP_KEYS[c["basis"]]: c["ramp_pct"]
        for c in (week or {}).get("ramp_comparisons", [])
        if c["basis"] in _RAMP_KEYS
    }
    return {key: found.get(key) for key in _RAMP_LABELS}


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
        b_ramp, a_ramp = _ramps(b), _ramps(a)
        for key, basis in _RAMP_LABELS.items():
            if b_ramp[key] != a_ramp[key]:
                out.append(
                    _metric(
                        f"week.{week}.ramp.{key}",
                        f"{name}: ramp vs {basis}",
                        b_ramp[key],
                        a_ramp[key],
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
    # The projected breach moves as the plan changes: it is one problem, wherever it falls.
    return ("ratio_breach", None) if v["kind"] == "ratio_breach" else (v["kind"], v["date"])


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
