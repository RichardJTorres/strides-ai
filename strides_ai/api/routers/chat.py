"""Chat route with SSE streaming."""

import asyncio
import base64
import queue
import threading
from pathlib import Path
from typing import AsyncIterator
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlmodel import Session

from ...coach import build_system
from ...config import MAX_FILE_BYTES, SUPPORTED_IMAGE_TYPES, UPLOADS_DIR
from ...db import activities as act_crud
from ...db import memories as mem_crud
from ...db import profiles as prof_crud
from ...db.engine import get_session
from ...profile import profile_to_text
from ..conversations import ConversationCoordinator

router = APIRouter()


async def _process_attachment(file: UploadFile) -> tuple[dict, str]:
    """Read an uploaded file and return (llm_content_block, db_display_string)."""
    data = await file.read()
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"{file.filename}: file too large (max 20 MB)",
        )

    content_type = (file.content_type or "").split(";")[0].strip()
    if content_type in SUPPORTED_IMAGE_TYPES:
        suffix = Path(file.filename or "upload").suffix or ".jpg"
        filename = f"{uuid4()}{suffix}"
        (UPLOADS_DIR / filename).write_bytes(data)
        llm_block = {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": content_type,
                "data": base64.standard_b64encode(data).decode(),
            },
        }
        db_display = f"![{file.filename}](/uploads/{filename})"
    else:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(
                status_code=400,
                detail=f"{file.filename}: unsupported binary file format; only images and UTF-8 text files are accepted",
            )
        llm_block = {"type": "text", "text": f"--- File: {file.filename} ---\n{text}"}
        db_display = f"📎 {file.filename}"

    return llm_block, db_display


def _build_chat_system(session: Session, mode: str) -> str:
    """Assemble the full system prompt from DB state."""
    memories = mem_crud.get_all(session)
    profile_fields = prof_crud.get_fields(session, mode)
    profile = profile_to_text(profile_fields, mode)
    coach_voice = (profile_fields or {}).get("coach_voice", "")
    activities = [r.model_dump() for r in act_crud.get_all(session)]
    return build_system(
        profile,
        [r.model_dump() for r in memories],
        mode=mode,
        activities=activities,
        coach_voice=coach_voice,
    )


async def _sse_event_stream(
    token_queue: "queue.Queue[str | None]",
    cancel_event: threading.Event,
    request: Request,
) -> AsyncIterator[str]:
    """Async generator that drains token_queue and yields SSE-encoded events."""
    loop = asyncio.get_event_loop()
    try:
        while True:
            try:
                chunk = await loop.run_in_executor(None, lambda: token_queue.get(timeout=1.0))
            except queue.Empty:
                if await request.is_disconnected():
                    break
                continue
            if chunk is None:
                break
            yield f"data: {chunk.replace(chr(10), chr(92) + 'n')}\n\n"
        yield "data: [DONE]\n\n"
    finally:
        cancel_event.set()


@router.post("/chat")
async def chat(
    request: Request,
    message: str = Form(...),
    mode: str = Form("running"),
    files: list[UploadFile] = File(default=[]),
    session: Session = Depends(get_session),
) -> StreamingResponse:
    coordinator: ConversationCoordinator = request.app.state.conversations
    turn = coordinator.acquire(mode)
    try:
        llm_blocks, db_parts = [], []
        for file in files:
            if not file.filename:
                continue
            block, display = await _process_attachment(file)
            llm_blocks.append(block)
            db_parts.append(display)

        saved_message = message
        if db_parts:
            saved_message += "\n\n" + "\n".join(db_parts)
        system = _build_chat_system(session, mode)
        coordinator.start(turn, system, message, saved_message, llm_blocks or None)
    except BaseException:
        coordinator.release(turn)
        raise

    return StreamingResponse(
        _sse_event_stream(turn.tokens, turn.cancel, request),
        media_type="text/event-stream",
    )
