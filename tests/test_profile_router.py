"""Profile routes, max HR resolution, and the update_profile backend tool."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlmodel import Session

from strides_ai import db
from strides_ai.api.routers import profile as router
from strides_ai.backends.base import BaseBackend
from strides_ai.budget import Limits, TurnBudget
from strides_ai.db import profiles as crud
from strides_ai.db.engine import get_engine


@pytest.fixture
def req(monkeypatch):
    monkeypatch.setattr(router, "init_backend", lambda app: None)
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(mode="running")))


def _put(req, section, fields):
    with Session(get_engine()) as s:
        return router.put_profile_section(section, req, router.SectionBody(fields=fields), s)


def _get(req, mode=None):
    with Session(get_engine()) as s:
        return router.get_profile(req, mode, s)


def test_get_returns_defaults_completeness_and_mode_sections(tmp_db, req):
    out = _get(req)
    assert out["fields"]["running"]["bests"]["5k"] == ""
    assert out["mode_sections"] == {"active": ["running"], "other": ["cycling", "lifting"]}
    assert out["completeness"]["percent"] == 0
    assert out["races"] == [] and set(out["updated"]) == {"shared", "running", "cycling", "lifting"}
    assert _get(req, "hybrid")["mode_sections"]["active"] == ["running", "cycling"]


def test_put_section_merges_and_other_sections_untouched(tmp_db, req):
    _put(req, "shared", {"goals": "Sub-3", "personal": {"name": "Alice", "max_hr": 188}})
    _put(req, "running", {"bests": {"5k": "20:00"}})
    _put(req, "running", {"bests": {"10k": "42:00"}, "since": "2015"})
    _put(req, "shared", {"injuries_and_health": "Knee"})
    fields = _get(req, "cycling")["fields"]  # visible from another mode
    assert fields["goals"] == "Sub-3" and fields["injuries_and_health"] == "Knee"
    assert fields["personal"]["name"] == "Alice"
    assert (
        fields["running"]["bests"]["5k"] == "20:00" and fields["running"]["bests"]["10k"] == "42:00"
    )
    assert fields["running"]["since"] == "2015"


@pytest.mark.parametrize(
    "section,fields",
    [
        ("shared", {"personal": {"max_hr": 20}}),
        ("shared", {"personal": {"max_hr": "fast"}}),
        ("shared", {"availability": {"preferred_days": ["funday"]}}),
        ("shared", {"mystery": "x"}),
        ("running", {"bests": {"nope": "x"}}),
        ("running", {"gear_typo": "x"}),
    ],
)
def test_put_rejects_invalid_bodies(tmp_db, req, section, fields):
    with pytest.raises(HTTPException) as exc:
        _put(req, section, fields)
    assert exc.value.status_code == 422


def test_unknown_section_is_404(tmp_db, req):
    with pytest.raises(HTTPException) as exc:
        _put(req, "hybrid", {})
    assert exc.value.status_code == 404


def test_voice_update_does_not_clobber_other_shared_fields(tmp_db, req):
    _put(req, "shared", {"goals": "Sub-3"})
    _put(req, "shared", {"coach_voice": "drill_sergeant"})
    fields = _get(req)["fields"]
    assert fields["goals"] == "Sub-3" and fields["coach_voice"] == "drill_sergeant"


def test_reset_shared_keeps_body_measurements_and_voice(tmp_db, req):
    _put(
        req,
        "shared",
        {"goals": "x", "coach_voice": "calm", "personal": {"name": "A", "height_cm": 180}},
    )
    with Session(get_engine()) as s:
        router.reset_profile_section("shared", req, s)
    fields = _get(req)["fields"]
    assert fields["goals"] == "" and fields["coach_voice"] == "calm"
    assert fields["personal"]["height_cm"] == 180


def test_reset_discipline(tmp_db, req):
    _put(req, "lifting", {"since": "2019"})
    with Session(get_engine()) as s:
        router.reset_profile_section("lifting", req, s)
    assert _get(req)["fields"]["lifting"]["since"] == ""


# ── max HR ────────────────────────────────────────────────────────────────────


def test_max_hr_resolution_order(tmp_db, req):
    assert db.get_max_hr() == 190
    db.set_setting("max_hr", "181")
    assert db.get_max_hr() == 181  # legacy setting fallback
    _put(req, "shared", {"personal": {"max_hr": 175}})
    assert db.get_max_hr() == 175  # profile wins
    _put(req, "shared", {"personal": {"max_hr": None}})
    assert db.get_max_hr() == 181  # clearing the profile value falls back, not stuck at 175
    db.set_setting("max_hr", "")
    assert db.get_max_hr() == 190


# ── update_profile tool ───────────────────────────────────────────────────────


class _Stub(BaseBackend):
    label = "stub"
    supports_attachments = False

    def stream_turn(self, *a, **k): ...

    def stateless_turn(self, *a, **k): ...

    def _count_request(self, *a, **k):
        return 0


def _stub():
    b = _Stub.__new__(_Stub)
    b._budget = TurnBudget(Limits())
    return b


def test_update_profile_tool_records_proposal_without_writing(tmp_db):
    b = _stub()
    msg = b._execute_update_profile({"field": "goals", "value": "Run Boston"})
    assert "Not saved yet" in msg
    proposals = b.take_profile_proposals()
    assert proposals[0]["fields"] == {"goals": "Run Boston"}
    assert db.get_profile_fields() is None  # nothing persisted


def test_update_profile_tool_rejects_bad_field_with_reason(tmp_db):
    b = _stub()
    msg = b._execute_update_profile({"field": "coach_voice", "value": "x"})
    assert msg.startswith("Rejected") and b.take_profile_proposals() == []


# ── review fixes ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "section,fields",
    [
        ("shared", {"personal": None}),
        ("shared", {"availability": None}),
        ("shared", {"nutrition_snacks": None}),
        ("running", {"bests": None}),
    ],
)
def test_put_rejects_explicit_null_objects(tmp_db, req, section, fields):
    with pytest.raises(HTTPException) as exc:
        _put(req, section, fields)
    assert exc.value.status_code == 422


def test_accepting_two_availability_proposals_keeps_both(tmp_db, req):
    from strides_ai.profile import build_profile_proposal

    a = build_profile_proposal({"field": "availability.sessions_per_week", "value": "5"}, None)
    b = build_profile_proposal({"field": "availability.long_session_day", "value": "sat"}, None)
    assert a["fields"] == {"availability": {"sessions_per_week": 5}}
    for p in (a, b):
        _put(req, p["section"], p["fields"])
    avail = _get(req)["fields"]["availability"]
    assert avail["sessions_per_week"] == 5 and avail["long_session_day"] == "sat"


def test_personal_proposal_does_not_clobber_intervening_edits(tmp_db, req):
    from strides_ai.profile import build_profile_proposal

    p = build_profile_proposal({"field": "personal.max_hr", "value": "185"}, None)
    _put(req, "shared", {"personal": {"name": "Alice"}})  # edit made after the proposal snapshot
    _put(req, p["section"], p["fields"])
    personal = _get(req)["fields"]["personal"]
    assert personal["name"] == "Alice" and personal["max_hr"] == 185
