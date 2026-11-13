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


def _row(name: str, *cells) -> str:
    return f"{name:<26}" + "".join(f"{cell:>12}" for cell in cells)


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
    ]
    if report.get("rejected"):
        lines.append(f"REJECTED: {report['rejected']}")
        return "\n".join(lines)
    fixed = report.get("fixed") or {}
    target = report.get("context_target") or 0
    sections = report.get("sections", [])
    required = [s for s in sections if s.get("kind") == "required"]
    reducible = [s for s in sections if s.get("kind") == "reducible"]
    lines.append(_row("Required (never cut)", "est tokens"))
    lines.append(_row("  tool definitions", fixed.get("tools")))
    lines.append(_row("  your message", fixed.get("submission")))
    lines.append(_row("  date_time", fixed.get("date_time")))
    for section in required:
        lines.append(_row(f"  {section['key']}", section["est"]))
    lines += [
        f"Required context: {report.get('required_est', 0):,} of a {target:,}-token target.",
        "",
        _row("Reducible", "level", "of", "cap", "est", "est at full"),
    ]
    for section in reducible:
        lines.append(
            _row(
                f"  {section['key']}",
                section["level"],
                section["full"],
                f"{section['cap']:,}",
                f"{section['est']:,}",
                f"{section['full_est']:,}",
            )
        )
    history = report.get("history") or {}
    lines.append(
        _row(
            "  history (pairs)",
            history.get("pairs", 0),
            history.get("of", 0),
            f"{history.get('cap', 0):,}",
            f"{history.get('est', 0):,}",
        )
    )
    ladder = report.get("ladder") or []
    lines += [
        "",
        "Ladder steps applied: " + (", ".join(ladder) if ladder else "none (everything fits)"),
        f"System prompt at full size: {report.get('system_bytes', 0):,} bytes.",
        f"Request as sent: {report.get('est_input', 0):,} of {target:,} ({report.get('count_kind')}).",
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
