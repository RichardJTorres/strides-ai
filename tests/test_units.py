"""Unit conversion module tests."""

import pytest

from strides_ai.units import (
    KG_TO_LB,
    M_TO_FT,
    M_TO_MI,
    S_PER_KM_TO_S_PER_MI,
    VALID_UNITS,
    dist_unit_label,
    elev_unit_label,
    format_distance,
    format_elevation,
    format_pace,
    format_speed,
    format_weight,
    imperial_input_to_km,
    imperial_input_to_m,
    kg_to_weight,
    km_to_distance,
    llm_unit_instruction,
    m_to_distance,
    m_to_elevation,
    pace_unit_label,
    s_per_km_to_pace_seconds,
    s_per_km_to_speed,
    speed_unit_label,
    weight_unit_label,
)


# ── Constants reference values ────────────────────────────────────────────────


def test_constants_match_known_values():
    # 1 km = 0.621371 mi
    assert M_TO_MI == pytest.approx(0.000621371, rel=1e-6)
    # 1 kg = 2.20462 lb
    assert KG_TO_LB == pytest.approx(2.20462, rel=1e-5)
    # 1 m = 3.28084 ft
    assert M_TO_FT == pytest.approx(3.28084, rel=1e-5)
    # 1 mile = 1.60934 km
    assert S_PER_KM_TO_S_PER_MI == pytest.approx(1.60934, rel=1e-5)


def test_valid_units_set():
    assert VALID_UNITS == {"metric", "imperial"}


# ── Labels ────────────────────────────────────────────────────────────────────


def test_dist_unit_label():
    assert dist_unit_label("metric") == "km"
    assert dist_unit_label("imperial") == "mi"


def test_weight_unit_label():
    assert weight_unit_label("metric") == "kg"
    assert weight_unit_label("imperial") == "lb"


def test_elev_unit_label():
    assert elev_unit_label("metric") == "m"
    assert elev_unit_label("imperial") == "ft"


def test_speed_unit_label():
    assert speed_unit_label("metric") == "km/h"
    assert speed_unit_label("imperial") == "mph"


def test_pace_unit_label():
    assert pace_unit_label("metric") == "min/km"
    assert pace_unit_label("imperial") == "min/mi"


# ── Numeric conversions ───────────────────────────────────────────────────────


def test_m_to_distance_metric():
    assert m_to_distance(5000, "metric") == pytest.approx(5.0)


def test_m_to_distance_imperial():
    # 5000 m = 3.10686 mi
    assert m_to_distance(5000, "imperial") == pytest.approx(3.10686, rel=1e-4)


def test_m_to_distance_none():
    assert m_to_distance(None, "metric") is None


def test_km_to_distance_metric_identity():
    assert km_to_distance(10.0, "metric") == pytest.approx(10.0)


def test_km_to_distance_imperial():
    # 10 km = 6.21371 mi
    assert km_to_distance(10.0, "imperial") == pytest.approx(6.21371, rel=1e-4)


def test_kg_to_weight_metric_identity():
    assert kg_to_weight(100.0, "metric") == pytest.approx(100.0)


def test_kg_to_weight_imperial():
    assert kg_to_weight(100.0, "imperial") == pytest.approx(220.462, rel=1e-4)


def test_kg_to_weight_none():
    assert kg_to_weight(None, "metric") is None


def test_m_to_elevation_metric_identity():
    assert m_to_elevation(1000.0, "metric") == pytest.approx(1000.0)


def test_m_to_elevation_imperial():
    # 1000 m = 3280.84 ft
    assert m_to_elevation(1000.0, "imperial") == pytest.approx(3280.84, rel=1e-4)


def test_s_per_km_to_pace_seconds_metric_identity():
    assert s_per_km_to_pace_seconds(360.0, "metric") == pytest.approx(360.0)


def test_s_per_km_to_pace_seconds_imperial():
    # 6:00/km × 1.60934 = 9:39.6/mi (579.36s)
    assert s_per_km_to_pace_seconds(360.0, "imperial") == pytest.approx(579.36, rel=1e-3)


def test_s_per_km_to_speed_metric():
    # 6:00/km = 10 km/h
    assert s_per_km_to_speed(360.0, "metric") == pytest.approx(10.0, rel=1e-4)


def test_s_per_km_to_speed_imperial():
    # 10 km/h ≈ 6.21 mph
    assert s_per_km_to_speed(360.0, "imperial") == pytest.approx(6.21371, rel=1e-3)


def test_s_per_km_to_speed_zero_or_negative():
    assert s_per_km_to_speed(0.0, "metric") is None
    assert s_per_km_to_speed(-1.0, "imperial") is None


# ── Round-trip ────────────────────────────────────────────────────────────────


def test_imperial_input_to_km_metric_passthrough():
    assert imperial_input_to_km(10.0, "metric") == pytest.approx(10.0)


def test_imperial_input_to_km_imperial():
    # 10 mi → 16.0934 km
    assert imperial_input_to_km(10.0, "imperial") == pytest.approx(16.0934, rel=1e-4)


def test_imperial_input_to_m_metric_passthrough():
    assert imperial_input_to_m(100.0, "metric") == pytest.approx(100.0)


def test_imperial_input_to_m_imperial():
    # 1000 ft → 304.8 m
    assert imperial_input_to_m(1000.0, "imperial") == pytest.approx(304.8, rel=1e-4)


def test_round_trip_distance_imperial():
    # km → mi → km should be lossless to numerical precision
    km = 12.5
    mi = km_to_distance(km, "imperial")
    back = imperial_input_to_km(mi, "imperial")
    assert back == pytest.approx(km, rel=1e-6)


def test_round_trip_elevation_imperial():
    m = 250.0
    ft = m_to_elevation(m, "imperial")
    back = imperial_input_to_m(ft, "imperial")
    assert back == pytest.approx(m, rel=1e-5)


# ── Formatters ────────────────────────────────────────────────────────────────


def test_format_distance_imperial():
    # 5000 m = 3.11 mi
    assert format_distance(5000, "imperial") == "3.11mi"


def test_format_distance_metric():
    assert format_distance(5000, "metric") == "5.00km"


def test_format_distance_none():
    assert format_distance(None, "metric") == "—"


def test_format_pace_metric():
    assert format_pace(360.0, "metric") == "6:00/km"


def test_format_pace_imperial():
    # 6:00/km × 1.60934 = 9:39 (579.36s → 9 min 39 s)
    assert format_pace(360.0, "imperial") == "9:39/mi"


def test_format_pace_none():
    assert format_pace(None, "metric") == "—"


def test_format_speed_metric():
    assert format_speed(360.0, "metric") == "10.0km/h"


def test_format_speed_imperial():
    assert format_speed(360.0, "imperial") == "6.2mph"


def test_format_elevation_imperial():
    assert format_elevation(1000.0, "imperial") == "3281ft"


def test_format_elevation_metric():
    assert format_elevation(1000.0, "metric") == "1000m"


def test_format_weight_imperial():
    assert format_weight(100.0, "imperial") == "220lb"


def test_format_weight_metric():
    assert format_weight(100.0, "metric") == "100kg"


# ── llm_unit_instruction ──────────────────────────────────────────────────────


def test_llm_unit_instruction_running_metric():
    s = llm_unit_instruction("running", "metric")
    assert "km" in s and "min/km" in s


def test_llm_unit_instruction_running_imperial():
    s = llm_unit_instruction("running", "imperial")
    assert "mi" in s and "min/mi" in s
    assert "km" not in s


def test_llm_unit_instruction_cycling_imperial_uses_mph():
    s = llm_unit_instruction("cycling", "imperial")
    assert "mph" in s
    assert "km/h" not in s


def test_llm_unit_instruction_lifting_imperial():
    s = llm_unit_instruction("lifting", "imperial")
    assert "lb" in s
    assert "kg" not in s


def test_llm_unit_instruction_lifting_metric():
    s = llm_unit_instruction("lifting", "metric")
    assert "kg" in s
    assert "lb" not in s
