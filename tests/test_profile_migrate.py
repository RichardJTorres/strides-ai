"""Legacy per-mode profile rows -> unified shared/running/cycling/lifting rows."""

import json

import sqlalchemy as sa

from strides_ai.profile_migrate import migrate_profile_rows, unify_rows


def test_shared_text_is_merged_without_duplicates():
    old = {
        "running": {"goals": "Sub-3", "injuries_and_health": "Left knee"},
        "cycling": {"goals": "  sub-3 ", "injuries_and_health": "Sore back"},
        "hybrid": {"goals": "Triathlon", "other_notes": "Early mornings"},
    }
    s = unify_rows(old)["shared"]
    assert s["goals"] == "Sub-3\n\nTriathlon"
    assert s["injuries_and_health"] == "Left knee\n\nSore back"
    assert s["other_notes"] == "Early mornings"


def test_snacks_union_and_voice_first_nonempty():
    old = {
        "running": {"nutrition_snacks": ["Gels", "Bananas"], "coach_voice": ""},
        "cycling": {"nutrition_snacks": ["gels", "Bars"], "coach_voice": "drill_sergeant"},
    }
    s = unify_rows(old)["shared"]
    assert s["nutrition_snacks"] == ["Gels", "Bananas", "Bars"]
    assert s["coach_voice"] == "drill_sergeant"


def test_hybrid_keys_fill_blank_running_and_cycling_fields():
    old = {
        "running": {"running_background": {"running_since": "2015"}},
        "hybrid": {
            "running_background": {"running_since": "2010", "weekly_run_volume": "40 km"},
            "running_bests": {"5k": "20:00"},
            "cycling_background": {"weekly_ride_distance": "120 km"},
            "cycling_bests": {"ftp": "250"},
        },
    }
    out = unify_rows(old)
    assert out["running"]["since"] == "2015"  # the running row wins
    assert out["running"]["volume"] == "40 km"
    assert out["running"]["bests"]["5k"] == "20:00"
    assert out["cycling"]["volume"] == "120 km"
    assert out["cycling"]["bests"]["ftp"] == "250"


def test_running_row_keys_are_renamed():
    old = {
        "running": {
            "running_background": {
                "weekly_volume": "50 km",
                "running_focus": "trail",
                "background": "b",
            },
            "personal_bests": {"marathon": "3:05"},
            "gear": "Shoes",
        }
    }
    r = unify_rows(old)["running"]
    assert (r["volume"], r["focus"], r["background"], r["gear"]) == ("50 km", "trail", "b", "Shoes")
    assert r["bests"]["marathon"] == "3:05"


def test_lifting_equipment_and_stray_gear():
    out = unify_rows({"lifting": {"equipment": "Home gym", "gear": "Belt"}})
    assert out["lifting"]["gear"] == "Home gym"
    out = unify_rows({"lifting": {"gear": "Belt"}})
    assert out["lifting"]["gear"] == "Belt"


def test_hybrid_gear_goes_to_first_empty_discipline():
    assert unify_rows({"hybrid": {"gear": "G"}})["running"]["gear"] == "G"
    out = unify_rows({"running": {"gear": "R"}, "hybrid": {"gear": "G"}})
    assert out["running"]["gear"] == "R" and out["cycling"]["gear"] == "G"
    out = unify_rows({"running": {"gear": "R"}, "cycling": {"gear": "C"}, "hybrid": {"gear": "G"}})
    assert out["running"]["gear"] == "R\n\nG" and out["cycling"]["gear"] == "C"


def test_max_hr_parsing_and_fallback():
    assert unify_rows({"personal": {"max_hr": "188"}})["shared"]["personal"]["max_hr"] == 188
    assert unify_rows({"personal": {"max_hr": "185 bpm"}})["shared"]["personal"]["max_hr"] == 185
    assert unify_rows({"personal": {}}, "176")["shared"]["personal"]["max_hr"] == 176
    p = unify_rows({"personal": {"max_hr": "around 190?"}}, "176")["shared"]["personal"]
    assert p["max_hr"] is None and "around 190?" in p["body_notes"]
    assert unify_rows({})["shared"]["personal"]["max_hr"] is None


def test_legacy_height_weight_are_normalized():
    p = unify_rows({"personal": {"height": "5'10\"", "weight": "170 lb"}})["shared"]["personal"]
    assert round(p["height_cm"], 1) == 177.8 and round(p["weight_kg"], 1) == 77.1


def _conn():
    engine = sa.create_engine("sqlite://")
    conn = engine.connect()
    conn.execute(
        sa.text(
            "CREATE TABLE profiles (mode TEXT PRIMARY KEY, fields_json TEXT, updated_at TEXT DEFAULT (datetime('now')))"
        )
    )
    conn.execute(sa.text("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)"))
    return conn


def _put(conn, mode, data):
    conn.execute(
        sa.text("INSERT INTO profiles (mode, fields_json) VALUES (:m, :f)"),
        {"m": mode, "f": json.dumps(data)},
    )


def test_migrate_rows_is_idempotent_and_keeps_legacy_rows():
    conn = _conn()
    _put(conn, "personal", {"name": "Alice"})
    _put(conn, "running", {"goals": "Sub-3"})
    _put(conn, "hybrid", {"goals": "Tri"})
    conn.execute(sa.text("INSERT INTO settings VALUES ('max_hr', '181')"))

    assert migrate_profile_rows(conn) is True
    modes = {r[0] for r in conn.execute(sa.text("SELECT mode FROM profiles"))}
    assert modes == {
        "shared",
        "running",
        "cycling",
        "lifting",
        "legacy:personal",
        "legacy:running",
        "legacy:hybrid",
    }
    shared = json.loads(
        conn.execute(sa.text("SELECT fields_json FROM profiles WHERE mode='shared'")).scalar()
    )
    assert shared["goals"] == "Sub-3\n\nTri"
    assert shared["personal"]["name"] == "Alice" and shared["personal"]["max_hr"] == 181

    before = conn.execute(
        sa.text("SELECT mode, fields_json FROM profiles ORDER BY mode")
    ).fetchall()
    assert migrate_profile_rows(conn) is False
    assert (
        conn.execute(sa.text("SELECT mode, fields_json FROM profiles ORDER BY mode")).fetchall()
        == before
    )


def test_migrate_rows_noop_on_empty_table():
    assert migrate_profile_rows(_conn()) is False
