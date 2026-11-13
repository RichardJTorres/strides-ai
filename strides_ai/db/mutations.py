"""Log of the changes a chat turn made, and the receipt built from it.

A row is added to the same session (and so the same transaction) as the change it records, so a
change and its record commit or roll back together. The receipt is built only from this log.
"""

import json

from sqlmodel import Session, select

from .models import ChatTurnMutation

RECEIPT_VERSION = 1


def log(session: Session, turn_id: int | None, kind: str, state: str, payload: dict) -> None:
    """Add a log row to ``session`` without committing. No turn id (tests, one-shot calls): no row."""
    if turn_id is None:
        return
    session.add(
        ChatTurnMutation(
            turn_id=turn_id, kind=kind, state=state, payload_json=json.dumps(payload, default=str)
        )
    )


def log_now(session: Session, turn_id: int | None, kind: str, state: str, payload: dict) -> None:
    """Log a change that has no database write of its own (a pending proposal) in a transaction."""
    log(session, turn_id, kind, state, payload)
    session.commit()


def build_receipt(session: Session, turn_id: int | None) -> dict | None:
    """What the turn changed, from its log; None when it changed nothing."""
    if turn_id is None:
        return None
    rows = session.exec(
        select(ChatTurnMutation)
        .where(ChatTurnMutation.turn_id == turn_id)
        .order_by(ChatTurnMutation.id)
    ).all()
    calendar = {"kind": "calendar", "created": [], "updated": [], "deleted": []}
    committed: list[dict] = []
    pending: list[dict] = []
    for row in rows:
        try:
            payload = json.loads(row.payload_json)
        except ValueError:
            continue
        if row.state == "pending":
            pending.append({"kind": row.kind, **payload})
        elif row.kind == "calendar":
            for key in ("created", "updated", "deleted"):
                calendar[key].extend(payload.get(key, []))
        else:
            committed.append({"kind": row.kind, **payload})
    if any(calendar[k] for k in ("created", "updated", "deleted")):
        committed.insert(0, calendar)
    if not committed and not pending:
        return None
    return {"v": RECEIPT_VERSION, "committed": committed, "pending": pending}
