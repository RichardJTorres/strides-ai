"""Unit tests for strides_ai.db — calendar features."""

import json
from datetime import date, timedelta

import pytest

from strides_ai import db

# ── get_calendar_prefs / save_calendar_prefs ──────────────────────────────────


def test_get_calendar_prefs_default(tmp_db):
    prefs = db.get_calendar_prefs()
    assert prefs == {"blocked_days": [], "races": []}


def test_save_and_get_calendar_prefs_blocked_days(tmp_db):
    db.save_calendar_prefs(["2025-07-04", "2025-12-25"], [])
    prefs = db.get_calendar_prefs()
    assert "2025-07-04" in prefs["blocked_days"]
    assert "2025-12-25" in prefs["blocked_days"]
    assert prefs["races"] == []


def test_save_and_get_calendar_prefs_races(tmp_db):
    races = [{"date": "2025-10-12", "name": "Chicago Marathon", "target_time": "3:30:00"}]
    db.save_calendar_prefs([], races)
    prefs = db.get_calendar_prefs()
    assert len(prefs["races"]) == 1
    assert prefs["races"][0]["name"] == "Chicago Marathon"
    assert prefs["races"][0]["target_time"] == "3:30:00"


def test_save_calendar_prefs_overwrites(tmp_db):
    db.save_calendar_prefs(["2025-01-01"], [])
    db.save_calendar_prefs(["2025-06-01"], [])
    prefs = db.get_calendar_prefs()
    assert prefs["blocked_days"] == ["2025-06-01"]


# ── save_planned_workout / get_training_plan ──────────────────────────────────


def test_save_and_get_planned_workout(tmp_db):
    db.save_planned_workout("2025-08-01", "Long Run", "Easy long run", 20.0, 300.0, 120, "easy")
    plan = db.get_training_plan()
    assert len(plan) == 1
    w = plan[0]
    assert w["date"] == "2025-08-01"
    assert w["workout_type"] == "Long Run"
    assert w["description"] == "Easy long run"
    assert w["distance_km"] == 20.0
    assert w["elevation_m"] == 300.0
    assert w["duration_min"] == 120
    assert w["intensity"] == "easy"


def test_save_planned_workout_optional_fields_can_be_none(tmp_db):
    db.save_planned_workout("2025-08-01", "Rest", None, None, None, None, "rest")
    plan = db.get_training_plan()
    assert len(plan) == 1
    w = plan[0]
    assert w["distance_km"] is None
    assert w["elevation_m"] is None
    assert w["duration_min"] is None
    assert w["description"] is None


def test_save_planned_workout_upserts_by_date(tmp_db):
    db.save_planned_workout("2025-08-01", "Easy Run", None, 8.0, None, 50, "easy")
    db.save_planned_workout("2025-08-01", "Tempo Run", None, 10.0, None, 60, "hard")
    plan = db.get_training_plan()
    assert len(plan) == 1
    assert plan[0]["workout_type"] == "Tempo Run"
    assert plan[0]["distance_km"] == 10.0


def test_save_planned_workout_upsert_clears_nutrition(tmp_db):
    """Re-saving a workout clears any cached nutrition advice."""
    db.save_planned_workout("2025-08-01", "Long Run", None, 20.0, None, 120, "easy")
    db.save_workout_nutrition("2025-08-01", {"calories_pre": 300})
    assert db.get_training_plan()[0]["nutrition_json"] is not None

    db.save_planned_workout("2025-08-01", "Long Run", None, 21.0, None, 125, "easy")
    assert db.get_training_plan()[0]["nutrition_json"] is None


def test_get_training_plan_ordered_by_date(tmp_db):
    db.save_planned_workout("2025-08-15", "Long Run", None, 20.0, None, 120, "easy")
    db.save_planned_workout("2025-08-01", "Easy Run", None, 8.0, None, 50, "easy")
    db.save_planned_workout("2025-08-10", "Tempo Run", None, 10.0, None, 60, "hard")
    plan = db.get_training_plan()
    dates = [w["date"] for w in plan]
    assert dates == sorted(dates)


def test_get_training_plan_date_range(tmp_db):
    db.save_planned_workout("2025-08-01", "Easy Run", None, 8.0, None, 50, "easy")
    db.save_planned_workout("2025-08-15", "Long Run", None, 20.0, None, 120, "easy")
    db.save_planned_workout("2025-09-01", "Race", None, 42.2, None, 210, "hard")
    plan = db.get_training_plan("2025-08-01", "2025-08-31")
    assert len(plan) == 2
    assert all(w["date"].startswith("2025-08") for w in plan)


def test_get_training_plan_empty(tmp_db):
    assert db.get_training_plan() == []


# ── delete_planned_workout ────────────────────────────────────────────────────


def test_delete_planned_workout(tmp_db):
    db.save_planned_workout("2025-08-01", "Easy Run", None, 8.0, None, 50, "easy")
    db.delete_planned_workout("2025-08-01")
    assert db.get_training_plan() == []


def test_delete_planned_workout_missing_is_noop(tmp_db):
    db.delete_planned_workout("2025-08-01")  # must not raise


def test_delete_planned_workout_only_removes_target(tmp_db):
    db.save_planned_workout("2025-08-01", "Easy Run", None, 8.0, None, 50, "easy")
    db.save_planned_workout("2025-08-02", "Long Run", None, 20.0, None, 120, "easy")
    db.delete_planned_workout("2025-08-01")
    plan = db.get_training_plan()
    assert len(plan) == 1
    assert plan[0]["date"] == "2025-08-02"


# ── save_workout_nutrition ────────────────────────────────────────────────────


def test_save_workout_nutrition(tmp_db):
    db.save_planned_workout("2025-08-01", "Long Run", None, 20.0, None, 120, "easy")
    nutrition = {
        "calories_pre": 400,
        "calories_during": 200,
        "calories_post": 500,
        "hydration_pre_ml": 500,
        "hydration_during_ml": 750,
        "hydration_post_ml": 500,
        "notes": "Fuel well before this long run.",
    }
    db.save_workout_nutrition("2025-08-01", nutrition)
    saved = json.loads(db.get_training_plan()[0]["nutrition_json"])
    assert saved["calories_pre"] == 400
    assert saved["hydration_during_ml"] == 750
    assert saved["notes"] == "Fuel well before this long run."


# ── get_upcoming_planned_workouts ─────────────────────────────────────────────


def test_get_upcoming_planned_workouts_excludes_past(tmp_db):
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    db.save_planned_workout(yesterday, "Easy Run", None, 8.0, None, 50, "easy")
    db.save_planned_workout(tomorrow, "Long Run", None, 20.0, None, 120, "easy")
    upcoming = db.get_upcoming_planned_workouts()
    dates = [w["date"] for w in upcoming]
    assert tomorrow in dates
    assert yesterday not in dates


def test_get_upcoming_planned_workouts_includes_today(tmp_db):
    today = date.today().isoformat()
    db.save_planned_workout(today, "Easy Run", None, 8.0, None, 50, "easy")
    upcoming = db.get_upcoming_planned_workouts()
    assert any(w["date"] == today for w in upcoming)


def test_get_upcoming_planned_workouts_respects_window(tmp_db):
    near = (date.today() + timedelta(days=5)).isoformat()
    far = (date.today() + timedelta(days=20)).isoformat()
    db.save_planned_workout(near, "Easy Run", None, 8.0, None, 50, "easy")
    db.save_planned_workout(far, "Long Run", None, 20.0, None, 120, "easy")
    upcoming = db.get_upcoming_planned_workouts(days=14)
    dates = [w["date"] for w in upcoming]
    assert near in dates
    assert far not in dates


def test_get_upcoming_planned_workouts_empty(tmp_db):
    assert db.get_upcoming_planned_workouts() == []
