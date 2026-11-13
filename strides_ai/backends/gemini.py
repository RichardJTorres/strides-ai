"""Google Gemini backend."""

import json
import time

from google import genai
from google.genai import types
from google.genai.errors import ClientError

from ..budget import BudgetExceeded
from ..kinds import KINDS, RACE_PRIORITIES, RACE_SPORTS, WORKOUT_TYPES
from ..workout_structure import WORKOUT_STRUCTURE_SCHEMA

from .base import (
    DISTANCE_UNITS,
    ELEVATION_UNITS,
    SAVE_MEMORY_CATEGORIES,
    SAVE_MEMORY_TIMING_PROPERTIES,
    SAVE_MEMORY_DESCRIPTION,
    UPDATE_PROFILE_DESCRIPTION,
    UPDATE_PROFILE_OPS,
    UPDATE_TRAINING_PLAN_DESCRIPTION,
    update_profile_fields,
    BaseBackend,
)

DEFAULT_MODEL = "gemini-2.5-flash"

_MAX_RETRIES = 3
_RETRY_DELAY_S = 10  # seconds to wait after a 429


def _gemini_structure_schema() -> "types.Schema":
    """Gemini mirror of workout_structure.WORKOUT_STRUCTURE_SCHEMA."""
    number, integer = types.Type.NUMBER, types.Type.INTEGER
    fields = {
        "duration_s": integer,
        "from_pct": number,
        "to_pct": number,
        "pct": number,
        "repeat": integer,
        "on_s": integer,
        "on_pct": number,
        "off_s": integer,
        "off_pct": number,
    }
    block = types.Schema(
        type=types.Type.OBJECT,
        properties={
            "kind": types.Schema(
                type=types.Type.STRING,
                enum=["warmup", "cooldown", "ramp", "steady", "intervals", "freeride"],
            ),
            **{name: types.Schema(type=t) for name, t in fields.items()},
        },
        required=["kind"],
    )
    return types.Schema(
        type=types.Type.OBJECT,
        description=WORKOUT_STRUCTURE_SCHEMA["description"],
        properties={"blocks": types.Schema(type=types.Type.ARRAY, items=block)},
        required=["blocks"],
    )


SAVE_MEMORY_TOOL = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="save_memory",
            description=SAVE_MEMORY_DESCRIPTION,
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    **{
                        key: types.Schema(
                            type=(
                                types.Type.INTEGER
                                if value["type"] == "integer"
                                else types.Type.STRING
                            ),
                            description=value.get("description"),
                            enum=value.get("enum"),
                        )
                        for key, value in SAVE_MEMORY_TIMING_PROPERTIES.items()
                    },
                    "category": types.Schema(
                        type=types.Type.STRING,
                        enum=SAVE_MEMORY_CATEGORIES,
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

UPDATE_PROFILE_TOOL = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="update_profile",
            description=UPDATE_PROFILE_DESCRIPTION,
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "field": types.Schema(type=types.Type.STRING, enum=update_profile_fields()),
                    "value": types.Schema(type=types.Type.STRING),
                    "op": types.Schema(type=types.Type.STRING, enum=UPDATE_PROFILE_OPS),
                },
                required=["field", "value"],
            ),
        )
    ]
)

UPDATE_TRAINING_PLAN_TOOL = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="update_training_plan",
            description=UPDATE_TRAINING_PLAN_DESCRIPTION,
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "set": types.Schema(
                        type=types.Type.ARRAY,
                        description="Entries to create (no id) or update (with id).",
                        items=types.Schema(
                            type=types.Type.OBJECT,
                            properties={
                                "id": types.Schema(
                                    type=types.Type.INTEGER,
                                    description="Entry id to change. Omit to create.",
                                ),
                                "date": types.Schema(
                                    type=types.Type.STRING, description="ISO date, YYYY-MM-DD"
                                ),
                                "kind": types.Schema(type=types.Type.STRING, enum=list(KINDS)),
                                "workout_type": types.Schema(
                                    type=types.Type.STRING,
                                    description="Workouts only: " + ", ".join(WORKOUT_TYPES),
                                ),
                                "title": types.Schema(type=types.Type.STRING),
                                "description": types.Schema(type=types.Type.STRING),
                                "distance": types.Schema(type=types.Type.NUMBER),
                                "distance_unit": types.Schema(
                                    type=types.Type.STRING, enum=list(DISTANCE_UNITS)
                                ),
                                "elevation": types.Schema(type=types.Type.NUMBER),
                                "elevation_unit": types.Schema(
                                    type=types.Type.STRING, enum=list(ELEVATION_UNITS)
                                ),
                                "duration_min": types.Schema(type=types.Type.INTEGER),
                                "intensity": types.Schema(
                                    type=types.Type.STRING, enum=["easy", "moderate", "hard"]
                                ),
                                "sport": types.Schema(
                                    type=types.Type.STRING, enum=list(RACE_SPORTS)
                                ),
                                "goal_time": types.Schema(type=types.Type.STRING),
                                "priority": types.Schema(
                                    type=types.Type.STRING, enum=list(RACE_PRIORITIES)
                                ),
                                "structure": _gemini_structure_schema(),
                            },
                        ),
                    ),
                    "delete": types.Schema(
                        type=types.Type.ARRAY,
                        description="Ids of entries to remove from the calendar.",
                        items=types.Schema(type=types.Type.INTEGER),
                    ),
                },
            ),
        )
    ]
)


class GeminiBackend(BaseBackend):
    _model_cache: dict = {"models": None, "ts": 0.0}
    _MODEL_CACHE_TTL: int = 300

    @classmethod
    def fetch_models(cls, api_key: str) -> list[dict]:
        """Fetch available Gemini generateContent models from the API, with a 5-minute cache."""
        if not api_key:
            return []
        now = time.monotonic()
        if (
            cls._model_cache["models"] is not None
            and now - cls._model_cache["ts"] < cls._MODEL_CACHE_TTL
        ):
            return cls._model_cache["models"]
        try:
            client = genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)),
            )
            models = []
            for m in client.models.list():
                if "generateContent" not in (m.supported_actions or []):
                    continue
                model_id = m.name.removeprefix("models/")
                if not model_id.startswith("gemini-"):
                    continue
                models.append({"id": model_id, "display_name": m.display_name or model_id})
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
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)),
        )
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

    def _submission_history(self, message, attachments):
        return [
            *self._history,
            types.Content(role="user", parts=[types.Part.from_text(text=message)]),
        ]

    def _count_request(self, system, history, tools):
        # The Gemini developer API's count_tokens rejects system_instruction and tools (the SDK
        # raises ValueError, which admission would report as a 413). Count them as leading text
        # instead: the same words, so the total tracks a real request closely.
        preamble = f"{system}\n\n{json.dumps(tools, default=str)}"
        try:
            return self._client.models.count_tokens(
                model=self._model,
                contents=[
                    types.Content(role="user", parts=[types.Part.from_text(text=preamble)]),
                    *history,
                ],
            ).total_tokens
        except (AttributeError, NotImplementedError, ValueError):
            return None
        except ClientError as exc:
            if exc.code in (400, 404, 405, 413, 422):
                return None
            raise

    def _record_usage(self, response):
        metadata = getattr(response, "usage_metadata", None)
        visible = getattr(metadata, "candidates_token_count", None)
        thoughts = getattr(metadata, "thoughts_token_count", None)
        if type(visible) is int:
            self._reported_output = visible + (thoughts if type(thoughts) is int else 0)

    def stream_turn(self, system, user_input, on_token, attachments=None):
        if attachments:
            raise NotImplementedError("Gemini backend does not support file attachments")

        self._history.append(
            types.Content(role="user", parts=[types.Part.from_text(text=user_input)])
        )

        config = types.GenerateContentConfig(
            system_instruction=system,
            tools=[SAVE_MEMORY_TOOL, UPDATE_TRAINING_PLAN_TOOL, UPDATE_PROFILE_TOOL],
        )

        response_text = ""
        memories_saved: list[tuple[str, str]] = []
        plan_changes: list[dict] = []
        first_turn = True

        while True:
            self._before_request(system)
            config.max_output_tokens = self._budget.output_remaining
            collected_text = ""
            fc_parts: list[types.Part] = []

            if first_turn:
                # Stream the first response to the user (with retry on rate limit)
                for attempt in range(self.limits.retries + 1):
                    try:
                        self._check_cancelled()
                        self._budget.check_request(system, self._history, self._tool_definitions())
                        for chunk in self._client.models.generate_content_stream(
                            model=self._model,
                            contents=self._history,
                            config=config,
                        ):
                            self._check_cancelled()
                            self._record_usage(chunk)
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
                        if exc.code != 429 or collected_text or fc_parts:
                            raise
                        if attempt == self.limits.retries:
                            raise BudgetExceeded("Transport retry limit reached.") from exc
                        on_token(f"\n\n*(Rate limit hit — retrying in {_RETRY_DELAY_S}s…)*\n\n")
                        collected_text = ""
                        fc_parts = []
                        self._budget.record.retry(_RETRY_DELAY_S)
                        event = getattr(self, "cancel_event", None)
                        if event is not None:
                            event.wait(_RETRY_DELAY_S)
                        else:
                            time.sleep(_RETRY_DELAY_S)
                first_turn = False
            else:
                # Non-streaming for follow-up turns after tool responses
                for attempt in range(self.limits.retries + 1):
                    try:
                        self._check_cancelled()
                        self._budget.check_request(system, self._history, self._tool_definitions())
                        resp = self._client.models.generate_content(
                            model=self._model,
                            contents=self._history,
                            config=config,
                        )
                        break  # success
                    except ClientError as exc:
                        if exc.code != 429 or collected_text or fc_parts:
                            raise
                        if attempt == self.limits.retries:
                            raise BudgetExceeded("Transport retry limit reached.") from exc
                        self._budget.record.retry(_RETRY_DELAY_S)
                        event = getattr(self, "cancel_event", None)
                        if event is not None:
                            event.wait(_RETRY_DELAY_S)
                        else:
                            time.sleep(_RETRY_DELAY_S)
                self._record_usage(resp)
                if resp.candidates:
                    for part in resp.candidates[0].content.parts:
                        if part.text:
                            on_token(part.text)
                            collected_text += part.text
                        else:
                            fc = getattr(part, "function_call", None)
                            if fc and getattr(fc, "name", None):
                                fc_parts.append(part)

            for part in fc_parts:
                self._budget.output(
                    {"name": part.function_call.name, "args": dict(part.function_call.args)}
                )

            self._budget.usage(self._reported_output)

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
                result = self._run_tool(fc.name, dict(fc.args or {}), memories_saved, plan_changes)
                if result is not None:
                    tool_response_parts.append(
                        types.Part.from_function_response(
                            name=fc.name,
                            response={"result": result},
                        )
                    )
            self._history.append(types.Content(role="user", parts=tool_response_parts))

        return response_text, memories_saved, plan_changes

    def stateless_turn(self, system, user_input, on_token):
        config = types.GenerateContentConfig(system_instruction=system)
        contents = [types.Content(role="user", parts=[types.Part.from_text(text=user_input)])]
        response_text = ""
        for attempt in range(_MAX_RETRIES):
            try:
                for chunk in self._client.models.generate_content_stream(
                    model=self._model,
                    contents=contents,
                    config=config,
                ):
                    if chunk.text:
                        on_token(chunk.text)
                        response_text += chunk.text
                break
            except ClientError as exc:
                if exc.code != 429 or attempt == _MAX_RETRIES - 1:
                    raise
                time.sleep(_RETRY_DELAY_S)
        return response_text
