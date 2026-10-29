"""Shared turn limits. Input fallback counts use UTF-8 bytes + 10% and framing overhead.

One byte per token deliberately overestimates input, including non-ASCII. Streamed output
is estimated at ~4 bytes per token until the provider reports real usage, which replaces
the estimate. Binary image payloads are charged at their encoded size rather than silently omitted.
"""

import json
import logging
from dataclasses import dataclass
from functools import wraps

log = logging.getLogger(__name__)


class BudgetExceeded(ValueError):
    pass


def serializable(value):
    from pydantic import BaseModel

    if isinstance(value, BaseModel):
        return value.model_dump(exclude_none=True)
    return str(value)


def estimate(value):
    raw = json.dumps(value, default=serializable, ensure_ascii=False)
    return (len(raw.encode("utf-8")) * 11 + 9) // 10 + 64


@dataclass(frozen=True)
class Limits:
    input_tokens: int = 24000
    output_tokens: int = 4000
    total_output_tokens: int = 12000
    context_window: int = 28000
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
    def __init__(self, limits):
        self.limits = limits
        self.rounds = self.tools = self.generated = self.input_size = 0
        self.memories = []
        self.changes = []
        self.profile_proposals = []
        self.text = []
        self.stop_reason = "complete"
        self.count_kind = "estimated"
        self.round_generated = 0
        self.counter = None

    @property
    def output_remaining(self):
        return min(self.limits.output_tokens, self.limits.total_output_tokens - self.generated)

    def check_request(self, system, history, tools):
        self.input_size = estimate([system, history, tools])
        self.count_kind = "estimated"
        if self.counter:
            measured = self.counter(system, history, tools)
            if type(measured) is int and measured >= 0:
                self.input_size = measured
                self.count_kind = "measured"
        if self.input_size > self.limits.input_tokens:
            raise BudgetExceeded(
                "Input context limit reached. Shorten your message or attachments, or start a new exchange."
            )

    def request(self, system, history, tools):
        if self.rounds >= self.limits.rounds or self.output_remaining <= 0:
            raise BudgetExceeded("Generation limit reached.")
        self.check_request(system, history, tools)
        self.rounds += 1
        self.round_generated = 0

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
        """Replace the streamed estimate with provider-reported generation (incl. reasoning)."""
        if type(measured) is int and measured >= 0:
            self.generated += measured - self.round_generated
            self.round_generated = measured
        if self.round_generated > self.limits.output_tokens:
            raise BudgetExceeded("Per-call generated output limit reached.")
        if self.generated > self.limits.total_output_tokens:
            raise BudgetExceeded("Total generated output limit reached.")

    def tool(self, args):
        if self.tools >= self.limits.tools:
            raise BudgetExceeded("Tool execution limit reached.")
        self.tools += 1


def bounded_turn(method):
    @wraps(method)
    def run(self, system, user_input, on_token, attachments=None):
        if not hasattr(self, "_retained_messages"):
            system = self.prepare_turn(system, user_input, attachments)
        self._budget = TurnBudget(self.limits)
        self._budget.counter = self._count_request

        def emit(chunk):
            self._check_cancelled()
            self._budget.output(chunk)
            self._budget.text.append(chunk)
            on_token(chunk)

        try:
            method(self, system, user_input, emit, attachments)
            return "".join(self._budget.text), self._budget.memories, self._budget.changes
        except BudgetExceeded as exc:
            self._budget.stop_reason = str(exc)
            notice = f"\n\n_Turn stopped: {exc} Earlier memory or calendar changes may already have completed._"
            on_token(notice)
            return "".join(self._budget.text) + notice, self._budget.memories, self._budget.changes
        except BaseException as exc:
            self._budget.stop_reason = (
                "cancelled" if isinstance(exc, InterruptedError) else "provider_error"
            )
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

    def __new__(cls, mandatory, priority, activities, activity_periods=None):
        obj = super().__new__(cls, "\n\n".join(filter(None, [mandatory, *priority, *activities])))
        obj.mandatory = mandatory
        obj.priority = list(filter(None, priority))
        obj.activities = list(filter(None, activities))
        obj.activity_periods = activity_periods or []
        return obj
