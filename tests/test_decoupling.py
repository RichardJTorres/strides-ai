"""The decoupling validity gate: when a stored drift value may be shown to the coach or the UI."""

import pytest

from strides_ai.activity_context import build_activity_card
from strides_ai.analysis import build_analysis_summary, build_precomputed_brief
from strides_ai.analytics.adapters import to_cardio_analytics
from strides_ai.decoupling import (
    DECOUPLING_MIN_MOVING_S,
    HIGH_CLIMB_M_PER_KM,
    NA_LABELS,
    decoupling_validity,
    gate_decoupling,
    na_text,
)


def _row(**kw):
    base = {
        "id": 1,
        "date": "2026-11-12",
        "name": "x",
        "sport_type": "Run",
        "moving_time_s": 3600,
        "distance_m": 10000.0,
        "climb_m_per_km": 5.0,
        "cardiac_decoupling_pct": 4.0,
    }
    base.update(kw)
    return base


# ── decoupling_validity ───────────────────────────────────────────────────────


def test_flat_steady_run_is_valid():
    assert decoupling_validity(_row()) == (True, None)


@pytest.mark.parametrize("sport", ["Ride", "VirtualRide", "GravelRide"])
def test_every_cycling_type_is_invalid(sport):
    # Nov 12 2026 Zwift ride: 40.9% with steady power; flat outdoor rides span -21%..+192%.
    assert decoupling_validity(_row(sport_type=sport, climb_m_per_km=2.0)) == (False, "cycling")


def test_virtual_run_is_valid_when_flat():
    assert decoupling_validity(_row(sport_type="VirtualRun", climb_m_per_km=3.0))[0] is True


def test_hilly_run_is_invalid_above_the_hilly_course_threshold():
    assert decoupling_validity(_row(climb_m_per_km=HIGH_CLIMB_M_PER_KM + 0.1)) == (False, "hilly")
    # Nov 7 2026 Squak trail run: 212 ft/mi = 40 m/km, decoupling -21.4%.
    assert decoupling_validity(_row(sport_type="TrailRun", climb_m_per_km=40.2)) == (False, "hilly")
    assert (
        decoupling_validity(_row(climb_m_per_km=HIGH_CLIMB_M_PER_KM))[0] is True
    )  # not strictly above


def test_climb_is_derived_from_elevation_and_distance_when_not_stored():
    # An older row: no climb_m_per_km, but 2000 m gained over 31 km = 64.5 m/km.
    row = _row(climb_m_per_km=None, elevation_gain_m=2000.0, distance_m=31000.0)
    assert decoupling_validity(row) == (False, "hilly")
    flat = _row(climb_m_per_km=None, elevation_gain_m=100.0, distance_m=31000.0)
    assert decoupling_validity(flat)[0] is True
    assert (
        decoupling_validity(_row(climb_m_per_km=None, elevation_gain_m=100.0, distance_m=0))[0]
        is True
    )


def test_short_activity_is_invalid():
    assert decoupling_validity(_row(moving_time_s=DECOUPLING_MIN_MOVING_S - 1)) == (False, "short")
    assert decoupling_validity(_row(moving_time_s=DECOUPLING_MIN_MOVING_S))[0] is True


def test_unknown_climb_or_time_does_not_invalidate():
    assert decoupling_validity(_row(climb_m_per_km=None, moving_time_s=None))[0] is True


def test_cycling_reason_wins_over_other_reasons():
    row = _row(sport_type="Ride", climb_m_per_km=50.0, moving_time_s=60)
    assert decoupling_validity(row) == (False, "cycling")


# ── gate_decoupling / na_text ─────────────────────────────────────────────────


def test_gate_nulls_invalid_value_sets_reason_and_does_not_mutate():
    row = _row(sport_type="VirtualRide", cardiac_decoupling_pct=40.9)
    gated = gate_decoupling(row)
    assert gated["cardiac_decoupling_pct"] is None
    assert gated["decoupling_na_reason"] == "cycling"
    assert row["cardiac_decoupling_pct"] == 40.9 and "decoupling_na_reason" not in row
    assert na_text(gated) == f"n/a ({NA_LABELS['cycling']})"


def test_gate_passes_valid_and_absent_values_through():
    valid = _row()
    assert gate_decoupling(valid) is valid
    absent = _row(sport_type="Ride", cardiac_decoupling_pct=None)
    assert gate_decoupling(absent) is absent  # no value, so nothing to explain
    assert na_text(absent) is None


def test_zero_is_a_value_not_missing():
    assert (
        gate_decoupling(_row(sport_type="Ride", cardiac_decoupling_pct=0.0))[
            "cardiac_decoupling_pct"
        ]
        is None
    )


# ── consumers ─────────────────────────────────────────────────────────────────

_ZONES = dict(
    hr_zone_1_pct=40.0, hr_zone_2_pct=40.0, hr_zone_3_pct=10.0, hr_zone_4_pct=5.0, hr_zone_5_pct=5.0
)


def test_summary_omits_decoupling_sentence_when_gated():
    ok = build_analysis_summary(_row(cardiac_decoupling_pct=14.0, **_ZONES))
    assert "decoupling" in ok.lower()
    gated = build_analysis_summary(
        _row(sport_type="VirtualRide", cardiac_decoupling_pct=40.9, **_ZONES)
    )
    assert "decoupling" not in gated.lower()


def test_chat_card_says_na_with_reason_instead_of_the_number():
    card = build_activity_card(_row(sport_type="VirtualRide", cardiac_decoupling_pct=40.9))
    assert "40.9" not in card
    assert f"cardiac decoupling n/a ({NA_LABELS['cycling']})" in card


def test_analytics_adapter_drops_gated_value():
    rows = [
        _row(date="2026-11-01", sport_type="Run", cardiac_decoupling_pct=4.0),
        _row(date="2026-11-02", sport_type="VirtualRide", cardiac_decoupling_pct=40.9),
    ]
    out = to_cardio_analytics(rows)
    assert [a.cardiac_decoupling_pct for a in out] == [4.0, None]


def test_precomputed_brief_shows_na_for_hilly_run():
    n = 120
    streams = {
        "time": list(range(n)),
        "heartrate": [140] * 60 + [160] * 60,
        "velocity_smooth": [3.0] * n,
        "cadence": [85] * n,
    }
    activity = {
        "sport_type": "TrailRun",
        "distance_m": 10000.0,
        "elevation_gain_m": 600.0,  # 60 m/km
        "moving_time_s": 3600,
    }
    brief = build_precomputed_brief(streams, activity)
    assert "Cardiac decoupling: n/a (" in brief and "hilly" in brief
