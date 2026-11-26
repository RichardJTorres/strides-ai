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


# ── effort efficiency ─────────────────────────────────────────────────────────

from strides_ai import db  # noqa: E402
from strides_ai.decoupling import (  # noqa: E402
    EFFICIENCY_NA_LABELS,
    efficiency_validity,
    gate_efficiency,
)


@pytest.mark.parametrize("sport", ["Ride", "VirtualRide", "GravelRide"])
def test_efficiency_is_never_valid_on_a_ride(sport):
    assert efficiency_validity(_row(sport_type=sport)) == (False, "cycling")


def test_efficiency_on_runs_short_hilly_and_unknown_terrain():
    assert efficiency_validity(_row(moving_time_s=300)) == (True, None)  # duration is irrelevant
    assert efficiency_validity(_row(climb_m_per_km=HIGH_CLIMB_M_PER_KM + 1)) == (False, "hilly")
    # Derived from the summary when the stored ratio is missing; no evidence is not invalid.
    assert efficiency_validity(_row(climb_m_per_km=None, elevation_gain_m=500.0)) == (
        False,
        "hilly",
    )
    assert efficiency_validity(_row(climb_m_per_km=None)) == (True, None)
    assert set(EFFICIENCY_NA_LABELS) == {"cycling", "hilly"}


def test_gate_efficiency_hides_an_invalid_score_without_mutating():
    ride = _row(sport_type="Ride", effort_efficiency_score=87.0, effort_efficiency_raw=1.1)
    gated = gate_efficiency(ride)
    assert gated["effort_efficiency_score"] is None
    assert gated["efficiency_na_reason"] == "cycling"
    assert ride["effort_efficiency_score"] == 87.0
    run = _row(effort_efficiency_score=60.0)
    assert gate_efficiency(run) is run
    no_value = _row(sport_type="Ride")
    assert gate_efficiency(no_value) is no_value


def test_ride_card_and_summary_never_quote_efficiency():
    ride = _row(
        sport_type="Ride",
        effort_efficiency_score=87.0,
        effort_efficiency_raw=1.1,
        analysis_status="done",
    )
    card = build_activity_card(ride)
    assert "87/100" not in card and "effort efficiency n/a" in card
    assert "Effort efficiency" not in build_analysis_summary(ride)
    assert "Effort efficiency 62/100" in build_analysis_summary(_row(effort_efficiency_score=62.0))


def _seed(i, sport, raw, climb=5.0):
    with db._session() as s:
        from strides_ai.db.models import Activity

        s.add(
            Activity(
                id=i,
                name=f"a{i}",
                date="2026-11-01",
                sport_type=sport,
                distance_m=10000.0,
                effort_efficiency_raw=raw,
                effort_efficiency_score=99.0,
                climb_m_per_km=climb,
            )
        )
        s.commit()


def _scores():
    with db._session() as s:
        from sqlalchemy import text

        return dict(s.execute(text("SELECT id, effort_efficiency_score FROM activities")).all())


def test_scores_are_scaled_over_valid_runs_only(tmp_db):
    _seed(1, "Run", 2.0)  # best run
    _seed(2, "Run", 4.0)  # worst run
    _seed(3, "Run", 3.0)
    _seed(4, "Ride", 0.8)  # would have topped the old cross-sport scale
    _seed(5, "Run", 1.5, climb=60.0)  # hilly: invalid, and does not set the best
    db.renormalize_effort_efficiency()
    assert _scores() == {1: 100.0, 2: 0.0, 3: 50.0, 4: None, 5: None}


def test_a_single_valid_run_scores_fifty_and_no_valid_run_clears_all(tmp_db):
    _seed(1, "Run", 3.0)
    _seed(2, "VirtualRide", 1.2)
    db.renormalize_effort_efficiency()
    assert _scores() == {1: 50.0, 2: None}


def test_migration_021_scores_exactly_like_renormalize(tmp_db):
    """The frozen SQL in migration 021 must agree with efficiency_validity row for row."""
    import importlib.util
    from pathlib import Path
    from types import SimpleNamespace

    from sqlalchemy import text

    from strides_ai.db.engine import get_engine
    from strides_ai.db.models import Activity

    rows = [
        dict(id=1, sport_type="Run", effort_efficiency_raw=2.0, climb_m_per_km=5.0),
        dict(id=2, sport_type="Run", effort_efficiency_raw=4.0, climb_m_per_km=5.0),
        # Analysed before the climb ratio was stored: 250 m over 10 km is hilly.
        dict(id=3, sport_type="Run", effort_efficiency_raw=1.0, elevation_gain_m=250.0),
        # ...and no ratio and no climb at all is not hilly.
        dict(id=4, sport_type="VirtualRun", effort_efficiency_raw=3.0),
        dict(id=5, sport_type=None, effort_efficiency_raw=3.5, climb_m_per_km=1.0),
        dict(id=6, sport_type="Ride", effort_efficiency_raw=0.8, climb_m_per_km=5.0),
        dict(id=7, sport_type="Run", effort_efficiency_raw=2.5, climb_m_per_km=30.0),
        dict(id=8, sport_type="Run", effort_efficiency_raw=None),
    ]

    def seed():
        with db._session() as s:
            s.execute(text("DELETE FROM activities"))
            for r in rows:
                s.add(
                    Activity(
                        name="a",
                        date="2026-11-01",
                        distance_m=10000.0,
                        effort_efficiency_score=99.0,
                        **r,
                    )
                )
            s.commit()

    seed()
    db.renormalize_effort_efficiency()
    python_scores = _scores()

    seed()
    path = Path(__file__).parent.parent / "alembic" / "versions" / "021_efficiency_runs_only.py"
    spec = importlib.util.spec_from_file_location("m021", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with get_engine().begin() as conn:
        migration.op = SimpleNamespace(execute=lambda sql: conn.execute(text(sql)))
        migration.upgrade()
    assert _scores() == python_scores
    assert python_scores[3] is None and python_scores[5] is not None and python_scores[6] is None
    assert python_scores[8] == 99.0  # no raw value: never touched
