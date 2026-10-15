"""Unit tests for strides_ai.compliance — plan-vs-actual scoring rules and edge cases."""

from datetime import date

from strides_ai.compliance import (
    ComplianceActivity,
    ComplianceStatus,
    DISTANCE_SHORTFALL_TOLERANCE,
    PlannedWorkout,
    SportGroup,
    classify_workout_type,
    compliance_activities_from_rows,
    compute_day_compliance,
    compute_range_compliance,
    planned_workouts_from_rows,
    summarize_compliance,
)

TODAY = date(2026, 6, 15)
PAST = date(2026, 6, 10)  # before TODAY
FUTURE = date(2026, 6, 20)  # after TODAY


def plan(workout_type: str, d: date = PAST, distance_km: float | None = 10.0) -> PlannedWorkout:
    return PlannedWorkout(date=d, workout_type=workout_type, distance_km=distance_km)


def activity(
    *,
    id: int = 1,
    d: date = PAST,
    sport_type: str | None = "Run",
    distance_m: float | None = 10_000.0,
) -> ComplianceActivity:
    return ComplianceActivity(id=id, date=d, sport_type=sport_type, distance_m=distance_m)


# ── classify_workout_type ───────────────────────────────────────────────────────


def test_classify_workout_type_run():
    assert classify_workout_type("Easy Run") is SportGroup.RUN


def test_classify_workout_type_ride():
    assert classify_workout_type("Long Ride") is SportGroup.RIDE


def test_classify_workout_type_unscored():
    assert classify_workout_type("Rest") is SportGroup.UNSCORED
    assert classify_workout_type("Yoga") is SportGroup.UNSCORED


def test_classify_workout_type_ambiguous_known():
    for t in ("Intervals", "Race", "Cross-Training"):
        assert classify_workout_type(t) is SportGroup.AMBIGUOUS


def test_classify_workout_type_unrecognized_future_type_is_ambiguous_not_crash():
    assert classify_workout_type("Swim") is SportGroup.AMBIGUOUS


def test_classify_workout_type_none_handled():
    assert classify_workout_type(None) is SportGroup.AMBIGUOUS


# ── distance tolerance boundary ─────────────────────────────────────────────────


def test_tolerance_boundary_exactly_at_threshold_is_completed():
    p = plan("Easy Run", distance_km=10.0)
    act = activity(distance_m=10_000.0 * DISTANCE_SHORTFALL_TOLERANCE)  # exactly 8.0km
    result = compute_day_compliance(p, [act], TODAY)
    assert result.status is ComplianceStatus.COMPLETED


def test_tolerance_just_below_threshold_is_modified():
    p = plan("Easy Run", distance_km=10.0)
    act = activity(distance_m=10_000.0 * DISTANCE_SHORTFALL_TOLERANCE - 1.0)  # just under 8.0km
    result = compute_day_compliance(p, [act], TODAY)
    assert result.status is ComplianceStatus.MODIFIED


def test_overshooting_distance_never_penalized():
    p = plan("Easy Run", distance_km=10.0)
    act = activity(distance_m=25_000.0)
    result = compute_day_compliance(p, [act], TODAY)
    assert result.status is ComplianceStatus.COMPLETED


# ── sport filtering ──────────────────────────────────────────────────────────────


def test_run_type_ignores_non_run_activity_same_day():
    p = plan("Easy Run", distance_km=5.0)
    ride = activity(sport_type="Ride", distance_m=20_000.0)
    result = compute_day_compliance(p, [ride], TODAY)
    assert result.status is ComplianceStatus.MISSED


def test_run_distance_summed_across_two_same_day_activities():
    p = plan("Easy Run", distance_km=10.0)
    a1 = activity(id=1, distance_m=5_000.0)
    a2 = activity(id=2, distance_m=5_000.0)
    result = compute_day_compliance(p, [a1, a2], TODAY)
    assert result.status is ComplianceStatus.COMPLETED
    assert result.actual_distance_km == 10.0


def test_matched_activity_id_tie_break_largest_distance_wins():
    p = plan("Easy Run", distance_km=1.0)
    small = activity(id=1, distance_m=1_000.0)
    big = activity(id=2, distance_m=5_000.0)
    result = compute_day_compliance(p, [small, big], TODAY)
    assert result.matched_activity_id == 2


def test_matched_activity_id_tie_break_deterministic_on_equal_distance():
    p = plan("Easy Run", distance_km=1.0)
    a2 = activity(id=2, distance_m=5_000.0)
    a1 = activity(id=1, distance_m=5_000.0)
    result = compute_day_compliance(p, [a2, a1], TODAY)
    assert result.matched_activity_id == 1


# ── ambiguous group ──────────────────────────────────────────────────────────────


def test_ambiguous_type_matched_by_any_sport_present():
    p = plan("Cross-Training", distance_km=None)
    lift = activity(sport_type="WeightTraining", distance_m=None)
    result = compute_day_compliance(p, [lift], TODAY)
    assert result.status is ComplianceStatus.COMPLETED


def test_ambiguous_type_never_modified_even_with_tiny_distance():
    p = plan("Intervals", distance_km=10.0)
    tiny = activity(sport_type="Run", distance_m=100.0)
    result = compute_day_compliance(p, [tiny], TODAY)
    assert result.status is ComplianceStatus.COMPLETED


# ── unscored ──────────────────────────────────────────────────────────────────────


def test_unscored_with_no_activity():
    p = plan("Rest", distance_km=None)
    result = compute_day_compliance(p, [], TODAY)
    assert result.status is ComplianceStatus.UNSCORED
    assert result.matched_activity_id is None


def test_unscored_with_activity_present_still_unscored_but_records_match():
    p = plan("Rest", distance_km=None)
    act = activity(distance_m=5_000.0)
    result = compute_day_compliance(p, [act], TODAY)
    assert result.status is ComplianceStatus.UNSCORED
    assert result.matched_activity_id == act.id
    assert "logged" in result.note.lower()


# ── date-boundary precedence ───────────────────────────────────────────────────────


def test_upcoming_exact_today_boundary_no_activity():
    p = plan("Easy Run", d=TODAY)
    result = compute_day_compliance(p, [], TODAY)
    assert result.status is ComplianceStatus.UPCOMING


def test_missed_one_day_before_today_no_activity():
    p = plan("Easy Run", d=PAST)
    result = compute_day_compliance(p, [], TODAY)
    assert result.status is ComplianceStatus.MISSED


def test_match_on_today_overrides_upcoming():
    p = plan("Easy Run", d=TODAY, distance_km=5.0)
    act = activity(d=TODAY, distance_m=5_000.0)
    result = compute_day_compliance(p, [act], TODAY)
    assert result.status is ComplianceStatus.COMPLETED


def test_match_in_future_overrides_upcoming():
    """An activity misdated into the future (shouldn't normally happen) still resolves via the
    match-first precedence rule rather than being masked by the date check."""
    p = plan("Easy Run", d=FUTURE, distance_km=5.0)
    act = activity(d=FUTURE, distance_m=5_000.0)
    result = compute_day_compliance(p, [act], TODAY)
    assert result.status is ComplianceStatus.COMPLETED


# ── duration-only plans / missing distance data ─────────────────────────────────────


def test_duration_only_run_with_activity_present_is_completed_regardless_of_distance():
    p = plan("Easy Run", distance_km=None)
    act = activity(distance_m=500.0)  # trivially short, but no target to fall short of
    result = compute_day_compliance(p, [act], TODAY)
    assert result.status is ComplianceStatus.COMPLETED


def test_duration_only_run_no_activity_past_date_is_missed():
    p = plan("Easy Run", distance_km=None)
    result = compute_day_compliance(p, [], TODAY)
    assert result.status is ComplianceStatus.MISSED


def test_matched_run_with_no_recorded_distance_and_real_target_is_modified():
    p = plan("Easy Run", distance_km=10.0)
    act = activity(distance_m=None)
    result = compute_day_compliance(p, [act], TODAY)
    assert result.status is ComplianceStatus.MODIFIED
    assert result.actual_distance_km is None


def test_matched_run_with_no_recorded_distance_and_no_target_is_completed():
    p = plan("Easy Run", distance_km=None)
    act = activity(distance_m=None)
    result = compute_day_compliance(p, [act], TODAY)
    assert result.status is ComplianceStatus.COMPLETED
    assert result.actual_distance_km is None


# ── summarize_compliance ────────────────────────────────────────────────────────────


def test_summarize_compliance_percentages():
    days = [
        compute_day_compliance(
            plan("Easy Run", d=PAST, distance_km=5.0), [activity(distance_m=5_000.0)], TODAY
        ),
        compute_day_compliance(
            plan("Easy Run", d=PAST, distance_km=5.0), [activity(distance_m=1_000.0)], TODAY
        ),
        compute_day_compliance(plan("Easy Run", d=PAST, distance_km=5.0), [], TODAY),
    ]
    summary = summarize_compliance(days)
    assert summary.completed == 1
    assert summary.modified == 1
    assert summary.missed == 1
    assert summary.total_scored == 3
    # consistency counts completed+modified ("did something"); on_target counts completed only
    assert summary.consistency_pct == round(100 * 2 / 3, 1)
    assert summary.on_target_pct == round(100 * 1 / 3, 1)
    assert summary.consistency_pct != summary.on_target_pct


def test_summarize_compliance_zero_scored_returns_none_percentages():
    days = [compute_day_compliance(plan("Rest", d=PAST, distance_km=None), [], TODAY)]
    summary = summarize_compliance(days)
    assert summary.total_scored == 0
    assert summary.consistency_pct is None
    assert summary.on_target_pct is None


# ── compute_range_compliance ─────────────────────────────────────────────────────────


def test_compute_range_compliance_duplicate_date_not_deduplicated():
    """Relies on TrainingPlan.date's DB-level PK to prevent this upstream; documents that this
    function itself does not deduplicate."""
    workouts = [plan("Easy Run", d=PAST), plan("Long Run", d=PAST)]
    days = compute_range_compliance(workouts, [], TODAY)
    assert len(days) == 2


# ── adapters ─────────────────────────────────────────────────────────────────────────


def test_planned_workouts_from_rows_drops_unparseable_date():
    rows = [
        {"date": "2026-06-10", "workout_type": "Easy Run", "distance_km": 5.0},
        {"date": "", "workout_type": "Long Run", "distance_km": 10.0},
        {"date": None, "workout_type": "Long Run", "distance_km": 10.0},
    ]
    result = planned_workouts_from_rows(rows)
    assert len(result) == 1
    assert result[0].date == date(2026, 6, 10)


def test_compliance_activities_from_rows_drops_empty_date():
    """Covers HEVY's date='' case for a workout with no start_time."""
    rows = [
        {"id": 1, "date": "2026-06-10", "sport_type": "Run", "distance_m": 5000.0},
        {"id": 2, "date": "", "sport_type": "WeightTraining", "distance_m": None},
    ]
    result = compliance_activities_from_rows(rows)
    assert len(result) == 1
    assert result[0].id == 1


def test_compliance_activities_from_rows_sport_type_none_handled():
    rows = [{"id": 1, "date": "2026-06-10", "sport_type": None, "distance_m": None}]
    result = compliance_activities_from_rows(rows)
    assert result[0].sport_type is None


def test_sport_type_match_is_case_sensitive():
    """Documents the exact-string-match assumption: Activity.sport_type is always written from
    Strava's/Hevy's own canonical strings, never user-typed, so this is a documented assumption
    rather than a defensive check."""
    p = plan("Easy Run", distance_km=5.0)
    act = activity(sport_type="run", distance_m=5_000.0)  # lowercase — does not match RUN_TYPES
    result = compute_day_compliance(p, [act], TODAY)
    assert result.status is ComplianceStatus.MISSED
