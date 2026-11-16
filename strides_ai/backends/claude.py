"""Anthropic Claude backend."""

import time

import anthropic

from ..budget import Usage
from .model_profile import claude_thinking, resolve_profile
from .base import (
    UPDATE_TRAINING_PLAN_PARAMETERS,
    SAVE_MEMORY_CATEGORIES,
    SAVE_MEMORY_TIMING_PROPERTIES,
    SAVE_MEMORY_DESCRIPTION,
    UPDATE_PROFILE_DESCRIPTION,
    UPDATE_PROFILE_OPS,
    UPDATE_TRAINING_PLAN_DESCRIPTION,
    update_profile_fields,
    BaseBackend,
)

DEFAULT_MODEL = "claude-sonnet-4-6"


def claude_usage(usage) -> Usage:
    """Normalize Anthropic usage. Input is the uncached part plus every cached part."""
    fresh = getattr(usage, "input_tokens", None)
    write = getattr(usage, "cache_creation_input_tokens", None)
    read = getattr(usage, "cache_read_input_tokens", None)
    total = None
    if type(fresh) is int:
        total = fresh + sum(v for v in (write, read) if type(v) is int)
    return Usage.of(
        input_total=total,
        cache_read=read,
        cache_write=write,
        output_total=getattr(usage, "output_tokens", None),
    )


# Below this much remaining output budget a round skips thinking so the reply still fits.
MIN_THINKING_ROOM = 4000

# Anthropic tool-use format
SAVE_MEMORY_TOOL = {
    "name": "save_memory",
    "description": SAVE_MEMORY_DESCRIPTION,
    "input_schema": {
        "type": "object",
        "properties": {
            **SAVE_MEMORY_TIMING_PROPERTIES,
            "category": {
                "type": "string",
                "enum": SAVE_MEMORY_CATEGORIES,
                "description": "Category of the memory",
            },
            "content": {
                "type": "string",
                "description": "The fact to remember, as a clear concise statement",
            },
        },
        "required": ["category", "content"],
    },
}

UPDATE_PROFILE_TOOL = {
    "name": "update_profile",
    "description": UPDATE_PROFILE_DESCRIPTION,
    "input_schema": {
        "type": "object",
        "properties": {
            "field": {"type": "string", "enum": update_profile_fields()},
            "value": {"type": "string"},
            "op": {"type": "string", "enum": UPDATE_PROFILE_OPS},
        },
        "required": ["field", "value"],
    },
}

UPDATE_TRAINING_PLAN_TOOL = {
    "name": "update_training_plan",
    "description": UPDATE_TRAINING_PLAN_DESCRIPTION,
    "input_schema": UPDATE_TRAINING_PLAN_PARAMETERS,
}


class ClaudeBackend(BaseBackend):
    _model_cache: dict = {"models": None, "ts": 0.0}
    _MODEL_CACHE_TTL: int = 300

    @classmethod
    def fetch_models(cls, api_key: str) -> list[dict]:
        """Fetch available Claude models from the Anthropic API, with a 5-minute cache."""
        if not api_key:
            return []
        now = time.monotonic()
        if (
            cls._model_cache["models"] is not None
            and now - cls._model_cache["ts"] < cls._MODEL_CACHE_TTL
        ):
            return cls._model_cache["models"]
        try:
            client = anthropic.Anthropic(api_key=api_key, max_retries=0)
            models = [
                {"id": m.id, "display_name": m.display_name} for m in client.models.list(limit=100)
            ]
        except Exception:
            models = []
        cls._model_cache["models"] = models
        cls._model_cache["ts"] = now
        return models

    def __init__(
        self,
        api_key: str,
        initial_history: list[dict],
        model: str = DEFAULT_MODEL,
    ) -> None:
        self._client = anthropic.Anthropic(api_key=api_key, max_retries=0)
        self._model = model
        # History stays in Anthropic format; initial messages have str content
        # which the API accepts directly.
        self._history: list = list(initial_history)

    @property
    def label(self) -> str:
        return self._model

    @property
    def supports_attachments(self) -> bool:
        return True

    def _count_request(self, system, history, tools):
        try:
            return self._client.messages.count_tokens(
                model=self._model, system=system, messages=history, tools=tools
            ).input_tokens
        except (AttributeError, NotImplementedError):
            return None
        except anthropic.APIStatusError as exc:
            if exc.status_code in (400, 404, 405, 413, 422):
                return None
            raise

    def _fetch_profile(self):
        return (
            self._client.with_options(max_retries=0, timeout=5)
            .models.retrieve(self._model)
            .model_dump()
        )

    @property
    def profile(self):
        return resolve_profile("claude", self._model, self._fetch_profile)

    def _thinking_kwargs(self, oneshot=False):
        """Thinking settings, as extra messages.stream kwargs, taken from the model's profile.

        Newer models think by default and reasoning counts against max_tokens, so an
        unmanaged default can starve the reply. Chat turns use the configured effort and the
        lightest setting the model takes when too little output budget is left; one-shot calls
        want the answer, so they ask for little thinking.
        """
        from ..config import get_settings

        effort = "low" if oneshot else get_settings().thinking_effort
        if not oneshot and self._budget.output_remaining < MIN_THINKING_ROOM:
            effort = "off"
        return claude_thinking(
            self.profile, effort, None if oneshot else self._budget.output_remaining
        )

    def stream_turn(self, system, user_input, on_token, attachments=None):
        if attachments:
            content = [*attachments, {"type": "text", "text": user_input}]
        else:
            content = user_input
        self._history.append({"role": "user", "content": content})
        response_text = ""
        memories_saved: list[tuple[str, str]] = []
        plan_changes: list[dict] = []

        while True:
            self._before_request(system)
            with self._transport_stream(
                lambda: self._client.messages.stream(
                    model=self._model,
                    max_tokens=self._budget.output_remaining,
                    **self._thinking_kwargs(),
                    system=system,
                    messages=self._history,
                    tools=[SAVE_MEMORY_TOOL, UPDATE_TRAINING_PLAN_TOOL, UPDATE_PROFILE_TOOL],
                )
            ) as stream:
                for chunk in stream.text_stream:
                    self._check_cancelled()
                    on_token(chunk)
                    response_text += chunk
                final = stream.get_final_message()

            for block in final.content:
                if getattr(block, "type", "") == "tool_use":
                    self._budget.output({"name": block.name, "input": block.input})
            self._budget.usage(claude_usage(getattr(final, "usage", None)))
            self._history.append({"role": "assistant", "content": final.content})

            if final.stop_reason == "max_tokens":
                self._budget.notice = "truncated"
                break

            if final.stop_reason != "tool_use":
                break

            tool_results = []
            for block in final.content:
                if not (hasattr(block, "type") and block.type == "tool_use"):
                    continue
                result = self._run_tool(block.name, block.input, memories_saved, plan_changes)
                if result is not None:
                    tool_results.append(
                        {"type": "tool_result", "tool_use_id": block.id, "content": result}
                    )

            self._history.append({"role": "user", "content": tool_results})

        return response_text, memories_saved, plan_changes

    def _stateless_turn(self, system, user_input, on_token):
        response_text = ""
        with self._client.messages.stream(
            model=self._model,
            # Thinking tokens count against max_tokens; a long structured answer (e.g. a training
            # block) can be starved to nothing, so ask for little thinking and leave headroom.
            max_tokens=min(16000, self.profile.max_output),
            **self._thinking_kwargs(oneshot=True),
            system=system,
            messages=[{"role": "user", "content": user_input}],
        ) as stream:
            for chunk in stream.text_stream:
                on_token(chunk)
                response_text += chunk
            final = stream.get_final_message()
        if final.stop_reason == "max_tokens":
            notice = "\n\n_[Response truncated — hit the length limit.]_"
            on_token(notice)
            response_text += notice
        return response_text, claude_usage(getattr(final, "usage", None))
