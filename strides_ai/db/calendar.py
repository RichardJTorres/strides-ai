"""Calendar preferences and calendar-entry CRUD.

An *entry* is one thing on the calendar (``kind``: workout, race, rest, travel, other); workout and
race entries own a detail row. Several entries may share a date. Every write goes through this
module so the invariants hold in one place:

- entry + detail are written in one transaction; ``kind`` never changes after create;
- at most one *scored* workout per sport group per date (so one activity can never be credited
  to two planned workouts);
- ``update_entry`` takes a patch: a key that is absent is unchanged, a key set to ``None`` clears;
- the nutrition / route-analysis caches survive edits to notes and are cleared only when a field
  those prompts read changes (``inputs_hash``), and a late analysis write for stale inputs is
  rejected.
"""

import hashlib
import json
from datetime import date as date_cls, timedelta

from sqlmodel import Session, select

from ..kinds import (
    KIND_RACE,
    KIND_REST,
    KIND_WORKOUT,
    KINDS,
    KINDS_WITH_DETAIL,
    RACE_PRIORITIES,
    RACE_SPORTS,
    display_type,
    is_valid_workout_type,
    scored_group,
)
from ..workout_structure import structure_for_type, structure_to_json, total_seconds
from .models import CalendarEntry, CalendarPref, ChangeRequest, RaceDetail, WorkoutDetail


class EntryError(ValueError):
    """A write that breaks a calendar invariant; the message is safe to show the athlete."""


class EntryNotFound(EntryError):
    pass


# ── Prefs (blocked days) ──────────────────────────────────────────────────────────


def get_prefs(session: Session) -> dict:
    """Blocked days plus ``races`` derived from race entries (the single source of races)."""
    row = session.get(CalendarPref, 1)
    return {
        "blocked_days": json.loads(row.blocked_days) if row else [],
        "races": get_races(session),
    }


def save_prefs(session: Session, blocked_days: list) -> None:
    row = session.get(CalendarPref, 1) or CalendarPref(id=1)
    row.blocked_days = json.dumps(blocked_days)
    session.add(row)
    session.commit()


# ── Reading ───────────────────────────────────────────────────────────────────────

_WORKOUT_FIELDS = (
    "workout_type",
    "objective",
    "distance_km",
    "elevation_m",
    "duration_min",
    "intensity",
    "route_url",
    "structure_json",
)
_RACE_FIELDS = (
    "sport",
    "distance_km",
    "elevation_m",
    "goal_time_s",
    "goal_text",
    "priority",
    "route_url",
    "result_activity_id",
    "result_time_s",
)
_CACHE_FIELDS = (
    "nutrition_json",
    "route_analysis_json",
    "route_analyzed_at",
    "route_analysis_model",
    "inputs_hash",
)


def _flat(entry: CalendarEntry, workout: WorkoutDetail | None, race: RaceDetail | None) -> dict:
    """The flattened row older consumers expect, plus ``id`` and ``kind``.

    ``workout_type`` is the legacy display string (races read "Running Race", rest "Rest") and
    ``description`` is what the old model stored there: the objective for a workout, the name for
    a race, the notes for rest.
    """
    row: dict = {
        "id": entry.id,
        "date": entry.date,
        "kind": entry.kind,
        "title": entry.title,
        "notes": entry.notes,
        "created_at": entry.created_at,
        "workout_type": None,
        "description": entry.notes,
        "distance_km": None,
        "elevation_m": None,
        "duration_min": None,
        "intensity": None,
        "route_url": None,
        "structure_json": None,
        "nutrition_json": None,
        "route_analysis_json": None,
        "route_analyzed_at": None,
        "route_analysis_model": None,
        "inputs_hash": None,
        "objective": None,
        "sport": None,
        "goal_time_s": None,
        "goal_text": None,
        "priority": None,
        "result_activity_id": None,
        "result_time_s": None,
    }
    if workout is not None:
        row.update(workout.model_dump(exclude={"entry_id"}))
        row["description"] = workout.objective
    if race is not None:
        row.update(race.model_dump(exclude={"entry_id"}))
        row["description"] = entry.title
    row["workout_type"] = display_type(
        entry.kind, workout.workout_type if workout else None, race.sport if race else None
    )
    if entry.kind == KIND_REST:
        row["intensity"] = "rest"
    return row


def _load(session: Session, entries: list[CalendarEntry]) -> list[dict]:
    if not entries:
        return []
    ids = [e.id for e in entries]
    workouts = {
        w.entry_id: w
        for w in session.exec(select(WorkoutDetail).where(WorkoutDetail.entry_id.in_(ids)))
    }
    races = {
        r.entry_id: r for r in session.exec(select(RaceDetail).where(RaceDetail.entry_id.in_(ids)))
    }
    return [_flat(e, workouts.get(e.id), races.get(e.id)) for e in entries]


def get_plan_rows(
    session: Session, start_date: str | None = None, end_date: str | None = None
) -> list[dict]:
    stmt = select(CalendarEntry).order_by(CalendarEntry.date, CalendarEntry.id)
    if start_date and end_date:
        stmt = stmt.where(CalendarEntry.date.between(start_date, end_date))
    return _load(session, session.exec(stmt).all())


def get_entry(session: Session, entry_id: int) -> dict | None:
    entry = session.get(CalendarEntry, entry_id)
    return _load(session, [entry])[0] if entry else None


def get_races(session: Session) -> list[dict]:
    """Race entries as ``{id, date, name, target_time, sport, priority}``, soonest first."""
    out = []
    for r in get_plan_rows(session):
        if r["kind"] != KIND_RACE:
            continue
        out.append(
            {
                "id": r["id"],
                "date": r["date"],
                "name": (r["title"] or "").strip() or "Race",
                "target_time": format_goal(r["goal_time_s"]) or r["goal_text"],
                "sport": r["sport"],
                "priority": r["priority"],
            }
        )
    return out


def format_goal(seconds: int | None) -> str | None:
    if seconds is None:
        return None
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def get_upcoming_workouts(session: Session, days: int = 14) -> list[dict]:
    """Plan rows from today through the next *days* days."""
    today = date_cls.today()
    return get_plan_rows(session, today.isoformat(), (today + timedelta(days=days)).isoformat())


# ── Validation ────────────────────────────────────────────────────────────────────


def inputs_hash(row: dict) -> str:
    """Hash of everything the route-analysis and nutrition prompts read for this entry."""
    keys = (
        "kind",
        "workout_type",
        "sport",
        "title",
        "objective",
        "distance_km",
        "elevation_m",
        "duration_min",
        "intensity",
        "route_url",
    )
    values = [
        float(v) if k in ("distance_km", "elevation_m") and v is not None else v
        for k, v in ((k, row.get(k)) for k in keys)
    ]
    payload = json.dumps(values, default=str)
    return hashlib.sha1(payload.encode()).hexdigest()[:16]


def _check_date(value) -> str:
    try:
        return date_cls.fromisoformat(str(value)).isoformat()
    except ValueError:
        raise EntryError(f"Invalid date: {value!r}") from None


def _check_one_scored_per_group(
    session: Session, date: str, workout_type: str, exclude_id: int | None
) -> None:
    group = scored_group(workout_type)
    if group is None:
        return
    others = session.exec(
        select(WorkoutDetail, CalendarEntry)
        .join(CalendarEntry, CalendarEntry.id == WorkoutDetail.entry_id)
        .where(CalendarEntry.date == date)
    ).all()
    for detail, entry in others:
        if entry.id != exclude_id and scored_group(detail.workout_type) == group:
            raise EntryError(
                f"{date} already has a scored {group} workout ({detail.workout_type}). "
                "Edit that one, or change this to a different sport."
            )


def _check_result_link(session: Session, entry_id: int, date: str, activity_id: int) -> None:
    from .models import Activity

    activity = session.get(Activity, activity_id)
    if activity is None or (activity.date or "") != date:
        raise EntryError("A race result must be an activity from the race day")
    taken = session.exec(
        select(RaceDetail).where(
            RaceDetail.result_activity_id == activity_id, RaceDetail.entry_id != entry_id
        )
    ).first()
    if taken is not None:
        raise EntryError("That activity is already linked to another race")


def _normalize_workout(fields: dict) -> dict:
    wtype = fields.get("workout_type")
    if not is_valid_workout_type(wtype):
        raise EntryError(f"Unknown workout type: {wtype!r}")
    out = {k: fields.get(k) for k in _WORKOUT_FIELDS if k != "structure_json"}
    structure = structure_for_type(wtype, fields.get("structure"))
    if structure:
        out["duration_min"] = round(total_seconds(structure) / 60)
    out["structure_json"] = structure_to_json(structure)
    return out


def _normalize_race(fields: dict) -> dict:
    out = {k: fields.get(k) for k in _RACE_FIELDS}
    out["sport"] = out["sport"] or "other"
    if out["sport"] not in RACE_SPORTS:
        raise EntryError(f"Unknown race sport: {out['sport']!r}")
    if out["priority"] is not None and out["priority"] not in RACE_PRIORITIES:
        raise EntryError(f"Race priority must be one of {', '.join(RACE_PRIORITIES)}")
    return out


# ── Writing (no commit; callers commit) ───────────────────────────────────────────


def _create(session: Session, data: dict) -> int:
    kind = data.get("kind")
    if kind not in KINDS:
        raise EntryError(f"Unknown entry kind: {kind!r}")
    date = _check_date(data.get("date"))
    detail_keys = set(_WORKOUT_FIELDS) | set(_RACE_FIELDS) | {"structure"}
    if kind not in KINDS_WITH_DETAIL and detail_keys & {
        k for k, v in data.items() if v is not None
    }:
        raise EntryError(f"A {kind} entry has no workout or race fields")

    entry = CalendarEntry(date=date, kind=kind, title=data.get("title"), notes=data.get("notes"))
    session.add(entry)
    session.flush()
    if kind == KIND_WORKOUT:
        fields = _normalize_workout(data)
        _check_one_scored_per_group(session, date, fields["workout_type"], entry.id)
        detail = WorkoutDetail(entry_id=entry.id, **fields)
        detail.inputs_hash = inputs_hash(
            {**fields, "kind": kind, "objective": fields["objective"], "title": entry.title}
        )
        session.add(detail)
    elif kind == KIND_RACE:
        fields = _normalize_race(data)
        detail = RaceDetail(entry_id=entry.id, **fields)
        detail.inputs_hash = inputs_hash({**fields, "kind": kind, "title": entry.title})
        session.add(detail)
    session.flush()
    return entry.id


def _refresh_caches(detail, before: str, after_inputs: dict) -> None:
    """Drop the cached nutrition / route analysis only when a prompt input actually changed."""
    after = inputs_hash(after_inputs)
    if after != before:
        detail.nutrition_json = None
        detail.route_analysis_json = None
        detail.route_analyzed_at = None
        detail.route_analysis_model = None
    detail.inputs_hash = after


def _update(session: Session, entry_id: int, patch: dict) -> None:
    """Apply a patch: absent keys are unchanged, ``None`` clears. ``kind`` cannot change."""
    entry = session.get(CalendarEntry, entry_id)
    if entry is None:
        raise EntryNotFound(f"No calendar entry with id {entry_id}")
    if "kind" in patch and patch["kind"] != entry.kind:
        raise EntryError("An entry's kind cannot change; delete it and add a new one")

    title_before = entry.title
    if "date" in patch:
        entry.date = _check_date(patch["date"])
    for key in ("title", "notes"):
        if key in patch:
            setattr(entry, key, patch[key])
    session.add(entry)

    if entry.kind == KIND_WORKOUT:
        detail = session.get(WorkoutDetail, entry_id)
        before = detail.inputs_hash or inputs_hash(
            {**detail.model_dump(), "kind": entry.kind, "title": title_before}
        )
        merged = {**detail.model_dump(exclude={"entry_id"}), "structure": None}
        merged["structure"] = json.loads(detail.structure_json) if detail.structure_json else None
        merged.update({k: v for k, v in patch.items() if k in (*_WORKOUT_FIELDS, "structure")})
        if "structure_json" in patch and "structure" not in patch:
            merged["structure"] = patch["structure_json"]
        fields = _normalize_workout(merged)
        _check_one_scored_per_group(session, entry.date, fields["workout_type"], entry_id)
        for k, v in fields.items():
            setattr(detail, k, v)
        _refresh_caches(detail, before, {**fields, "kind": entry.kind, "title": entry.title})
        session.add(detail)
    elif entry.kind == KIND_RACE:
        detail = session.get(RaceDetail, entry_id)
        if patch.get("result_activity_id") is not None:
            _check_result_link(session, entry_id, entry.date, patch["result_activity_id"])
        before = detail.inputs_hash or inputs_hash(
            {**detail.model_dump(), "kind": entry.kind, "title": title_before}
        )
        merged = detail.model_dump(exclude={"entry_id"})
        merged.update({k: v for k, v in patch.items() if k in _RACE_FIELDS})
        fields = _normalize_race(merged)
        for k, v in fields.items():
            setattr(detail, k, v)
        _refresh_caches(detail, before, {**fields, "kind": entry.kind, "title": entry.title})
        session.add(detail)
    session.flush()


def _delete(session: Session, entry_id: int) -> None:
    entry = session.get(CalendarEntry, entry_id)
    if entry is None:
        return
    # Explicit, so correctness does not depend on the foreign-key pragma.
    for model in (WorkoutDetail, RaceDetail):
        detail = session.get(model, entry_id)
        if detail is not None:
            session.delete(detail)
    session.delete(entry)
    session.flush()


def create_entry(session: Session, data: dict) -> dict:
    try:
        entry_id = _create(session, data)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return get_entry(session, entry_id)


def update_entry(session: Session, entry_id: int, patch: dict) -> dict:
    try:
        _update(session, entry_id, patch)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return get_entry(session, entry_id)


def delete_entry(session: Session, entry_id: int) -> None:
    _delete(session, entry_id)
    session.commit()


def apply_changes(session: Session, ops: list[dict], request_id: str | None = None) -> dict:
    """Apply create / update / delete operations atomically and idempotently.

    ``ops`` items: ``{"op": "create", ...entry fields}``, ``{"op": "update", "id": n, ...patch}``,
    ``{"op": "delete", "id": n}``. Any failure rolls the whole set back. A repeated
    ``request_id`` returns the first result without applying anything again.
    Returns ``{"created": [ids], "updated": [ids], "deleted": [ids]}``.
    """
    ops_hash = hashlib.sha1(json.dumps(ops, sort_keys=True, default=str).encode()).hexdigest()
    if request_id:
        prior = session.get(ChangeRequest, request_id)
        if prior is not None:
            stored = json.loads(prior.result_json)
            if stored.get("ops_hash") != ops_hash:
                raise EntryError("This request id was already used for different changes")
            return stored["result"]
    for op in ops:
        if op.get("op") in ("update", "delete") and op.get("id") is None:
            raise EntryError(f"A {op.get('op')} operation needs an entry id")
    result: dict = {"created": [], "updated": [], "deleted": []}
    try:
        # Deletes first, so a replace (delete + create on the same date) never trips the
        # one-scored-workout-per-sport rule.
        for op in (o for o in ops if o.get("op") == "delete"):
            _delete(session, int(op["id"]))
            result["deleted"].append(int(op["id"]))
        for op in ops:
            kind = op.get("op")
            if kind == "delete":
                continue
            body = {k: v for k, v in op.items() if k != "op"}
            if kind == "create":
                result["created"].append(_create(session, body))
            elif kind == "update":
                entry_id = int(body.pop("id"))
                _update(session, entry_id, body)
                result["updated"].append(entry_id)
            else:
                raise EntryError(f"Unknown operation: {kind!r}")
        if request_id:
            session.add(
                ChangeRequest(
                    request_id=request_id,
                    result_json=json.dumps({"ops_hash": ops_hash, "result": result}),
                )
            )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return result


# ── Cached analyses (compare-and-set on the inputs they were computed from) ───────


def _cache_row(session: Session, entry_id: int):
    return session.get(WorkoutDetail, entry_id) or session.get(RaceDetail, entry_id)


def _stale(session: Session, row, entry_id: int, expected_hash: str | None) -> bool:
    """True when the entry's prompt inputs changed since ``expected_hash`` was read. Rows from
    before migration 015 have no stored hash, so theirs is computed from the current entry."""
    if not expected_hash:
        return False
    current = row.inputs_hash or inputs_hash(get_entry(session, entry_id) or {})
    return current != expected_hash


def save_workout_nutrition(
    session: Session, entry_id: int, nutrition: dict, expected_hash: str | None = None
) -> bool:
    row = _cache_row(session, entry_id)
    if row is None or _stale(session, row, entry_id, expected_hash):
        return False
    row.nutrition_json = json.dumps(nutrition)
    session.add(row)
    session.commit()
    return True


def save_route_analysis(
    session: Session,
    entry_id: int,
    analysis: dict,
    analyzed_at: str,
    model: str,
    expected_hash: str | None = None,
) -> bool:
    row = _cache_row(session, entry_id)
    if row is None or _stale(session, row, entry_id, expected_hash):
        return False
    row.route_analysis_json = json.dumps(analysis)
    row.route_analyzed_at = analyzed_at
    row.route_analysis_model = model
    session.add(row)
    session.commit()
    return True
