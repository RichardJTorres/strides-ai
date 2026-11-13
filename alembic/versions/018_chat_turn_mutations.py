"""Chat turn mutation log, and app notices split out of stored replies.

Adds ``chat_turn_mutations`` plus ``conversations.notice`` and ``conversations.receipt_json``, and
moves the app's own stop/failure text out of ``conversations.content`` into ``notice`` so the
model's words and the app's stay separate. When rows are rewritten a SQLite backup is written
first (as in 015); if it cannot be, the migration aborts. The downgrade appends the notice text back to ``content``.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None

# Frozen copies of the strings the app used to write into ``content``.
FAILED = "_Chat failed — resend your message to try again._"
INTERRUPTED = "_Chat interrupted — resend your message to generate a full response._"
TRUNCATED = "_[Response truncated — hit the length limit. Ask me to continue.]_"
STOPPED_PREFIX = "_Turn stopped: "
STOPPED_SUFFIX = " Earlier memory or calendar changes may already have completed._"

# What the downgrade writes back for each code.
RESTORE = {
    "failed": FAILED,
    "interrupted": INTERRUPTED,
    "cancelled": INTERRUPTED,
    "truncated": TRUNCATED,
    "limit": STOPPED_PREFIX + "a size or time limit was reached." + STOPPED_SUFFIX,
}


def _backup(bind) -> None:
    db_path = bind.engine.url.database
    if not db_path or db_path == ":memory:":
        return
    backups = Path(db_path).parent / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    target = backups / f"activities-pre-018-{datetime.now():%Y%m%d-%H%M%S}.db"
    src = sqlite3.connect(db_path)
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    if not target.exists() or target.stat().st_size == 0:
        raise RuntimeError(f"Pre-migration backup failed: {target}")


def _split(content: str) -> tuple[str, str | None]:
    """(model text, notice code) for a stored reply, matching only the app's exact strings."""
    for marker, code in (
        (FAILED, "failed"),
        (INTERRUPTED, "interrupted"),
        (TRUNCATED, "truncated"),
    ):
        if content == marker:
            return "", code
        if content.endswith("\n\n" + marker):
            return content[: -len(marker) - 2], code
    stopped_at = content.rfind("\n\n" + STOPPED_PREFIX)
    start = stopped_at + 2 if stopped_at >= 0 else (0 if content.startswith(STOPPED_PREFIX) else -1)
    if start >= 0 and content.endswith(STOPPED_SUFFIX):
        return content[: max(start - 2, 0)] if start else "", "limit"
    return content, None


def upgrade():
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, content FROM conversations WHERE role = 'assistant'")
    ).fetchall()
    rewrites = []
    for row_id, content in rows:
        text, code = _split(content or "")
        if code is not None:
            rewrites.append((row_id, text, code))
    if rewrites:  # like 015, only when there is something to lose
        _backup(bind)
    op.create_table(
        "chat_turn_mutations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("turn_id", sa.Integer, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("state", sa.Text, nullable=False, server_default="committed"),
        sa.Column("payload_json", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, server_default=sa.text("datetime('now')")),
    )
    op.create_index("ix_chat_turn_mutations_turn_id", "chat_turn_mutations", ["turn_id"])
    op.add_column("conversations", sa.Column("notice", sa.Text, nullable=True))
    op.add_column("conversations", sa.Column("receipt_json", sa.Text, nullable=True))
    for row_id, text, code in rewrites:
        bind.execute(
            sa.text("UPDATE conversations SET content = :c, notice = :n WHERE id = :i"),
            {"c": text, "n": code, "i": row_id},
        )


def downgrade():
    bind = op.get_bind()
    _backup(bind)  # the receipts and the mutation log are dropped
    rows = bind.execute(
        sa.text("SELECT id, content, notice FROM conversations WHERE notice IS NOT NULL")
    ).fetchall()
    for row_id, content, code in rows:
        marker = RESTORE.get(code)
        if marker is None:
            continue
        restored = f"{content.rstrip()}\n\n{marker}" if (content or "").strip() else marker
        bind.execute(
            sa.text("UPDATE conversations SET content = :c WHERE id = :i"),
            {"c": restored, "i": row_id},
        )
    with op.batch_alter_table("conversations") as batch:
        batch.drop_column("receipt_json")
        batch.drop_column("notice")
    op.drop_index("ix_chat_turn_mutations_turn_id", table_name="chat_turn_mutations")
    op.drop_table("chat_turn_mutations")
