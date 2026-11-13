"""What a model can do, looked up from the provider and cached, and the thinking settings it takes.

Request parameters used to be hard-coded for one model, and the next model rejected them (a 400
for ``thinking.type.enabled`` on sonnet-5, ``disabled`` on sonnet-5-5). A profile is read from the
provider's own capability API where there is one, falls back to a longest-prefix table, and
finally to a conservative default that sends no thinking parameter at all.

Pure functions here take plain data; each backend supplies a ``fetch`` that talks to its client.
"""

import logging
import time
from dataclasses import dataclass
from typing import Callable

log = logging.getLogger(__name__)

EFFORTS = ("low", "medium", "high")
FALLBACK_RETRY_S = 300
DEFAULT_WINDOW, DEFAULT_OUTPUT = 128_000, 8_000


@dataclass(frozen=True)
class ModelProfile:
    context_window: int = DEFAULT_WINDOW
    max_output: int = DEFAULT_OUTPUT
    family: str = "none"  # claude | gemini3 | gemini25 | openai-reasoning | ollama | none
    thinking_adaptive: bool = False  # Claude: thinking={"type": "adaptive"}
    thinking_budget: bool = False  # Claude: thinking={"type": "enabled", "budget_tokens": n}
    thinking_off: bool = False  # the model accepts thinking turned off
    thinking_between_tools: bool = False  # Claude: the lightest mode a model without "off" takes
    effort_levels: tuple[str, ...] = ()
    can_minimize: bool = False  # OpenAI reasoning_effort="minimal"; Gemini cannot be turned off
    bytes_per_token: float = 2.5
    source: str = "default"  # api | table | default


# Longest prefix wins. Values are conservative where the provider's API is not reachable.
_CLAUDE_TABLE = {
    "claude-haiku-4-5": ModelProfile(
        200_000, 64_000, "claude", thinking_budget=True, thinking_off=True, bytes_per_token=2.4
    ),
    "claude-sonnet-4-6": ModelProfile(
        200_000,
        64_000,
        "claude",
        thinking_adaptive=True,
        thinking_off=True,
        effort_levels=EFFORTS,
        bytes_per_token=2.4,
    ),
    "claude-opus-4-6": ModelProfile(
        200_000,
        64_000,
        "claude",
        thinking_adaptive=True,
        thinking_off=True,
        effort_levels=EFFORTS,
        bytes_per_token=2.4,
    ),
    "claude-sonnet-5": ModelProfile(
        200_000,
        64_000,
        "claude",
        thinking_adaptive=True,
        thinking_between_tools=True,
        effort_levels=EFFORTS,
        bytes_per_token=2.4,
    ),
    "claude-opus-5": ModelProfile(
        200_000,
        64_000,
        "claude",
        thinking_adaptive=True,
        thinking_between_tools=True,
        effort_levels=EFFORTS,
        bytes_per_token=2.4,
    ),
    "claude-fable-5": ModelProfile(
        200_000,
        64_000,
        "claude",
        thinking_adaptive=True,
        thinking_between_tools=True,
        effort_levels=EFFORTS,
        bytes_per_token=2.4,
    ),
}
_GEMINI_TABLE = {
    "gemini-3": ModelProfile(1_048_576, 65_536, "gemini3"),  # pro-class until a flash entry
    "gemini-3-flash": ModelProfile(1_048_576, 65_536, "gemini3", thinking_off=True),
    "gemini-3.5-flash": ModelProfile(1_048_576, 65_536, "gemini3", thinking_off=True),
    "gemini-2.5-pro": ModelProfile(1_048_576, 65_536, "gemini25"),  # cannot be turned off
    "gemini-2.5": ModelProfile(1_048_576, 65_536, "gemini25", thinking_off=True),
}
_OPENAI_TABLE = {
    "gpt-5": ModelProfile(400_000, 128_000, "openai-reasoning", can_minimize=True),
    "o1": ModelProfile(200_000, 100_000, "openai-reasoning"),
    "o3": ModelProfile(200_000, 100_000, "openai-reasoning"),
    "o4": ModelProfile(200_000, 100_000, "openai-reasoning"),
    "gpt-5-chat": ModelProfile(128_000, 16_000),  # not a reasoning model
    "o1-mini": ModelProfile(128_000, 65_000),
    "o1-preview": ModelProfile(128_000, 32_000),
    "gpt-4": ModelProfile(128_000, 16_000),
}
_TABLES = {"claude": _CLAUDE_TABLE, "gemini": _GEMINI_TABLE, "openai": _OPENAI_TABLE}


def _int(value) -> int | None:
    return value if type(value) is int and value > 0 else None


def _supported(node) -> bool:
    return isinstance(node, dict) and node.get("supported") is True


def _table_profile(provider: str, model: str) -> ModelProfile | None:
    table = _TABLES.get(provider, {})
    for prefix in sorted(table, key=len, reverse=True):
        if model.startswith(prefix):
            return table[prefix]
    return None


def profile_from_claude(model: str, data: dict) -> ModelProfile | None:
    """Read ``client.models.retrieve(model).model_dump()``; None if it holds nothing usable."""
    window, output = _int(data.get("max_input_tokens")), _int(data.get("max_tokens"))
    if window is None or output is None:
        return None
    caps = data.get("capabilities")
    if not isinstance(caps, dict) or not isinstance(caps.get("thinking"), dict):
        return None  # without them every flag would read False; the table knows better
    thinking = caps.get("thinking") if isinstance(caps.get("thinking"), dict) else {}
    types = thinking.get("types") if isinstance(thinking.get("types"), dict) else {}
    effort = caps.get("effort") if isinstance(caps.get("effort"), dict) else {}
    return ModelProfile(
        window,
        output,
        "claude",
        thinking_adaptive=_supported(types.get("adaptive")),
        thinking_budget=_supported(types.get("enabled")),
        thinking_off=_supported(types.get("disabled")),
        thinking_between_tools=_supported(types.get("between_tools")),
        effort_levels=tuple(e for e in EFFORTS if _supported(effort.get(e))),
        bytes_per_token=2.4,
        source="api",
    )


def profile_from_gemini(model: str, data: dict) -> ModelProfile | None:
    window, output = _int(data.get("input_token_limit")), _int(data.get("output_token_limit"))
    base = _table_profile("gemini", model)
    if window is None or output is None or base is None:
        return None  # the table decides how a Gemini model takes thinking
    return ModelProfile(
        **{**base.__dict__, "context_window": window, "max_output": output, "source": "api"}
    )


def profile_from_ollama(model: str, data: dict) -> ModelProfile | None:
    window = None
    info = data.get("model_info")
    if isinstance(info, dict):
        for key, value in info.items():
            if key.endswith(".context_length") and _int(value):
                window = value
    capabilities = data.get("capabilities")
    thinks = isinstance(capabilities, list) and "thinking" in capabilities
    if window is None and not isinstance(capabilities, list):
        return None
    return ModelProfile(
        # num_ctx is sent from this, and a larger window costs local memory.
        min(window, 32_768) if window else 16_384,
        4_096,
        "ollama" if thinks else "none",
        thinking_off=thinks,
        source="api",
    )


_FROM_API = {
    "claude": profile_from_claude,
    "gemini": profile_from_gemini,
    "ollama": profile_from_ollama,
}
_cache: dict[tuple[str, str], tuple[ModelProfile, float]] = {}


def clear_cache() -> None:
    _cache.clear()


def resolve_profile(
    provider: str,
    model: str,
    fetch: Callable[[], dict | None] | None = None,
    now: Callable[[], float] = time.monotonic,
) -> ModelProfile:
    """The model's profile. A profile read from the provider is kept for the process; a fallback
    is retried after FALLBACK_RETRY_S. ``fetch`` returns the provider's raw answer or None."""
    key = (provider, model)
    cached = _cache.get(key)
    if cached is not None and (cached[0].source == "api" or now() - cached[1] < FALLBACK_RETRY_S):
        return cached[0]
    profile = None
    parse = _FROM_API.get(provider)
    if fetch is not None and parse is not None:
        try:
            data = fetch()
            profile = parse(model, data) if isinstance(data, dict) else None
        except Exception as exc:  # a capability lookup must never cost the turn
            log.info(
                "model profile lookup failed for %s/%s: %s", provider, model, type(exc).__name__
            )
    if profile is None:
        table = _table_profile(provider, model)
        profile = ModelProfile(**{**table.__dict__, "source": "table"}) if table else ModelProfile()
        if profile.source != "api":
            log.info("model profile for %s/%s from %s", provider, model, profile.source)
    _cache[key] = (profile, now())
    return profile


# ── Thinking parameters ──────────────────────────────────────────────────────


def _level(effort: str) -> str:
    return effort if effort in EFFORTS else "medium"


def claude_thinking(profile: ModelProfile, effort: str, max_tokens: int | None = None) -> dict:
    """Extra ``messages.stream`` kwargs. ``effort`` is off | low | medium | high.

    ``max_tokens`` is the request's output cap; a thinking budget must stay under it."""
    if effort == "off":
        if profile.thinking_off:
            return {"thinking": {"type": "disabled"}}
        if profile.thinking_between_tools:
            return {"thinking": {"type": "between_tools"}}
        if profile.thinking_adaptive and "low" in profile.effort_levels:
            return {"thinking": {"type": "adaptive"}, "output_config": {"effort": "low"}}
        return {}
    level = _level(effort)
    if profile.thinking_adaptive:
        out = {"thinking": {"type": "adaptive"}}
        if level in profile.effort_levels:
            out["output_config"] = {"effort": level}
        return out
    if profile.thinking_budget:
        budget = {"low": 2000, "medium": 4000, "high": 8000}[level]
        if max_tokens is not None:
            budget = min(budget, max_tokens - 1000)  # leave room for the reply itself
        if budget < 1024:  # the API's minimum
            return {"thinking": {"type": "disabled"}} if profile.thinking_off else {}
        return {"thinking": {"type": "enabled", "budget_tokens": budget}}
    return {}


def gemini_thinking(profile: ModelProfile, effort: str) -> dict | None:
    """Fields for ``types.ThinkingConfig``, or None to send nothing."""
    level = _level(effort)
    if profile.family == "gemini3":
        if profile.thinking_off:  # flash-class: all four levels
            return {"thinking_level": "MINIMAL" if effort == "off" else level.upper()}
        # pro-class takes only LOW and HIGH; its default is already high
        if effort in ("off", "low"):
            return {"thinking_level": "LOW"}
        return {"thinking_level": "HIGH"} if effort == "high" else None
    if profile.family == "gemini25":
        if effort == "off":
            return {"thinking_budget": 0} if profile.thinking_off else None
        return {"thinking_budget": {"low": 1024, "medium": -1, "high": 8192}[level]}
    return None


def openai_thinking(profile: ModelProfile, effort: str) -> dict:
    if profile.family != "openai-reasoning":
        return {}
    if effort == "off":
        return {"reasoning_effort": "minimal" if profile.can_minimize else "low"}
    return {"reasoning_effort": _level(effort)}


def ollama_thinking(profile: ModelProfile, effort: str) -> dict:
    if profile.family != "ollama":
        return {}
    return {"think": effort != "off"}
