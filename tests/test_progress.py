"""Tests for strides_ai.progress — the plan streak, weekly quests and personal records."""

import json
from datetime import date, timedelta

import pytest

from strides_ai.compliance import ComplianceStatus, DayCompliance
from strides_ai.progress import (
    build_progress,
    build_records,
    build_week_quests,
    compute_streak,
    streak_weeks,
    this_week,
)
from strides_ai.units import UnitSystem

TODAY = date(2026, 6, 3)  # Wednesday; this week's Monday is 2026-06-01
MON = date(2026, 6, 1)
START = date(2026, 3, 9)


def run_row(i: int, d: date, km: float | None = 10.0, **extra) -> dict:
    return {
        "id": i,
        "source": "strava",
        "sport_type": "Run",
        "date": d.isoformat(),
        "name": "Run",
        "moving_time_s": 3600,
        "distance_m": None if km is None else km * 1000,
        **extra,
    }


def steady_rows(km: float = 10.0, sport: str = "Run") -> list[dict]:
    rows, d, i = [], START, 1
    while d <= TODAY:
        rows.append(run_row(i, d, km, sport_type=sport))
        d += timedelta(days=2)
        i += 1
    return rows


def lift_row(i: int, d: date, sets: list[tuple[float, int]], volume: float | None = 1000.0):
    exercises = [
        {
            "title": "Bench Press",
            "primary_muscle_group": "chest",
            "sets": [{"type": "normal", "weight_kg": w, "reps": r} for w, r in sets],
        }
    ]
    return {
        "id": i,
        "source": "hevy",
        "sport_type": "WeightTraining",
        "date": d.isoformat(),
        "distance_m": None,
        "total_volume_kg": volume,
        "exercises_json": json.dumps(exercises),
    }


def plan_row(d: date, wtype: str = "Easy Run", km: float | None = 10.0) -> dict:
    return {"date": d.isoformat(), "workout_type": wtype, "distance_km": km, "intensity": "easy"}


def day(d: date, status: ComplianceStatus, wtype="Easy Run", matched=None) -> DayCompliance:
    return DayCompliance(d, wtype, status, 10.0, None, matched, "")


C, M, X, U, R = (
    ComplianceStatus.COMPLETED,
    ComplianceStatus.MODIFIED,
    ComplianceStatus.MISSED,
    ComplianceStatus.UPCOMING,
    ComplianceStatus.UNSCORED,
)


def week_days(monday: date, statuses: list[ComplianceStatus]) -> list[DayCompliance]:
    return [day(monday + timedelta(days=i), s) for i, s in enumerate(statuses)]


def records(rows, units=UnitSystem.METRIC, today=TODAY) -> dict:
    return {r.id: r for r in build_records(rows, units, today)}


# ── streak ──


@pytest.mark.parametrize(
    "statuses, weeks",
    [
        ([C, C, C, C], 1),  # no misses
        ([C, C, C, X], 1),  # one miss is allowed (3 of 4 would fail an 80% rule)
        ([C, M, X], 1),  # shortened still counts as done
        ([C, C, X, X], 0),  # two misses
        ([X], 0),  # a lone miss: nothing done
        ([C, X], 1),  # one done, one missed
        ([R, R], 0),  # nothing scored: paused, never a hit
    ],
)
def test_week_hit_rule(statuses, weeks):
    assert compute_streak(week_days(MON - timedelta(weeks=1), statuses), TODAY) == weeks


def test_streak_counts_consecutive_hit_weeks_and_stops_at_a_broken_week():
    w1, w2, w3, w4 = (MON - timedelta(weeks=n) for n in (1, 2, 3, 4))
    days = (
        week_days(w1, [C, C, M])
        + week_days(w2, [C, C])
        + week_days(w3, [C, X, X])
        + week_days(w4, [C, C])
    )
    assert streak_weeks(days, TODAY) == (2, 2)


def test_best_streak_outlives_the_current_one():
    hit = lambda n: week_days(MON - timedelta(weeks=n), [C, C])  # noqa: E731
    days = hit(1) + week_days(MON - timedelta(weeks=2), [X, X]) + hit(3) + hit(4) + hit(5)
    assert streak_weeks(days, TODAY) == (1, 3)


def test_paused_weeks_pause_and_the_current_week_is_ignored():
    w1, w3 = MON - timedelta(weeks=1), MON - timedelta(weeks=3)
    days = week_days(w1, [C, C]) + week_days(w3, [C, C]) + week_days(MON, [X, X])
    assert compute_streak(days, TODAY) == 2  # w2 has no plan: paused, not broken
    assert streak_weeks([], TODAY) == (0, 0)
    assert streak_weeks(week_days(MON, [C, C]), TODAY) == (0, 0)  # only the in-progress week


def test_rest_only_week_does_not_break_the_streak():
    w1, w2 = MON - timedelta(weeks=1), MON - timedelta(weeks=2)
    assert compute_streak(week_days(w1, [R] * 3) + week_days(w2, [C, C]), TODAY) == 1


def test_streak_does_not_survive_a_long_unplanned_gap():
    hit = lambda n: week_days(MON - timedelta(weeks=n), [C, C])  # noqa: E731
    assert streak_weeks(hit(3), TODAY) == (1, 1)  # two paused weeks since: survives
    assert streak_weeks(hit(4), TODAY) == (0, 1)  # three paused weeks: ended, best remembered
    # A gap inside history splits two runs instead of joining them.
    assert streak_weeks(hit(1) + hit(5) + hit(6), TODAY) == (1, 2)


def test_streak_has_no_lookback_limit():
    days = [d for n in range(1, 61) for d in week_days(MON - timedelta(weeks=n), [C])]
    assert streak_weeks(days, TODAY) == (60, 60)


@pytest.mark.parametrize(
    "statuses, status",
    [
        ([], "no_plan"),
        ([R, R], "no_plan"),
        ([C, U, U], "on_track"),
        ([U, U, U], "on_track"),
        ([C, X, U], "at_risk"),  # one more miss would lose it
        ([X, U, U], "at_risk"),
        ([C, U], "hit"),  # secured: even a miss on the last day still counts
        ([C, C, X], "hit"),
        ([C], "hit"),
        ([X, X, U], "lost"),
        ([X], "lost"),  # nothing done and nothing left
        ([U], "on_track"),  # nothing done yet, so one upcoming day is not secured
    ],
)
def test_this_week_status(statuses, status):
    result = this_week(week_days(MON, statuses))
    assert result.status == status
    assert (result.done, result.missed, result.upcoming) == (
        sum(s in (C, M) for s in statuses),
        statuses.count(X),
        statuses.count(U),
    )


# ── quests ──


def test_quests_map_status_order_and_activity():
    days = [
        day(MON + timedelta(days=2), U, "Tempo Run"),
        day(MON, C, "Long Run", matched=11),
        day(MON + timedelta(days=1), M, "Long Ride", matched=12),
        day(MON + timedelta(days=3), X, "Easy Run"),  # not a quest
    ]
    quests = build_week_quests(days, TODAY)
    assert [(q.kind, q.label, q.status, q.activity_id) for q in quests] == [
        ("long", "Long Run", "done", 11),
        ("long", "Long Ride", "partial", 12),
        ("quality", "Tempo Run", "pending", None),
    ]
    assert quests[0].id == "long:2026-06-01"


def test_rest_day_is_broken_only_by_cardio():
    future = day(TODAY + timedelta(days=1), R, "Rest")
    clean = day(MON, R, "Rest")
    lifted = day(MON + timedelta(days=1), R, "Rest", matched=7)  # a lift was logged
    ran = day(TODAY, R, "Rest", matched=8)
    quests = build_week_quests([clean, lifted, ran, future], TODAY, frozenset({TODAY}))
    assert [q.status for q in quests] == ["done", "done", "missed", "pending"]
    assert all(q.activity_id is None for q in quests)


def test_quests_capped_and_empty_week():
    many = [day(MON + timedelta(days=i), C, "Long Run") for i in range(6)]
    assert len(build_week_quests(many, TODAY)) == 4
    assert build_week_quests([], TODAY) == []


# ── records ──


def test_no_records_until_enough_activities_and_history():
    six = [run_row(i, TODAY - timedelta(days=28 + i)) for i in range(6)]
    assert "run.longest" in records(six)
    assert records(six[:5]) == {}  # 5 activities
    recent = [run_row(i, TODAY - timedelta(days=27 - i)) for i in range(6)]
    assert records(recent) == {}  # earliest is 27 days old
    assert "run.longest" in records(recent + [run_row(99, TODAY - timedelta(days=28))])


def test_eligibility_is_per_sport():
    rows = steady_rows() + [run_row(900, TODAY - timedelta(days=40), 80, sport_type="Ride")]
    recs = records(rows)
    assert "run.longest" in recs
    assert not any(r.startswith("ride.") for r in recs)


def test_longest_and_biggest_week_with_ties_previous_and_ids():
    rows = steady_rows() + [
        run_row(900, date(2026, 4, 12), km=30),
        run_row(901, date(2026, 5, 20), km=30),  # tie: the earlier one holds the record
        run_row(902, date(2026, 3, 20), km=25),
    ]
    longest = records(rows)["run.longest"]
    assert (longest.date, longest.activity_id, longest.value) == ("2026-04-12", 900, 30000.0)
    assert longest.formatted == "30.0 km" and longest.sport == "run"
    assert longest.is_new is False
    assert (longest.previous.date, longest.previous.formatted) == ("2026-03-20", "25.0 km")
    week = records(rows)["run.biggest_week"]
    assert week.date == "2026-04-06" and week.activity_id is None  # Monday of the 30 km week


def test_same_day_tie_goes_to_lowest_id_and_first_record_has_no_previous():
    rows = [run_row(i, TODAY - timedelta(days=40), 10) for i in (7, 3, 5)] + [
        run_row(i, TODAY - timedelta(days=30 - i), 5) for i in (10, 11, 12)
    ]
    longest = records(rows)["run.longest"]
    assert longest.activity_id == 3
    assert longest.previous is None


def test_new_flag_boundary_and_in_progress_week_excluded():
    fresh = steady_rows() + [run_row(900, TODAY - timedelta(days=13), km=50)]
    assert records(fresh)["run.longest"].is_new is True
    stale = steady_rows() + [run_row(900, TODAY - timedelta(days=14), km=50)]
    assert records(stale)["run.longest"].is_new is False
    this_week_run = steady_rows() + [run_row(900, TODAY - timedelta(days=1), km=50)]
    assert records(this_week_run)["run.biggest_week"].date != MON.isoformat()


def test_week_record_is_new_for_two_weeks_after_the_week_ends():
    # The big week ran Mon 18 - Sun 24 May; it ended 10 days before TODAY.
    rows = steady_rows() + [run_row(900, date(2026, 5, 19), km=60)]
    week = records(rows)["run.biggest_week"]
    assert week.date == "2026-05-18" and week.is_new is True
    assert records(rows, today=TODAY + timedelta(days=5))["run.biggest_week"].is_new is False


def test_null_and_zero_values_never_hold_a_record():
    rows = steady_rows() + [
        run_row(900, date(2026, 4, 12), km=0, elevation_gain_m=900),
        run_row(901, date(2026, 4, 13), km=None, elevation_gain_m=900),
        run_row(902, date(2026, 4, 14), km=12, elevation_gain_m=0),
        {**run_row(903, date(2026, 4, 15), km=99), "date": ""},
    ]
    recs = records(rows)
    assert recs["run.longest"].formatted == "12.0 km"
    assert "run.most_climb" not in recs  # no run has both distance and climbing


def test_climb_records_and_ride_only_week_climb():
    rows = steady_rows(sport="Ride") + [
        run_row(900, date(2026, 4, 14), km=40, sport_type="GravelRide", elevation_gain_m=1200)
    ]
    recs = records(rows)
    assert recs["ride.most_climb"].formatted == "1200 m"
    assert recs["ride.most_climb"].activity_id == 900
    assert recs["ride.biggest_week_climb"].date == "2026-04-13"
    assert recs["ride.longest"].label == "Longest ride"
    runs = steady_rows() + [run_row(900, date(2026, 4, 14), km=20, elevation_gain_m=300)]
    assert "run.biggest_week_climb" not in records(runs)


def test_imperial_formatting():
    rows = steady_rows() + [run_row(900, date(2026, 4, 12), km=16.09344, elevation_gain_m=304.8)]
    recs = records(rows, UnitSystem.IMPERIAL)
    assert recs["run.longest"].formatted == "10.0 mi"
    assert recs["run.longest"].value == pytest.approx(16093.44)  # value stays SI
    assert recs["run.most_climb"].formatted == "1000 ft"


def test_lifting_records():
    rows = [lift_row(i, TODAY - timedelta(days=40 - i), [(100, 5)]) for i in range(1, 6)] + [
        lift_row(20, TODAY - timedelta(days=5), [(110, 5), (60, 20)], volume=2400),
        lift_row(21, TODAY - timedelta(days=3), [(110, 5)]),  # ties the best: not a new record
    ]
    recs = records(rows)
    bench = recs["lift.e1rm:Bench Press"]
    assert (bench.sport, bench.activity_id, bench.is_new) == ("lift", 20, True)
    assert bench.value == pytest.approx(128.3)  # Epley 110 x 5; the 20-rep set is ignored
    assert bench.formatted == "128.3 kg"
    assert bench.previous.value == pytest.approx(116.7)
    assert recs["lift.session_volume"].activity_id == 20
    assert records(rows, UnitSystem.IMPERIAL)["lift.e1rm:Bench Press"].formatted == "282.9 lb"
    assert records(rows[:5]) == {}


# ── end to end ──


def test_build_progress_end_to_end():
    plan = [
        plan_row(MON - timedelta(days=7), "Easy Run"),  # last Monday, done
        plan_row(MON, "Long Run", km=20),  # this Monday, done
        plan_row(MON + timedelta(days=1), "Rest", km=None),  # Tuesday: a lift only
        plan_row(MON + timedelta(days=4), "Tempo Run"),  # Friday, upcoming
    ]
    acts = [
        run_row(1, MON - timedelta(days=7)),
        run_row(2, MON, km=20),
        lift_row(3, MON + timedelta(days=1), [(100, 5)]),
    ]
    result = build_progress(plan, acts, TODAY, UnitSystem.IMPERIAL)
    assert (result.as_of, result.week_start, result.unit_system) == (
        "2026-06-03",
        "2026-06-01",
        "imperial",
    )
    assert [(q.kind, q.status, q.activity_id) for q in result.quests] == [
        ("long", "done", 2),
        ("quality", "pending", None),
        ("rest", "done", None),
    ]
    assert result.streak.model_dump() == {
        "weeks": 1,
        "best_weeks": 1,
        "max_misses": 1,
        "this_week": {"done": 1, "missed": 0, "upcoming": 1, "status": "hit"},
    }
    assert result.records == []


def test_progress_scores_every_sport_whatever_the_mode():
    # A planned ride completed by a ride counts; nothing here is mode-filtered.
    plan = [plan_row(MON - timedelta(days=6), "Long Ride", km=50)]
    acts = [run_row(1, MON - timedelta(days=6), km=50, sport_type="Ride")]
    assert build_progress(plan, acts, TODAY, UnitSystem.METRIC).streak.weeks == 1
    assert build_progress(plan, [], TODAY, UnitSystem.METRIC).streak.weeks == 0
