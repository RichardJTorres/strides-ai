"""Shared turn limits and token accounting.

Input is estimated from UTF-8 bytes at a static per-model ratio (``ModelProfile.bytes_per_token``)
plus framing overhead; an image block counts a flat ``IMAGE_TOKENS``. After round 1 the estimate
is built from what the provider reported for the previous round (``Usage``), so it does not drift.
The provider's token counter is a last resort, used at most once per turn and only when a request
would otherwise be rejected on the estimate. Streamed output is estimated at ~4 bytes per token
until the provider reports real usage, which replaces the estimate.
"""

import json
import logging
import math
from dataclasses import dataclass
from functools import wraps

from .turn_record import TurnRecord

log = logging.getLogger(__name__)


class BudgetExceeded(ValueError):
    pass


def serializable(value):
    from pydantic import BaseModel

    if isinstance(value, BaseModel):
        return value.model_dump(exclude_none=True)
    return str(value)


DEFAULT_BYTES_PER_TOKEN = 2.5
IMAGE_TOKENS = 5000
FRAMING_TOKENS = 64
# Measured input beyond the estimate by more than this share is worth a warning.
UNDERESTIMATE_WARN = 0.15


def _is_image(value) -> bool:
    return isinstance(value, dict) and value.get("type") in ("image", "image_url")


def _strip_images(value, found: list):
    """Copy of ``value`` with every image block replaced by a stub; each one is appended to found."""
    from pydantic import BaseModel

    if isinstance(value, BaseModel):
        value = value.model_dump(exclude_none=True)
    if _is_image(value):
        found.append(value)
        return {"type": value.get("type")}
    if isinstance(value, dict):
        return {k: _strip_images(v, found) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_strip_images(v, found) for v in value]
    return value


def estimate(value, bytes_per_token: float = DEFAULT_BYTES_PER_TOKEN):
    images: list = []
    raw = json.dumps(_strip_images(value, images), default=serializable, ensure_ascii=False)
    ratio = bytes_per_token if bytes_per_token and bytes_per_token > 0 else DEFAULT_BYTES_PER_TOKEN
    return math.ceil(len(raw.encode("utf-8")) / ratio) + FRAMING_TOKENS + IMAGE_TOKENS * len(images)


def _count(value) -> int | None:
    """A provider-reported token count, or None when it is missing or not a plain int."""
    return value if type(value) is int and value >= 0 else None


@dataclass(frozen=True)
class Usage:
    """One round's provider usage in a shape shared by every backend. None = not reported."""

    input_total: int | None = None  # everything sent, cached or not
    cache_read: int | None = None
    cache_write: int | None = None
    output_total: int | None = None  # everything generated, including reasoning
    reasoning: int | None = None

    @classmethod
    def of(cls, **fields) -> "Usage":
        return cls(**{k: _count(v) for k, v in fields.items()})


@dataclass(frozen=True)
class Limits:
    input_tokens: int = 24000
    output_tokens: int = 10000
    total_output_tokens: int = 24000
    context_window: int = 36000
    rounds: int = 6
    tools: int = 16
    retries: int = 2
    history_messages: int = 40
    recent_activities: int = 30

    def __post_init__(self):
        from dataclasses import fields

        zero_allowed = {"retries", "tools", "history_messages", "recent_activities"}
        for field in fields(self):
            value = getattr(self, field.name)
            if type(value) is not int or value < (0 if field.name in zero_allowed else 1):
                raise ValueError(f"{field.name} must be a valid nonnegative budget")
            if field.name != "context_window" and value > field.default:
                raise ValueError(f"{field.name} may only lower the default limit ({field.default})")
        if self.input_tokens + self.output_tokens > self.context_window:
            raise ValueError(
                "Input budget plus reserved output exceeds configured model context window"
            )


class TurnBudget:
    def __init__(self, limits, bytes_per_token: float = DEFAULT_BYTES_PER_TOKEN):
        self.limits = limits
        self.bytes_per_token = bytes_per_token
        self.admitted_input: int | None = None  # measured at admission; stands for round 1
        self._sent = 0  # history length at the last request
        self._prev_input: int | None = None  # last round's input: reported, else estimated
        self._prev_output: int | None = None
        self.rounds = self.tools = self.generated = self.input_size = 0
        self.memories = []
        self.changes = []
        self.profile_proposals = []
        self.text = []
        self.stop_reason = "complete"
        self.notice: str | None = None  # how the turn ended, if not normally (turn_notice.py)
        self.count_kind = "estimated"
        self.round_generated = 0
        self.counter = None
        self.record = TurnRecord(limits=limits)

    @property
    def output_remaining(self):
        return min(self.limits.output_tokens, self.limits.total_output_tokens - self.generated)

    def _estimate(self, value):
        return estimate(value, self.bytes_per_token)

    def _estimate_input(self, system, history, tools):
        if self._prev_input is None:
            return self._estimate([system, history, tools])
        # The previous assistant message is already in output_total, so only what followed it
        # (tool results, an app note) is new.
        fresh = list(history)[self._sent + 1 :]
        return self._prev_input + (self._prev_output or 0) + (self._estimate(fresh) if fresh else 0)

    def _admit(self, estimated, system, history, tools):
        self.input_size = estimated
        self.count_kind = "estimated"
        if estimated > self.limits.input_tokens and self.rounds == 0 and self.admitted_input:
            # Admission already measured this request (its one count); don't reject it again.
            self.input_size, self.count_kind = self.admitted_input, "measured"
        elif estimated > self.limits.input_tokens and self.counter:
            # Last resort, and the backend allows it once per turn.
            measured = self.counter(system, history, tools)
            if type(measured) is int and measured >= 0:
                self.input_size = measured
                self.count_kind = "measured"
        if self.input_size > self.limits.input_tokens:
            raise BudgetExceeded(
                "Input context limit reached. Shorten your message or attachments, or start a new exchange."
            )

    def check_request(self, system, history, tools):
        """Admission check for a first request (no rounds yet); changes no round state."""
        self._admit(self._estimate([system, history, tools]), system, history, tools)

    def request(self, system, history, tools):
        if self.rounds >= self.limits.rounds or self.output_remaining <= 0:
            raise BudgetExceeded("Generation limit reached.")
        self._admit(self._estimate_input(system, history, tools), system, history, tools)
        self._sent = len(history)
        self.rounds += 1
        self.round_generated = 0
        self._prev_input = self.input_size
        self._prev_output = None
        self.record.start_round(self.rounds, self.input_size, self.count_kind)

    def output(self, value):
        # Charge every emitted chunk, including tool arguments, conservatively.
        amount = max(1, (len(str(value).encode("utf-8")) + 3) // 4)
        self.generated += amount
        self.round_generated += amount
        if self.round_generated > self.limits.output_tokens:
            raise BudgetExceeded("Per-call generated output limit reached.")
        if self.generated > self.limits.total_output_tokens:
            raise BudgetExceeded("Total generated output limit reached.")

    def usage(self, measured):
        """Replace the streamed estimate with provider-reported usage (incl. reasoning).

        ``measured`` is a ``Usage``, or just the output token count (an int or None).
        """
        if not isinstance(measured, Usage):
            measured = Usage.of(output_total=measured)
        output = measured.output_total
        if output is not None:
            self.generated += output - self.round_generated
            self.round_generated = output
        self.record.end_round(
            output,
            self.round_generated,
            input_total=measured.input_total,
            cache_read=measured.cache_read,
            cache_write=measured.cache_write,
            reasoning=measured.reasoning,
        )
        # What the next round's estimate builds on: this round's input and everything it generated.
        if measured.input_total is not None:
            estimated = self._prev_input
            self._prev_input = measured.input_total
            if estimated and measured.input_total > estimated * (1 + UNDERESTIMATE_WARN):
                log.warning(
                    "input estimate low: estimated=%s measured=%s bytes_per_token=%s",
                    estimated,
                    measured.input_total,
                    self.bytes_per_token,
                )
        self._prev_output = self.round_generated
        if self.round_generated > self.limits.output_tokens:
            raise BudgetExceeded("Per-call generated output limit reached.")
        if self.generated > self.limits.total_output_tokens:
            raise BudgetExceeded("Total generated output limit reached.")

    def tool(self, args):
        if self.tools >= self.limits.tools:
            raise BudgetExceeded("Tool execution limit reached.")
        self.tools += 1
        self.record.tool()


def bounded_turn(method):
    @wraps(method)
    def run(self, system, user_input, on_token, attachments=None):
        if not hasattr(self, "_retained_messages"):
            system = self.prepare_turn(system, user_input, attachments)
        self._budget = TurnBudget(self.limits, self._bytes_per_token())
        self._budget.counter = self._count_once
        record = self._budget.record
        record.model = self.label
        record.ratio = self._budget.bytes_per_token
        self._budget.admitted_input = getattr(self, "_admitted_input", None)
        record.set_admission(getattr(self, "_admission", None))

        def emit(chunk):
            self._check_cancelled()
            self._budget.output(chunk)
            self._budget.text.append(chunk)
            record.first_text()
            on_token(chunk)

        try:
            method(self, system, user_input, emit, attachments)
            return "".join(self._budget.text), self._budget.memories, self._budget.changes
        except BudgetExceeded as exc:
            self._budget.stop_reason = str(exc)
            record.set_stop("stopped", str(exc))
            # The app's note about the stop is stored beside the reply (turn_notice.py), not in it.
            self._budget.notice = "limit"
            return "".join(self._budget.text), self._budget.memories, self._budget.changes
        except BaseException as exc:
            self._budget.stop_reason = (
                "cancelled" if isinstance(exc, InterruptedError) else "provider_error"
            )
            status = getattr(exc, "status_code", getattr(exc, "code", None))
            record.set_stop(
                self._budget.stop_reason,
                type(exc).__name__ + (f" status={status}" if type(status) is int else ""),
            )
            if self._budget.stop_reason == "provider_error":
                log.warning("chat turn failed: %s: %s", type(exc).__name__, exc)
            raise
        finally:
            b = self._budget
            log.info(
                "chat_budget provider_model=%s input_tokens=%s count_kind=%s retained_messages=%s retained_activities=%s rounds=%s tools=%s generated_estimate=%s stop_reason=%s",
                self.label,
                b.input_size,
                b.count_kind,
                self._retained_messages,
                self._retained_activities,
                b.rounds,
                b.tools,
                b.generated,
                b.stop_reason,
            )

    return run


class ContextPrompt(str):
    """Keeps optional sections atomic so reductions never split instructions."""

    def __new__(
        cls,
        mandatory,
        priority,
        activities,
        activity_periods=None,
        priority_keys=None,
        activity_keys=None,
    ):
        obj = super().__new__(cls, "\n\n".join(filter(None, [mandatory, *priority, *activities])))
        obj.mandatory = mandatory
        obj.priority = list(filter(None, priority))
        obj.activities = list(filter(None, activities))
        obj.activity_periods = activity_periods or []
        # Names for the per-turn record, aligned with the filtered lists above.
        obj.priority_keys = _keys(priority, priority_keys, "priority")
        obj.activity_keys = _keys(activities, activity_keys, "activity")
        return obj


def _keys(sections, keys, prefix):
    keys = list(keys) if keys is not None and len(keys) == len(sections) else None
    return [keys[i] if keys else f"{prefix}_{i}" for i, section in enumerate(sections) if section]
