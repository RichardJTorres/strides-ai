import json
import xml.etree.ElementTree as ET

from strides_ai.workout_structure import (
    normalize_structure,
    render_text,
    structure_for_type,
    structure_to_json,
    to_zwo,
    total_seconds,
    zwo_filename,
)

GOOD = {
    "blocks": [
        {"kind": "warmup", "duration_s": 600, "from_pct": 0.5, "to_pct": 0.75},
        {"kind": "steady", "duration_s": 300, "pct": 0.9},
        {
            "kind": "intervals",
            "repeat": 5,
            "on_s": 240,
            "on_pct": 1.05,
            "off_s": 180,
            "off_pct": 0.55,
        },
        {"kind": "freeride", "duration_s": 120},
        {"kind": "cooldown", "duration_s": 300, "from_pct": 0.7, "to_pct": 0.45},
    ]
}


def test_valid_structure_round_trips_unchanged():
    assert normalize_structure(GOOD) == GOOD
    assert normalize_structure(json.dumps(GOOD)) == GOOD


def test_none_garbage_and_empty_become_none():
    for raw in (None, "", "not json", 5, [], {}, {"blocks": []}, {"blocks": "x"}, '{"blocks": 3}'):
        assert normalize_structure(raw) is None


def test_invalid_blocks_are_dropped_not_the_whole_structure():
    raw = {
        "blocks": [
            {"kind": "steady", "duration_s": 300, "pct": 0.8},
            {"kind": "bogus", "duration_s": 300},
            {"kind": "steady", "duration_s": "abc", "pct": 0.8},
            {"kind": "steady", "duration_s": True, "pct": 0.8},
            {"kind": "steady", "pct": 0.8},
            "text",
        ]
    }
    assert normalize_structure(raw) == {
        "blocks": [{"kind": "steady", "duration_s": 300, "pct": 0.8}]
    }


def test_values_are_clamped_and_extra_keys_stripped():
    out = normalize_structure(
        {
            "blocks": [
                {"kind": "steady", "duration_s": 1, "pct": 9, "junk": 1},
                {
                    "kind": "intervals",
                    "repeat": 500,
                    "on_s": 20,
                    "on_pct": 0,
                    "off_s": 30,
                    "off_pct": 0.5,
                },
                {"kind": "freeride", "duration_s": 99999},
            ]
        }
    )
    assert out["blocks"][0] == {"kind": "steady", "duration_s": 10, "pct": 2.0}
    assert out["blocks"][1]["repeat"] == 50 and out["blocks"][1]["on_pct"] == 0.3
    assert out["blocks"][2]["duration_s"] == 14400


def test_total_duration_and_block_caps():
    assert total_seconds(GOOD) == 600 + 300 + 5 * 420 + 120 + 300
    many = {"blocks": [{"kind": "steady", "duration_s": 600, "pct": 0.6}] * 60}
    assert len(normalize_structure(many)["blocks"]) == 36  # capped by the 6 h total, not 40
    short = {"blocks": [{"kind": "steady", "duration_s": 10, "pct": 0.6}] * 60}
    assert len(normalize_structure(short)["blocks"]) == 40


def test_structure_only_allowed_on_cycling_types():
    assert structure_for_type("Indoor Ride", GOOD) == GOOD
    assert structure_for_type("Easy Run", GOOD) is None
    assert structure_for_type(None, GOOD) is None


def test_storage_form_is_null_for_no_structure():
    assert structure_to_json(None) is None
    assert json.loads(structure_to_json(GOOD)) == GOOD


def test_render_text():
    assert render_text(GOOD).startswith(
        "10:00 warmup 50→75% · 5:00 @ 90% · 5×(4:00 @ 105%, 3:00 @ 55%)"
    )
    assert render_text(None) == ""


def test_zwo_is_valid_xml_with_expected_elements():
    xml = to_zwo(GOOD, 'Indoor <Ride> & "Co"', "desc & more")
    root = ET.fromstring(xml)
    assert root.findtext("name") == 'Indoor <Ride> & "Co"'
    assert root.findtext("sportType") == "bike"
    tags = [e.tag for e in root.find("workout")]
    assert tags == ["Warmup", "SteadyState", "IntervalsT", "FreeRide", "Cooldown"]
    iv = root.find("workout/IntervalsT")
    assert iv.attrib == {
        "Repeat": "5",
        "OnDuration": "240",
        "OffDuration": "180",
        "OnPower": "1.05",
        "OffPower": "0.55",
    }
    assert root.find("workout/SteadyState").attrib == {"Duration": "300", "Power": "0.9"}


def test_zwo_filename_is_ascii_safe():
    assert zwo_filename("2026-10-02", 'Indoor <Ride> / "x"') == "2026-10-02-indoor-ride-x.zwo"
    assert zwo_filename("2026-10-02", "???") == "2026-10-02-workout.zwo"
