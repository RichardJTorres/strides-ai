"""Abstract base class for LLM backends."""

from abc import ABC, abstractmethod
from typing import Callable


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
    ) -> tuple[str, list[tuple[str, str]]]:
        """
        Append user_input to history, call on_token(chunk) for each text token,
        handle any tool calls, and return:
          - full response text
          - list of (category, content) tuples for memories saved this turn

        attachments: optional list of Anthropic-format content blocks (image or text)
          to prepend before the user's text in the message.
        """

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
