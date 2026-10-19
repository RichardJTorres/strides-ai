"""Abstract base class for LLM backends."""

from abc import ABC, abstractmethod
from typing import Callable

from .. import db
from ..budget import Limits, TurnBudget, bounded_turn, BudgetExceeded, estimate
from ..units import Quantity, UnitSystem, to_si

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

UPDATE_TRAINING_PLAN_DESCRIPTION = (
    "Create, update, or remove planned workouts on the athlete's training calendar. "
    "Use `set` to schedule or overwrite workouts (one entry per date, `date` and `workout_type` "
    "required) and `delete` to clear a date back to a rest day. Always check the "
    "'Upcoming Planned Workouts' and 'Calendar Constraints' sections of this prompt first so you "
    "work around races, blocked-out days, and workouts already scheduled — never schedule over "
    "them without the athlete's go-ahead (scheduling on a blocked-out day or race day is rejected). "
    "Also use the 'Training State' section: keep weekly ramp and the projected fatigue/fitness "
    "ratio inside its guardrails and add a down week after a few rising weeks. When the athlete says they can't complete a workout, or "
    "a conflict shows up on a date you'd otherwise use, delete or move that day rather than "
    "double-booking it. When regenerating a whole block, combine `delete` for the days that need "
    "to change with `set` for their replacements in the same call. Give `distance` and "
    "`elevation` in the athlete's units and say which with `distance_unit` / `elevation_unit`."
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


def _normalized_plan_changes(args: dict) -> dict:
    """update_training_plan args -> {"set": [...distance_km...], "delete": [...]} in stored units."""
    sets = []
    for w in args.get("set", []) or []:
        if not w.get("date"):
            continue
        distance_km, _ = _workout_measurements(w)
        sets.append(
            {
                "date": w["date"],
                "workout_type": w.get("workout_type", "Workout"),
                "distance_km": distance_km,
                "intensity": w.get("intensity"),
            }
        )
    return {"set": sets, "delete": list(args.get("delete", []) or [])}


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
    def limits(self):
        from ..config import get_settings

        if hasattr(self, "_limits"):
            return self._limits
        overrides = get_settings().chat_limits
        provider = self.__class__.__name__.replace("Backend", "").lower()
        values = {
            **overrides.get("default", {}),
            **overrides.get(provider, {}),
            **overrides.get(self.label, {}),
        }
        self._limits = Limits(**values)
        return self._limits

    def prepare_turn(self, system, message, attachments=None):
        """Select atomic context by priority; admission never changes the submission."""
        from ..budget import ContextPrompt

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
        b = TurnBudget(self.limits)
        submission = self._submission_history(message, attachments)
        optional, activities, periods = [], [], []
        if isinstance(system, ContextPrompt):
            optional, activities = system.priority, system.activities
            periods = system.activity_periods
            system = system.mandatory
        mandatory = system
        selected_optional, selected_activities = [], []
        # Leave room for an explicit omission notice with date coverage.
        reserve = 300 if activities else 0

        def fits(prompt, messages, margin=reserve):
            if (
                estimate([prompt, messages, self._tool_definitions()]) + margin
                <= self.limits.input_tokens
            ):
                return True
            # Prefer measured counts when a conservative estimate would reject context.
            measured = self._count_request(prompt, messages, self._tool_definitions())
            return type(measured) is int and measured + margin <= self.limits.input_tokens

        if not fits(system, submission, margin=0):
            # No optional context is left to remove.
            raise BudgetExceeded(
                "Your message and attachments exceed the input context limit. Shorten them or send smaller files."
            )
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
        b.counter = self._count_request
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
                else:
                    raise
        self._retained_messages = len(self._history)
        self._retained_activities = sum(
            section.count("\nACTIVITY ") for _, section in selected_activities
        )
        return system

    def _submission_history(self, message, attachments):
        return [
            *self._history,
            {"role": "user", "content": [*(attachments or []), {"type": "text", "text": message}]},
        ]

    def _count_request(self, system, history, tools):
        return None

    def _transport_call(self, call):
        """Retry transport setup only; tool execution is always outside this boundary."""
        import time

        for attempt in range(self.limits.retries + 1):
            self._check_cancelled()
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
                    raise BudgetExceeded("Transport retry limit reached.") from exc
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

    def _before_request(self, system):
        self._check_cancelled()
        self._budget.request(system, self._history, self._tool_definitions())
        self._reported_output = None

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
        return (
            f"Proposed {proposal['op']} for '{proposal['label']}': {proposal['proposed']}. "
            "Not saved yet; the athlete must accept it."
        )

    def take_profile_proposals(self) -> list[dict]:
        """Proposals recorded by the last turn (empty if none)."""
        return list(getattr(getattr(self, "_budget", None), "profile_proposals", []) or [])

    def _execute_update_training_plan(self, args: dict) -> tuple[str, list[dict]]:
        """
        Persist an update_training_plan tool call to the DB.

        Applies each `set` entry (upsert) and each `delete` date (removal) from the
        tool args, and returns (summary_string, changes) so the caller can append
        summary_string as the tool_result and record changes in plan_changes.
        """
        self._check_cancelled()
        self._budget.tool(args)
        change_start = len(self._budget.changes)
        set_summaries: list[str] = []
        proposed = _normalized_plan_changes(args)
        violations = _check_proposed_changes(proposed, getattr(self, "mode", None))
        hard = [v for v in violations if v.hard]
        if hard:
            # Nothing is saved: the model gets the reasons and can resubmit a corrected call.
            reasons = "; ".join(f"{v.date}: {v.detail}" for v in hard)
            return (
                f"Rejected, no changes made. {reasons} Choose other dates, or ask the athlete "
                "to unblock the day first.",
                [],
            )
        for workout in args.get("set", []) or []:
            date = workout.get("date")
            if not date:
                continue
            workout_type = workout.get("workout_type", "Workout")
            distance_km, elevation_m = _workout_measurements(workout)
            db.save_planned_workout(
                date,
                workout_type,
                workout.get("description"),
                distance_km,
                elevation_m,
                workout.get("duration_min"),
                workout.get("intensity"),
            )
            self._budget.changes.append(
                {"action": "set", "date": date, "workout_type": workout_type}
            )
            set_summaries.append(f"{date} ({workout_type})")

        delete_summaries: list[str] = []
        for date in args.get("delete", []) or []:
            db.delete_planned_workout(date)
            self._budget.changes.append({"action": "delete", "date": date})
            delete_summaries.append(date)

        parts = []
        if set_summaries:
            parts.append(f"Scheduled {len(set_summaries)} workout(s): {', '.join(set_summaries)}")
        if delete_summaries:
            parts.append(
                f"Removed {len(delete_summaries)} workout(s): {', '.join(delete_summaries)}"
            )
        summary = ". ".join(parts) if parts else "No changes made."
        warnings = [v for v in violations if not v.hard]
        if warnings:
            summary += ". Warnings: " + "; ".join(v.detail for v in warnings)
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
