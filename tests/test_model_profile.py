"""Model profiles: read from the provider, fall back to a table, and the thinking they allow."""

from strides_ai.backends.model_profile import (
    ModelProfile,
    claude_thinking,
    gemini_thinking,
    ollama_thinking,
    openai_thinking,
    profile_from_claude,
    profile_from_ollama,
    resolve_profile,
)


def _claude_api(adaptive, enabled, disabled, between, efforts):
    return {
        "max_input_tokens": 1_000_000,
        "max_tokens": 128_000,
        "capabilities": {
            "thinking": {
                "types": {
                    "adaptive": {"supported": adaptive},
                    "enabled": {"supported": enabled},
                    "disabled": {"supported": disabled},
                    "between_tools": {"supported": between},
                }
            },
            "effort": {e: {"supported": e in efforts} for e in ("low", "medium", "high")},
        },
    }


SONNET_5 = profile_from_claude(
    "claude-sonnet-5-5", _claude_api(True, False, False, True, ("low", "medium", "high"))
)
HAIKU = profile_from_claude("claude-haiku-4-5", _claude_api(False, True, True, False, ()))
SONNET_46 = profile_from_claude(
    "x", _claude_api(True, False, True, False, ("low", "medium", "high"))
)


def test_claude_profile_reads_window_output_and_capabilities():
    assert (SONNET_5.context_window, SONNET_5.max_output, SONNET_5.source) == (
        1_000_000,
        128_000,
        "api",
    )
    assert SONNET_5.thinking_adaptive and not SONNET_5.thinking_off


def test_claude_thinking_per_model_shape():
    assert claude_thinking(SONNET_5, "medium") == {
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "medium"},
    }
    # sonnet-5-5 rejects "disabled": off means the lightest mode it takes.
    assert claude_thinking(SONNET_5, "off") == {"thinking": {"type": "between_tools"}}
    assert claude_thinking(SONNET_46, "off") == {"thinking": {"type": "disabled"}}
    assert claude_thinking(HAIKU, "high") == {
        "thinking": {"type": "enabled", "budget_tokens": 8000}
    }
    assert claude_thinking(HAIKU, "off") == {"thinking": {"type": "disabled"}}
    assert claude_thinking(ModelProfile(), "medium") == {}  # unknown model: send nothing


def test_unusable_api_answers_fall_back_to_the_table():
    for bad in (None, {}, {"max_input_tokens": "big", "max_tokens": 1}, "text"):
        profile = resolve_profile("claude", "claude-sonnet-5-5", lambda bad=bad: bad)
        assert profile.source == "table" and profile.thinking_between_tools
    boom = resolve_profile("claude", "claude-haiku-4-5", lambda: 1 / 0)
    assert boom.source == "table" and boom.thinking_budget
    assert resolve_profile("claude", "claude-unknown-9").source == "default"


def test_api_profile_is_cached_and_a_fallback_is_retried_later():
    calls = []
    clock = [0.0]

    def fetch():
        calls.append(1)
        return (
            None
            if len(calls) == 1
            else _claude_api(True, False, False, True, ("low", "medium", "high"))
        )

    first = resolve_profile("claude", "claude-sonnet-5-5", fetch, now=lambda: clock[0])
    assert first.source == "table"
    clock[0] = 10
    assert resolve_profile("claude", "claude-sonnet-5-5", fetch, now=lambda: clock[0]) is first
    clock[0] = 301
    second = resolve_profile("claude", "claude-sonnet-5-5", fetch, now=lambda: clock[0])
    assert second.source == "api"
    clock[0] = 9999
    assert resolve_profile("claude", "claude-sonnet-5-5", fetch, now=lambda: clock[0]) is second
    assert len(calls) == 2


def test_gemini_thinking_by_family():
    g3 = resolve_profile("gemini", "gemini-3-flash-preview")
    g25_flash = resolve_profile("gemini", "gemini-2.5-flash")
    g25_pro = resolve_profile("gemini", "gemini-2.5-pro")
    assert gemini_thinking(g3, "high") == {"thinking_level": "HIGH"}
    assert gemini_thinking(g3, "off") == {"thinking_level": "MINIMAL"}
    assert gemini_thinking(g25_flash, "medium") == {"thinking_budget": -1}
    assert gemini_thinking(g25_flash, "off") == {"thinking_budget": 0}
    assert gemini_thinking(g25_pro, "off") is None  # cannot be turned off
    assert gemini_thinking(resolve_profile("gemini", "other"), "low") is None


def test_openai_and_ollama_thinking():
    assert openai_thinking(resolve_profile("openai", "gpt-5-mini"), "off") == {
        "reasoning_effort": "minimal"
    }
    assert openai_thinking(resolve_profile("openai", "o3"), "off") == {"reasoning_effort": "low"}
    assert openai_thinking(resolve_profile("openai", "gpt-4o"), "high") == {}
    thinker = profile_from_ollama(
        "m",
        {
            "model_info": {"llama.context_length": 131072},
            "capabilities": ["completion", "thinking"],
        },
    )
    assert thinker.context_window == 32_768  # capped: num_ctx costs local memory
    assert ollama_thinking(thinker, "medium") == {"think": True}
    assert ollama_thinking(thinker, "off") == {"think": False}
    plain = profile_from_ollama("m", {"capabilities": ["completion"]})
    assert ollama_thinking(plain, "medium") == {} and plain.context_window == 16_384
    assert profile_from_ollama("m", {}) is None


def test_budget_thinking_stays_under_the_output_cap():
    assert claude_thinking(HAIKU, "high", 20_000)["thinking"]["budget_tokens"] == 8000
    assert claude_thinking(HAIKU, "high", 4_000)["thinking"]["budget_tokens"] == 3000
    # Too little room for the API's 1024 minimum: no thinking rather than a 400.
    assert claude_thinking(HAIKU, "medium", 1_500) == {"thinking": {"type": "disabled"}}


def test_partial_claude_answer_falls_back_to_the_table():
    partial = {"max_input_tokens": 200_000, "max_tokens": 64_000}  # no capabilities
    assert profile_from_claude("claude-sonnet-4-6", partial) is None
    assert resolve_profile("claude", "claude-sonnet-4-6", lambda: partial).thinking_adaptive


def test_non_reasoning_openai_names_get_no_reasoning_effort():
    for name in ("gpt-5-chat-latest", "o1-mini", "o1-preview", "gpt-4o"):
        assert openai_thinking(resolve_profile("openai", name), "medium") == {}, name
    assert openai_thinking(resolve_profile("openai", "gpt-5"), "medium") == {
        "reasoning_effort": "medium"
    }


def test_gemini_3_pro_takes_only_low_and_high():
    pro = resolve_profile("gemini", "gemini-3-pro-preview")
    assert gemini_thinking(pro, "off") == {"thinking_level": "LOW"}
    assert gemini_thinking(pro, "medium") is None
    assert gemini_thinking(pro, "high") == {"thinking_level": "HIGH"}
