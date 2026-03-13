"""Ollama backend (native /api/chat endpoint)."""

import json
import time

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
    _model_cache: dict = {"models": None, "ts": 0.0}
    _MODEL_CACHE_TTL: int = 300

    @classmethod
    def fetch_models(cls, host: str) -> list[dict]:
        """Fetch available models from the Ollama API, with a 5-minute cache."""
        host = host.rstrip("/")
        now = time.monotonic()
        if (
            cls._model_cache["models"] is not None
            and now - cls._model_cache["ts"] < cls._MODEL_CACHE_TTL
        ):
            return cls._model_cache["models"]
        try:
            resp = httpx.get(f"{host}/api/tags", timeout=3)
            models = [
                {"id": m["name"], "display_name": m["name"]} for m in resp.json().get("models", [])
            ]
        except Exception:
            models = []
        cls._model_cache["models"] = models
        cls._model_cache["ts"] = now
        return models

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
        # None = not yet tested; False = model doesn't support tools (e.g. Gemma)
        self._supports_tools: bool | None = None

    @property
    def label(self) -> str:
        return f"ollama:{self._model}"

    @property
    def supports_attachments(self) -> bool:
        return False

    def stream_turn(self, system, user_input, on_token, attachments=None):
        if attachments:
            raise NotImplementedError("Ollama backend does not support file attachments")
        self._history.append({"role": "user", "content": user_input})
        response_text = ""
        memories_saved: list[tuple[str, str]] = []

        while True:
            # Prepend system message each call (Ollama has no separate system param)
            messages = [{"role": "system", "content": system}, *self._history]

            full_content = ""
            tool_calls: list[dict] = []

            body: dict = {"model": self._model, "messages": messages, "stream": True}
            if self._supports_tools is not False:
                body["tools"] = [SAVE_MEMORY_TOOL]

            retry_without_tools = False
            with httpx.Client(timeout=120) as client:
                with client.stream("POST", f"{self._host}/api/chat", json=body) as resp:
                    if resp.status_code == 400 and "tools" in body:
                        # Model doesn't support tool calling (e.g. Gemma) — retry without
                        self._supports_tools = False
                        retry_without_tools = True
                    else:
                        resp.raise_for_status()
                        for line in resp.iter_lines():
                            if not line:
                                continue
                            chunk = json.loads(line)
                            msg = chunk.get("message", {})

                            text = msg.get("content", "")
                            if text:
                                on_token(text)
                                full_content += text
                                response_text += text

                            # Tool calls typically arrive in the final chunk
                            if msg.get("tool_calls"):
                                tool_calls = msg["tool_calls"]

                            if chunk.get("done"):
                                break

            if retry_without_tools:
                continue

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
