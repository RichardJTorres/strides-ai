"""Tests for the unit registry, model measurement helpers, and the unit_system setting."""

import json
from pathlib import Path

import pytest
from sqlmodel import Session

from strides_ai.db.models import Activity, TrainingPlan
from strides_ai.units import (
    DEFAULT_UNIT_SYSTEM,
    Quantity,
    UnitSystem,
    convert,
    format_value,
    format_speed_from_pace,
    to_si,
    unit_label,
)

CASES = json.loads((Path(__file__).parent / "fixtures" / "unit_cases.json").read_text())
M, I = UnitSystem.METRIC, UnitSystem.IMPERIAL


# ── Registry (shared fixture — the TS mirror asserts the same cases) ──────────


@pytest.mark.parametrize("case", CASES["convert"], ids=lambda c: c["qty"])
def test_convert_matches_shared_fixture(case):
    qty = Quantity(case["qty"])
    assert convert(case["si"], qty, M) == pytest.approx(case["metric"], rel=1e-5)
    assert convert(case["si"], qty, I) == pytest.approx(case["imperial"], rel=1e-5)


@pytest.mark.parametrize("case", CASES["format"], ids=lambda c: f"{c['qty']}:{c['si']}")
def test_format_matches_shared_fixture(case):
    qty = Quantity(case["qty"])
    assert format_value(case["si"], qty, M) == case["metric"]
    assert format_value(case["si"], qty, I) == case["imperial"]


@pytest.mark.parametrize("qty", list(Quantity))
@pytest.mark.parametrize("system", list(UnitSystem))
def test_to_si_round_trips(qty, system):
    assert to_si(convert(1234.5, qty, system), qty, system) == pytest.approx(1234.5)


def test_every_quantity_has_both_systems():
    for qty in Quantity:
        assert unit_label(qty, M) and unit_label(qty, I)
        assert unit_label(qty, M) != unit_label(qty, I)


def test_none_passes_through():
    assert convert(None, Quantity.DISTANCE, I) is None
    assert to_si(None, Quantity.DISTANCE, I) is None
    assert format_value(None, Quantity.DISTANCE, I) == "—"
    assert format_value(None, Quantity.DISTANCE, I, empty="-") == "-"


def test_format_options():
    assert format_value(10000, Quantity.DISTANCE, I, decimals=1) == "6.2 mi"
    assert format_value(10000, Quantity.DISTANCE, M, with_label=False) == "10.00"
    assert format_value(361.9, Quantity.PACE, M) == "6:01/km"


def test_speed_from_pace():
    assert format_speed_from_pace(360, M) == "10.0 km/h"
    assert format_speed_from_pace(360, I) == "6.2 mph"
    assert format_speed_from_pace(0, M) == "—"
    assert format_speed_from_pace(None, M) == "—"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("metric", M),
        ("imperial", I),
        ("km", M),
        ("miles", I),
        ("IMPERIAL ", I),
        (None, DEFAULT_UNIT_SYSTEM),
        ("furlongs", DEFAULT_UNIT_SYSTEM),
        (object(), DEFAULT_UNIT_SYSTEM),
    ],
)
def test_parse(raw, expected):
    assert UnitSystem.parse(raw) is expected


def test_default_is_metric():
    assert DEFAULT_UNIT_SYSTEM is UnitSystem.METRIC


# ── Model-level helpers ────────────────────────────────────────────────────────


def test_activity_measurements_resolve_both_systems():
    a = Activity(id=1, distance_m=10000, avg_pace_s_per_km=300, total_volume_kg=100)
    assert a.measurement("distance_m", M).formatted == "10.00 km"
    imperial = a.measurements(I)
    assert imperial["distance_m"].formatted == "6.21 mi"
    assert imperial["distance_m"].unit == "mi"
    assert imperial["avg_pace_s_per_km"].formatted == "8:02/mi"
    assert imperial["total_volume_kg"].value == pytest.approx(220.462)


def test_measurements_skip_missing_fields():
    a = Activity(id=1, distance_m=5000)
    assert set(a.measurements(I)) == {"distance_m"}
    assert a.measurement("elevation_gain_m", I) is None


def test_training_plan_scales_stored_km():
    w = TrainingPlan(date="2026-10-20", distance_km=8.04672, elevation_m=100)
    assert w.measurement("distance_km", I).formatted == "5.00 mi"
    assert w.measurement("distance_km", M).formatted == "8.05 km"
    assert w.measurement("elevation_m", I).formatted == "328 ft"


def test_measure_field_works_on_plain_dicts():
    row = {"distance_km": 10.0}
    assert TrainingPlan.measure_field(row, "distance_km", I).formatted == "6.21 mi"


def test_every_declared_measurement_is_a_real_column():
    for model in (Activity, TrainingPlan):
        for field in model.__measurements__:
            assert field in model.model_fields, f"{model.__name__}.{field}"


# ── unit_system setting ────────────────────────────────────────────────────────


def _settings_call(fn, **kwargs):
    from strides_ai.db.engine import get_engine

    with Session(get_engine()) as session:
        return fn(session=session, **kwargs)


def test_settings_default_unit_system_is_metric(tmp_db):
    from strides_ai.api.routers.settings import get_api_settings

    assert _settings_call(get_api_settings)["unit_system"] == "metric"


def test_settings_put_unit_system(tmp_db):
    from strides_ai.api.routers.settings import SettingsBody, put_settings
    from strides_ai import db

    result = _settings_call(put_settings, request=None, body=SettingsBody(unit_system="imperial"))
    assert result["unit_system"] == "imperial"
    assert db.get_unit_system() is UnitSystem.IMPERIAL


def test_settings_put_invalid_unit_system_is_400(tmp_db):
    from fastapi import HTTPException

    from strides_ai.api.routers.settings import SettingsBody, put_settings

    with pytest.raises(HTTPException) as exc_info:
        _settings_call(put_settings, request=None, body=SettingsBody(unit_system="furlongs"))
    assert exc_info.value.status_code == 400


def test_charts_default_to_unit_setting(tmp_db):
    from strides_ai import db
    from strides_ai.api.routers.charts import charts

    db.set_setting("unit_system", "imperial")
    assert _settings_call(charts, unit=None, mode="running", units=I)["unit"] == "miles"
    assert _settings_call(charts, unit=None, mode="running", units=M)["unit"] == "km"
    # An explicit ?unit= still wins.
    assert _settings_call(charts, unit="km", mode="running", units=I)["unit"] == "km"


# ── Migration 011 ───────────────────────────────────────────────────────────────


def test_migration_011_converts_imperial_columns_to_si(tmp_path, monkeypatch):
    import sqlalchemy as sa
    from alembic import command

    from strides_ai.db import engine

    monkeypatch.setattr(engine, "DB_PATH", tmp_path / "old.db")
    engine.reset_engine()
    cfg = engine._make_alembic_config()
    command.upgrade(cfg, "010")
    with engine.get_engine().begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO activities (id, elevation_per_mile, pace_fade_seconds) "
                "VALUES (1, 100.0, 16.09344)"
            )
        )
    command.upgrade(cfg, "011")
    with engine.get_engine().connect() as conn:
        climb, fade = conn.execute(
            sa.text("SELECT climb_m_per_km, pace_fade_s_per_km FROM activities")
        ).one()
    assert climb == pytest.approx(18.9394, rel=1e-4)  # 100 ft/mi
    assert fade == pytest.approx(10.0)  # 16.09 s/mi

    command.downgrade(cfg, "010")
    with engine.get_engine().connect() as conn:
        per_mile, fade_mi = conn.execute(
            sa.text("SELECT elevation_per_mile, pace_fade_seconds FROM activities")
        ).one()
    assert per_mile == pytest.approx(100.0)
    assert fade_mi == pytest.approx(16.09344)
    engine.reset_engine()
