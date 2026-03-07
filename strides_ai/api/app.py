"""FastAPI application factory."""

import os
import queue
import threading
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import db
from ..coach import build_initial_history, build_system, RECALL_MESSAGES
from ..profile import profile_to_text, get_default_fields


app = FastAPI(title="Strides AI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_methods=["*"],
    allow_headers=["*"],
)

# Backend is created once and shared across requests
_backend = None
_current_mode: str = "running"

VALID_MODES = {"running", "cycling", "hybrid"}


def get_backend():
    global _backend
    if _backend is None:
        raise HTTPException(status_code=503, detail="Backend not initialised")
    return _backend


def init_backend(mode: str | None = None) -> None:
    """Called at server startup (and on mode/profile changes) to build the LLM backend."""
    global _backend, _current_mode
    if mode is not None:
        _current_mode = mode

    activities = db.get_activities_for_mode(_current_mode)
    prior_messages = db.get_recent_messages(RECALL_MESSAGES, mode=_current_mode)
    initial_history = build_initial_history(activities, prior_messages, mode=_current_mode)

    provider = os.environ.get("PROVIDER", "claude").lower()
    if provider == "ollama":
        from ..backends.ollama import OllamaBackend, DEFAULT_HOST
        model = os.environ.get("OLLAMA_MODEL", "llama3.1")
        host = os.environ.get("OLLAMA_HOST", DEFAULT_HOST)
        _backend = OllamaBackend(model, initial_history, host)
    else:
        from ..backends.claude import ClaudeBackend
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        model = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
        _backend = ClaudeBackend(api_key, initial_history, model)


# ── Settings ──────────────────────────────────────────────────────────────────

class SettingsBody(BaseModel):
    mode: str


@app.get("/api/settings")
def get_settings():
    return {"mode": db.get_setting("mode", "running")}


@app.put("/api/settings")
def put_settings(body: SettingsBody):
    if body.mode not in VALID_MODES:
        raise HTTPException(status_code=400, detail=f"mode must be one of {sorted(VALID_MODES)}")
    db.set_setting("mode", body.mode)
    init_backend(mode=body.mode)
    return {"mode": body.mode}


# ── Chat ─────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    mode: str = "running"


@app.post("/api/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    backend = get_backend()
    memories = db.get_all_memories()
    profile_fields = db.get_profile_fields(req.mode)
    profile = profile_to_text(profile_fields, req.mode)
    system = build_system(profile, memories, mode=req.mode)

    token_queue: queue.SimpleQueue[str | None] = queue.SimpleQueue()

    def on_token(chunk: str) -> None:
        token_queue.put(chunk)

    def run_turn():
        try:
            response_text, memories_saved = backend.stream_turn(system, req.message, on_token)
            # Signal memories in a special SSE event
            if memories_saved:
                import json as _json
                token_queue.put(
                    "[MEMORIES]"
                    + _json.dumps([{"category": c, "content": t} for c, t in memories_saved])
                )
            db.save_message("user", req.message, mode=req.mode)
            db.save_message("assistant", response_text, mode=req.mode)
        finally:
            token_queue.put(None)  # sentinel

    threading.Thread(target=run_turn, daemon=True).start()

    async def event_stream() -> AsyncIterator[str]:
        while True:
            chunk = token_queue.get()
            if chunk is None:
                break
            yield f"data: {chunk.replace(chr(10), chr(92) + 'n')}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ── Activities ────────────────────────────────────────────────────────────────

@app.get("/api/activities")
def activities(mode: str | None = None):
    if mode and mode in VALID_MODES:
        rows = db.get_activities_for_mode(mode)
    else:
        rows = db.get_all_activities()
    return [dict(r) for r in rows]


# ── Charts ────────────────────────────────────────────────────────────────────

@app.get("/api/charts")
def charts(unit: str = "miles", mode: str = "running"):
    if unit not in ("miles", "km"):
        raise HTTPException(status_code=400, detail="unit must be 'miles' or 'km'")
    if mode not in VALID_MODES:
        mode = "running"
    from ..charts_data import get_chart_data
    rows = db.get_activities_for_mode(mode)
    return get_chart_data(rows, unit)


# ── Memories ──────────────────────────────────────────────────────────────────

@app.get("/api/memories")
def memories():
    return db.get_all_memories()


# ── Profile ───────────────────────────────────────────────────────────────────

class ProfileBody(BaseModel):
    fields: dict


@app.get("/api/profile")
def get_profile(mode: str | None = None):
    m = mode or _current_mode
    fields = db.get_profile_fields(m) or get_default_fields(m)
    return {"fields": fields}


@app.put("/api/profile")
def put_profile(body: ProfileBody, mode: str | None = None):
    m = mode or _current_mode
    db.save_profile_fields(m, body.fields)
    init_backend()
    return {"status": "ok"}


@app.post("/api/profile/reset")
def reset_profile(mode: str | None = None):
    m = mode or _current_mode
    fields = get_default_fields(m)
    db.save_profile_fields(m, fields)
    init_backend()
    return {"fields": fields}


# ── Sync ──────────────────────────────────────────────────────────────────────

@app.post("/api/sync")
def sync(full: bool = False):
    import os
    from ..auth import get_access_token
    from ..sync import sync_activities

    client_id = os.environ.get("STRAVA_CLIENT_ID", "")
    client_secret = os.environ.get("STRAVA_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise HTTPException(status_code=500, detail="Strava credentials not configured")

    access_token = get_access_token(client_id, client_secret)
    new_count = sync_activities(access_token, full=full)
    if new_count > 0:
        init_backend()
    return {"new_activities": new_count}


# ── History ───────────────────────────────────────────────────────────────────

@app.get("/api/history")
def history(limit: int = RECALL_MESSAGES, mode: str | None = None):
    messages = db.get_recent_messages(limit, mode=mode)
    total = db.get_message_count(mode=mode)
    return {"messages": messages, "total": total}


@app.get("/api/history/older")
def history_older(before_id: int, limit: int = 40, mode: str | None = None):
    messages = db.get_messages_before(before_id, limit, mode=mode)
    return {"messages": messages}


@app.get("/api/history/search")
def history_search(q: str, limit: int = 20, mode: str | None = None):
    if not q or not q.strip():
        return {"results": []}
    return {"results": db.search_messages(q.strip(), limit, mode=mode)}


# ── Status ────────────────────────────────────────────────────────────────────

@app.get("/api/status")
def status():
    backend = get_backend()
    return {
        "backend": backend.label,
        "activities": len(db.get_all_activities()),
        "memories": len(db.get_all_memories()),
        "mode": _current_mode,
    }
