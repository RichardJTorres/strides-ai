"""Per-turn record: what a chat turn sent, how long it took and why it stopped.

Sizes and timings only, never prompt or reply content. Stored in ``chat_turns.budget_json`` and
read back through ``GET /api/chat/turns/{id}/budget``. Fields a later phase fills are ``None``.
"""

import time
from dataclasses import asdict, is_dataclass

VERSION = 1


def _ms(seconds: float) -> int:
    return int(round(seconds * 1000))


class TurnRecord:
    """Collects one turn's facts. Every method is cheap and never raises on bad input."""

    def __init__(self, model: str | None = None, limits=None, clock=time.monotonic):
        self._clock = clock
        self._started = clock()
        self._round_started: float | None = None
        self._early_retries = [0, 0]  # count, wait ms: retries before the first round started
        self.model = model
        self.ratio: float | None = None  # bytes per token the input estimate used
        self.limits = asdict(limits) if is_dataclass(limits) else None
        self.admission: dict = {}
        self.rounds: list[dict] = []
        self.stop: dict = {"reason": "complete", "detail": None}

    def set_admission(self, admission: dict | None) -> None:
        self.admission = dict(admission or {})

    def start_round(self, n: int, est_input: int, count_kind: str) -> None:
        self._round_started = self._clock()
        self.rounds.append(
            {
                "n": n,
                # Tools are offered on every round until the turn policy distinguishes reply rounds.
                "kind": "tool",
                "est_input": est_input,
                "count_kind": count_kind,
                "input_total": None,
                "cache_read": None,
                "cache_write": None,
                "output_total": None,
                "output_est": None,
                "reasoning": None,
                "first_event_ms": None,
                "first_text_ms": None,
                "duration_ms": None,
                "retries": self._early_retries[0],
                "retry_wait_ms": self._early_retries[1],
                "stop": None,
                "tools_run": 0,
            }
        )
        self._early_retries = [0, 0]

    def _current(self) -> dict | None:
        return self.rounds[-1] if self.rounds else None

    def first_text(self) -> None:
        current = self._current()
        if current is not None and current["first_text_ms"] is None and self._round_started:
            current["first_text_ms"] = _ms(self._clock() - self._round_started)

    def end_round(
        self,
        output_total: int | None,
        output_est: int | None = None,
        *,
        input_total: int | None = None,
        cache_read: int | None = None,
        cache_write: int | None = None,
        reasoning: int | None = None,
    ) -> None:
        """Called at the end of a round's generation; the last call wins for the output fields.

        ``output_total`` is the provider's own count (None when it reported none);
        ``output_est`` is the app's running estimate. A usage field the provider did not report
        stays None, and a later call without it never erases one already recorded.
        """
        current = self._current()
        if current is None or self._round_started is None:
            return
        if type(output_total) is int:
            current["output_total"] = output_total
        if type(output_est) is int:
            current["output_est"] = output_est
        for key, value in (
            ("input_total", input_total),
            ("cache_read", cache_read),
            ("cache_write", cache_write),
            ("reasoning", reasoning),
        ):
            if type(value) is int:
                current[key] = value
        current["duration_ms"] = _ms(self._clock() - self._round_started)

    def tool(self) -> None:
        current = self._current()
        if current is not None:
            current["tools_run"] += 1

    def retry(self, wait_seconds: float) -> None:
        """A transport retry. It can precede the first round, so it is kept for the next one."""
        current = self._current()
        if current is None:
            self._early_retries[0] += 1
            self._early_retries[1] += _ms(wait_seconds)
            return
        current["retries"] += 1
        current["retry_wait_ms"] += _ms(wait_seconds)

    def set_stop(self, reason: str, detail: str | None = None) -> None:
        """``detail`` must be app-authored text or an error class and status, never provider or
        user text, which could echo prompt content."""
        self.stop = {"reason": reason, "detail": detail[:300] if detail else None}

    def to_dict(self, total_ms: int | None = None) -> dict:
        admission = self.admission
        return {
            "v": VERSION,
            "model": self.model,
            "profile": None,
            "limits": self.limits,
            "ratio": self.ratio,
            "admission_ms": admission.get("admission_ms"),
            "total_ms": total_ms,
            "fixed": admission.get("fixed"),
            "sections": admission.get("sections", []),
            "history": admission.get("history"),
            "ladder": [],
            "est_input": admission.get("est_input"),
            "count_kind": admission.get("count_kind"),
            "rounds": self.rounds,
            "stop": self.stop,
        }
