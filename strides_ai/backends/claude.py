"""Anthropic Claude backend."""

import time

import anthropic

from .base import (
    SAVE_MEMORY_CATEGORIES,
    SAVE_MEMORY_TIMING_PROPERTIES,
    SAVE_MEMORY_DESCRIPTION,
    UPDATE_TRAINING_PLAN_DESCRIPTION,
    BaseBackend,
)

DEFAULT_MODEL = "claude-sonnet-4-6"

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

_WORKOUT_ENTRY_SCHEMA = {
    "type": "object",
    "properties": {
        "date": {"type": "string", "description": "ISO date, YYYY-MM-DD"},
        "workout_type": {
            "type": "string",
            "description": (
                "e.g. Easy Run, Long Run, Tempo Run, Easy Ride, Long Ride, Tempo Ride, "
                "Indoor Ride, Intervals, Cross-Training, Race, Rest"
            ),
        },
        "description": {"type": "string"},
        "distance_km": {"type": "number"},
        "elevation_m": {"type": "number"},
        "duration_min": {"type": "integer"},
        "intensity": {"type": "string", "enum": ["easy", "moderate", "hard", "rest"]},
    },
    "required": ["date", "workout_type"],
}

UPDATE_TRAINING_PLAN_TOOL = {
    "name": "update_training_plan",
    "description": UPDATE_TRAINING_PLAN_DESCRIPTION,
    "input_schema": {
        "type": "object",
        "properties": {
            "set": {
                "type": "array",
                "description": "Workouts to create or overwrite, one entry per date.",
                "items": _WORKOUT_ENTRY_SCHEMA,
            },
            "delete": {
                "type": "array",
                "description": "Dates (YYYY-MM-DD) to clear from the calendar.",
                "items": {"type": "string"},
            },
        },
    },
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
                    system=system,
                    messages=self._history,
                    tools=[SAVE_MEMORY_TOOL, UPDATE_TRAINING_PLAN_TOOL],
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
            self._budget.usage(getattr(getattr(final, "usage", None), "output_tokens", None))
            self._history.append({"role": "assistant", "content": final.content})

            if final.stop_reason == "max_tokens":
                notice = "\n\n_[Response truncated — hit the length limit. Ask me to continue.]_"
                on_token(notice)
                response_text += notice
                break

            if final.stop_reason != "tool_use":
                break

            tool_results = []
            for block in final.content:
                if not (hasattr(block, "type") and block.type == "tool_use"):
                    continue
                if block.name == "save_memory":
                    result, category, content = self._execute_save_memory(block.input)
                    memories_saved.append((category, content))
                    tool_results.append(
                        {"type": "tool_result", "tool_use_id": block.id, "content": result}
                    )
                elif block.name == "update_training_plan":
                    result, changes = self._execute_update_training_plan(block.input)
                    plan_changes.extend(changes)
                    tool_results.append(
                        {"type": "tool_result", "tool_use_id": block.id, "content": result}
                    )

            self._history.append({"role": "user", "content": tool_results})

        return response_text, memories_saved, plan_changes

    def stateless_turn(self, system, user_input, on_token):
        response_text = ""
        with self._client.messages.stream(
            model=self._model,
            max_tokens=8192,
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
        return response_text
