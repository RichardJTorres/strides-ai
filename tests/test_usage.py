"""Provider usage normalization and the static-ratio input estimator."""

import json
import logging
import math
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from strides_ai.backends.base import BaseBackend
from strides_ai.budget import (
    BudgetExceeded,
    IMAGE_TOKENS,
    Limits,
    TurnBudget,
    Usage,
    estimate,
)
from tests.test_backends import _claude_stream, _claude_tool_block
from tests.test_budgets import adapter  # noqa: F401  (shared four-provider fixture)

RATIO = 2.4


# ── Adapters ────────────────────────────────────────────────────────────────


def test_claude_usage_sums_cached_and_uncached_input():
    from strides_ai.backends.claude import claude_usage

    usage = claude_usage(
        SimpleNamespace(
            input_tokens=100,
            cache_creation_input_tokens=50,
            cache_read_input_tokens=8000,
            output_tokens=500,
        )
    )
    assert usage == Usage(
        input_total=8150, cache_read=8000, cache_write=50, output_total=500, reasoning=None
    )


def test_claude_usage_missing_and_non_int_values_are_none():
    from strides_ai.backends.claude import claude_usage

    assert claude_usage(None) == Usage()
    assert claude_usage(MagicMock()) == Usage()
    # Cache fields absent: the uncached count is the whole input.
    partial = claude_usage(SimpleNamespace(input_tokens=7, output_tokens="9"))
    assert partial == Usage(input_total=7)
    # Without the base count the total is unknown, whatever the cache fields say.
    assert claude_usage(SimpleNamespace(cache_read_input_tokens=5)).input_total is None


def test_openai_usage_reads_nested_details():
    from strides_ai.backends.openai import openai_usage

    usage = openai_usage(
        SimpleNamespace(
            prompt_tokens=1200,
            completion_tokens=900,
            prompt_tokens_details=SimpleNamespace(cached_tokens=1024),
            completion_tokens_details=SimpleNamespace(reasoning_tokens=700),
        )
    )
    assert usage == Usage(
        input_total=1200, cache_read=1024, cache_write=None, output_total=900, reasoning=700
    )


def test_openai_usage_missing_and_non_int_values_are_none():
    from strides_ai.backends.openai import openai_usage

    assert openai_usage(None) == Usage()
    assert openai_usage(MagicMock()) == Usage()
    bare = openai_usage(SimpleNamespace(prompt_tokens=10, completion_tokens=None))
    assert bare == Usage(input_total=10)
    bad = openai_usage(
        SimpleNamespace(
            prompt_tokens=True,
            completion_tokens=3.5,
            prompt_tokens_details=SimpleNamespace(cached_tokens="1"),
            completion_tokens_details=None,
        )
    )
    assert bad == Usage()


def test_gemini_usage_adds_tool_prompt_and_thoughts():
    from strides_ai.backends.gemini import gemini_usage

    usage = gemini_usage(
        SimpleNamespace(
            prompt_token_count=1000,
            tool_use_prompt_token_count=200,
            cached_content_token_count=600,
            candidates_token_count=300,
            thoughts_token_count=4000,
        )
    )
    assert usage == Usage(
        input_total=1200, cache_read=600, cache_write=None, output_total=4300, reasoning=4000
    )


def test_gemini_usage_missing_and_non_int_values_are_none():
    from strides_ai.backends.gemini import gemini_usage

    assert gemini_usage(None) == Usage()
    assert gemini_usage(MagicMock()) == Usage()
    # No thoughts or tool-prompt count reported: they add nothing, and reasoning stays unknown.
    plain = gemini_usage(SimpleNamespace(prompt_token_count=50, candidates_token_count=20))
    assert plain == Usage(input_total=50, output_total=20)
    # A reply that is all thinking has no visible count; the thoughts are still output.
    assert gemini_usage(SimpleNamespace(thoughts_token_count=9)) == Usage(
        output_total=9, reasoning=9
    )


def test_ollama_usage_reads_final_chunk_counts():
    from strides_ai.backends.ollama import ollama_usage

    assert ollama_usage({"prompt_eval_count": 800, "eval_count": 120}) == Usage(
        input_total=800, output_total=120
    )
    assert ollama_usage({}) == Usage()
    assert ollama_usage(None) == Usage()
    assert ollama_usage({"prompt_eval_count": "800", "eval_count": None}) == Usage()


# ── Estimator ───────────────────────────────────────────────────────────────


def test_estimate_is_bytes_over_ratio_plus_framing():
    value = {"text": "é" * 100}  # 200 bytes of text in the JSON
    raw = len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
    assert estimate(value, 2.4) == math.ceil(raw / 2.4) + 64
    assert estimate(value, 5.0) < estimate(value, 2.4)


def test_image_block_counts_a_flat_amount_whatever_its_payload():
    image = {"type": "image", "source": {"type": "base64", "data": "A" * 2_000_000}}
    small = estimate([image], RATIO)
    assert IMAGE_TOKENS <= small < IMAGE_TOKENS + 100
    assert estimate([image, image], RATIO) >= 2 * IMAGE_TOKENS
    # The same bytes as text are charged at the ratio.
    assert estimate(["A" * 2_000_000], RATIO) > 800_000


def _tool_round(text="x" * 3000):
    return [
        {"role": "assistant", "content": "calling"},
        {"role": "user", "content": [{"type": "tool_result", "content": text}]},
    ]


def test_cache_heavy_second_round_counts_input_total_not_just_fresh_tokens():
    budget = TurnBudget(Limits(), RATIO)
    history = [{"role": "user", "content": "hi"}]
    budget.request("sys", history, [])
    # Almost everything came from the cache: 100 fresh + 50 written + 8000 read.
    budget.usage(Usage(input_total=8150, cache_read=8000, cache_write=50, output_total=500))
    history += _tool_round()
    budget.request("sys", history, [])
    expected = 8150 + 500 + estimate(history[2:], RATIO)
    assert budget.input_size == expected
    assert budget.count_kind == "estimated"
    first, second = budget.record.rounds
    assert first["input_total"] == 8150 and first["cache_read"] == 8000
    assert first["cache_write"] == 50 and first["output_total"] == 500
    assert second["est_input"] == expected


def test_reasoning_heavy_response_is_carried_into_the_next_estimate():
    budget = TurnBudget(Limits(), RATIO)
    history = [{"role": "user", "content": "plan my block"}]
    budget.request("sys", history, [])
    # 9000 of the 9200 output tokens were thinking; the stored assistant message is tiny.
    budget.usage(Usage(input_total=1000, output_total=9200, reasoning=9000))
    history += _tool_round("ok")
    budget.request("sys", history, [])
    assert budget.input_size == 1000 + 9200 + estimate(history[2:], RATIO)
    assert budget.record.rounds[0]["reasoning"] == 9000


def test_second_round_without_reported_usage_falls_back_to_the_estimates():
    budget = TurnBudget(Limits(), RATIO)
    history = [{"role": "user", "content": "hi"}]
    budget.request("sys", history, [])
    first_est = budget.input_size
    budget.output("y" * 400)  # streamed output estimate, 100 tokens
    budget.usage(None)
    history += _tool_round()
    budget.request("sys", history, [])
    assert budget.input_size == first_est + 100 + estimate(history[2:], RATIO)


def test_a_round_that_adds_nothing_new_carries_forward_without_double_counting():
    budget = TurnBudget(Limits(), RATIO)
    history = [{"role": "user", "content": "hi"}]
    budget.request("sys", history, [])
    budget.usage(Usage(input_total=500, output_total=40))
    history.append({"role": "assistant", "content": "done"})  # only the assistant message
    budget.request("sys", history, [])
    assert budget.input_size == 540


def test_warns_when_measured_input_exceeds_the_estimate_by_more_than_15_percent(caplog):
    caplog.set_level(logging.WARNING, logger="strides_ai.budget")
    budget = TurnBudget(Limits(), RATIO)
    budget.request("sys", [{"role": "user", "content": "hi"}], [])
    estimated = budget.input_size
    budget.usage(Usage(input_total=int(estimated * 1.10), output_total=5))
    assert not caplog.records

    budget.request("sys", [{"role": "user", "content": "hi"}], [])
    budget.usage(Usage(input_total=int(budget.input_size * 1.20), output_total=5))
    assert any("input estimate low" in r.getMessage() for r in caplog.records)


def test_usage_still_accepts_a_bare_output_count():
    budget = TurnBudget(Limits(turn_output_ceiling=5000), RATIO)
    budget.request("sys", [], [])
    budget.usage(3900)
    assert budget.output_remaining == 1100
    assert budget.record.rounds[0]["output_total"] == 3900
    assert budget.record.rounds[0]["input_total"] is None


# ── count_tokens is a last resort ───────────────────────────────────────────


def _claude(mocker, *streams, count=None):
    client = mocker.patch("strides_ai.backends.claude.anthropic.Anthropic").return_value
    client.messages.stream.side_effect = list(streams)
    if count is not None:
        client.messages.count_tokens.return_value = SimpleNamespace(input_tokens=count)
    from strides_ai.backends.claude import ClaudeBackend

    return ClaudeBackend("fake", []), client


def _with_usage(stream, **usage):
    stream.get_final_message.return_value.usage = SimpleNamespace(**usage)
    return stream


def test_two_round_claude_turn_records_usage_and_never_counts_tokens(mocker):
    mocker.patch("strides_ai.backends.base.db.save_memory", return_value="saved")
    args = {"category": "goal", "content": "race"}
    first = _with_usage(
        _claude_stream(["a"], "tool_use", [_claude_tool_block("save_memory", args, "t1")]),
        input_tokens=100,
        cache_creation_input_tokens=50,
        cache_read_input_tokens=8000,
        output_tokens=500,
    )
    second = _with_usage(
        _claude_stream(["done"], "end_turn"),
        input_tokens=20,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=8700,
        output_tokens=30,
    )
    backend, client = _claude(mocker, first, second)
    backend.stream_turn("mandatory", "hello", lambda _: None)

    one, two = backend._budget.record.rounds
    assert (one["input_total"], one["cache_read"], one["cache_write"]) == (8150, 8000, 50)
    assert one["output_total"] == 500 and one["reasoning"] is None
    assert two["input_total"] == 8720 and two["cache_write"] == 0
    # Round 2 was estimated from round 1's measured usage plus the tool result.
    tool_message = backend._history[2:3]
    ratio = backend.profile.bytes_per_token
    assert two["est_input"] == 8150 + 500 + estimate(tool_message, ratio)
    assert backend._budget.record.to_dict()["ratio"] == ratio
    client.messages.count_tokens.assert_not_called()


def test_count_tokens_confirms_a_message_the_estimate_would_reject(mocker):
    backend, client = _claude(mocker, count=1500)
    # About 167k tokens by the estimate, 1.5k by the provider's own count.
    system = backend.prepare_turn("mandatory", "x" * 400000)
    assert system == "mandatory"
    assert client.messages.count_tokens.call_count == 1
    # The turn has used its one count.
    assert backend._count_once("s", [], []) is None
    assert client.messages.count_tokens.call_count == 1


def test_count_tokens_that_agrees_with_the_estimate_rejects_once(mocker):
    backend, client = _claude(mocker, count=400000)
    with pytest.raises(BudgetExceeded):
        backend.prepare_turn("mandatory", "x" * 400000)
    assert client.messages.count_tokens.call_count == 1


def test_a_later_round_over_the_ceiling_becomes_the_reply_round_and_never_counts(mocker):
    mocker.patch("strides_ai.backends.base.db.save_memory", return_value="y" * 400000)
    args = {"category": "goal", "content": "race"}
    streams = [
        _claude_stream(["a"], "tool_use", [_claude_tool_block("save_memory", args, "t1")]),
        _claude_stream(["b"], "end_turn"),
    ]
    backend, client = _claude(mocker, *streams, count=2000)
    backend.stream_turn("mandatory", "hello", lambda _: None)
    # The count is only for admitting a message; a later round is judged on the estimate alone.
    assert client.messages.stream.call_count == 2
    assert client.messages.count_tokens.call_count == 0
    assert backend._budget.stop_reason == "input_ceiling"
    assert [r["kind"] for r in backend._budget.record.rounds] == ["tool", "reply"]


def test_no_count_tokens_when_the_estimate_fits_on_every_provider(
    adapter, monkeypatch, mocker
):  # noqa: F811
    monkeypatch.setattr(BaseBackend, "limits", property(lambda _: Limits(tool_rounds=2, tools=16)))
    mocker.patch("strides_ai.backends.base.db.save_memory", return_value="saved")
    backend, _ = adapter()
    spy = mocker.patch.object(backend, "_count_request", wraps=backend._count_request)
    backend.stream_turn("mandatory", "hello", lambda _: None)
    spy.assert_not_called()


def test_missing_provider_usage_leaves_the_record_null_and_the_estimate_growing(
    adapter, monkeypatch, mocker  # noqa: F811
):
    monkeypatch.setattr(BaseBackend, "limits", property(lambda _: Limits(tool_rounds=1, tools=16)))
    mocker.patch("strides_ai.backends.base.db.save_memory", return_value="saved")
    backend, _ = adapter()
    backend.stream_turn("mandatory", "hello", lambda _: None)
    first, second = backend._budget.record.rounds
    for round_ in (first, second):
        assert round_["input_total"] is None and round_["cache_read"] is None
        assert round_["cache_write"] is None and round_["reasoning"] is None
        assert round_["output_total"] is None
    assert type(first["est_input"]) is int and second["est_input"] > first["est_input"]


def test_a_message_admitted_by_the_measured_count_is_not_rejected_again_in_round_one(mocker):
    backend, client = _claude(mocker, _claude_stream(["ok"], "end_turn"), count=1500)
    text, _, _ = backend.stream_turn("mandatory", "x" * 400000, lambda _: None)
    assert text == "ok"
    assert client.messages.count_tokens.call_count == 1
    assert backend._budget.record.rounds[0]["count_kind"] == "measured"
