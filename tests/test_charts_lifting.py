"""Unit tests for strides_ai.charts_lifting — pure metric computations."""

import json
from datetime import date, timedelta

from strides_ai.charts_lifting import (
    _avg_rpe_from_exercises,
    compute_muscle_group_sets_per_week,
    compute_one_rm_progression,
    compute_rpe_trend,
    compute_weekly_sessions,
    compute_weekly_volume,
    get_chart_data,
)


# Fixed past Monday — keeps tests deterministic regardless of when they run.
PAST_MONDAY = "2024-01-01"
PAST_TUESDAY = "2024-01-02"
NEXT_MONDAY = "2024-01-08"


def _exercises(*items: tuple[str, str, list[dict]]) -> str:
    """Build an exercises_json string. items = (title, muscle, sets)."""
    return json.dumps([{"title": t, "primary_muscle_group": m, "sets": s} for t, m, s in items])


def _set(weight_kg: float, reps: int, *, type_: str = "normal", rpe: float | None = None) -> dict:
    out: dict = {"type": type_, "weight_kg": weight_kg, "reps": reps}
    if rpe is not None:
        out["rpe"] = rpe
    return out


def make_session(
    date_str: str,
    *,
    total_volume_kg: float | None = 1000.0,
    perceived_exertion: float | None = None,
    exercises_json: str | None = None,
) -> dict:
    return {
        "date": date_str,
        "total_volume_kg": total_volume_kg,
        "perceived_exertion": perceived_exertion,
        "exercises_json": exercises_json,
    }


# ── _avg_rpe_from_exercises ───────────────────────────────────────────────────


def test_avg_rpe_returns_none_for_empty():
    assert _avg_rpe_from_exercises(None) is None
    assert _avg_rpe_from_exercises("") is None


def test_avg_rpe_skips_warmups():
    j = _exercises(
        ("Bench", "Chest", [_set(60, 10, type_="warmup", rpe=5), _set(80, 8, rpe=8)]),
    )
    assert _avg_rpe_from_exercises(j) == 8.0


def test_avg_rpe_averages_across_exercises():
    j = _exercises(
        ("Bench", "Chest", [_set(80, 8, rpe=8), _set(80, 8, rpe=9)]),
        ("Row", "Back", [_set(70, 8, rpe=7)]),
    )
    assert _avg_rpe_from_exercises(j) == 8.0


def test_avg_rpe_returns_none_when_no_rpe_recorded():
    j = _exercises(("Bench", "Chest", [_set(80, 8)]))
    assert _avg_rpe_from_exercises(j) is None


def test_avg_rpe_handles_invalid_json():
    assert _avg_rpe_from_exercises("not json") is None


# ── compute_weekly_volume ─────────────────────────────────────────────────────


def test_weekly_volume_empty():
    assert compute_weekly_volume([]) == []


def test_weekly_volume_skips_sessions_missing_volume():
    rows = [make_session(PAST_MONDAY, total_volume_kg=None)]
    assert compute_weekly_volume(rows) == []


def test_weekly_volume_buckets_by_iso_week():
    rows = [
        make_session(PAST_MONDAY, total_volume_kg=1000),
        make_session(PAST_TUESDAY, total_volume_kg=500),
    ]
    out = compute_weekly_volume(rows)
    # First entry should be week starting PAST_MONDAY with 1500 kg total
    assert out[0]["week"] == PAST_MONDAY
    assert out[0]["value"] == 1500.0


def test_weekly_volume_separates_consecutive_weeks():
    rows = [
        make_session(PAST_MONDAY, total_volume_kg=1000),
        make_session(NEXT_MONDAY, total_volume_kg=2000),
    ]
    out = compute_weekly_volume(rows)
    assert out[0]["week"] == PAST_MONDAY
    assert out[0]["value"] == 1000.0
    assert out[1]["week"] == NEXT_MONDAY
    assert out[1]["value"] == 2000.0


def test_weekly_volume_includes_zero_filler_weeks():
    rows = [
        make_session(PAST_MONDAY, total_volume_kg=1000),
        make_session("2024-01-15", total_volume_kg=2000),  # 2 weeks later
    ]
    out = compute_weekly_volume(rows)
    # Three weeks: 01-01 (1000), 01-08 (0), 01-15 (2000)
    assert len(out) >= 3
    middle = next(r for r in out if r["week"] == NEXT_MONDAY)
    assert middle["value"] == 0


def test_weekly_volume_rolling_avg_4_week_trailing():
    rows = [
        make_session("2024-01-01", total_volume_kg=1000),
        make_session("2024-01-08", total_volume_kg=2000),
        make_session("2024-01-15", total_volume_kg=3000),
        make_session("2024-01-22", total_volume_kg=4000),
    ]
    out = compute_weekly_volume(rows)
    week_4 = next(r for r in out if r["week"] == "2024-01-22")
    # 4-week trailing average = (1000+2000+3000+4000)/4 = 2500
    assert week_4["rolling_avg"] == 2500.0


def test_weekly_volume_marks_current_week():
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    rows = [make_session(monday.isoformat(), total_volume_kg=500)]
    out = compute_weekly_volume(rows)
    current = [r for r in out if r["is_current"]]
    assert len(current) == 1
    assert current[0]["week"] == monday.isoformat()


# ── compute_weekly_sessions ───────────────────────────────────────────────────


def test_weekly_sessions_empty():
    assert compute_weekly_sessions([]) == []


def test_weekly_sessions_counts_per_week():
    rows = [
        make_session(PAST_MONDAY),
        make_session(PAST_TUESDAY),
        make_session(NEXT_MONDAY),
    ]
    out = compute_weekly_sessions(rows)
    assert next(r for r in out if r["week"] == PAST_MONDAY)["value"] == 2
    assert next(r for r in out if r["week"] == NEXT_MONDAY)["value"] == 1


def test_weekly_sessions_value_is_int():
    rows = [make_session(PAST_MONDAY), make_session(PAST_TUESDAY)]
    out = compute_weekly_sessions(rows)
    assert isinstance(out[0]["value"], int)


# ── compute_one_rm_progression ────────────────────────────────────────────────


def test_one_rm_progression_empty():
    assert compute_one_rm_progression([]) == {"series": {}, "exercises": []}


def test_one_rm_progression_uses_epley():
    # Epley: 100 * (1 + 5/30) = 116.7
    rows = [
        make_session(
            PAST_MONDAY,
            exercises_json=_exercises(
                ("Bench", "Chest", [_set(100, 5)]),
            ),
        ),
    ]
    out = compute_one_rm_progression(rows)
    assert out["series"]["Bench"][0]["one_rm_kg"] == 116.7


def test_one_rm_progression_keeps_daily_max():
    # Two sets same day — keep the higher 1RM
    rows = [
        make_session(
            PAST_MONDAY,
            exercises_json=_exercises(
                ("Bench", "Chest", [_set(80, 8), _set(100, 5)]),
            ),
        ),
    ]
    out = compute_one_rm_progression(rows)
    assert len(out["series"]["Bench"]) == 1
    # 100 * (1 + 5/30) = 116.7 wins over 80 * (1 + 8/30) = 101.3
    assert out["series"]["Bench"][0]["one_rm_kg"] == 116.7


def test_one_rm_progression_drops_high_rep_sets():
    rows = [
        make_session(
            PAST_MONDAY,
            exercises_json=_exercises(
                ("Bench", "Chest", [_set(50, 20)]),  # >12 reps → dropped
            ),
        ),
    ]
    out = compute_one_rm_progression(rows)
    assert "Bench" not in out["series"]


def test_one_rm_progression_top_n_limits_exercises():
    sets = [_set(50, 5)]
    rows = [
        make_session(
            PAST_MONDAY,
            exercises_json=_exercises(
                ("A", "Chest", sets * 5),
                ("B", "Chest", sets * 4),
                ("C", "Chest", sets * 3),
                ("D", "Chest", sets * 2),
                ("E", "Chest", sets * 1),
            ),
        ),
    ]
    out = compute_one_rm_progression(rows, top_n=2)
    assert set(out["series"].keys()) == {"A", "B"}
    assert out["exercises"] == ["A", "B"]


def test_one_rm_progression_sorts_points_by_date():
    j_first = _exercises(("Bench", "Chest", [_set(80, 5)]))
    j_second = _exercises(("Bench", "Chest", [_set(85, 5)]))
    rows = [
        make_session(NEXT_MONDAY, exercises_json=j_second),
        make_session(PAST_MONDAY, exercises_json=j_first),
    ]
    out = compute_one_rm_progression(rows)
    dates = [p["date"] for p in out["series"]["Bench"]]
    assert dates == sorted(dates)


# ── compute_muscle_group_sets_per_week ────────────────────────────────────────


def test_muscle_group_sets_empty():
    out = compute_muscle_group_sets_per_week([])
    assert out == {"weeks": [], "categories": []}


def test_muscle_group_sets_aggregates_by_muscle():
    rows = [
        make_session(
            PAST_MONDAY,
            exercises_json=_exercises(
                ("Bench", "Chest", [_set(80, 8), _set(80, 8)]),
                ("Row", "Back", [_set(70, 8)]),
            ),
        ),
    ]
    out = compute_muscle_group_sets_per_week(rows)
    week = out["weeks"][0]
    assert week["Chest"] == 2
    assert week["Back"] == 1


def test_muscle_group_sets_categories_ordered_by_total_volume():
    rows = [
        make_session(
            PAST_MONDAY,
            exercises_json=_exercises(
                ("Row", "Back", [_set(70, 8)] * 5),
                ("Bench", "Chest", [_set(80, 8)] * 2),
                ("Curl", "Biceps", [_set(20, 10)] * 1),
            ),
        ),
    ]
    out = compute_muscle_group_sets_per_week(rows)
    assert out["categories"] == ["Back", "Chest", "Biceps"]


def test_muscle_group_sets_skips_warmups():
    rows = [
        make_session(
            PAST_MONDAY,
            exercises_json=_exercises(
                ("Bench", "Chest", [_set(60, 10, type_="warmup"), _set(80, 8)]),
            ),
        ),
    ]
    out = compute_muscle_group_sets_per_week(rows)
    assert out["weeks"][0]["Chest"] == 1


def test_muscle_group_sets_resolves_via_template_map():
    # Real HEVY workouts ship without primary_muscle_group; only exercise_template_id.
    payload = json.dumps(
        [
            {
                "title": "Bench Press",
                "exercise_template_id": "TPL_BENCH",
                "sets": [{"type": "normal", "weight_kg": 80, "reps": 8}],
            },
            {
                "title": "Row",
                "exercise_template_id": "TPL_ROW",
                "sets": [{"type": "normal", "weight_kg": 70, "reps": 8}],
            },
        ]
    )
    rows = [make_session(PAST_MONDAY, exercises_json=payload)]
    muscle_map = {"TPL_BENCH": "Chest", "TPL_ROW": "Back"}
    out = compute_muscle_group_sets_per_week(rows, muscle_map)
    week = out["weeks"][0]
    assert week["Chest"] == 1
    assert week["Back"] == 1
    assert "Unknown" not in out["categories"]


def test_muscle_group_sets_template_map_beats_inline_field():
    payload = json.dumps(
        [
            {
                "title": "Bench",
                "primary_muscle_group": "Wrong",
                "exercise_template_id": "TPL_BENCH",
                "sets": [{"type": "normal", "weight_kg": 80, "reps": 8}],
            },
        ]
    )
    rows = [make_session(PAST_MONDAY, exercises_json=payload)]
    out = compute_muscle_group_sets_per_week(rows, {"TPL_BENCH": "Chest"})
    assert out["weeks"][0]["Chest"] == 1
    assert "Wrong" not in out["categories"]


def test_muscle_group_sets_falls_back_when_template_missing():
    payload = json.dumps(
        [
            {
                "title": "Mystery",
                "exercise_template_id": "TPL_UNKNOWN",
                "sets": [{"type": "normal", "weight_kg": 50, "reps": 10}],
            },
        ]
    )
    rows = [make_session(PAST_MONDAY, exercises_json=payload)]
    out = compute_muscle_group_sets_per_week(rows, {"TPL_BENCH": "Chest"})
    assert out["weeks"][0]["Unknown"] == 1


def test_muscle_group_sets_handles_no_template_id_gracefully():
    payload = json.dumps(
        [
            {"title": "X", "sets": [{"type": "normal", "weight_kg": 50, "reps": 10}]},
        ]
    )
    rows = [make_session(PAST_MONDAY, exercises_json=payload)]
    # Map provided but exercise has no template id and no inline muscle → Unknown
    out = compute_muscle_group_sets_per_week(rows, {"TPL_BENCH": "Chest"})
    assert out["weeks"][0]["Unknown"] == 1


# ── compute_rpe_trend ─────────────────────────────────────────────────────────


def test_rpe_trend_empty():
    assert compute_rpe_trend([]) == []


def test_rpe_trend_uses_perceived_exertion_when_set():
    rows = [make_session(PAST_MONDAY, perceived_exertion=8.0)]
    out = compute_rpe_trend(rows)
    assert out[0]["rpe"] == 8.0


def test_rpe_trend_falls_back_to_exercises_avg():
    rows = [
        make_session(
            PAST_MONDAY,
            perceived_exertion=None,
            exercises_json=_exercises(
                ("Bench", "Chest", [_set(80, 8, rpe=7), _set(80, 8, rpe=9)]),
            ),
        ),
    ]
    out = compute_rpe_trend(rows)
    assert out[0]["rpe"] == 8.0


def test_rpe_trend_skips_sessions_without_rpe():
    rows = [
        make_session(PAST_MONDAY, perceived_exertion=None, exercises_json=None),
        make_session(PAST_TUESDAY, perceived_exertion=8.0),
    ]
    out = compute_rpe_trend(rows)
    assert len(out) == 1
    assert out[0]["date"] == PAST_TUESDAY


def test_rpe_trend_includes_4_session_rolling_avg():
    rows = [
        make_session("2024-01-01", perceived_exertion=6.0),
        make_session("2024-01-03", perceived_exertion=7.0),
        make_session("2024-01-05", perceived_exertion=8.0),
        make_session("2024-01-07", perceived_exertion=9.0),
    ]
    out = compute_rpe_trend(rows)
    # 4-session trailing avg of last point: (6+7+8+9)/4 = 7.5
    assert out[-1]["rolling_avg"] == 7.5


def test_rpe_trend_sorts_by_date():
    rows = [
        make_session("2024-02-01", perceived_exertion=8.0),
        make_session("2024-01-01", perceived_exertion=6.0),
    ]
    out = compute_rpe_trend(rows)
    assert [p["date"] for p in out] == ["2024-01-01", "2024-02-01"]


# ── get_chart_data ────────────────────────────────────────────────────────────


def test_get_chart_data_returns_all_keys():
    out = get_chart_data([])
    assert set(out.keys()) == {
        "weekly_volume",
        "weekly_sessions",
        "one_rm_progression",
        "muscle_group_sets",
        "rpe_trend",
    }


def test_get_chart_data_with_real_session():
    rows = [
        make_session(
            PAST_MONDAY,
            total_volume_kg=2000.0,
            perceived_exertion=8.0,
            exercises_json=_exercises(("Bench", "Chest", [_set(100, 5, rpe=8)])),
        ),
    ]
    out = get_chart_data(rows)
    assert out["weekly_volume"][0]["value"] == 2000.0
    assert out["weekly_sessions"][0]["value"] == 1
    assert "Bench" in out["one_rm_progression"]["series"]
    assert out["muscle_group_sets"]["categories"] == ["Chest"]
    assert out["rpe_trend"][0]["rpe"] == 8.0


def test_get_chart_data_passes_template_map_through():
    payload = json.dumps(
        [
            {
                "title": "Bench",
                "exercise_template_id": "TPL_BENCH",
                "sets": [{"type": "normal", "weight_kg": 80, "reps": 8}],
            },
        ]
    )
    rows = [make_session(PAST_MONDAY, exercises_json=payload)]
    out = get_chart_data(rows, template_muscle_map={"TPL_BENCH": "Chest"})
    assert out["muscle_group_sets"]["categories"] == ["Chest"]
