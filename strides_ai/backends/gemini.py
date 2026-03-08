"""Google Gemini backend."""

import time

from google import genai
from google.genai import types
from google.genai.errors import ClientError

from .. import db
from .base import BaseBackend

DEFAULT_MODEL = "gemini-2.0-flash"

_MAX_RETRIES = 3
_RETRY_DELAY_S = 10  # seconds to wait after a 429

SAVE_MEMORY_TOOL = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="save_memory",
            description=(
                "Save an important fact about the athlete to persistent memory. "
                "Call this whenever the athlete mentions: goals, target races or times, "
                "injuries or niggles, training preferences, weekly mileage targets, "
                "or any coaching context that should be remembered in future sessions."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "category": types.Schema(
                        type=types.Type.STRING,
                        enum=["goal", "race", "injury", "preference", "training", "other"],
                        description="Category of the memory",
                    ),
                    "content": types.Schema(
                        type=types.Type.STRING,
                        description="The fact to remember, as a clear concise statement",
                    ),
                },
                required=["category", "content"],
            ),
        )
    ]
)


class GeminiBackend(BaseBackend):
    def __init__(
        self,
        api_key: str,
        initial_history: list[dict],
        model: str = DEFAULT_MODEL,
    ) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model
        # Convert neutral history (role: user/assistant, content: str) to Gemini Content objects
        self._history: list[types.Content] = []
        for msg in initial_history:
            role = "model" if msg["role"] == "assistant" else "user"
            content = msg["content"]
            if isinstance(content, str):
                self._history.append(
                    types.Content(role=role, parts=[types.Part.from_text(text=content)])
                )

    @property
    def label(self) -> str:
        return f"gemini:{self._model}"

    @property
    def supports_attachments(self) -> bool:
        return False

    def stream_turn(self, system, user_input, on_token, attachments=None):
        if attachments:
            raise NotImplementedError("Gemini backend does not support file attachments")

        self._history.append(
            types.Content(role="user", parts=[types.Part.from_text(text=user_input)])
        )

        config = types.GenerateContentConfig(
            system_instruction=system,
            tools=[SAVE_MEMORY_TOOL],
        )

        response_text = ""
        memories_saved: list[tuple[str, str]] = []
        first_turn = True

        while True:
            collected_text = ""
            fc_parts: list[types.Part] = []

            if first_turn:
                # Stream the first response to the user (with retry on rate limit)
                for attempt in range(_MAX_RETRIES):
                    try:
                        for chunk in self._client.models.generate_content_stream(
                            model=self._model,
                            contents=self._history,
                            config=config,
                        ):
                            if chunk.text:
                                on_token(chunk.text)
                                collected_text += chunk.text
                            # Collect function-call parts (arrive as complete parts, not deltas)
                            if chunk.candidates:
                                for part in chunk.candidates[0].content.parts:
                                    fc = getattr(part, "function_call", None)
                                    if fc and getattr(fc, "name", None):
                                        fc_parts.append(part)
                        break  # success
                    except ClientError as exc:
                        if exc.code != 429 or attempt == _MAX_RETRIES - 1:
                            raise
                        on_token(f"\n\n*(Rate limit hit — retrying in {_RETRY_DELAY_S}s…)*\n\n")
                        collected_text = ""
                        fc_parts = []
                        time.sleep(_RETRY_DELAY_S)
                first_turn = False
            else:
                # Non-streaming for follow-up turns after tool responses
                for attempt in range(_MAX_RETRIES):
                    try:
                        resp = self._client.models.generate_content(
                            model=self._model,
                            contents=self._history,
                            config=config,
                        )
                        break  # success
                    except ClientError as exc:
                        if exc.code != 429 or attempt == _MAX_RETRIES - 1:
                            raise
                        time.sleep(_RETRY_DELAY_S)
                if resp.candidates:
                    for part in resp.candidates[0].content.parts:
                        if part.text:
                            on_token(part.text)
                            collected_text += part.text
                        else:
                            fc = getattr(part, "function_call", None)
                            if fc and getattr(fc, "name", None):
                                fc_parts.append(part)

            # Append the model's response to history
            model_parts: list[types.Part] = []
            if collected_text:
                model_parts.append(types.Part.from_text(text=collected_text))
                response_text += collected_text
            model_parts.extend(fc_parts)
            if model_parts:
                self._history.append(types.Content(role="model", parts=model_parts))

            if not fc_parts:
                break

            # Execute tool calls and add responses
            tool_response_parts: list[types.Part] = []
            for part in fc_parts:
                fc = part.function_call
                if fc.name == "save_memory":
                    args = dict(fc.args)
                    category = args.get("category", "other")
                    content = args.get("content", "")
                    result = db.save_memory(category, content)
                    memories_saved.append((category, content))
                    tool_response_parts.append(
                        types.Part.from_function_response(
                            name="save_memory",
                            response={"result": result},
                        )
                    )
            self._history.append(types.Content(role="user", parts=tool_response_parts))

        return response_text, memories_saved
