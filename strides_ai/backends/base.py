"""Abstract base class for LLM backends."""

from abc import ABC, abstractmethod
from typing import Callable

from .. import db
from ..budget import (
    DEFAULT_BYTES_PER_TOKEN,
    TOOL_BUDGET_NOTE,
    Limits,
    RoundPlan,
    TurnBudget,
    TurnStop,
    bounded_turn,
    BudgetExceeded,
    estimate,
    normalize_limits,
)
from ..kinds import (
    KINDS,
    display_type,
    parse_goal_time,
    race_sport_for_legacy_type,
    RACE_PRIORITIES,
    RACE_SPORTS,
    RIDE_DISPLAY_TYPES,
    RUN_DISPLAY_TYPES,
    WORKOUT_TYPES,
)
from ..db.calendar import EntryError
from ..units import Quantity, UnitSystem, to_si
from ..workout_structure import INDOOR_RIDE_GUIDANCE, WORKOUT_STRUCTURE_SCHEMA

# Mirrors ROUTE_CAPABLE_WORKOUT_TYPES in web/src/pages/calendar/constants.ts.
ROUTE_CAPABLE_WORKOUT_TYPES = RUN_DISPLAY_TYPES | RIDE_DISPLAY_TYPES

SAVE_MEMORY_DESCRIPTION = (
    "Save an important fact about the athlete to persistent memory. "
    "Call this whenever the athlete mentions: goals, target races or times, "
    "injuries or niggles, training preferences, weekly mileage targets, "
    "or any coaching context that should be remembered in future sessions."
)

SAVE_MEMORY_TIMING_PROPERTIES = {
    "status": {"type": "string", "enum": ["current", "temporary", "superseded"]},
    "topic": {
        "type": "string",
        "description": "Stable specific topic, e.g. primary_goal or running_intensity. Reuse an existing topic only for replacement facts.",
    },
    "effective_from": {
        "type": "string",
        "description": "Inclusive start date YYYY-MM-DD. Use today's date for a new current preference, unless athlete specifies otherwise.",
    },
    "effective_until": {
        "type": "string",
        "description": "Inclusive end date YYYY-MM-DD; omit if unknown. Never invent an expiry.",
    },
    "memory_id": {
        "type": "integer",
        "description": "Existing memory ID to revise or mark superseded; omit to create a new fact.",
    },
}
SAVE_MEMORY_DESCRIPTION += (
    " Use status=current for standing facts, temporary for temporary changes, superseded for "
    "explicitly replaced facts. Set effective dates from the athlete's statements. Omit unknown "
    "end dates. Use specific shared topics to connect replacements: active temporary facts "
    "override standing facts on that topic, and the standing fact resumes after expiry. "
    "When a legacy fact has no topic, revise it using memory_id to assign the same topic before "
    "saving its replacement. Never group unrelated races or goals into a single topic. "
    "Never infer a past fact's effective date from its save timestamp."
)

UPDATE_PROFILE_DESCRIPTION = (
    "Propose a change to the athlete's saved profile. Use it for stable facts that belong on "
    "their profile page (goals, injuries, weekly availability, max heart rate, training "
    "background, personal bests, gear); use save_memory for temporary or time-bound facts. "
    "The change is NOT applied: the athlete sees it and accepts or dismisses it, so tell them "
    "what you proposed. Only propose what the athlete actually stated, one field per call. "
    "`value` is plain text: a number for sessions_per_week and max_hr, comma-separated weekdays "
    "(mon, wed) for preferred_days, a focus key for focus. Use op=append to add to existing text."
)
UPDATE_PROFILE_OPS = ["set", "append"]


def update_profile_fields() -> list[str]:
    from ..profile import profile_update_fields

    return sorted(profile_update_fields())


SAVE_MEMORY_CATEGORIES: list[str] = ["goal", "race", "injury", "preference", "training", "other"]

# One update_training_plan call changes at most this many entries (set items plus deleted ids);
# a larger call is rejected whole and the coach is told to split it. Bounds the call's size, so
# the result, which lists every id, stays small too.
MAX_PLAN_OPERATIONS = 31
# A result names at most this many warnings or rejection reasons, each clipped, then "and N more".
MAX_RESULT_REASONS = 5
MAX_REASON_CHARS = 200


def bounded_reasons(items) -> str:
    """Reasons for a tool result, bounded by construction: the first few, each clipped."""
    items = [str(item) for item in items]
    shown = [
        item if len(item) <= MAX_REASON_CHARS else item[: MAX_REASON_CHARS - 1] + "…"
        for item in items[:MAX_RESULT_REASONS]
    ]
    text = "; ".join(shown)
    if len(items) > MAX_RESULT_REASONS:
        text += f"; and {len(items) - MAX_RESULT_REASONS} more"
    return text


UPDATE_TRAINING_PLAN_DESCRIPTION = (
    "Create, update, or remove entries on the athlete's training calendar: workouts, races, rest "
    "days, travel. A day can hold several entries. In `set`, an item without `id` creates a new "
    "entry (`date` required; `kind` defaults to workout, which needs `workout_type`); an item "
    "with the `id` shown in the 'Upcoming Planned Workouts' table changes only the fields you "
    "send on that entry. `delete` takes entry ids. The result lists the id of every entry you "
    "create so you can edit it later. Always check the 'Upcoming Planned Workouts' and "
    "'Calendar Constraints' sections of this prompt first so you work around races, blocked-out "
    "days, and entries already scheduled — never schedule over them without the athlete's go-ahead "
    "(scheduling on a blocked-out day, or anything but a short easy shakeout on race day, is "
    "rejected). Also use the 'Training State' section: keep weekly ramp and the projected "
    "fatigue/fitness ratio inside its guardrails and add a down week after a few rising weeks. "
    "When the athlete says they can't complete a workout, or a conflict shows up on a date you'd "
    "otherwise use, delete or move that entry (send its `id` with a new `date`) rather than "
    "double-booking it. When regenerating a block, `delete` the ids that need to change and `set` "
    "their replacements in the same call. Only one scored workout per sport per day is allowed. "
    f"A call may change at most {MAX_PLAN_OPERATIONS} entries (`set` items plus `delete` ids); "
    "a larger call is rejected whole, so split a big block across several calls. "
    "Give `distance` and `elevation` in the athlete's units and say which with `distance_unit` / "
    "`elevation_unit`. " + INDOOR_RIDE_GUIDANCE
)

# Measurement fields of an update_training_plan workout entry, as JSON Schema (Claude, OpenAI and
# Ollama share this; Gemini mirrors it with its own Schema types). The model states its units
# instead of converting, and _workout_measurements() normalizes to the stored km / m.
DISTANCE_UNITS = {"km": UnitSystem.METRIC, "mi": UnitSystem.IMPERIAL}
ELEVATION_UNITS = {"m": UnitSystem.METRIC, "ft": UnitSystem.IMPERIAL}
WORKOUT_MEASUREMENT_PROPERTIES = {
    "distance": {"type": "number", "description": "Planned distance, in distance_unit"},
    "distance_unit": {"type": "string", "enum": list(DISTANCE_UNITS)},
    "elevation": {"type": "number", "description": "Planned elevation gain, in elevation_unit"},
    "elevation_unit": {"type": "string", "enum": list(ELEVATION_UNITS)},
    "structure": WORKOUT_STRUCTURE_SCHEMA,
}


PLAN_ENTRY_PROPERTIES = {
    "id": {
        "type": "integer",
        "description": "Entry id to change. Omit to create a new entry.",
    },
    "date": {"type": "string", "description": "ISO date, YYYY-MM-DD"},
    "kind": {"type": "string", "enum": list(KINDS), "description": "Defaults to workout."},
    "workout_type": {
        "type": "string",
        "description": "Workouts only: " + ", ".join(WORKOUT_TYPES),
    },
    "title": {"type": "string", "description": "Race name, or a label for travel/other."},
    "description": {
        "type": "string",
        "description": "A workout's objective, or notes for other kinds.",
    },
    **WORKOUT_MEASUREMENT_PROPERTIES,
    "duration_min": {"type": "integer"},
    "intensity": {"type": "string", "enum": ["easy", "moderate", "hard"]},
    "sport": {"type": "string", "enum": list(RACE_SPORTS), "description": "Races only."},
    "goal_time": {"type": "string", "description": "Races only: H:MM:SS or MM:SS."},
    "priority": {"type": "string", "enum": list(RACE_PRIORITIES), "description": "Races only."},
}

UPDATE_TRAINING_PLAN_PARAMETERS = {
    "type": "object",
    "properties": {
        "set": {
            "type": "array",
            "description": "Entries to create (no id) or update (with id).",
            "items": {"type": "object", "properties": PLAN_ENTRY_PROPERTIES},
        },
        "delete": {
            "type": "array",
            "description": "Ids of entries to remove from the calendar.",
            "items": {"type": "integer"},
        },
    },
}


def _workout_measurements(workout: dict) -> tuple[float | None, float | None]:
    """(distance_km, elevation_m) for a tool workout entry. Accepts the unit-tagged fields and
    falls back to the legacy distance_km / elevation_m keys."""
    distance_km = workout.get("distance_km")
    if workout.get("distance") is not None:
        system = DISTANCE_UNITS.get(workout.get("distance_unit") or "km", UnitSystem.METRIC)
        distance_km = round(to_si(float(workout["distance"]), Quantity.DISTANCE, system) / 1000, 2)
    elevation_m = workout.get("elevation_m")
    if workout.get("elevation") is not None:
        system = ELEVATION_UNITS.get(workout.get("elevation_unit") or "m", UnitSystem.METRIC)
        elevation_m = round(to_si(float(workout["elevation"]), Quantity.ELEVATION, system))
    return distance_km, elevation_m


_LEGACY_KINDS = {"Rest": ("rest", None)}


def _entry_kind(w: dict, existing: dict | None) -> tuple[str, str | None]:
    """(kind, race sport) for a tool item. Legacy workout_type strings ("Race", "Running Race",
    "Rest") still land on the right kind, so older prompts and habits keep working."""
    if existing:
        return existing["kind"], existing.get("sport")
    wtype = w.get("workout_type")
    if w.get("kind"):
        return w["kind"], w.get("sport")
    sport = race_sport_for_legacy_type(wtype)
    if sport:
        return "race", sport
    if wtype in _LEGACY_KINDS:
        return _LEGACY_KINDS[wtype][0], None
    return "workout", None


def _plan_ops(args: dict, plan_rows: list[dict]) -> tuple[list[dict], dict, list[str]]:
    """update_training_plan args -> (ops for the calendar, guardrail changes, errors).

    ``ops`` are the create / update / delete operations ``db.apply_calendar_changes`` takes; the
    guardrail changes describe the same operations for ``training_state.check_plan_changes``."""
    by_id = {p["id"]: p for p in plan_rows}
    ops: list[dict] = []
    creates, updates, deletes, errors = [], [], [], []
    for entry_id in args.get("delete", []) or []:
        try:
            entry_id = int(entry_id)
        except (TypeError, ValueError):
            errors.append(f"Not an entry id: {entry_id!r}")
            continue
        ops.append({"op": "delete", "id": entry_id})
        deletes.append(entry_id)
    for w in args.get("set", []) or []:
        entry_id = w.get("id")
        existing = by_id.get(entry_id) if entry_id is not None else None
        if entry_id is not None and existing is None:
            errors.append(f"No calendar entry with id {entry_id}")
            continue
        if entry_id is None and not w.get("date"):
            errors.append("A new entry needs a date")
            continue
        kind, sport = _entry_kind(w, existing)
        data: dict = {}
        for key in ("date", "title"):
            if key in w:
                data[key] = w[key]
        if "description" in w:
            data["objective" if kind == "workout" else "notes"] = w["description"]
            if kind == "race" and "title" not in w and entry_id is None:
                data["title"] = w["description"]
        if kind in ("workout", "race"):
            if "distance" in w or "distance_km" in w:
                data["distance_km"] = _workout_measurements(w)[0]
            if "elevation" in w or "elevation_m" in w:
                data["elevation_m"] = _workout_measurements(w)[1]
        if kind == "workout":
            for key in ("workout_type", "duration_min", "intensity", "structure"):
                if key in w:
                    data[key] = w[key]
            if entry_id is None:
                data.setdefault("workout_type", w.get("workout_type", "Workout"))
        elif kind == "race":
            if sport and entry_id is None:
                data["sport"] = sport
            elif "sport" in w:
                data["sport"] = w["sport"]
            if "goal_time" in w:
                seconds = parse_goal_time(w["goal_time"])
                data["goal_time_s"] = seconds
                data["goal_text"] = None if seconds is not None else w["goal_time"]
            if "priority" in w:
                data["priority"] = w["priority"]
            if entry_id is None and not data.get("title"):
                data["title"] = "Race"
        if entry_id is None:
            data["kind"] = kind
            ops.append({"op": "create", **data})
            creates.append(
                {
                    "date": data["date"],
                    "kind": kind,
                    "workout_type": display_type(kind, data.get("workout_type"), data.get("sport")),
                    "distance_km": data.get("distance_km"),
                    "duration_min": data.get("duration_min"),
                    "intensity": data.get("intensity"),
                }
            )
        else:
            ops.append({"op": "update", "id": entry_id, **data})
            updates.append(
                {
                    "id": entry_id,
                    **{
                        k: v
                        for k, v in data.items()
                        if k in ("date", "workout_type", "distance_km", "duration_min", "intensity")
                    },
                }
            )
    return ops, {"create": creates, "update": updates, "delete": deletes}, errors


def _check_proposed_changes(changes: dict, mode: str | None = None) -> list:
    """Guardrail violations for a proposed plan edit. Never raises: a failure here must not stop
    the coach from editing the calendar."""
    try:
        from datetime import date as date_cls

        from .. import training_state
        from ..modes import MODES

        # Same mode scoping as the coach prompt, Calendar and Analytics, so all agree on load.
        sport_types = MODES[mode].sport_types if mode in MODES else None
        rows = [
            a
            for a in db.get_all_activities()
            if sport_types is None or a.get("sport_type") in sport_types
        ]
        return training_state.check_plan_changes(
            rows,
            db.get_training_plan(),
            db.get_calendar_prefs(),
            mode,
            db.get_unit_system(),
            date_cls.today(),
            changes,
        )
    except Exception:
        return []


def _section_fact(
    keys: list, index: int, section: str, included: bool, bytes_per_token: float
) -> dict:
    """One context section in the per-turn record: sizes only, never the text."""
    return {
        "key": keys[index] if index < len(keys) else f"section_{index}",
        # 0 = sent in full; None = left out of this request.
        "level": 0 if included else None,
        "bytes": len(section.encode("utf-8")),
        "est": estimate(section, bytes_per_token),
    }


class BaseBackend(ABC):
    """
    A backend wraps one LLM provider and manages its own conversation history.

    Constructed per accepted chat turn with private bounded history from DB. Each call to stream_turn adds one user/assistant
    exchange and returns the text the model emitted plus any memories it saved.
    """

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if "stream_turn" in cls.__dict__:
            cls.stream_turn = bounded_turn(cls.stream_turn)

    @property
    def profile(self):
        """What is known of the model in use; backends override this with a lookup."""
        from .model_profile import ModelProfile

        return ModelProfile()

    def _bytes_per_token(self) -> float:
        try:
            ratio = self.profile.bytes_per_token
        except Exception:
            ratio = None
        return ratio if type(ratio) is float and ratio > 0 else DEFAULT_BYTES_PER_TOKEN

    @property
    def limits(self):
        from ..config import get_settings

        if hasattr(self, "_limits"):
            return self._limits
        overrides = get_settings().chat_limits
        provider = self.__class__.__name__.replace("Backend", "").lower()
        values: dict = {}
        for layer in (overrides.get("default"), overrides.get(provider), overrides.get(self.label)):
            values.update(normalize_limits(layer or {}))
        try:
            profile = self.profile
        except Exception:
            from .model_profile import ModelProfile

            profile = ModelProfile()
        self._limits = Limits.derive(profile, values, self.label)
        return self._limits

    def prepare_turn(self, system, message, attachments=None):
        """Select atomic context by priority; admission never changes the submission."""
        import time

        from ..budget import ContextPrompt

        admission_started = time.monotonic()
        # A turn starts clean: nothing from an earlier turn on this instance can be stored for it.
        self._admission = None
        self._budget = None
        self._count_spent = False
        self._admitted_input = None
        self._check_cancelled()
        if attachments and not self.supports_attachments:
            raise BudgetExceeded(
                "This provider does not support attachments. Choose Claude or paste text."
            )
        history = self._history
        groups = []

        def role(m):
            return m.get("role") if isinstance(m, dict) else m.role

        def plain(m):
            if isinstance(m, dict):
                return isinstance(m.get("content"), str) and not m.get("tool_calls")
            return all(getattr(p, "text", None) is not None for p in m.parts or [])

        i = 0
        while i + 1 < len(history):
            if (
                role(history[i]) == "user"
                and role(history[i + 1]) in ("assistant", "model")
                and plain(history[i])
                and plain(history[i + 1])
            ):
                groups.append(history[i : i + 2])
                i += 2
            else:
                i += 1
        self._history = []
        ratio = self._bytes_per_token()
        b = TurnBudget(self.limits, ratio)
        submission = self._submission_history(message, attachments)
        optional, activities, periods = [], [], []
        optional_keys, activity_keys = [], []
        if isinstance(system, ContextPrompt):
            optional, activities = system.priority, system.activities
            periods = system.activity_periods
            optional_keys = getattr(system, "priority_keys", [])
            activity_keys = getattr(system, "activity_keys", [])
            system = system.mandatory
        mandatory = system
        selected_optional, selected_activities = [], []
        # Leave room for an explicit omission notice with date coverage.
        reserve = 300 if activities else 0

        def fits(prompt, messages, margin=reserve):
            return (
                estimate([prompt, messages, self._tool_definitions()], ratio) + margin
                <= self.limits.input_ceiling
            )

        b.counter = self._count_once
        try:
            # The one place a measured count may reject a message on its own: the estimate says
            # the submission cannot fit, so confirm before refusing the athlete's message.
            b.check_request(system, submission, self._tool_definitions())
        except BudgetExceeded:
            # No optional context is left to remove.
            raise BudgetExceeded(
                "Your message and attachments exceed the input context limit. Shorten them or send smaller files."
            )
        # When the provider's own count admitted the bare request, that count stands even though
        # the estimate says otherwise; only optional context is dropped (the estimate decides it).
        bare_measured = b.count_kind == "measured"
        self._admitted_input = b.input_size if bare_measured else None
        for section in optional:
            candidate = system + "\n\n" + section
            if not fits(candidate, submission):
                break
            selected_optional.append(section)
            system = candidate
        for group in reversed(groups):
            candidate = group + self._history
            if len(candidate) > self.limits.history_messages or not fits(
                system, [*candidate, *submission]
            ):
                break
            self._history = candidate
        retained_activities = 0
        for index, section in enumerate(activities):
            count = section.count("\nACTIVITY ")
            if retained_activities + count > self.limits.recent_activities:
                continue
            candidate = system + "\n\n" + section
            if not fits(candidate, [*self._history, *submission]):
                continue
            selected_activities.append((index, section))
            retained_activities += count
            system = candidate
        while True:
            included = {index for index, _ in selected_activities}
            omitted = [periods[i] for i in range(len(periods)) if i not in included and periods[i]]
            notice = ""
            if omitted:
                dates = [day for period in omitted for day in period]
                notice = f"Context omitted: activity sections covering {min(dates)}..{max(dates)}. Individual details or aggregates for those omitted sections are unavailable."
            system = "\n\n".join(
                filter(
                    None,
                    [
                        mandatory,
                        *selected_optional,
                        *[section for _, section in selected_activities],
                        notice,
                    ],
                )
            )
            try:
                b.check_request(
                    system, self._submission_history(message, attachments), self._tool_definitions()
                )
                break
            except BudgetExceeded:
                if selected_activities:
                    selected_activities.pop()
                elif self._history:
                    self._history = self._history[2:]
                elif selected_optional:
                    selected_optional.pop()
                elif bare_measured:
                    break
                else:
                    raise
        self._retained_messages = len(self._history)
        self._retained_activities = sum(
            section.count("\nACTIVITY ") for _, section in selected_activities
        )
        included_activities = {index for index, _ in selected_activities}
        self._admission = {
            "admission_ms": int(round((time.monotonic() - admission_started) * 1000)),
            "fixed": {
                "mandatory": estimate(mandatory, ratio),
                "tools": estimate(self._tool_definitions(), ratio),
                "submission": estimate(submission, ratio),
            },
            "sections": [
                _section_fact(optional_keys, i, section, i < len(selected_optional), ratio)
                for i, section in enumerate(optional)
            ]
            + [
                _section_fact(activity_keys, i, section, i in included_activities, ratio)
                for i, section in enumerate(activities)
            ],
            "history": {
                "messages": len(self._history),
                "est": estimate(self._history, ratio) if self._history else 0,
                "dropped": len(history) - len(self._history),
            },
            "est_input": b.input_size,
            "count_kind": b.count_kind,
        }
        return system

    def _submission_history(self, message, attachments):
        return [
            *self._history,
            {"role": "user", "content": [*(attachments or []), {"type": "text", "text": message}]},
        ]

    def _count_request(self, system, history, tools):
        return None

    def _count_once(self, system, history, tools):
        """The provider's token counter, at most once per turn (a network round trip each)."""
        if getattr(self, "_count_spent", False):
            return None
        self._count_spent = True
        return self._count_request(system, history, tools)

    def _transport_call(self, call):
        """Retry transport setup only; tool execution is always outside this boundary."""
        import time

        for attempt in range(self.limits.retries + 1):
            self._tick()
            try:
                return call()
            except Exception as exc:
                status = getattr(exc, "status_code", getattr(exc, "code", None))
                if status is None:
                    status = getattr(getattr(exc, "response", None), "status_code", None)
                retryable = (
                    status in (429, 500, 502, 503, 504)
                    or isinstance(exc, (TimeoutError, ConnectionError))
                    or type(exc).__name__
                    in ("APIConnectionError", "APITimeoutError", "ConnectError", "ReadTimeout")
                )
                if not retryable:
                    raise
                if attempt == self.limits.retries:
                    raise TurnStop("retry_limit", "Transport retry limit reached.") from exc
                record = getattr(getattr(self, "_budget", None), "record", None)
                if record is not None:
                    record.retry(min(2**attempt, 4))
                event = getattr(self, "cancel_event", None)
                if event is not None:
                    event.wait(min(2**attempt, 4))
                else:
                    time.sleep(min(2**attempt, 4))

    def _transport_stream(self, call, validate=None):
        from contextlib import contextmanager

        @contextmanager
        def stream():
            manager = None

            def enter():
                nonlocal manager
                manager = call()
                value = manager.__enter__()
                if validate is not None:
                    try:
                        validate(value)
                    except BaseException:
                        import sys

                        manager.__exit__(*sys.exc_info())
                        raise
                return value

            value = self._transport_call(enter)
            try:
                yield value
            except BaseException:
                import sys

                if not manager.__exit__(*sys.exc_info()):
                    raise
            else:
                manager.__exit__(None, None, None)

        return stream()

    def _tool_definitions(self):
        import sys

        module = sys.modules[self.__class__.__module__]
        return [
            getattr(module, n)
            for n in ("SAVE_MEMORY_TOOL", "UPDATE_TRAINING_PLAN_TOOL", "UPDATE_PROFILE_TOOL")
            if hasattr(module, n)
        ]

    def _begin_round(self, system) -> RoundPlan:
        """Start the next provider request and say what it may do.

        A tool round offers tools; the reply round (``plan.kind == "reply"``) does not, carries
        the app's note after the tool results, and is the last. The caller builds its request
        from ``plan``: ``max_tokens``, and tools off for a reply. Raises TurnStop when even the
        reply cannot be sent.
        """
        self._tick()
        budget = self._budget
        tools = self._tool_definitions()
        plan = budget.plan_round(system, self._history, tools)
        if plan.kind == "reply" and budget.rounds:
            self._add_app_note(TOOL_BUDGET_NOTE)
        budget.request(system, self._history, tools, plan)
        self._reported_usage = None
        return plan

    def _add_app_note(self, note: str) -> None:
        """Put the app's note after the tool results in this provider's history format."""
        self._history.append({"role": "user", "content": note})

    def _tick(self):
        """Called on every provider event (and before each request): cancel and deadline checks."""
        self._check_cancelled()
        budget = getattr(self, "_budget", None)
        if budget is not None:
            budget.check_deadline()

    def _on_event(self):
        self._tick()
        self._budget.record.first_event()

    def _end_round(self, plan: RoundPlan, *, cut_off: bool, calls: int) -> bool:
        """The response is complete. True when its tool calls should run and the loop continue.

        A response cut off at its token limit never has its tool calls run (their arguments may be
        incomplete), and neither does a reply round's: tools were off.
        """
        budget = self._budget
        budget.end_round()
        record = budget.record
        if cut_off:
            record.round_stop("truncated")
            budget.stop("truncated")
            return False
        if not calls:
            record.round_stop("complete")
            return False
        if plan.kind == "reply":
            record.round_stop("calls_ignored")
            return False
        record.round_stop("tool_calls")
        return True

    @property
    @abstractmethod
    def label(self) -> str:
        """Human-readable identifier shown in the startup banner, e.g. 'claude-sonnet-4-6'."""

    @property
    @abstractmethod
    def supports_attachments(self) -> bool:
        """Whether this backend can accept file/image attachments."""

    @property
    def prefers_precomputed_brief(self) -> bool:
        """
        When True the deep-dive endpoint sends pre-computed metric summaries
        instead of a raw data table.  Override in backends whose models
        struggle to reason over tabular stream data (e.g. small local models).
        """
        return False

    @abstractmethod
    def stream_turn(
        self,
        system: str,
        user_input: str,
        on_token: Callable[[str], None],
        attachments: list[dict] | None = None,
    ) -> tuple[str, list[tuple[str, str]], list[dict]]:
        """
        Append user_input to history, call on_token(chunk) for each text token,
        handle any tool calls, and return:
          - full response text
          - list of (category, content) tuples for memories saved this turn
          - list of {"action": "set"|"delete", "date": ..., "workout_type"?: ...} dicts
            for training plan changes made this turn

        attachments: optional list of Anthropic-format content blocks (image or text)
          to prepend before the user's text in the message.
        """

    def _check_cancelled(self):
        event = getattr(self, "cancel_event", None)
        if event is not None and event.is_set():
            raise InterruptedError("client disconnected")

    def _run_tool(
        self,
        name: str,
        args: dict,
        memories_saved: list[tuple[str, str]],
        plan_changes: list[dict],
    ) -> str | None:
        """Run one model tool call and return its result text for the tool message.

        Memories and calendar changes made are appended to the caller's turn lists. An unknown
        tool returns None and the caller adds no result, as before.
        """
        if name == "save_memory":
            result, category, content = self._execute_save_memory(args)
            memories_saved.append((category, content))
            return result
        if name == "update_profile":
            return self._execute_update_profile(args)
        if name == "update_training_plan":
            result, changes = self._execute_update_training_plan(args)
            plan_changes.extend(changes)
            return result
        return None

    def _run_call(
        self,
        name: str,
        args: dict | None,
        memories_saved: list[tuple[str, str]],
        plan_changes: list[dict],
    ) -> str:
        """The tool result for one call; every call gets one so the history stays valid.

        ``args`` is None when the model's arguments could not be parsed: nothing is run.
        """
        if args is None:
            return (
                "Error: the arguments were not valid JSON, so nothing was run. Send the call again."
            )
        if self._budget.tools >= self.limits.tools:
            return "Not executed: tool limit reached"
        result = self._run_tool(name, args, memories_saved, plan_changes)
        return result if result is not None else f"Unknown tool: {name}"

    def _execute_save_memory(self, args: dict) -> tuple[str, str, str]:
        """
        Persist a save_memory tool call to the DB.

        Extracts category and content from the tool args dict, calls db.save_memory,
        and returns (db_result, category, content) so the caller can append to history
        and record the memory in the turn's memories_saved list.
        """
        self._check_cancelled()
        self._budget.tool(args)
        category = args.get("category", "other")
        content = args.get("content", "")
        metadata = {k: args[k] for k in SAVE_MEMORY_TIMING_PROPERTIES if k in args}
        turn_id = getattr(self, "turn_id", None)
        if turn_id is not None:
            metadata["turn_id"] = turn_id
        result = db.save_memory(category, content, **metadata)
        if not result.startswith("Error:"):
            self._budget.memories.append((category, content))
        return result, category, content

    def _execute_update_profile(self, args: dict) -> str:
        """
        Validate an update_profile tool call and record it as a pending proposal.

        Nothing is written: the proposal is surfaced to the athlete, whose acceptance applies it
        through the profile API. Returns the tool_result string for the model.
        """
        from ..profile import build_profile_proposal

        self._check_cancelled()
        self._budget.tool(args)
        try:
            proposal = build_profile_proposal(args, db.get_profile_fields(None))
        except ValueError as exc:
            return f"Rejected, nothing proposed. {exc}"
        self._budget.profile_proposals.append(proposal)
        db.log_mutation(
            getattr(self, "turn_id", None),
            "profile_proposal",
            "pending",
            {k: proposal[k] for k in ("label", "op", "proposed") if k in proposal},
        )
        return (
            f"Proposed {proposal['op']} for '{proposal['label']}': {proposal['proposed']}. "
            "Not saved yet; the athlete must accept it."
        )

    def take_profile_proposals(self) -> list[dict]:
        """Proposals recorded by the last turn (empty if none)."""
        return list(getattr(getattr(self, "_budget", None), "profile_proposals", []) or [])

    def _execute_update_training_plan(self, args: dict) -> tuple[str, list[dict]]:
        """
        Persist an update_training_plan tool call as one atomic change set.

        ``set`` items create (no id) or patch (id) entries, ``delete`` removes entry ids.
        Returns (summary, changes): the summary becomes the tool_result and names the id of every
        entry created, so the model can address it later.
        """
        self._check_cancelled()
        self._budget.tool(args)
        change_start = len(self._budget.changes)
        count = sum(
            len(args.get(key) or []) if isinstance(args.get(key), list) else 0
            for key in ("set", "delete")
        )
        if count > MAX_PLAN_OPERATIONS:
            return (
                f"Rejected, no changes made. This call has {count} operations; at most "
                f"{MAX_PLAN_OPERATIONS} are allowed per call. Send it again as several calls of "
                f"{MAX_PLAN_OPERATIONS} or fewer (for example one per two weeks).",
                [],
            )
        ops, proposed, errors = _plan_ops(args, db.get_training_plan())
        if errors:
            return "Rejected, no changes made. " + bounded_reasons(errors), []
        violations = _check_proposed_changes(proposed, getattr(self, "mode", None))
        hard = [v for v in violations if v.hard]
        if hard:
            # Nothing is saved: the model gets the reasons and can resubmit a corrected call.
            reasons = bounded_reasons(f"{v.date}: {v.detail}" for v in hard)
            return (
                f"Rejected, no changes made. {reasons} Choose other dates, or ask the athlete "
                "to unblock the day first.",
                [],
            )
        try:
            turn_id = getattr(self, "turn_id", None)
            result = (
                db.apply_calendar_changes(ops, turn_id=turn_id)
                if turn_id is not None
                else db.apply_calendar_changes(ops)
            )
        except EntryError as exc:
            return f"Rejected, no changes made. {exc}", []

        created_ids = iter(result["created"])
        created, updated, removed = [], [], []
        for op in ops:
            if op["op"] == "create":
                entry_id = next(created_ids)
                label = display_type(op["kind"], op.get("workout_type"), op.get("sport"))
                created.append(f"{op['date']} ({label}) [id {entry_id}]")
                self._budget.changes.append(
                    {"action": "set", "id": entry_id, "date": op["date"], "workout_type": label}
                )
            elif op["op"] == "update":
                updated.append(f"[id {op['id']}]")
                self._budget.changes.append({"action": "set", "id": op["id"]})
            else:
                removed.append(f"[id {op['id']}]")
                self._budget.changes.append({"action": "delete", "id": op["id"]})

        parts = []
        if created:
            parts.append(f"Created {len(created)} entr(ies): {', '.join(created)}")
        if updated:
            parts.append(f"Updated {len(updated)} entr(ies): {', '.join(updated)}")
        if removed:
            parts.append(f"Removed {len(removed)} entr(ies): {', '.join(removed)}")
        summary = ". ".join(parts) if parts else "No changes made."
        warnings = [v for v in violations if not v.hard]
        if warnings:
            summary += ". Warnings: " + bounded_reasons(v.detail for v in warnings)
            summary += " Consider revising the plan to stay within the Training State guardrails."
        return summary, self._budget.changes[change_start:]

    @abstractmethod
    def stateless_turn(
        self,
        system: str,
        user_input: str,
        on_token: Callable[[str], None],
    ) -> str:
        """
        Send a single [system + user] exchange to the LLM with no conversation
        history and no tool calls.  Does NOT modify self._history.

        Used for one-shot analysis tasks (e.g. deep-dive) where carrying the
        full chat history would overflow small-context local models and is
        irrelevant to the task at hand.

        Returns the full response text.
        """
