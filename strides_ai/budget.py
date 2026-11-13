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
import time
from dataclasses import dataclass, fields
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


# Old CHAT_LIMITS keys, still accepted.
LIMIT_ALIASES = {
    "output_tokens": "round_max_tokens",
    "total_output_tokens": "turn_output_ceiling",
    "input_tokens": "input_ceiling",
    "rounds": "tool_rounds",
}
# These may be 0; everything else must be at least 1.
ZERO_ALLOWED = frozenset({"retries", "tools", "history_messages", "recent_activities"})
SECONDS_FIELDS = frozenset(
    {"first_event_s", "stream_idle_s", "round_deadline_s", "reply_deadline_s", "turn_deadline_s"}
)
# Context the tool definitions are expected to cost per allowed tool call, for input_ceiling.
TOOL_ALLOWANCE = 1500


@dataclass(frozen=True)
class Limits:
    """One turn's limits. Build them from a model with ``Limits.derive``; the defaults here are
    what that gives for a 200k-window, 64k-output model.
    """

    round_max_tokens: int = 16000  # max_tokens of a tool round
    reply_reserve: int = 4000  # output kept back so the closing reply always has room
    turn_output_ceiling: int = 52000  # all output of a turn, thinking included
    context_target: int = 60000  # what prompt selection aims for (context builder)
    input_ceiling: int = 136000  # a tool round is not offered above this estimated input
    context_window: int = 200000
    tool_rounds: int = 5  # tool rounds; one tool-less reply round follows
    tools: int = 16  # tool calls per turn
    retries: int = 2
    history_messages: int = 40
    recent_activities: int = 30
    first_event_s: float = 60
    stream_idle_s: float = 120
    round_deadline_s: float = 240
    reply_deadline_s: float = 120
    turn_deadline_s: float = 600

    def __post_init__(self):
        for field in fields(self):
            _check_limit(field.name, getattr(self, field.name))

    @classmethod
    def derive(cls, profile, overrides: dict | None = None, label: str = "model") -> "Limits":
        """Limits for ``profile`` (window W, max output M), then ``overrides`` (up or down),
        then clamped to what the model can do, with a warning for each clamp."""
        ov = normalize_limits(overrides or {})
        window = ov.get("context_window", profile.context_window)
        top = profile.max_output

        def clamp(name, value, high=None, low=1):
            if high is not None and value > high:
                log.warning(
                    "chat limit %s=%s exceeds %s for %s; using %s", name, value, high, label, high
                )
                value = high
            if value < low:
                log.warning(
                    "chat limit %s=%s below %s for %s; using %s", name, value, low, label, low
                )
                value = low
            return value

        round_max = clamp(
            "round_max_tokens",
            ov.get("round_max_tokens", min(16000, top, window // 4)),
            min(top, max(1, window // 2)),
        )
        reserve = clamp(
            "reply_reserve", ov.get("reply_reserve", min(4000, round_max // 2)), round_max
        )
        ceiling = clamp(
            "turn_output_ceiling",
            ov.get("turn_output_ceiling", 3 * round_max + reserve),
            low=reserve,
        )
        tools = ov.get("tools", cls.tools)
        target = ov.get("context_target", min(60000, (window - round_max) * 3 // 4))
        room = max(1, window - round_max)
        input_ceiling = clamp(
            "input_ceiling",
            ov.get("input_ceiling", min(room, target + ceiling + tools * TOOL_ALLOWANCE)),
            room,
        )
        target = clamp("context_target", target, input_ceiling)
        derived = {
            "round_max_tokens",
            "reply_reserve",
            "turn_output_ceiling",
            "context_target",
            "input_ceiling",
            "context_window",
        }
        return cls(
            round_max_tokens=round_max,
            reply_reserve=reserve,
            turn_output_ceiling=ceiling,
            context_target=target,
            input_ceiling=input_ceiling,
            context_window=window,
            **{k: v for k, v in ov.items() if k not in derived},
        )


def _check_limit(name: str, value) -> None:
    ok = type(value) is int or (name in SECONDS_FIELDS and type(value) is float)
    if not ok or value < (0 if name in ZERO_ALLOWED else 1):
        kind = "nonnegative" if name in ZERO_ALLOWED else "positive"
        raise ValueError(f"{name} must be a {kind} number")


def normalize_limits(values: dict) -> dict:
    """A CHAT_LIMITS layer with old keys renamed and every key and value checked."""
    known = {f.name for f in fields(Limits)}
    out: dict = {}
    for key, value in (values or {}).items():
        name = LIMIT_ALIASES.get(key, key)
        if name not in known:
            raise ValueError(f"unknown chat limit {key!r}")
        _check_limit(name, value)
        out[name] = value
    return out


class TurnStop(BudgetExceeded):
    """The turn ends here, normally: ``code`` is the stop code stored as the turn's notice."""

    def __init__(self, code: str, message: str | None = None):
        super().__init__(message or code)
        self.code = code


_STALL_NAMES = frozenset(
    {"APITimeoutError", "ReadTimeout", "ConnectTimeout", "WriteTimeout", "PoolTimeout"}
)


def is_stall(exc: BaseException) -> bool:
    """A provider that stopped sending: a read/connect timeout from any SDK's HTTP client."""
    if isinstance(exc, TimeoutError):
        return True
    return any(cls.__name__ in _STALL_NAMES for cls in type(exc).__mro__)


@dataclass(frozen=True)
class RoundPlan:
    kind: str  # "tool": tools offered | "reply": tools off, the closing reply
    max_tokens: int
    reason: str | None = None  # why this is a reply round (a stop code)


def _now() -> float:
    return time.monotonic()


# Appended after the tool results when tools are switched off for the closing reply.
TOOL_BUDGET_NOTE = "[App note: Tool budget used; summarise what was done and what remains.]"


class TurnBudget:
    def __init__(self, limits, bytes_per_token: float = DEFAULT_BYTES_PER_TOKEN):
        self.limits = limits
        self.bytes_per_token = bytes_per_token
        self.admitted_input: int | None = None  # measured at admission; stands for round 1
        self._sent = 0  # history length at the last request
        self._prev_input: int | None = None  # last round's input: reported, else estimated
        self._prev_output: int | None = None
        self.rounds = self.tools = self.generated = self.input_size = 0
        self.tool_rounds = 0  # rounds that offered tools
        self.memories = []
        self.changes = []
        self.profile_proposals = []
        self.text = []
        self.stop_reason = "complete"
        self.notice: str | None = None  # how the turn ended, if not normally (turn_notice.py)
        self.count_kind = "estimated"
        self.round_generated = 0
        self.counter = None
        self.started = _now()
        self.round_started: float | None = None
        self.round_kind: str | None = None
        self.record = TurnRecord(limits=limits)

    def elapsed(self) -> float:
        return _now() - self.started

    @property
    def output_remaining(self):
        """Output the turn may still generate before its ceiling."""
        return self.limits.turn_output_ceiling - self.generated

    def stop(self, code: str, detail: str | None = None) -> None:
        """End the turn with ``code``. A cut-off never replaces a more specific stop."""
        if code == "truncated" and self.notice:
            return
        self.stop_reason = code
        self.notice = code
        self.record.set_stop(code, detail)

    def check_deadline(self) -> None:
        """Raise TurnStop("deadline") once the turn, or the round in flight, has run too long."""
        limits = self.limits
        if self.elapsed() > limits.turn_deadline_s:
            raise TurnStop("deadline", "Turn time limit reached.")
        if self.round_started is not None:
            allowed = (
                limits.reply_deadline_s if self.round_kind == "reply" else limits.round_deadline_s
            )
            if _now() - self.round_started > allowed:
                raise TurnStop("deadline", "Round time limit reached.")

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
        """Admission of a first request: the one place a measured count may stand in."""
        ceiling = self.limits.input_ceiling
        self.input_size = estimated
        self.count_kind = "estimated"
        if estimated > ceiling and self.rounds == 0 and self.admitted_input:
            # Admission already measured this request (its one count); don't reject it again.
            self.input_size, self.count_kind = self.admitted_input, "measured"
        elif estimated > ceiling and self.counter:
            # Last resort, and the backend allows it once per turn.
            measured = self.counter(system, history, tools)
            if type(measured) is int and measured >= 0:
                self.input_size = measured
                self.count_kind = "measured"
        if self.input_size > ceiling:
            raise BudgetExceeded(
                "Input context limit reached. Shorten your message or attachments, or start a new exchange."
            )

    def check_request(self, system, history, tools):
        """Admission check for a first request (no rounds yet); changes no round state."""
        self._admit(self._estimate([system, history, tools]), system, history, tools)

    def plan_round(self, system, history, tools) -> RoundPlan:
        """Decide whether the next request offers tools or is the tool-less closing reply.

        A tool round needs: tool rounds left, tool calls left, room for ``round_max_tokens``
        plus ``reply_reserve`` under the output ceiling, input at most ``input_ceiling``, and time
        for a round and a reply. Otherwise the reply round runs, unless it cannot fit the model's
        window, which ends the turn (TurnStop) with the receipt alone.
        """
        limits = self.limits
        estimated = self._estimate_input(system, history, tools)
        measured = bool(
            self.rounds == 0 and estimated > limits.input_ceiling and self.admitted_input
        )
        size = self.admitted_input if measured else estimated
        remaining = self.output_remaining
        if self.tool_rounds >= limits.tool_rounds:
            reason = "round_limit"
        elif self.tools >= limits.tools:
            reason = "tool_limit"
        elif remaining < limits.round_max_tokens + limits.reply_reserve:
            reason = "output_ceiling"
        elif size > limits.input_ceiling:
            reason = "input_ceiling"
        elif (
            limits.turn_deadline_s - self.elapsed()
            < limits.round_deadline_s + limits.reply_deadline_s
        ):
            reason = "deadline"
        else:
            reason = None
        count_kind = "measured" if measured else "estimated"
        if reason is None:
            self.input_size, self.count_kind = size, count_kind
            return RoundPlan("tool", limits.round_max_tokens)
        # The note rides on the request after round 1 only.
        size += self._estimate(TOOL_BUDGET_NOTE) if self.rounds else 0
        max_tokens = min(limits.round_max_tokens, max(remaining, limits.reply_reserve))
        if size + max_tokens > limits.context_window:
            raise TurnStop(reason, "The closing reply would not fit the model's context window.")
        self.input_size, self.count_kind = size, count_kind
        return RoundPlan("reply", max_tokens, reason)

    def request(self, system, history, tools, plan: RoundPlan | None = None):
        plan = plan or self.plan_round(system, history, tools)
        if plan.kind == "reply" and plan.reason and not self.notice:
            self.stop(plan.reason, "Tool budget used; the closing reply was requested.")
        self._sent = len(history)
        self.rounds += 1
        self.tool_rounds += plan.kind == "tool"
        self.round_generated = 0
        self.round_kind = plan.kind
        self.round_started = _now()
        self._prev_input = self.input_size
        self._prev_output = None
        self.record.start_round(
            self.rounds, self.input_size, self.count_kind, plan.kind, plan.max_tokens
        )

    def end_round(self) -> None:
        """The response is complete; the round's clock stops (tools run outside it)."""
        self.round_started = None

    def output(self, value):
        # Estimate every emitted chunk, including tool arguments; usage() replaces the estimate
        # with the provider's own count. Nothing is enforced here: max_tokens bounds the output.
        amount = max(1, (len(str(value).encode("utf-8")) + 3) // 4)
        self.generated += amount
        self.round_generated += amount

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
        over = self.generated - self.limits.turn_output_ceiling
        if over > 0:
            # Only a provider that ignored max_tokens, or a closing reply that ran into its
            # reserve, gets here; it is recorded, not enforced.
            self.record.output_overshoot = max(self.record.output_overshoot, over)
            log.warning("turn output passed its ceiling by %s tokens", over)

    def tool(self, args):
        if self.tools >= self.limits.tools:
            raise TurnStop("tool_limit", "Tool execution limit reached.")
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
            self._tick()
            self._budget.output(chunk)
            self._budget.text.append(chunk)
            record.first_text()
            on_token(chunk)

        def partial():
            return "".join(self._budget.text), self._budget.memories, self._budget.changes

        try:
            method(self, system, user_input, emit, attachments)
            return partial()
        except TurnStop as exc:
            # The app's note about the stop is stored beside the reply (turn_notice.py), not in it.
            self._budget.stop(exc.code, str(exc))
            return partial()
        except BudgetExceeded as exc:
            self._budget.stop("limit", str(exc))
            return partial()
        except BaseException as exc:
            if is_stall(exc) and not isinstance(exc, InterruptedError):
                # The provider went quiet past its idle timeout: the turn ends as a deadline.
                self._budget.stop("deadline", f"stalled: {type(exc).__name__}")
                return partial()
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
