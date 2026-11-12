"""Legacy ``calendar_prefs.races`` -> planned race workouts (used by alembic revision 014)."""

import json
import logging

import sqlalchemy as sa

logger = logging.getLogger(__name__)


def migrate_races(conn) -> None:
    """Each stored race becomes a generic ``Race`` workout on its date, unless that date already
    has a workout; then the list is emptied. Idempotent, and a no-op without a prefs row."""
    row = conn.execute(sa.text("SELECT races FROM calendar_prefs WHERE id = 1")).fetchone()
    if row is None:
        return
    try:
        races = json.loads(row[0] or "[]")
    except ValueError:
        races = []
    for race in races if isinstance(races, list) else []:
        day = race.get("date") if isinstance(race, dict) else None
        if not day:
            continue
        name = str(race.get("name") or "").strip() or "Race"
        if race.get("target_time"):
            name += f" (target {race['target_time']})"
        # INSERT OR IGNORE: never overwrite a workout already planned for that date.
        result = conn.execute(
            sa.text(
                "INSERT OR IGNORE INTO training_plan (date, workout_type, description) "
                "VALUES (:date, 'Race', :name)"
            ),
            {"date": day, "name": name},
        )
        if result.rowcount == 0:
            logger.warning("Race %r on %s not migrated: that date already has a workout", name, day)
    conn.execute(sa.text("UPDATE calendar_prefs SET races = '[]' WHERE id = 1"))
