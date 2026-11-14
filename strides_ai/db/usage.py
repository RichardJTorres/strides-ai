"""LLM usage log (see LlmUsage): one row per model call, summarised on read."""

import logging
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from .models import LlmUsage

TOKEN_FIELDS = ("input_total", "cache_read", "cache_write", "output_total", "reasoning")


def record(
    session: Session,
    *,
    source: str,
    provider: str,
    model: str,
    mode: str | None = None,
    turn_id: int | None = None,
    **tokens,
) -> None:
    session.add(
        LlmUsage(
            source=source,
            provider=provider,
            model=model,
            mode=mode,
            turn_id=turn_id,
            **{k: v for k, v in tokens.items() if k in TOKEN_FIELDS},
        )
    )
    session.commit()


def record_safely(**fields) -> None:
    """Log a call's usage in its own session. A usage row must never cost the caller its reply."""
    try:
        from .engine import get_engine

        with Session(get_engine()) as session:
            record(session, **fields)
    except Exception:
        logging.getLogger(__name__).exception("llm usage could not be recorded")


def _sum(values):
    """Sum of the reported values, or None when none was reported."""
    reported = [v for v in values if v is not None]
    return sum(reported) if reported else None


def sum_rounds(rounds: list[dict]) -> dict:
    """One turn's usage from its record's rounds; a figure no round reported stays None."""
    return {f: _sum(r.get(f) for r in rounds) for f in TOKEN_FIELDS}


def _aggregate(rows: list[LlmUsage]) -> dict:
    from ..backends.pricing import cost  # lazy: the backends package imports this package

    costs = [cost(r.provider, r.model, r.__dict__) for r in rows]
    return {
        "calls": len(rows),
        "input_tokens": sum(r.input_total or 0 for r in rows),
        "output_tokens": sum(r.output_total or 0 for r in rows),
        "cache_read_tokens": sum(r.cache_read or 0 for r in rows),
        "cache_write_tokens": sum(r.cache_write or 0 for r in rows),
        "cost_usd": round(sum(c for c in costs if c is not None), 6),
        # Calls whose cost could not be estimated (unpriced model, or tokens not reported).
        "unpriced_calls": sum(1 for c in costs if c is None),
    }


def _grouped(rows: list[LlmUsage], key, label: str) -> list[dict]:
    groups: dict[str, list[LlmUsage]] = {}
    for row in rows:
        groups.setdefault(key(row), []).append(row)
    out = [{label: k, **_aggregate(v)} for k, v in groups.items()]
    return sorted(out, key=lambda g: g[label])


def summarize(session: Session, days: int = 30, now: datetime | None = None) -> dict:
    """Totals and per-day / per-model / per-source breakdowns for the last ``days`` days."""
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    rows = list(session.exec(select(LlmUsage).where(LlmUsage.ts >= cutoff)).all())
    return {
        "days": days,
        "totals": _aggregate(rows),
        "by_day": _grouped(rows, lambda r: (r.ts or "")[:10], "day"),
        "by_model": _grouped(rows, lambda r: r.model, "model"),
        "by_source": _grouped(rows, lambda r: r.source, "source"),
    }
