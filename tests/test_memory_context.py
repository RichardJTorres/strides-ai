"""Dated context selection and persistence regression tests."""

from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from strides_ai import db
from strides_ai.api.routers.memories import router
from strides_ai.db.engine import get_engine, get_session
from strides_ai.memory_context import memories_section, resolve_memories


def fact(id, **kwargs):
    return {"id": id, "category": "preference", "content": f"Fact {id}", **kwargs}


def ids(facts, day):
    return [m["id"] for m in resolve_memories(facts, date.fromisoformat(day))]


def test_temporary_override_and_baseline_resumes():
    facts = [
        fact(1, topic="running_intensity", status="current", effective_from="2026-01-01"),
        fact(
            2,
            topic="running_intensity",
            status="temporary",
            effective_from="2026-10-14",
            effective_until="2026-10-20",
        ),
        fact(3, topic="cycling_goal", status="current"),
    ]
    assert ids(facts, "2026-10-13") == [1, 3]
    assert ids(facts, "2026-10-14") == [2, 3]
    assert ids(facts, "2026-10-20") == [2, 3]
    assert ids(facts, "2026-10-21") == [1, 3]


def test_superseded_future_expired_and_unrelated_facts():
    facts = [
        fact(1),
        fact(2),
        fact(3, status="superseded"),
        fact(4, effective_from="2027-01-01"),
        fact(5, effective_until="2026-01-01"),
    ]
    assert ids(facts, "2026-10-15") == [1, 2]


def test_newer_standing_fact_wins_and_unknown_expiry_remains():
    facts = [
        fact(1, topic="goal", effective_from="2025-01-01"),
        fact(2, topic="goal", effective_from="2026-01-01"),
        fact(3, topic="goal", status="temporary", effective_from="2026-10-01"),
    ]
    assert ids(facts[:2], "2026-10-15") == [2]
    assert ids(facts, "2028-01-01") == [3]


def test_prompt_excludes_inactive_facts_but_keeps_precedence_instructions():
    text = memories_section([fact(1, status="superseded"), fact(2)])
    assert "Fact 1" not in text and "Fact 2" in text
    assert "profile goals/preferences" in text
    assert "superseded instructions" in memories_section([fact(1, status="superseded")])


def test_persistence_and_revision(tmp_db):
    assert db.save_memory("goal", "Cycling priority", topic=" Primary_Goal ") == "Memory saved."
    memory = db.get_all_memories()[0]
    assert memory["topic"] == "primary_goal"
    assert memory["effective_from"] == date.today().isoformat()
    assert (
        db.save_memory("goal", "Cycling priority", memory_id=memory["id"], status="superseded")
        == "Memory updated."
    )
    assert db.get_all_memories()[0]["status"] == "superseded"
    assert db.save_memory(
        "goal", "Bad date", effective_from="2026-12-01", effective_until="2026-01-01"
    ).startswith("Error:")
    assert len(db.get_all_memories()) == 1


@pytest.fixture
def client(tmp_db):
    app = FastAPI()
    app.include_router(router)

    def session():
        with Session(get_engine()) as s:
            yield s

    app.dependency_overrides[get_session] = session
    with TestClient(app) as c:
        yield c


def test_api_dates_partial_updates_and_applicability(client):
    db.save_memory("preference", "Standing", topic="intensity", effective_from="2026-01-01")
    db.save_memory(
        "preference",
        "Temporary",
        topic="intensity",
        status="temporary",
        effective_from="2026-01-01",
    )
    rows = client.get("/memories").json()
    assert [r["applicable"] for r in rows] == [False, True]
    row = rows[1]
    response = client.put(
        f"/memories/{row['id']}",
        json={"category": row["category"], "content": row["content"], "status": "superseded"},
    )
    assert response.status_code == 200
    assert response.json()["topic"] == "intensity"
    assert client.get("/memories").json()[0]["applicable"] is True
    for change in [
        {"status": "bad"},
        {"effective_from": "nonsense"},
        {"effective_until": "2025-01-01"},
        {"content": "   "},
    ]:
        body = {"category": "preference", "content": "Standing", **change}
        assert client.put(f"/memories/{rows[0]['id']}", json=body).status_code == 422


def test_upgrade_legacy_memories(tmp_path, monkeypatch):
    from alembic import command
    from strides_ai.db import engine

    monkeypatch.setattr(engine, "DB_PATH", tmp_path / "old.db")
    engine.reset_engine()
    cfg = engine._make_alembic_config()
    command.upgrade(cfg, "009")
    import sqlalchemy as sa

    with engine.get_engine().begin() as conn:
        conn.execute(
            sa.text("INSERT INTO memories (category, content) VALUES ('goal', 'Legacy fact')")
        )
    command.upgrade(cfg, "head")
    with engine.get_engine().connect() as conn:
        row = conn.execute(sa.text("SELECT content, status, effective_from FROM memories")).one()
    assert tuple(row) == ("Legacy fact", "current", None)
    engine.reset_engine()


def test_future_plan_uses_correct_context_for_each_period():
    from strides_ai.memory_context import memory_timeline_section

    facts = [
        fact(1, topic="intensity", effective_from="2026-01-01"),
        fact(
            2,
            topic="intensity",
            status="temporary",
            effective_from="2026-10-14",
            effective_until="2026-10-20",
        ),
    ]
    text = memory_timeline_section(facts, date(2026, 10, 15), date(2026, 10, 25))
    before, after = text.split("### 2026-10-21")
    assert "Fact 2" in before and "Fact 1" not in before
    assert "Fact 1" in after and "Fact 2" not in after


def test_new_permanent_preference_can_replace_temporary_change():
    facts = [
        fact(1, topic="intensity", status="temporary", effective_from="2026-10-01"),
        fact(2, topic="intensity", status="current", effective_from="2026-10-15"),
    ]
    assert ids(facts, "2026-10-16") == [2]
