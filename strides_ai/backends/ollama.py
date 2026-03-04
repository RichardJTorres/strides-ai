"""Ollama backend (native /api/chat endpoint)."""

import json

import httpx

from .. import db
from .base import BaseBackend

DEFAULT_HOST = "http://localhost:11434"

# Ollama uses the OpenAI function-calling schema
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


class OllamaBackend(BaseBackend):
    def __init__(
        self,
        model: str,
        initial_history: list[dict],
        host: str = DEFAULT_HOST,
    ) -> None:
        self._model = model
        self._host = host.rstrip("/")
        # Ollama uses the same OpenAI-style role/content format as our neutral format,
        # so initial_history requires no conversion.
        self._history: list[dict] = list(initial_history)

    @property
    def label(self) -> str:
        return f"ollama:{self._model}"

    def stream_turn(self, system, user_input, console):
        self._history.append({"role": "user", "content": user_input})
        response_text = ""
        memories_saved: list[tuple[str, str]] = []

        while True:
            # Prepend system message each call (Ollama has no separate system param)
            messages = [{"role": "system", "content": system}, *self._history]

            full_content = ""
            tool_calls: list[dict] = []

            with httpx.Client(timeout=120) as client:
                with client.stream(
                    "POST",
                    f"{self._host}/api/chat",
                    json={
                        "model": self._model,
                        "messages": messages,
                        "tools": [SAVE_MEMORY_TOOL],
                        "stream": True,
                    },
                ) as resp:
                    resp.raise_for_status()
                    for line in resp.iter_lines():
                        if not line:
                            continue
                        chunk = json.loads(line)
                        msg = chunk.get("message", {})

                        text = msg.get("content", "")
                        if text:
                            console.print(text, end="", markup=False)
                            full_content += text
                            response_text += text

                        # Tool calls typically arrive in the final chunk
                        if msg.get("tool_calls"):
                            tool_calls = msg["tool_calls"]

                        if chunk.get("done"):
                            break

            self._history.append({"role": "assistant", "content": full_content})

            if not tool_calls:
                break

            # Execute tool calls and add results to history
            for tc in tool_calls:
                fn = tc.get("function", {})
                if fn.get("name") == "save_memory":
                    args = fn.get("arguments", {})
                    category = args.get("category", "other")
                    content = args.get("content", "")
                    result = db.save_memory(category, content)
                    memories_saved.append((category, content))
                    self._history.append({"role": "tool", "content": result})

        return response_text, memories_saved
