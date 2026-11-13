"""Chat turn lifecycle rows (see ChatTurn)."""

import json

from sqlmodel import Session, select

from .models import ChatTurn


def create(session: Session, mode: str, user_message_id: int | None) -> int:
    row = ChatTurn(mode=mode, user_message_id=user_message_id)
    session.add(row)
    session.commit()
    return row.id


def update(
    session: Session,
    turn_id: int,
    *,
    status: str | None = None,
    partial_text: str | None = None,
    events: dict | None = None,
    assistant_message_id: int | None = None,
    budget: dict | None = None,
) -> None:
    row = session.get(ChatTurn, turn_id)
    if row is None:
        return
    if status is not None:
        row.status = status
    if partial_text is not None:
        row.partial_text = partial_text
    if events is not None:
        row.events_json = json.dumps(events)
    if assistant_message_id is not None:
        row.assistant_message_id = assistant_message_id
    if budget is not None:
        row.budget_json = json.dumps(budget)
    session.add(row)
    session.execute(
        ChatTurn.__table__.update().where(ChatTurn.id == turn_id).values(updated_at=_now())
    )
    session.commit()


def _now():
    from sqlalchemy import text

    return text("datetime('now')")


def latest(session: Session, mode: str) -> ChatTurn | None:
    return session.exec(
        select(ChatTurn).where(ChatTurn.mode == mode).order_by(ChatTurn.id.desc()).limit(1)
    ).first()


def mark_delivered(session: Session, turn_id: int) -> None:
    row = session.get(ChatTurn, turn_id)
    if row is not None and not row.delivered:
        row.delivered = True
        session.add(row)
        session.commit()


def running(session: Session) -> list[ChatTurn]:
    return list(session.exec(select(ChatTurn).where(ChatTurn.status == "running")).all())


def budget(row: ChatTurn) -> dict | None:
    """The turn's stored record, or None when it has none (older rows, rejected turns)."""
    try:
        value = json.loads(row.budget_json) if row.budget_json else None
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def to_dict(row: ChatTurn) -> dict:
    return {
        "id": row.id,
        "mode": row.mode,
        "status": row.status,
        "partial_text": row.partial_text,
        "events": json.loads(row.events_json or "{}"),
        "user_message_id": row.user_message_id,
        "assistant_message_id": row.assistant_message_id,
        "delivered": row.delivered,
    }


def pending_modes(session: Session) -> list[str]:
    """Modes whose latest turn is still running or finished without the client receiving it."""
    modes = session.exec(select(ChatTurn.mode).distinct()).all()
    result = []
    for mode in modes:
        row = latest(session, mode)
        if row is not None and (row.status == "running" or not row.delivered):
            result.append(mode)
    return sorted(result)
