"""The shared turn policy on all four providers: the output invariant, the reply round, cut-offs,
bad tool arguments, deadlines and the stop codes."""

import json

import httpx
import pytest

from strides_ai import db
from strides_ai.api.conversations import ConversationCoordinator
from strides_ai.backends.base import BaseBackend
from strides_ai.budget import Limits, TurnBudget, TurnStop
from tests.policy_helpers import PROVIDERS, make_backend

REMEMBER = ("save_memory", {"category": "goal", "content": "race"})


@pytest.fixture(params=PROVIDERS)
def provider(request):
    return request.param


@pytest.fixture
def memory_write(mocker):
    return mocker.patch("strides_ai.backends.base.db.save_memory", return_value="saved")


def use_limits(monkeypatch, **fields):
    limits = Limits(**fields)
    monkeypatch.setattr(BaseBackend, "limits", property(lambda _: limits))
    return limits


# ── Output invariant ──────────────────────────────────────────────────────────


def plan_after(backend, generated):
    backend._history = []
    backend._budget = TurnBudget(backend.limits)
    backend._budget.generated = generated
    return backend._begin_round("system")


def test_a_tool_round_needs_a_round_and_the_reserve_left_under_the_ceiling(
    provider, mocker, monkeypatch
):
    use_limits(monkeypatch)  # 16,000 per round, 4,000 reserve, 52,000 ceiling
    backend, _ = make_backend(provider, mocker, [])
    # 52,000 - 32,000 = 20,000 = round + reserve: still a tool round, at exactly round_max.
    plan = plan_after(backend, 32_000)
    assert (plan.kind, plan.max_tokens, plan.reason) == ("tool", 16_000, None)
    # One more token generated and it is not.
    plan = plan_after(backend, 32_001)
    assert (plan.kind, plan.reason) == ("reply", "output_ceiling")
    assert plan.max_tokens == min(16_000, 52_000 - 32_001)


@pytest.mark.parametrize(
    "generated,expected",
    [
        (32_001, 16_000),  # plenty left: a full round
        (40_000, 12_000),  # what is left
        (49_000, 4_000),  # less than the reserve: the reserve, so the reply still has room
        (60_000, 4_000),  # already past the ceiling
    ],
)
def test_the_reply_round_gets_what_is_left_but_at_least_the_reserve(
    provider, mocker, monkeypatch, generated, expected
):
    use_limits(monkeypatch)
    backend, _ = make_backend(provider, mocker, [])
    plan = plan_after(backend, generated)
    assert (plan.kind, plan.max_tokens) == ("reply", expected)
    assert backend._budget.record.rounds[-1]["max_tokens"] == expected


def test_output_past_the_ceiling_is_recorded_not_enforced():
    budget = TurnBudget(Limits())
    budget.request("s", [], [])
    budget.usage(53_000)
    assert budget.record.output_overshoot == 1_000
    assert budget.record.to_dict()["output_overshoot"] == 1_000


# ── Reply round ───────────────────────────────────────────────────────────────


def test_the_reply_round_turns_tools_off_and_never_runs_them(
    provider, mocker, monkeypatch, memory_write
):
    limits = use_limits(monkeypatch, tool_rounds=1)
    # The provider calls a tool in the reply round anyway; it must not run.
    backend, requests = make_backend(
        provider, mocker, [{"calls": [REMEMBER]}, {"text": "all done", "calls": [REMEMBER]}]
    )
    text, memories, _ = backend.stream_turn("mandatory", "hello", lambda _: None)

    assert [r.tools_off for r in requests] == [False, True]
    assert requests[0].max_tokens == limits.round_max_tokens
    assert requests[1].max_tokens == min(
        limits.round_max_tokens, max(backend._budget.output_remaining, limits.reply_reserve)
    )
    assert memory_write.call_count == 1 and len(memories) == 1
    assert backend._budget.notice == backend._budget.stop_reason == "round_limit"
    record = backend._budget.record.to_dict()
    assert [r["kind"] for r in record["rounds"]] == ["tool", "reply"]
    assert [r["stop"] for r in record["rounds"]] == ["tool_calls", "calls_ignored"]
    assert record["stop"]["reason"] == "round_limit"
    # The app's note follows the tool results and asks for a summary.
    assert "Tool budget used; summarise what was done and what remains" in str(backend._history)


def test_tool_rounds_are_five_by_default_then_one_reply(provider, mocker, memory_write):
    backend, requests = make_backend(provider, mocker, [{"calls": [REMEMBER]}] * 6)
    backend.stream_turn("mandatory", "hello", lambda _: None)
    assert [r.tools_off for r in requests] == [False] * 5 + [True]
    assert memory_write.call_count == 5


def test_a_deadline_too_near_for_a_round_and_a_reply_skips_straight_to_the_reply(
    provider, mocker, monkeypatch, memory_write
):
    # 60 s is less than a round (240) plus a reply (120): never offer tools.
    use_limits(monkeypatch, turn_deadline_s=60)
    backend, requests = make_backend(provider, mocker, [{"text": "short"}])
    backend.stream_turn("mandatory", "hello", lambda _: None)
    assert [r.tools_off for r in requests] == [True]
    assert backend._budget.notice == "deadline"


def test_calls_past_the_tool_limit_are_answered_not_dropped(
    provider, mocker, monkeypatch, memory_write
):
    use_limits(monkeypatch, tools=1)
    backend, requests = make_backend(
        provider, mocker, [{"calls": [REMEMBER, REMEMBER, REMEMBER]}, {"text": "done"}]
    )
    backend.stream_turn("mandatory", "hello", lambda _: None)
    assert memory_write.call_count == 1
    assert str(backend._history).count("Not executed: tool limit reached") == 2
    assert backend._budget.notice == "tool_limit"
    assert [r.tools_off for r in requests] == [False, True]


# ── Cut-off responses ─────────────────────────────────────────────────────────


def test_a_cut_off_response_never_runs_its_tool_calls(provider, mocker, monkeypatch, memory_write):
    backend, requests = make_backend(
        provider, mocker, [{"text": "partial", "calls": [REMEMBER], "cut_off": True}]
    )
    text, memories, _ = backend.stream_turn("mandatory", "hello", lambda _: None)
    assert text == "partial"
    assert memory_write.call_count == 0 and memories == []
    assert len(requests) == 1
    assert backend._budget.notice == backend._budget.stop_reason == "truncated"
    assert backend._budget.record.rounds[0]["stop"] == "truncated"


def test_a_cut_off_closing_reply_keeps_the_more_specific_notice(
    provider, mocker, monkeypatch, memory_write
):
    use_limits(monkeypatch, tool_rounds=1)
    backend, _ = make_backend(
        provider, mocker, [{"calls": [REMEMBER]}, {"text": "half a summ", "cut_off": True}]
    )
    backend.stream_turn("mandatory", "hello", lambda _: None)
    assert backend._budget.notice == "round_limit"


def test_openai_arguments_that_do_not_parse_are_not_run_and_the_model_is_told(mocker, memory_write):
    backend, requests = make_backend(
        "openai", mocker, [{"calls": [("save_memory", "{not json")]}, {"text": "sorry"}]
    )
    backend.stream_turn("mandatory", "hello", lambda _: None)
    assert memory_write.call_count == 0
    results = [m for m in backend._history if m.get("role") == "tool"]
    assert len(results) == 1 and "not valid JSON" in results[0]["content"]
    assert len(requests) == 2  # the model got to answer


def test_an_unknown_tool_gets_a_result_so_the_history_stays_valid(provider, mocker, memory_write):
    backend, _ = make_backend(provider, mocker, [{"calls": [("nope", {})]}, {"text": "ok"}])
    backend.stream_turn("mandatory", "hello", lambda _: None)
    assert "Unknown tool: nope" in str(backend._history)


# ── Deadlines ─────────────────────────────────────────────────────────────────


def test_a_stalled_stream_ends_the_turn_as_a_deadline(provider, mocker, memory_write):
    backend, _ = make_backend(
        provider,
        mocker,
        [
            {"calls": [REMEMBER]},
            {"text": "partial reply", "raise_after_text": httpx.ReadTimeout("x")},
        ],
    )
    text, memories, _ = backend.stream_turn("mandatory", "hello", lambda _: None)
    assert text.startswith("ok")  # round 1's reply is kept
    assert len(memories) == 1
    assert backend._budget.notice == backend._budget.stop_reason == "deadline"
    assert backend._budget.record.stop["reason"] == "deadline"


def test_a_stalled_turn_stores_a_receipt_of_what_it_saved(provider, mocker, tmp_db):
    backend, _ = make_backend(
        provider,
        mocker,
        [{"calls": [REMEMBER]}, {"text": "xx", "raise_after_text": httpx.ReadTimeout("x")}],
    )
    coordinator = ConversationCoordinator(lambda _: backend)
    turn = coordinator.acquire("running")
    coordinator.start(turn, "mandatory", "hello", "hello", None)
    turn.worker.join(5)
    assert not turn.worker.is_alive()

    saved = db.get_recent_messages(mode="running")[-1]
    assert saved["notice"] == "deadline"
    assert "race" in saved["receipt_json"]
    chunks = [c for c in turn.tokens.queue if isinstance(c, str)]
    notice = next(c for c in chunks if c.startswith("[NOTICE]"))
    assert json.loads(notice[len("[NOTICE]") :])["code"] == "deadline"
    assert "Saved:" in json.loads(notice[len("[NOTICE]") :])["receipt_text"]


def test_a_round_running_past_its_deadline_is_cut_at_the_next_event(
    provider, mocker, monkeypatch, memory_write
):
    now = [1000.0]
    monkeypatch.setattr("strides_ai.budget._now", lambda: now[0])
    use_limits(monkeypatch, round_deadline_s=240)
    backend, requests = make_backend(provider, mocker, [{"text": "a long answer"}])

    def slow(chunk):
        now[0] += 300  # the provider is slow: this one chunk took longer than a round may

    text, _, _ = backend.stream_turn("mandatory", "hello", slow)
    assert backend._budget.notice == "deadline"
    assert len(text) < len("a long answer")  # the second piece never arrived
    assert len(requests) == 1


def test_a_turn_past_its_own_deadline_makes_no_further_request(
    provider, mocker, monkeypatch, memory_write
):
    now = [0.0]
    monkeypatch.setattr("strides_ai.budget._now", lambda: now[0])
    use_limits(monkeypatch, turn_deadline_s=1000)
    backend, requests = make_backend(provider, mocker, [{"calls": [REMEMBER]}, {"text": "late"}])

    def tick_after_tool(*args, **kwargs):
        now[0] += 5000
        return "saved"

    memory_write.side_effect = tick_after_tool
    backend.stream_turn("mandatory", "hello", lambda _: None)
    assert backend._budget.notice == "deadline"
    assert len(requests) == 1 and memory_write.call_count == 1


def test_each_provider_gets_the_stall_timeout(provider, mocker, monkeypatch, memory_write):
    limits = use_limits(monkeypatch, stream_idle_s=77, first_event_s=33, round_deadline_s=222)
    backend, requests = make_backend(provider, mocker, [{"text": "ok"}])
    backend.stream_turn("mandatory", "hello", lambda _: None)
    # Gemini's one timeout is the request's total time, so it takes the round deadline.
    expected = limits.round_deadline_s if provider == "gemini" else limits.stream_idle_s
    assert requests[0].timeout_s == expected


# ── Stop codes ────────────────────────────────────────────────────────────────


def test_every_stop_code_has_notice_text():
    from strides_ai.turn_notice import notice_text

    for code in (
        "truncated",
        "limit",
        "round_limit",
        "tool_limit",
        "output_ceiling",
        "input_ceiling",
        "deadline",
        "retry_limit",
        "provider_error",
        "failed",
        "interrupted",
        "cancelled",
    ):
        assert notice_text(code), code


def test_turn_stop_carries_its_code():
    stop = TurnStop("deadline", "too slow")
    assert stop.code == "deadline" and str(stop) == "too slow"


# ── Tool results: bounded by construction, every id kept ──────────────────────


def _plan_call(mocker, args, violations=(), created=()):
    """One update_training_plan call against a stub backend; returns (summary, changes, apply)."""
    from types import SimpleNamespace

    mocker.patch("strides_ai.backends.base.db.get_training_plan", return_value=[])
    mocker.patch("strides_ai.backends.base._check_proposed_changes", return_value=list(violations))
    apply = mocker.patch(
        "strides_ai.backends.base.db.apply_calendar_changes",
        return_value={"created": list(created), "updated": [], "deleted": []},
    )
    stub = SimpleNamespace(
        _check_cancelled=lambda: None,
        _budget=SimpleNamespace(tool=lambda a: None, changes=[]),
    )
    summary, changes = BaseBackend._execute_update_training_plan(stub, args)
    return summary, changes, apply


def _workout(day, workout_type):
    return {"date": f"2026-12-{day:02d}", "workout_type": workout_type, "distance": 5}


def test_the_largest_possible_plan_result_stays_small_and_keeps_every_id(mocker):
    from types import SimpleNamespace

    from strides_ai.backends.base import MAX_PLAN_OPERATIONS
    from strides_ai.budget import estimate
    from strides_ai.kinds import WORKOUT_TYPES, display_type

    longest = max(WORKOUT_TYPES, key=lambda t: len(display_type("workout", t, None)))
    ids = [900_000 + i for i in range(MAX_PLAN_OPERATIONS)]
    warnings = [
        SimpleNamespace(hard=False, date="2026-12-01", detail=f"warning {i} " + "w" * 500)
        for i in range(40)
    ]
    args = {"set": [_workout(1 + i % 28, longest) for i in range(MAX_PLAN_OPERATIONS)]}
    summary, changes, _ = _plan_call(mocker, args, violations=warnings, created=ids)

    assert estimate(summary) < 1_500
    for entry_id in ids:
        assert f"[id {entry_id}]" in summary  # nothing that names an entry is ever dropped
    assert len(changes) == MAX_PLAN_OPERATIONS
    assert summary.count("warning ") == 5 and "and 35 more" in summary


def test_the_largest_rejection_stays_small_too(mocker):
    from strides_ai.backends.base import MAX_PLAN_OPERATIONS
    from strides_ai.budget import estimate

    # 31 entries with no date: 31 reasons, five shown.
    summary, changes, apply = _plan_call(
        mocker, {"set": [{"workout_type": "Easy Run"} for _ in range(MAX_PLAN_OPERATIONS)]}
    )
    assert summary.startswith("Rejected, no changes made.") and "and 26 more" in summary
    assert estimate(summary) < 1_500 and changes == []
    apply.assert_not_called()


def test_a_call_over_the_operation_limit_is_rejected_whole_with_advice(mocker):
    from strides_ai.backends.base import MAX_PLAN_OPERATIONS

    args = {
        "set": [_workout(1 + i % 28, "Easy Run") for i in range(MAX_PLAN_OPERATIONS)],
        "delete": [1],
    }
    summary, changes, apply = _plan_call(mocker, args)
    assert summary.startswith("Rejected, no changes made.")
    assert f"{MAX_PLAN_OPERATIONS + 1} operations" in summary and "several calls" in summary
    assert changes == []
    apply.assert_not_called()
    # Exactly the limit is accepted.
    args = {"set": [_workout(1 + i % 28, "Easy Run") for i in range(MAX_PLAN_OPERATIONS)]}
    summary, _, apply = _plan_call(mocker, args, created=range(MAX_PLAN_OPERATIONS))
    assert summary.startswith("Created 31 entr")
    apply.assert_called_once()


def test_the_limit_is_stated_in_the_tool_description_and_the_prompt():
    from strides_ai.backends.base import MAX_PLAN_OPERATIONS, UPDATE_TRAINING_PLAN_DESCRIPTION
    from strides_ai.coach import PLAN_CHUNK_RULE

    assert MAX_PLAN_OPERATIONS == 31
    assert "at most 31 entries" in UPDATE_TRAINING_PLAN_DESCRIPTION
    assert "at most 31 entries" in PLAN_CHUNK_RULE
