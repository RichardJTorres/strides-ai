"""Limits derived from the model, CHAT_LIMITS overrides and aliases, and clamping."""

import logging

import pytest
from pydantic import ValidationError

from strides_ai.backends.model_profile import ModelProfile
from strides_ai.budget import Limits, normalize_limits
from strides_ai.config import Settings

SONNET_5 = ModelProfile(context_window=200_000, max_output=64_000)


def test_sonnet_5_limits_match_the_plan_table():
    limits = Limits.derive(SONNET_5)
    assert limits.round_max_tokens == 16_000
    assert limits.reply_reserve == 4_000
    assert limits.turn_output_ceiling == 52_000
    assert limits.context_target == 60_000
    assert limits.input_ceiling == 136_000
    assert limits.tool_rounds == 5 and limits.tools == 16
    assert (limits.first_event_s, limits.stream_idle_s) == (60, 120)
    assert (limits.round_deadline_s, limits.reply_deadline_s, limits.turn_deadline_s) == (
        240,
        120,
        600,
    )
    assert limits == Limits()  # the dataclass defaults are this model's


def test_limits_follow_a_small_model():
    limits = Limits.derive(ModelProfile(context_window=16_384, max_output=4_096))
    assert limits.round_max_tokens == 4_096  # min(16000, M, W // 4)
    assert limits.reply_reserve == 2_048
    assert limits.turn_output_ceiling == 3 * 4_096 + 2_048
    assert limits.context_target == (16_384 - 4_096) * 3 // 4
    assert limits.input_ceiling == 16_384 - 4_096  # capped by what the window leaves


def test_overrides_may_go_up_or_down_and_dependents_follow():
    lower = Limits.derive(SONNET_5, {"round_max_tokens": 8_000, "tool_rounds": 2})
    assert lower.round_max_tokens == 8_000 and lower.tool_rounds == 2
    assert lower.turn_output_ceiling == 3 * 8_000 + 4_000
    higher = Limits.derive(SONNET_5, {"round_max_tokens": 32_000, "tools": 24})
    assert higher.round_max_tokens == 32_000 and higher.tools == 24
    assert higher.reply_reserve == 4_000


def test_old_keys_are_aliases():
    assert normalize_limits(
        {"output_tokens": 1, "total_output_tokens": 2, "input_tokens": 3, "rounds": 4}
    ) == {"round_max_tokens": 1, "turn_output_ceiling": 2, "input_ceiling": 3, "tool_rounds": 4}
    limits = Limits.derive(SONNET_5, {"rounds": 3, "output_tokens": 5_000})
    assert limits.tool_rounds == 3 and limits.round_max_tokens == 5_000


def test_values_past_the_model_are_clamped_with_a_warning(caplog):
    caplog.set_level(logging.WARNING, logger="strides_ai.budget")
    limits = Limits.derive(
        ModelProfile(context_window=100_000, max_output=8_000),
        {"round_max_tokens": 50_000, "input_ceiling": 500_000, "reply_reserve": 20_000},
        label="m",
    )
    assert limits.round_max_tokens == 8_000
    assert limits.input_ceiling == 100_000 - 8_000  # the window less one round of output
    assert limits.reply_reserve == 8_000  # never more than a round
    assert limits.context_target <= limits.input_ceiling
    messages = " ".join(r.getMessage() for r in caplog.records)
    for name in ("round_max_tokens", "input_ceiling", "reply_reserve"):
        assert name in messages


@pytest.mark.parametrize(
    "bad",
    [
        {"nope": 1},
        {"rounds": 0},
        {"tool_rounds": "5"},
        {"turn_deadline_s": -1},
        {"tools": 1.5},
        {"round_max_tokens": True},
    ],
)
def test_bad_overrides_are_rejected(bad):
    with pytest.raises(ValueError):
        normalize_limits(bad)


def test_zero_is_allowed_where_it_means_none():
    assert normalize_limits({"tools": 0, "retries": 0, "history_messages": 0}) == {
        "tools": 0,
        "retries": 0,
        "history_messages": 0,
    }


def test_settings_validate_chat_limits_at_startup():
    ok = Settings(chat_limits={"default": {"rounds": 3}, "claude": {"turn_deadline_s": 300}})
    assert ok.chat_limits["default"]["rounds"] == 3
    with pytest.raises(ValidationError):
        Settings(chat_limits={"default": {"not_a_limit": 3}})
    with pytest.raises(ValidationError):
        Settings(chat_limits={"default": {"tool_rounds": 0}})


def test_a_backend_derives_its_limits_from_its_profile_and_settings(mocker, monkeypatch):
    from strides_ai import config

    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: Settings(chat_limits={"default": {"rounds": 2}, "claude": {"tools": 3}}),
    )
    mocker.patch("strides_ai.backends.claude.anthropic.Anthropic")
    from strides_ai.backends.claude import ClaudeBackend

    limits = ClaudeBackend("fake", [], model="claude-sonnet-5").limits
    assert (limits.tool_rounds, limits.tools) == (2, 3)
    assert (
        limits.round_max_tokens == 16_000 and limits.input_ceiling == 116_500  # fewer tools
    )  # fewer tools, less room


def test_context_window_override_is_clamped_to_the_model():
    limits = Limits.derive(SONNET_5, {"context_window": 1_000_000})
    assert limits.context_window == 200_000
    small = Limits.derive(SONNET_5, {"context_window": 50_000})
    assert small.context_window == 50_000
