"""Profile height/weight: legacy free-text parsing, normalize-on-read, unit-aware rendering."""

import pytest
from sqlmodel import Session

from strides_ai.body_metrics import normalize_personal, parse_height_cm, parse_weight_kg
from strides_ai.db import profiles as crud
from strides_ai.db.engine import get_engine
from strides_ai.profile import get_default_fields, profile_to_text
from strides_ai.units import UnitSystem


@pytest.mark.parametrize(
    "text,cm",
    [
        ("178cm", 178.0),
        ("178 cm", 178.0),
        ("1.78 m", 178.0),
        ("1,78m", 178.0),
        ("178", 178.0),
        ("1.78", 178.0),
        ("5'10\"", 177.8),
        ("5' 10", 177.8),
        ("5’10”", 177.8),
        ("5ft 10in", 177.8),
        ("5 feet 10 inches", 177.8),
        ("6 ft", 182.9),
        ("70 in", 177.8),
    ],
)
def test_parse_height(text, cm):
    assert parse_height_cm(text) == pytest.approx(cm, abs=0.1)


@pytest.mark.parametrize("text", ["", "tall", "70", "5", "about six foot-ish"])
def test_parse_height_rejects_ambiguous(text):
    assert parse_height_cm(text) is None


@pytest.mark.parametrize(
    "text,kg",
    [("77kg", 77.0), ("77 kg", 77.0), ("77.5 kilos", 77.5), ("170 lb", 77.1), ("170 lbs", 77.1)],
)
def test_parse_weight(text, kg):
    assert parse_weight_kg(text) == pytest.approx(kg, abs=0.1)


@pytest.mark.parametrize("text", ["", "77", "heavy", "12 st"])
def test_parse_weight_rejects_ambiguous(text):
    assert parse_weight_kg(text) is None


def test_normalize_moves_parseable_legacy_text():
    p = normalize_personal({"name": "R", "height": "178cm", "weight": "77kg"})
    assert p == {"name": "R", "height_cm": 178.0, "weight_kg": 77.0}


def test_normalize_keeps_unparseable_text_as_note():
    p = normalize_personal({"height": "tall", "weight": "77"})
    assert p == {"body_notes": "Height: tall; Weight: 77"}


def test_normalize_is_idempotent_and_prefers_structured_values():
    once = normalize_personal({"height": "tall", "weight_kg": 70.0, "weight": "77kg"})
    assert once == {"weight_kg": 70.0, "body_notes": "Height: tall"}
    assert normalize_personal(once) == once


def test_defaults_use_structured_fields():
    personal = get_default_fields()["personal"]
    assert personal["height_cm"] is None and personal["weight_kg"] is None
    assert "height" not in personal and "weight" not in personal


def test_get_fields_normalizes_legacy_profile(tmp_db):
    with Session(get_engine()) as s:
        crud.save_section(s, "shared", {"personal": {"height": "5'10\"", "weight": "170 lb"}})
        personal = crud.get_fields(s, "running")["personal"]
    assert personal["height_cm"] == pytest.approx(177.8)
    assert personal["weight_kg"] == pytest.approx(77.1)
    assert "height" not in personal


@pytest.mark.parametrize(
    "system,height,weight",
    [
        (UnitSystem.METRIC, "Height: 178 cm", "Weight: 77.0 kg"),
        (UnitSystem.IMPERIAL, "Height: 5' 10\"", "Weight: 169.8 lb"),
    ],
)
def test_profile_text_renders_in_selected_units(system, height, weight):
    text = profile_to_text({"personal": {"height_cm": 177.8, "weight_kg": 77.0}}, "running", system)
    assert height in text and weight in text


def test_profile_text_renders_legacy_and_notes():
    text = profile_to_text({"personal": {"height": "178cm", "weight": "heavy"}}, "running")
    assert "Height: 178 cm" in text
    assert "Body notes: Weight: heavy" in text
