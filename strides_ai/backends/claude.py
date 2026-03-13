"""Anthropic Claude backend."""

import time

import anthropic

from .. import db
from .base import BaseBackend

DEFAULT_MODEL = "claude-sonnet-4-6"

# Anthropic tool-use format
SAVE_MEMORY_TOOL = {
    "name": "save_memory",
    "description": (
        "Save an important fact about the athlete to persistent memory. "
        "Call this whenever the athlete mentions: goals, target races or times, "
        "injuries or niggles, training preferences, weekly mileage targets, "
        "or any coaching context that should be remembered in future sessions."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "enum": ["goal", "race", "injury", "preference", "training", "other"],
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
            client = anthropic.Anthropic(api_key=api_key)
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
        self._client = anthropic.Anthropic(api_key=api_key)
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

    def stream_turn(self, system, user_input, on_token, attachments=None):
        if attachments:
            content = [*attachments, {"type": "text", "text": user_input}]
        else:
            content = user_input
        self._history.append({"role": "user", "content": content})
        response_text = ""
        memories_saved: list[tuple[str, str]] = []

        while True:
            with self._client.messages.stream(
                model=self._model,
                max_tokens=2048,
                system=system,
                messages=self._history,
                tools=[SAVE_MEMORY_TOOL],
            ) as stream:
                for chunk in stream.text_stream:
                    on_token(chunk)
                    response_text += chunk
                final = stream.get_final_message()

            self._history.append({"role": "assistant", "content": final.content})

            if final.stop_reason != "tool_use":
                break

            tool_results = []
            for block in final.content:
                if not (hasattr(block, "type") and block.type == "tool_use"):
                    continue
                if block.name == "save_memory":
                    result = db.save_memory(block.input["category"], block.input["content"])
                    memories_saved.append((block.input["category"], block.input["content"]))
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        }
                    )

            self._history.append({"role": "user", "content": tool_results})

        return response_text, memories_saved
