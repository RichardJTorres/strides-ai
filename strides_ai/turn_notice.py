"""App-authored text for how a chat turn ended, and the receipt of what it changed.

Notices and receipts are stored beside a reply, never inside it, so the model's own words stay
separate from the app's. The text is rendered from a code (and the logged changes) at read time,
which keeps it deterministic and lets the wording change without rewriting history.
"""

import json

NOTICE_TEXT = {
    "truncated": "Response cut off at the length limit. Ask me to continue.",
    "limit": "Turn stopped: a size or time limit was reached.",
    "failed": "Chat failed — resend your message to try again.",
    "interrupted": "Chat interrupted — resend your message to generate a full response.",
}
# A turn that was cancelled reads the same as one a restart interrupted.
NOTICE_TEXT["cancelled"] = NOTICE_TEXT["interrupted"]


def notice_text(code: str | None) -> str | None:
    return NOTICE_TEXT.get(code) if code else None


def _calendar_line(item: dict) -> str:
    parts = []
    created = item.get("created") or []
    if created:
        parts.append(
            "created "
            + ", ".join(f"{c.get('date')} ({c.get('label')}) [id {c.get('id')}]" for c in created)
        )
    if item.get("updated"):
        parts.append("updated " + ", ".join(f"[id {i}]" for i in item["updated"]))
    if item.get("deleted"):
        parts.append("removed " + ", ".join(f"[id {i}]" for i in item["deleted"]))
    return "Calendar: " + "; ".join(parts) if parts else ""


def receipt_text(receipt: dict | None) -> str | None:
    """Plain text for a receipt, or None when the turn changed nothing."""
    if not isinstance(receipt, dict):
        return None
    lines = []
    for item in receipt.get("committed") or []:
        if item.get("kind") == "calendar":
            line = _calendar_line(item)
        elif item.get("kind") == "memory":
            line = f"Memory {item.get('action', 'saved')} [{item.get('category')}]: {item.get('content')}"
        else:
            continue
        if line:
            lines.append(f"- {line}")
    pending = [
        f"- {p.get('op')} '{p.get('label')}': {p.get('proposed')}"
        for p in receipt.get("pending") or []
    ]
    out = []
    if lines:
        out += ["Saved:", *lines]
    if pending:
        out += ["Not saved; waiting for you to accept:", *pending]
    return "\n".join(out) if out else None


def parse_receipt(raw) -> dict | None:
    try:
        value = json.loads(raw) if isinstance(raw, str) and raw else None
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def replay_content(content: str, notice: str | None, receipt_json: str | None) -> str:
    """What the coach sees for a stored reply: its words, then the app's note about how it ended."""
    text = notice_text(notice)
    if not text:
        return content
    note = " ".join(p for p in (text, receipt_text(parse_receipt(receipt_json))) if p)
    return f"{content.rstrip()}\n\n[App note: {note}]" if content.strip() else f"[App note: {note}]"
