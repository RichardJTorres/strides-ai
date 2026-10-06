"""Abstract base class for LLM backends."""

from abc import ABC, abstractmethod
from typing import Callable

from .. import db

SAVE_MEMORY_DESCRIPTION = (
    "Save an important fact about the athlete to persistent memory. "
    "Call this whenever the athlete mentions: goals, target races or times, "
    "injuries or niggles, training preferences, weekly mileage targets, "
    "or any coaching context that should be remembered in future sessions."
)

SAVE_MEMORY_CATEGORIES: list[str] = ["goal", "race", "injury", "preference", "training", "other"]

UPDATE_TRAINING_PLAN_DESCRIPTION = (
    "Create, update, or remove planned workouts on the athlete's training calendar. "
    "Use `set` to schedule or overwrite workouts (one entry per date, `date` and `workout_type` "
    "required) and `delete` to clear a date back to a rest day. Always check the "
    "'Upcoming Planned Workouts' and 'Calendar Constraints' sections of this prompt first so you "
    "work around races, blocked-out days, and workouts already scheduled — never schedule over "
    "them without the athlete's go-ahead. When the athlete says they can't complete a workout, or "
    "a conflict shows up on a date you'd otherwise use, delete or move that day rather than "
    "double-booking it. When regenerating a whole block, combine `delete` for the days that need "
    "to change with `set` for their replacements in the same call."
)


class BaseBackend(ABC):
    """
    A backend wraps one LLM provider and manages its own conversation history.

    Constructed once per session with the initial history (training-log seed +
    prior messages from DB).  Each call to stream_turn adds one user/assistant
    exchange and returns the text the model emitted plus any memories it saved.
    """

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

    def _execute_save_memory(self, args: dict) -> tuple[str, str, str]:
        """
        Persist a save_memory tool call to the DB.

        Extracts category and content from the tool args dict, calls db.save_memory,
        and returns (db_result, category, content) so the caller can append to history
        and record the memory in the turn's memories_saved list.
        """
        category = args.get("category", "other")
        content = args.get("content", "")
        result = db.save_memory(category, content)
        return result, category, content

    def _execute_update_training_plan(self, args: dict) -> tuple[str, list[dict]]:
        """
        Persist an update_training_plan tool call to the DB.

        Applies each `set` entry (upsert) and each `delete` date (removal) from the
        tool args, and returns (summary_string, changes) so the caller can append
        summary_string as the tool_result and record changes in plan_changes.
        """
        changes: list[dict] = []
        set_summaries: list[str] = []
        for workout in args.get("set", []) or []:
            date = workout.get("date")
            if not date:
                continue
            workout_type = workout.get("workout_type", "Workout")
            db.save_planned_workout(
                date,
                workout_type,
                workout.get("description"),
                workout.get("distance_km"),
                workout.get("elevation_m"),
                workout.get("duration_min"),
                workout.get("intensity"),
            )
            changes.append({"action": "set", "date": date, "workout_type": workout_type})
            set_summaries.append(f"{date} ({workout_type})")

        delete_summaries: list[str] = []
        for date in args.get("delete", []) or []:
            db.delete_planned_workout(date)
            changes.append({"action": "delete", "date": date})
            delete_summaries.append(date)

        parts = []
        if set_summaries:
            parts.append(f"Scheduled {len(set_summaries)} workout(s): {', '.join(set_summaries)}")
        if delete_summaries:
            parts.append(
                f"Removed {len(delete_summaries)} workout(s): {', '.join(delete_summaries)}"
            )
        summary = ". ".join(parts) if parts else "No changes made."
        return summary, changes

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
