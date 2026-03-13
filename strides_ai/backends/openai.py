"""OpenAI ChatGPT backend."""

import json
import time

import openai as _openai

from .. import db
from .base import BaseBackend

DEFAULT_MODEL = "gpt-4o"

# OpenAI function-calling format
SAVE_MEMORY_TOOL = {
    "type": "function",
    "function": {
        "name": "save_memory",
        "description": (
            "Save an important fact about the athlete to persistent memory. "
            "Call this whenever the athlete mentions: goals, target races or times, "
            "injuries or niggles, training preferences, weekly mileage targets, "
            "or any coaching context that should be remembered in future sessions."
        ),
        "parameters": {
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
    },
}


class OpenAIBackend(BaseBackend):
    _model_cache: dict = {"models": None, "ts": 0.0}
    _MODEL_CACHE_TTL: int = 300

    @classmethod
    def fetch_models(cls, api_key: str) -> list[dict]:
        """Fetch available OpenAI chat models from the API, with a 5-minute cache."""
        if not api_key:
            return []
        now = time.monotonic()
        if (
            cls._model_cache["models"] is not None
            and now - cls._model_cache["ts"] < cls._MODEL_CACHE_TTL
        ):
            return cls._model_cache["models"]
        try:
            client = _openai.OpenAI(api_key=api_key)
            models = sorted(
                [
                    {"id": m.id, "display_name": m.id}
                    for m in client.models.list()
                    if m.id.startswith("gpt-") or m.id.startswith("o1") or m.id.startswith("o3")
                ],
                key=lambda m: m["id"],
                reverse=True,
            )
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
        self._client = _openai.OpenAI(api_key=api_key)
        self._model = model
        # OpenAI uses the same role/content format as our neutral history format.
        self._history: list[dict] = list(initial_history)

    @property
    def label(self) -> str:
        return f"openai:{self._model}"

    @property
    def supports_attachments(self) -> bool:
        return False

    def stream_turn(self, system, user_input, on_token, attachments=None):
        if attachments:
            raise NotImplementedError("OpenAI backend does not support file attachments")

        self._history.append({"role": "user", "content": user_input})
        response_text = ""
        memories_saved: list[tuple[str, str]] = []

        while True:
            messages = [{"role": "system", "content": system}, *self._history]

            full_content = ""
            # tool_calls_by_index accumulates streaming tool-call deltas
            tool_calls_by_index: dict[int, dict] = {}

            with self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                tools=[SAVE_MEMORY_TOOL],
                tool_choice="auto",
                stream=True,
            ) as stream:
                for chunk in stream:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta is None:
                        continue

                    if delta.content:
                        on_token(delta.content)
                        full_content += delta.content

                    if delta.tool_calls:
                        for tc_delta in delta.tool_calls:
                            idx = tc_delta.index
                            if idx not in tool_calls_by_index:
                                tool_calls_by_index[idx] = {
                                    "id": "",
                                    "name": "",
                                    "arguments": "",
                                }
                            if tc_delta.id:
                                tool_calls_by_index[idx]["id"] = tc_delta.id
                            if tc_delta.function:
                                if tc_delta.function.name:
                                    tool_calls_by_index[idx]["name"] += tc_delta.function.name
                                if tc_delta.function.arguments:
                                    tool_calls_by_index[idx][
                                        "arguments"
                                    ] += tc_delta.function.arguments

            tool_calls = [tool_calls_by_index[i] for i in sorted(tool_calls_by_index)]

            # Build the assistant history entry
            if tool_calls:
                self._history.append(
                    {
                        "role": "assistant",
                        "content": full_content or None,
                        "tool_calls": [
                            {
                                "id": tc["id"],
                                "type": "function",
                                "function": {
                                    "name": tc["name"],
                                    "arguments": tc["arguments"],
                                },
                            }
                            for tc in tool_calls
                        ],
                    }
                )
            else:
                self._history.append({"role": "assistant", "content": full_content})
                response_text += full_content
                break

            # Execute tool calls and append results
            for tc in tool_calls:
                if tc["name"] == "save_memory":
                    try:
                        args = json.loads(tc["arguments"])
                    except json.JSONDecodeError:
                        args = {}
                    category = args.get("category", "other")
                    content = args.get("content", "")
                    result = db.save_memory(category, content)
                    memories_saved.append((category, content))
                    self._history.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": result,
                        }
                    )

        return response_text, memories_saved
