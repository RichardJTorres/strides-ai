"""Offline report of the chat context for a mode: what each section costs and what is sent.

Runs the same assembly and admission as a chat turn, without calling a model and without writing
to the database. Sizes are the app's estimates, not provider token counts, unless ``measure`` is
set (which lets admission call the provider's token-count endpoint, as a live turn would).
"""

import argparse
from dataclasses import asdict
from types import SimpleNamespace

from sqlmodel import Session

REPORT_MESSAGE = "(context report)"


def build_report(mode: str, measure: bool = False) -> dict:
    from .api.deps import build_backend
    from .api.routers.chat import _build_chat_system
    from .budget import BudgetExceeded
    from .db.engine import get_engine

    with Session(get_engine()) as session:
        system = _build_chat_system(session, mode)
    backend = build_backend(SimpleNamespace(state=SimpleNamespace()), mode)
    if not measure:
        backend._count_request = lambda *args, **kwargs: None
    report = {
        "mode": mode,
        "model": backend.label,
        "measured": measure,
        "limits": asdict(backend.limits),
        "system_bytes": len(str(system).encode("utf-8")),
        "rejected": None,
    }
    try:
        backend.prepare_turn(system, REPORT_MESSAGE, None)
    except BudgetExceeded as exc:
        report["rejected"] = str(exc)
    report.update(backend._admission or {})
    return report


def _row(name: str, size: int | None, est: int | None, sent: str) -> str:
    size_text = f"{size:,}" if size is not None else ""
    est_text = f"{est:,}" if est is not None else ""
    return f"{name:<28}{size_text:>10}{est_text:>10}  {sent}"


def format_report(report: dict) -> str:
    limits = report.get("limits") or {}
    lines = [
        f"Context report: mode={report['mode']} model={report['model']}",
        "Sizes are the app's estimates"
        + (
            " checked against the provider's token count."
            if report.get("measured")
            else " (offline), not provider token counts."
        ),
        "Limits: " + ", ".join(f"{key}={value:,}" for key, value in limits.items()),
        "",
        f"{'Section':<28}{'bytes':>10}{'est':>10}  Sent",
    ]
    if report.get("rejected"):
        lines.append(f"REJECTED: {report['rejected']}")
        return "\n".join(lines)
    fixed = report.get("fixed") or {}
    for key in ("mandatory", "tools", "submission"):
        lines.append(_row(key, None, fixed.get(key), "yes"))
    activity_rows = []
    for section in report.get("sections", []):
        if str(section["key"]).startswith("activity:"):
            activity_rows.append(section)
            continue
        lines.append(
            _row(
                section["key"],
                section["bytes"],
                section["est"],
                "yes" if section["level"] is not None else "NO",
            )
        )
    if activity_rows:
        sent = [s for s in activity_rows if s["level"] is not None]
        lines.append(
            _row(
                "recent activities",
                sum(s["bytes"] for s in activity_rows),
                sum(s["est"] for s in activity_rows),
                f"{len(sent)} of {len(activity_rows)}",
            )
        )
    history = report.get("history") or {}
    lines += [
        "",
        f"History: {history.get('messages', 0)} messages sent, "
        f"{history.get('dropped', 0)} left out (est {history.get('est', 0):,}).",
        f"System prompt before trimming: {report.get('system_bytes', 0):,} bytes.",
        f"Request as sent: {report.get('est_input', 0):,} ({report.get('count_kind')}).",
        f"Admission took {report.get('admission_ms', 0)} ms.",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", default="running")
    parser.add_argument(
        "--measure",
        action="store_true",
        help="let admission call the provider's token-count endpoint (network)",
    )
    args = parser.parse_args(argv)
    print(format_report(build_report(args.mode, measure=args.measure)))
    return 0
