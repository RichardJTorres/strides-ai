"""Chat route with SSE streaming."""

import asyncio
import base64
import json
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
from ...db import conversations as conv_crud
from ...db import memories as mem_crud
from ...db import profiles as prof_crud
from ...db.engine import get_engine, get_session
from ...profile import profile_to_text
from ..deps import get_backend

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


@router.post("/chat")
async def chat(
    request: Request,
    message: str = Form(...),
    mode: str = Form("running"),
    files: list[UploadFile] = File(default=[]),
    session: Session = Depends(get_session),
    backend=Depends(get_backend),
) -> StreamingResponse:
    llm_blocks: list[dict] = []
    db_parts: list[str] = []
    for file in files:
        if not file.filename:
            continue
        block, display = await _process_attachment(file)
        llm_blocks.append(block)
        db_parts.append(display)

    saved_message = message
    if db_parts:
        saved_message += "\n\n" + "\n".join(db_parts)

    memories = mem_crud.get_all(session)
    profile_fields = prof_crud.get_fields(session, mode)
    profile = profile_to_text(profile_fields, mode)
    coach_voice = (profile_fields or {}).get("coach_voice", "")
    weight_unit = (profile_fields or {}).get("weight_unit", "kg")
    activities = [r.model_dump() for r in act_crud.get_all(session)]
    system = build_system(
        profile,
        [r.model_dump() for r in memories],
        mode=mode,
        activities=activities,
        coach_voice=coach_voice,
        weight_unit=weight_unit,
    )

    conv_crud.save(session, "user", saved_message, mode=mode)

    token_queue: queue.Queue[str | None] = queue.Queue()
    cancel_event = threading.Event()

    def on_token(chunk: str) -> None:
        if cancel_event.is_set():
            raise InterruptedError("client disconnected")
        token_queue.put(chunk)

    def run_turn():
        # Background thread — needs its own session since the request-scoped
        # session is not safe to share across threads.
        with Session(get_engine()) as thread_session:
            try:
                response_text, memories_saved = backend.stream_turn(
                    system, message, on_token, attachments=llm_blocks or None
                )
                token_queue.put(f"[MODEL]{backend.label}")
                if memories_saved:
                    token_queue.put(
                        "[MEMORIES]"
                        + json.dumps([{"category": c, "content": t} for c, t in memories_saved])
                    )
                conv_crud.save(
                    thread_session, "assistant", response_text, mode=mode, model=backend.label
                )
            except InterruptedError:
                conv_crud.save(
                    thread_session,
                    "assistant",
                    "_Chat interrupted — resend your message to generate a full response._",
                    mode=mode,
                )
            except Exception as exc:
                token_queue.put(f"[ERROR]{exc}")
            finally:
                token_queue.put(None)  # sentinel

    threading.Thread(target=run_turn, daemon=True).start()

    async def event_stream() -> AsyncIterator[str]:
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

    return StreamingResponse(event_stream(), media_type="text/event-stream")
