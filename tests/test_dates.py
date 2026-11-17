"""Weekday labels and days-away text that every prompt shares."""

import os
import time
from datetime import date, datetime

import pytest

from strides_ai.coach import (
    _calendar_prefs_section,
    _datetime_section,
    _upcoming_workouts,
    build_initial_history,
)
from strides_ai.dates import days_away, fmt_day, local_stamp, parse_day, week_bounds


def test_fmt_day_adds_the_weekday():
    assert fmt_day("2026-11-14") == "Sat 2026-11-14"
    assert fmt_day(date(2026, 11, 16)) == "Mon 2026-11-16"
    assert fmt_day("2026-11-14T08:30:00") == "Sat 2026-11-14"  # a timestamp keeps its date


def test_fmt_day_never_raises():
    assert fmt_day(None) == "?" and fmt_day("") == "?"
    assert fmt_day("not a date") == "not a date"


def test_days_away():
    today = date(2026, 11, 16)
    assert days_away("2026-11-16", today) == "today"
    assert days_away("2026-11-17", today) == "tomorrow"
    assert days_away("2026-12-12", today) == "in 26 days"
    assert days_away("2026-11-15", today) == "yesterday"
    assert days_away("2026-11-11", today) == "5 days ago"
    assert days_away("garbage", today) == ""


def test_week_bounds_are_monday_to_sunday():
    assert week_bounds(date(2026, 11, 18)) == (date(2026, 11, 16), date(2026, 11, 22))
    assert week_bounds(date(2026, 11, 22))[0] == date(2026, 11, 16)  # Sunday belongs to the week
    assert week_bounds(date(2026, 11, 16))[0] == date(2026, 11, 16)


def test_parse_day():
    assert parse_day(datetime(2026, 11, 14, 23, 59)) == date(2026, 11, 14)
    assert parse_day("x") is None


@pytest.fixture
def pacific(monkeypatch):
    monkeypatch.setenv("TZ", "America/Los_Angeles")
    time.tzset()
    yield
    monkeypatch.delenv("TZ", raising=False)
    time.tzset()


def test_local_stamp_converts_stored_utc_to_the_local_day(pacific):
    # 04:03 UTC on Nov 16 is still Sunday evening, Nov 15, in Seattle.
    assert local_stamp("2026-11-16 04:03:00") == "Sun 2026-11-15 20:03"
    assert local_stamp(None) is None and local_stamp("garbage") is None


def test_history_dates_the_athletes_messages_only(pacific):
    history = build_initial_history(
        [],
        [
            {
                "role": "user",
                "content": "Should I ride tomorrow?",
                "created_at": "2026-11-15 02:28:31",
            },
            {"role": "assistant", "content": "Yes, easy.", "created_at": "2026-11-15 02:28:41"},
            {"role": "user", "content": "no timestamp stored", "created_at": None},
        ],
    )
    assert history[0]["content"] == "[sent Sat 2026-11-14 18:28] Should I ride tomorrow?"
    assert history[1]["content"] == "Yes, easy."  # never teach the model to prefix its own replies
    assert history[2]["content"] == "no timestamp stored"


def test_datetime_section_gives_iso_date_week_and_the_resolution_rule():
    text = _datetime_section()
    today = datetime.now().astimezone().date()
    monday, sunday = week_bounds(today)
    assert today.isoformat() in text
    assert f"{fmt_day(monday)} to {fmt_day(sunday)}" in text
    assert "YYYY-MM-DD" in text


def test_calendar_constraints_show_weekday_and_days_to_race(mocker):
    today = datetime.now().date()
    race = date.fromordinal(today.toordinal() + 26)
    mocker.patch(
        "strides_ai.coach.db.get_calendar_prefs",
        return_value={
            "races": [{"date": race.isoformat(), "name": "Evergreen Grinder"}],
            "blocked_days": [race.isoformat()],
        },
    )
    text = _calendar_prefs_section()
    assert f"- {fmt_day(race)}, in 26 days: Evergreen Grinder" in text
    assert f"  - {fmt_day(race)}\n" in text + "\n"


def test_upcoming_table_has_weekday_dates(mocker):
    day = datetime.now().date()
    mocker.patch(
        "strides_ai.coach.db.get_upcoming_planned_workouts",
        return_value=[
            {
                "id": 7,
                "date": day.isoformat(),
                "workout_type": "Easy Run",
                "kind": "workout",
                "distance_km": None,
                "elevation_m": None,
                "duration_min": 30,
                "intensity": "easy",
            }
        ],
    )
    near, _ = _upcoming_workouts()
    assert fmt_day(day) in near and "Date           |" in near
