"""Unit tests for strides_ai.activity_context.build_activity_card."""

from strides_ai.activity_context import build_activity_card


def _base_run():
    return {
        "name": "Tuesday Long Run",
        "date": "2025-06-15",
        "sport_type": "Run",
        "distance_m": 10_000.0,
        "moving_time_s": 3_600,
        "avg_pace_s_per_km": 360.0,
        "avg_hr": 145.3,
        "max_hr": 165,
        "elevation_gain_m": 50.0,
        "analysis_summary": None,
        "analysis_status": None,
        "cardiac_decoupling_pct": None,
        "effort_efficiency_score": None,
        "pace_fade_seconds": None,
        "avg_cadence": None,
        "elevation_per_mile": None,
        "hr_zone_1_pct": None,
        "hr_zone_2_pct": None,
        "hr_zone_3_pct": None,
        "hr_zone_4_pct": None,
        "hr_zone_5_pct": None,
        "suffer_score_mismatch_flag": None,
        "user_notes": None,
        "deep_dive_report": None,
        "total_sets": None,
        "total_volume_kg": None,
        "exercises_json": None,
    }


def test_header_includes_name_and_date():
    card = build_activity_card(_base_run())
    assert card.startswith("## Attached Activity: Tuesday Long Run (2025-06-15)")


def test_missing_name_and_date_fall_back_to_placeholders():
    activity = _base_run()
    activity["name"] = None
    activity["date"] = None
    card = build_activity_card(activity)
    assert card.startswith("## Attached Activity: Untitled (unknown date)")


def test_run_uses_pace_not_speed():
    card = build_activity_card(_base_run())
    assert "Pace: 6:00/km" in card
    assert "Speed:" not in card


def test_ride_uses_speed_not_pace():
    activity = _base_run()
    activity["sport_type"] = "Ride"
    card = build_activity_card(activity)
    assert "Speed: 10.0 km/h" in card
    assert "Pace:" not in card


def test_stats_line_omits_fields_with_no_data():
    activity = _base_run()
    activity["avg_hr"] = None
    activity["max_hr"] = None
    activity["elevation_gain_m"] = None
    card = build_activity_card(activity)
    assert "Avg HR" not in card
    assert "Max HR" not in card
    assert "Elevation gain" not in card
    assert "Distance: 10.00 km" in card


def test_zero_values_are_not_treated_as_missing():
    activity = _base_run()
    activity["avg_hr"] = 0.0
    activity["elevation_gain_m"] = 0.0
    activity["pace_fade_seconds"] = 0.0
    card = build_activity_card(activity)
    assert "Avg HR: 0 bpm" in card
    assert "Elevation gain: 0 m" in card
    assert "pace fade +0 s/mile" in card


def test_no_analysis_summary_or_status_reports_not_analyzed():
    card = build_activity_card(_base_run())
    assert "Analysis: not yet analyzed." in card


def test_pending_analysis_status_is_reported():
    activity = _base_run()
    activity["analysis_status"] = "pending"
    card = build_activity_card(activity)
    assert "Analysis status: pending." in card


def test_analysis_summary_takes_priority_over_status():
    activity = _base_run()
    activity["analysis_status"] = "done"
    activity["analysis_summary"] = "Aerobic effort — 80% time in Z1/Z2."
    card = build_activity_card(activity)
    assert "Analysis: Aerobic effort — 80% time in Z1/Z2." in card
    assert "Analysis status:" not in card


def test_computed_metrics_line_includes_present_fields_only():
    activity = _base_run()
    activity["cardiac_decoupling_pct"] = 7.5
    activity["effort_efficiency_score"] = 82.0
    card = build_activity_card(activity)
    assert "Computed metrics: cardiac decoupling 7.5%; effort efficiency 82/100." in card


def test_no_computed_metrics_omits_the_line_entirely():
    card = build_activity_card(_base_run())
    assert "Computed metrics" not in card


def test_hr_zones_are_grouped_into_one_segment():
    activity = _base_run()
    activity["hr_zone_1_pct"] = 40.0
    activity["hr_zone_2_pct"] = 35.0
    activity["hr_zone_3_pct"] = 25.0
    card = build_activity_card(activity)
    assert "HR zones Z1 40% Z2 35% Z3 25%" in card


def test_suffer_score_mismatch_flag_is_called_out():
    activity = _base_run()
    activity["suffer_score_mismatch_flag"] = 1
    activity["cardiac_decoupling_pct"] = 3.0  # ensure metrics line is non-empty
    card = build_activity_card(activity)
    assert "HR data may be unreliable (suffer score mismatch)" in card


def test_user_notes_included_when_present():
    activity = _base_run()
    activity["user_notes"] = "Felt great, cool morning."
    card = build_activity_card(activity)
    assert "Athlete notes: Felt great, cool morning." in card


def test_user_notes_omitted_when_absent():
    card = build_activity_card(_base_run())
    assert "Athlete notes" not in card


def test_deep_dive_report_included_verbatim():
    activity = _base_run()
    activity["deep_dive_report"] = "## Pacing\nEven effort throughout."
    card = build_activity_card(activity)
    assert "Deep dive analysis:\n## Pacing\nEven effort throughout." in card


def test_deep_dive_absent_reports_not_yet_run():
    card = build_activity_card(_base_run())
    assert "Deep dive analysis: not yet run for this activity." in card


def test_lifting_activity_uses_volume_and_sets_not_distance():
    activity = _base_run()
    activity["sport_type"] = "WeightTraining"
    activity["distance_m"] = None
    activity["avg_pace_s_per_km"] = None
    activity["total_sets"] = 18
    activity["total_volume_kg"] = 4320.5
    card = build_activity_card(activity)
    assert "Sets: 18" in card
    assert "Volume: 4320 kg" in card
    assert "Distance:" not in card


def test_sport_type_missing_falls_back_to_exercises_json_for_lifting_detection():
    activity = _base_run()
    activity["sport_type"] = None
    activity["exercises_json"] = "[]"
    activity["total_sets"] = 5
    activity["total_volume_kg"] = 100.0
    card = build_activity_card(activity)
    assert "Sets: 5" in card
