"""The context builder: required context, capped reducible sections and the degradation ladder."""

from datetime import date, timedelta

import pytest
from fastapi import HTTPException

from strides_ai import coach, db
from strides_ai.api.conversations import ConversationCoordinator
from strides_ai.backends.model_profile import ModelProfile
from strides_ai.budget import ContextPrompt, Limits, PreparedPrompt, Reducible, Required, estimate
from strides_ai.coach import build_system
from strides_ai.context_builder import LADDER, select_context
from strides_ai.db import engine as db_engine
from strides_ai.memory_context import memory_rank_key, split_memories
from tests.plan_helpers import save_planned_workout
from tests.test_backends import _claude_stream


def claude(mocker, window=1_000_000, limits=None):
    mocker.patch("strides_ai.backends.claude.anthropic.Anthropic")
    from strides_ai.backends.claude import ClaudeBackend

    backend = ClaudeBackend("fake", [])
    backend._limits = limits or Limits.derive(
        ModelProfile(context_window=window, max_output=64000), {}, "test"
    )
    return backend


def run(row_id, days_ago, **extra):
    from strides_ai.db.models import Activity

    return Activity(
        id=row_id,
        date=(date.today() - timedelta(days=days_ago)).isoformat(),
        sport_type="Run",
        distance_m=8000,
        moving_time_s=2400,
        elapsed_time_s=2400,
        elevation_gain_m=40,
        name=f"run {row_id}",
        avg_pace_s_per_km=300,
        **extra,
    ).model_dump()


def memories(count, category="preference", size=300):
    return [
        {
            "id": i + 1,
            "category": category,
            "content": f"note {i} " + "x" * size,
            "status": "current",
            "effective_from": None,
            "effective_until": None,
            "topic": None,
        }
        for i in range(count)
    ]


# ── Memory ranking ────────────────────────────────────────────────────────────


def test_memory_rank_is_category_then_newest_start_then_newest_id():
    notes = [
        {"id": 1, "category": "other"},
        {"id": 2, "category": "preference"},
        {"id": 3, "category": "goal", "effective_from": "2026-01-01"},
        {"id": 4, "category": "goal", "effective_from": "2026-03-01"},
        {"id": 5, "category": "goal"},
        {"id": 6, "category": "goal"},
        {"id": 7, "category": "race"},
        {"id": 8, "category": "training"},
        {"id": 9, "category": "injury"},
        {"id": 10, "category": "unknown"},
    ]
    ranked = [m["id"] for m in sorted(notes, key=memory_rank_key)]
    # injury, race, goal (newest start first, undated last, newest id first), training,
    # preference, other, then anything unrecognised.
    assert ranked == [9, 7, 4, 3, 6, 5, 8, 2, 1, 10]


def test_injury_and_temporary_notes_are_protected_the_rest_are_ranked():
    notes = [
        {**memories(1, "injury")[0], "id": 1},
        {**memories(1, "goal")[0], "id": 2, "status": "temporary"},
        {**memories(1, "goal")[0], "id": 3},
        {**memories(1, "race")[0], "id": 4},
    ]
    protected, other = split_memories(notes)
    assert [line.split("id=")[1][0] for line in protected] == ["1", "2"]
    assert [line.split("id=")[1][0] for line in other] == ["4", "3"]


# ── Required context ──────────────────────────────────────────────────────────


def test_protected_memories_too_large_are_rejected_before_anything_is_saved(mocker, tmp_db):
    backend = claude(mocker)
    for i in range(40):
        db.save_memory("injury", f"knee {i} " + "x" * 6000)
    from sqlmodel import Session

    from strides_ai.api.routers.chat import _build_chat_system

    with Session(db_engine.get_engine()) as session:
        system = _build_chat_system(session, "running")
    # A 16k-window model: 9,216 tokens for a request; the notes alone are far above that.
    backend._limits = Limits.derive(ModelProfile(context_window=16384, max_output=64000), {}, "t")
    coordinator = ConversationCoordinator(lambda _: backend)
    turn = coordinator.acquire("running")

    with pytest.raises(HTTPException) as caught:
        coordinator.start(turn, system, "hello", "hello", None)

    assert caught.value.status_code == 413
    message = caught.value.detail
    assert "injury and temporary coaching notes" in message
    assert "larger context window" in message and "Shorten" in message
    assert message.count("tokens)") == 3  # names the three largest parts
    assert db.get_recent_messages(mode="running") == []
    backend._client.messages.stream.assert_not_called()


@pytest.mark.parametrize("window, admitted", [(16384, True), (8192, False)])
def test_smallest_supported_window_admits_and_a_smaller_one_rejects(
    mocker, tmp_db, window, admitted
):
    backend = claude(mocker, window)
    system = build_system("", [])
    if admitted:
        backend.prepare_turn(system, "hello", None)
        assert backend._admission["required_est"] <= backend.limits.context_target
    else:
        with pytest.raises(ValueError, match="larger context window"):
            backend.prepare_turn(system, "hello", None)


def test_required_sections_are_never_reduced(mocker, tmp_db):
    backend = claude(mocker, 16384)
    system = build_system("PROFILE-TEXT", [], coach_voice="technical", activities=[run(1, 1)] * 30)
    sent = backend.prepare_turn(system, "hello", None)
    for required in system.required:
        assert required.text in sent


# ── Reducible sections and the ladder ─────────────────────────────────────────


def test_oversized_ordinary_memories_do_not_remove_the_sections_after_them(mocker, tmp_db):
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    save_planned_workout(tomorrow, "Easy Run", None, 5.0, None, 30, "easy")
    rows = [run(i, i + 1) for i in range(40)]
    system = build_system(
        "PROFILE", memories(200, size=400), activities=rows, coach_voice="technical"
    )
    assert len(str(system)) > 80_000
    backend = claude(mocker)

    sent = backend.prepare_turn(system, "hello", None)

    sections = {s["key"]: s for s in backend._admission["sections"]}
    assert 0 < sections["other_memories"]["level"] < sections["other_memories"]["full"]
    assert sections["other_memories"]["est"] <= sections["other_memories"]["cap"]
    # What used to be lost behind one big section is still there.
    for text in ("Coaching Voice", "Upcoming Planned Workouts", "Recent Activities", "Training"):
        assert text in sent
    assert sections["recent_activities"]["level"] == 30
    assert "notes omitted" in sent
    assert backend._admission["ladder"] == []


def test_activities_are_one_table_with_one_header(tmp_db):
    rows = [run(i, i + 1) for i in range(30)]
    system = str(build_system("", [], activities=rows))
    header = coach.MODES["running"].log_header(coach.DEFAULT_UNIT_SYSTEM)
    assert system.count(header) == 1
    assert system.count("## Recent Activities") == 1
    assert "ACTIVITY" not in system


def test_a_shorter_activity_table_keeps_the_same_columns(tmp_db):
    rows = [run(i, i + 1) for i in range(30)]
    rows[20]["sport_type"] = "Ride"  # outside the newest 7, still decides the formatter
    prompt = build_system("", [], activities=rows, mode="running")
    part = next(p for p in prompt.reducible if p.key == "recent_activities")
    assert part.render(7).splitlines()[2] == part.render(30).splitlines()[2]


def test_omission_labels_say_what_was_left_out(mocker, tmp_db):
    rows = [run(i, i + 1) for i in range(30)]
    system = build_system("", memories(60, size=900), activities=rows)
    backend = claude(mocker, 36_000)
    sent = backend.prepare_turn(system, "hello", None)
    assert "## Context Omitted" in sent
    assert "notes omitted" in sent
    assert backend.limits.context_target < 25_000


def select(prompt, groups=(), target=1000, **kw):
    """select_context with sizes counted in characters, so every number is easy to follow."""
    return select_context(
        prompt,
        list(groups),
        target=target,
        cost=lambda value: len(str(value)) if value else 0,
        size=lambda text, history: len(text) + len(str(history)) * bool(history),
        max_pairs=20,
        **kw,
    )


def ladder_prompt(required=600):
    return ContextPrompt(
        [
            Required("mandatory", "base", "m" * required),
            Reducible("other_memories", 0.15, lambda k: "n" * 18 * k, full=8, join="\n"),
            Reducible("upcoming_later", 0.10, lambda k: "u" * k, full=60, levels=(60, 28, 0)),
            Reducible("progress_group", 0.05, lambda k: "p" * 30, full=1, levels=(1, 0)),
            Reducible(
                "recent_activities", 0.25, lambda k: "r" * 3 * k, full=30, levels=(30, 15, 7, 0)
            ),
            Reducible("older_summary", 0.10, lambda k: "o" * 30, full=1, levels=(1, 0)),
        ]
    )


PAIRS = [
    [{"role": "user", "content": "q" * 40}, {"role": "assistant", "content": "a" * 40}]
    for _ in range(10)
]


def test_ladder_steps_run_in_the_plan_order_until_the_request_fits():
    prompt = ladder_prompt()
    roomy = select(prompt, PAIRS, target=100_000)
    assert roomy.ladder == [] and roomy.pairs == 10 and roomy.knobs["recent_activities"] == 30
    chosen = select(prompt, PAIRS, target=1000)
    names = [name for name, *_ in LADDER]
    assert [names.index(step) for step in chosen.ladder] == sorted(
        names.index(step) for step in chosen.ladder
    )
    assert chosen.ladder[0] == "older_summary:drop"
    assert "recent_activities:none" not in chosen.ladder  # it fit well before the last step
    assert chosen.knobs["older_summary"] == 0


def test_ladder_ends_at_the_required_context_alone_in_full_order():
    prompt = ladder_prompt()
    required = select(prompt, PAIRS, target=100_000).required_est
    # The target is exactly the required context: every reducible section must go.
    floor = select(prompt, PAIRS, target=required)
    assert set(floor.knobs.values()) == {0} and floor.pairs == 0
    assert floor.ladder[0] == "older_summary:drop" and floor.ladder[-1] == "recent_activities:none"
    expected = [name for name, *_ in LADDER]
    # Steps that would change nothing (a section already lower) are skipped, never reordered.
    assert [step for step in expected if step in floor.ladder] == floor.ladder


def test_ladder_halves_other_memories_by_rank_before_dropping_them():
    prompt = ContextPrompt(
        [
            Required("mandatory", "base", "m" * 100),
            Reducible("other_memories", 1.0, lambda k: "n" * 20 * k, full=8, join="\n"),
        ]
    )
    chosen = select(prompt, target=100 + 20 * 4 + 5)
    assert chosen.knobs["other_memories"] == 4
    assert chosen.ladder == ["other_memories:halve"]


def test_each_section_starts_at_the_fullest_level_within_its_cap():
    prompt = ContextPrompt(
        [
            Required("mandatory", "base", "m" * 10),
            Reducible(
                "recent_activities", 0.25, lambda k: "r" * k, full=200, levels=(200, 100, 50, 0)
            ),
            Reducible("older_summary", 0.10, lambda k: "o" * 200, full=1, levels=(1, 0)),
        ]
    )
    chosen = select(prompt, target=1000)
    # 250 characters allowed: the 200-row level fits. The 200-character summary exceeds its 100.
    assert chosen.knobs == {"recent_activities": 200, "older_summary": 0}
    assert select(prompt, target=300).knobs["recent_activities"] == 50  # 75 allowed


def test_caps_hold_on_real_prompts_at_every_window(mocker, tmp_db):
    rows = [run(i, i + 1) for i in range(60)]
    history = [
        {"role": role, "content": f"{i} " + "history " * 150}
        for i in range(30)
        for role in ("user", "assistant")
    ]
    for window in (20_000, 36_000, 100_000, 1_000_000):
        backend = claude(mocker, window)
        backend._history = list(history)
        system = build_system("PROFILE", memories(80), activities=rows)
        backend.prepare_turn(system, "hello", None)
        admission = backend._admission
        for section in admission["sections"]:
            if section["kind"] == "reducible":
                assert section["est"] <= section["cap"], (window, section["key"])
        assert admission["history"]["est"] <= admission["history"]["cap"]
        assert admission["est_input"] <= backend.limits.context_target
        assert backend._retained_messages == admission["history"]["messages"]


def test_history_keeps_the_newest_whole_pairs_that_fit_its_cap(mocker, tmp_db):
    backend = claude(mocker, 36_000)
    backend._history = [
        {"role": role, "content": f"{i} " + "history " * 400}
        for i in range(30)
        for role in ("user", "assistant")
    ]
    backend.prepare_turn(build_system("", []), "hello", None)
    kept = backend._history
    assert len(kept) % 2 == 0 and 0 < len(kept) < 60
    assert kept[-1]["content"].startswith("29 ") and kept[0]["role"] == "user"


# ── Date and time last, stable prefix ─────────────────────────────────────────


def test_date_and_time_come_last_and_the_rest_is_byte_stable(mocker, tmp_db, monkeypatch):
    backend = claude(mocker)
    rows = [run(i, i + 1) for i in range(5)]
    monkeypatch.setattr(coach, "_datetime_section", lambda: "## Current Date & Time\nMonday 9:00")
    first = backend.prepare_turn(build_system("PROFILE", memories(3), activities=rows), "hi", None)
    monkeypatch.setattr(coach, "_datetime_section", lambda: "## Current Date & Time\nMonday 9:05")
    second = backend.prepare_turn(build_system("PROFILE", memories(3), activities=rows), "hi", None)

    assert isinstance(first, PreparedPrompt)
    assert first.stable == second.stable and first.tail != second.tail
    assert first.endswith("Monday 9:00") and second.endswith("Monday 9:05")
    assert "Current Date" not in first.stable


def test_claude_sends_the_stable_part_and_the_date_as_two_blocks(mocker, tmp_db):
    client = mocker.patch("strides_ai.backends.claude.anthropic.Anthropic").return_value
    client.messages.stream.return_value = _claude_stream(["hi"])
    from strides_ai.backends.claude import ClaudeBackend

    backend = ClaudeBackend("fake", [])
    backend._limits = Limits()
    system = backend.prepare_turn(build_system("", []), "hello", None)
    backend.stream_turn(system, "hello", lambda _: None)

    call = client.messages.stream.call_args.kwargs
    first, second = call["system"]
    assert first["text"] == system.stable and first["cache_control"] == {"type": "ephemeral"}
    assert second["text"] == system.tail and "cache_control" not in second
    # The request-level cache setting from the turn loop is still sent.
    assert call["cache_control"] == {"type": "ephemeral"}


def test_a_plain_string_system_prompt_is_sent_unchanged(mocker, tmp_db):
    client = mocker.patch("strides_ai.backends.claude.anthropic.Anthropic").return_value
    client.messages.stream.return_value = _claude_stream(["hi"])
    from strides_ai.backends.claude import ClaudeBackend

    backend = ClaudeBackend("fake", [])
    backend.stream_turn("just text", "hello", lambda _: None)
    assert client.messages.stream.call_args.kwargs["system"] == "just text"


# ── Golden ────────────────────────────────────────────────────────────────────

GOLDEN = """base instructions

profile text

Notes line one
Notes line two

## Upcoming Planned Workouts
row 1
row 2

## Context Omitted
- 2 notes omitted (lowest-ranked coaching notes)
- Older activity summary omitted

## Current Date & Time
Monday 9:00"""


def test_golden_prompt_for_fixed_input():
    other = ["Notes line two", "dropped one", "dropped two"]
    prompt = ContextPrompt(
        [
            Required("mandatory", "base", "base instructions"),
            Required("profile", "profile", "profile text"),
            Required("voice", "voice", ""),
            Required("protected_memories", "protected", "Notes line one"),
            Reducible(
                "other_memories",
                0.15,
                lambda k: "\n".join(other[:k]),
                full=3,
                join="\n",
                omitted=lambda k: (
                    f"{3 - k} notes omitted (lowest-ranked coaching notes)" if k < 3 else ""
                ),
            ),
            Required("upcoming_workouts", "workouts", "## Upcoming Planned Workouts\nrow 1\nrow 2"),
            Reducible(
                "older_summary",
                0.10,
                lambda k: "summary",
                full=1,
                levels=(1, 0),
                omitted=lambda k: "Older activity summary omitted" if not k else "",
            ),
        ],
        tail="## Current Date & Time\nMonday 9:00",
    )
    sent = PreparedPrompt(prompt.stable({"other_memories": 1, "older_summary": 0}), prompt.tail)
    assert str(sent) == GOLDEN
    # Fullest version: every part, no omission section.
    assert "Context Omitted" not in str(prompt) and str(prompt).endswith("Monday 9:00")
