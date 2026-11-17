"""The compact analysis columns of the cardio training log (replaced a 60-character summary)."""

from strides_ai.coach import _analysis_guide_section
from strides_ai.modes import MODES, _analysis_columns, _hybrid_log_row
from strides_ai.units import UnitSystem

M, I = UnitSystem.METRIC, UnitSystem.IMPERIAL


def row(**kw):
    base = {
        "date": "2026-11-12",
        "sport_type": "Run",
        "name": "Easy",
        "distance_m": 10000.0,
        "moving_time_s": 3600,
        "avg_pace_s_per_km": 360.0,
        "avg_hr": 140,
        "max_hr": 160,
        "avg_cadence": 170,
        "elevation_gain_m": 50.0,
        "suffer_score": 40,
        "perceived_exertion": None,
        "climb_m_per_km": 5.0,
        "pace_fade_s_per_km": 12.0,
        "cardiac_decoupling_pct": 3.4,
        "hr_zone_1_pct": 30.0,
        "hr_zone_2_pct": 55.0,
        "hr_zone_3_pct": 10.0,
        "hr_zone_4_pct": 4.0,
        "hr_zone_5_pct": 1.0,
        "effort_efficiency_score": 62.4,
        "suffer_score_mismatch_flag": 0,
        "analysis_status": "done",
    }
    base.update(kw)
    return base


def cols(r, units=M):
    return [c.strip() for c in _analysis_columns(r, units).split("|")]


def test_columns_for_a_flat_steady_run():
    assert cols(row()) == ["5", "+12", "3.4", "85", "5", "62"]


def test_zwift_ride_decoupling_is_na_not_the_number():
    # Nov 12 2026: 40.9% on a Zwift ride with steady power.
    out = cols(row(sport_type="VirtualRide", cardiac_decoupling_pct=40.9, pace_fade_s_per_km=62.0))
    assert out[2] == "n/a" and "40.9" not in " ".join(out)
    assert out[1] == "+62"  # fade is still shown; the guide says how to read it


def test_hilly_run_is_na_and_missing_data_is_a_dash_never_zero():
    assert cols(row(climb_m_per_km=40.0))[2] == "n/a"
    blank = cols(
        row(
            cardiac_decoupling_pct=None,
            pace_fade_s_per_km=None,
            climb_m_per_km=None,
            hr_zone_1_pct=None,
            hr_zone_4_pct=None,
            effort_efficiency_score=None,
        )
    )
    assert blank == ["—", "—", "—", "—", "—", "—"]


def test_negative_fade_keeps_its_sign_and_hr_flag_shows():
    out = cols(row(pace_fade_s_per_km=-44.0, suffer_score_mismatch_flag=1))
    assert out[1] == "-44" and out[-1] == "HR?"


def test_fade_and_climb_follow_the_unit_system():
    metric = cols(row(climb_m_per_km=10.0, pace_fade_s_per_km=10.0), M)
    imperial = cols(row(climb_m_per_km=10.0, pace_fade_s_per_km=10.0), I)
    assert metric[0] == "10" and imperial[0] == "53"  # 10 m/km = 52.8 ft/mi
    assert metric[1] == "+10" and imperial[1] == "+16"  # 10 s/km = 16.1 s/mi


def test_headers_name_the_columns_and_units():
    header_m = MODES["hybrid"].log_header(M)
    header_i = MODES["running"].log_header(I)
    for h in (header_m, header_i, MODES["cycling"].log_header(M)):
        assert "DECPL%" in h and "Z1-2%" in h and "Z4-5%" in h and "EFF" in h and "HR?" in h
        assert "ANALYSIS" not in h
    assert "CLIMB(m/km)" in header_m and "FADE(s/km)" in header_m
    assert "CLIMB(ft/mi)" in header_i and "FADE(s/mi)" in header_i
    assert "ANALYSIS" in MODES["lifting"].log_header(M)  # lifting is unchanged


def test_hybrid_row_ends_with_the_columns_and_no_truncated_prose():
    line = _hybrid_log_row(row(), M)
    assert line.rstrip().endswith("62")
    assert "Aerobic effort" not in line


def test_guide_documents_na_and_the_terrain_caveat():
    guide = _analysis_guide_section(MODES["hybrid"], [{"analysis_summary": "x"}], M)
    assert "n/a" in guide and "not zero" in guide
    assert "Zwift" in guide and "never call it fatigue" in guide
    assert "equally important" not in guide
