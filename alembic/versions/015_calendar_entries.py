"""Calendar entries: one row per thing on the calendar, with workout/race detail tables.

Replaces ``training_plan`` (one row per date). The old table is *renamed*, not dropped, and the
old ``calendar_prefs.races`` JSON is copied to ``races_legacy``; a later migration drops both
once the cutover has been verified. When there is anything to lose, a SQLite backup is written
next to the database first and the migration aborts if it cannot be written.

Revision id is 015 (not 014) so it can never collide with the abandoned races-from-plan branch.
"""

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "015"
down_revision = "013"
branch_labels = None
depends_on = None

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_GOAL_RE = re.compile(r"^(?:(\d{1,2}):)?(\d{1,2}):(\d{2})$")
_RACE_SPORT = {"Running Race": "run", "Cycling Race": "ride", "Race": "other"}


def parse_goal_time(text) -> int | None:
    """Strict ``H:MM:SS`` / ``MM:SS`` -> seconds; anything else (``sub 4``, ``3h30``) is None."""
    m = _GOAL_RE.match(str(text or "").strip())
    if not m:
        return None
    h, mnt, sec = int(m.group(1) or 0), int(m.group(2)), int(m.group(3))
    if sec > 59 or (m.group(1) is not None and mnt > 59):
        return None
    return h * 3600 + mnt * 60 + sec


def _race_name(description) -> tuple[str, str | None]:
    """(short name, full text as notes). Old race rows kept a whole paragraph in `description`;
    the name is its first clause, and the full text is kept as the entry's notes."""
    text = (description or "").strip()
    if not text:
        return "Race", None
    name = re.split(r"\s+[(—–-]\s*|\.\s|\n|:\s", text, maxsplit=1)[0].strip() or text
    if len(name) > 60:
        name = name[:57].rstrip() + "…"
    return name, (text if name != text else None)


def _backup(bind) -> None:
    db_path = bind.engine.url.database
    if not db_path or db_path == ":memory:":
        return
    backups = Path(db_path).parent / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    target = backups / f"activities-pre-015-{datetime.now():%Y%m%d-%H%M%S}.db"
    src = sqlite3.connect(db_path)
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    if not target.exists() or target.stat().st_size == 0:
        raise RuntimeError(f"Pre-migration backup failed: {target}")


def _load_races(raw) -> list[dict]:
    try:
        data = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if isinstance(item, dict) and _DATE_RE.match(str(item.get("date") or "")):
            out.append(item)
    return out


def upgrade() -> None:
    bind = op.get_bind()
    plan_rows = [
        dict(r._mapping) for r in bind.execute(sa.text("SELECT * FROM training_plan ORDER BY date"))
    ]
    prefs = bind.execute(sa.text("SELECT races FROM calendar_prefs WHERE id = 1")).first()
    raw_races = prefs[0] if prefs else "[]"
    if plan_rows or _load_races(raw_races) or (raw_races or "[]") not in ("[]", ""):
        _backup(bind)

    op.create_table(
        "calendar_entry",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("date", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.Text(), nullable=True, server_default=sa.text("datetime('now')")
        ),
    )
    op.create_index("ix_calendar_entry_date_id", "calendar_entry", ["date", "id"])
    op.create_table(
        "workout_detail",
        sa.Column(
            "entry_id",
            sa.Integer(),
            sa.ForeignKey("calendar_entry.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("workout_type", sa.Text(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=True),
        sa.Column("distance_km", sa.Float(), nullable=True),
        sa.Column("elevation_m", sa.Float(), nullable=True),
        sa.Column("duration_min", sa.Integer(), nullable=True),
        sa.Column("intensity", sa.Text(), nullable=True),
        sa.Column("route_url", sa.Text(), nullable=True),
        sa.Column("route_analysis_json", sa.Text(), nullable=True),
        sa.Column("route_analyzed_at", sa.Text(), nullable=True),
        sa.Column("route_analysis_model", sa.Text(), nullable=True),
        sa.Column("structure_json", sa.Text(), nullable=True),
        sa.Column("nutrition_json", sa.Text(), nullable=True),
        sa.Column("inputs_hash", sa.Text(), nullable=True),
    )
    op.create_table(
        "race_detail",
        sa.Column(
            "entry_id",
            sa.Integer(),
            sa.ForeignKey("calendar_entry.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("sport", sa.Text(), nullable=False, server_default="other"),
        sa.Column("distance_km", sa.Float(), nullable=True),
        sa.Column("elevation_m", sa.Float(), nullable=True),
        sa.Column("goal_time_s", sa.Integer(), nullable=True),
        sa.Column("goal_text", sa.Text(), nullable=True),
        sa.Column("priority", sa.Text(), nullable=True),
        sa.Column("route_url", sa.Text(), nullable=True),
        sa.Column("result_activity_id", sa.Integer(), nullable=True),
        sa.Column("result_time_s", sa.Integer(), nullable=True),
        sa.Column("route_analysis_json", sa.Text(), nullable=True),
        sa.Column("route_analyzed_at", sa.Text(), nullable=True),
        sa.Column("route_analysis_model", sa.Text(), nullable=True),
        sa.Column("nutrition_json", sa.Text(), nullable=True),
        sa.Column("inputs_hash", sa.Text(), nullable=True),
    )

    op.create_table(
        "change_request",
        sa.Column("request_id", sa.Text(), primary_key=True),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.Text(), nullable=True, server_default=sa.text("datetime('now')")
        ),
    )

    def new_entry(date, kind, title, notes, created_at) -> int:
        res = bind.execute(
            sa.text(
                "INSERT INTO calendar_entry (date, kind, title, notes, created_at) "
                "VALUES (:d, :k, :t, :n, COALESCE(:c, datetime('now')))"
            ),
            {"d": date, "k": kind, "t": title, "n": notes, "c": created_at},
        )
        return res.lastrowid

    races_by_date: dict[str, list[tuple[int, str]]] = {}
    for r in plan_rows:
        wtype, intensity, desc = r.get("workout_type"), r.get("intensity"), r.get("description")
        if wtype == "Rest" or intensity == "rest":
            new_entry(r["date"], "rest", None, desc, r.get("created_at"))
        elif wtype in _RACE_SPORT:
            name, full = _race_name(desc)
            eid = new_entry(r["date"], "race", name, full, r.get("created_at"))
            bind.execute(
                sa.text(
                    "INSERT INTO race_detail (entry_id, sport, distance_km, elevation_m, route_url, "
                    "route_analysis_json, route_analyzed_at, route_analysis_model, nutrition_json) "
                    "VALUES (:e, :s, :d, :el, :u, :rj, :ra, :rm, :n)"
                ),
                {
                    "e": eid,
                    "s": _RACE_SPORT[wtype],
                    "d": r.get("distance_km"),
                    "el": r.get("elevation_m"),
                    "u": r.get("route_url"),
                    "rj": r.get("route_analysis_json"),
                    "ra": r.get("route_analyzed_at"),
                    "rm": r.get("route_analysis_model"),
                    "n": r.get("nutrition_json"),
                },
            )
            races_by_date.setdefault(r["date"], []).append((eid, name.lower()))
        else:
            eid = new_entry(r["date"], "workout", None, None, r.get("created_at"))
            bind.execute(
                sa.text(
                    "INSERT INTO workout_detail (entry_id, workout_type, objective, distance_km, "
                    "elevation_m, duration_min, intensity, route_url, route_analysis_json, "
                    "route_analyzed_at, route_analysis_model, structure_json, nutrition_json) "
                    "VALUES (:e, :t, :o, :d, :el, :du, :i, :u, :rj, :ra, :rm, :s, :n)"
                ),
                {
                    "e": eid,
                    "t": wtype or "Workout",
                    "o": desc,
                    "d": r.get("distance_km"),
                    "el": r.get("elevation_m"),
                    "du": r.get("duration_min"),
                    "i": intensity,
                    "u": r.get("route_url"),
                    "rj": r.get("route_analysis_json"),
                    "ra": r.get("route_analyzed_at"),
                    "rm": r.get("route_analysis_model"),
                    "s": r.get("structure_json"),
                    "n": r.get("nutrition_json"),
                },
            )

    for item in _load_races(raw_races):
        date = item["date"]
        name = str(item.get("name") or "").strip()
        target = str(item.get("target_time") or "").strip()
        goal_s = parse_goal_time(target)
        goal_text = target if target and goal_s is None else None
        match = None
        for eid, title in races_by_date.get(date, []):
            # Same race from both sources: same name, or the plan row only had a generic title.
            if title == name.lower() or title in ("", "race"):
                match = eid
                break
        if match is not None:
            bind.execute(
                sa.text(
                    "UPDATE race_detail SET goal_time_s = COALESCE(goal_time_s, :g), "
                    "goal_text = COALESCE(goal_text, :t) WHERE entry_id = :e"
                ),
                {"g": goal_s, "t": goal_text, "e": match},
            )
            if name:
                bind.execute(
                    sa.text(
                        "UPDATE calendar_entry SET title = :n WHERE id = :e AND (title IS NULL OR lower(title) = 'race')"
                    ),
                    {"n": name, "e": match},
                )
            continue
        eid = new_entry(date, "race", name or "Race", None, None)
        bind.execute(
            sa.text(
                "INSERT INTO race_detail (entry_id, sport, goal_time_s, goal_text) VALUES (:e, 'other', :g, :t)"
            ),
            {"e": eid, "g": goal_s, "t": goal_text},
        )
        races_by_date.setdefault(date, []).append((eid, name.lower()))

    op.rename_table("training_plan", "training_plan_legacy")
    with op.batch_alter_table("calendar_prefs") as batch:
        batch.add_column(sa.Column("races_legacy", sa.Text(), nullable=True))
    bind.execute(sa.text("UPDATE calendar_prefs SET races_legacy = races, races = '[]'"))


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_table("change_request")
    op.drop_table("race_detail")
    op.drop_table("workout_detail")
    op.drop_index("ix_calendar_entry_date_id", table_name="calendar_entry")
    op.drop_table("calendar_entry")
    op.rename_table("training_plan_legacy", "training_plan")
    bind.execute(sa.text("UPDATE calendar_prefs SET races = COALESCE(races_legacy, '[]')"))
    with op.batch_alter_table("calendar_prefs") as batch:
        batch.drop_column("races_legacy")
