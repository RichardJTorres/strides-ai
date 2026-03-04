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
from ..profile import load_profile, parse_profile, serialize_profile, is_parseable, PROFILE_PATH, TEMPLATE


app = FastAPI(title="Strides AI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_methods=["*"],
    allow_headers=["*"],
)

# Backend is created once and shared across requests
_backend = None


def get_backend():
    global _backend
    if _backend is None:
        raise HTTPException(status_code=503, detail="Backend not initialised")
    return _backend


def init_backend() -> None:
    """Called at server startup to build the LLM backend."""
    global _backend
    activities = db.get_all_activities()
    prior_messages = db.get_recent_messages(RECALL_MESSAGES)
    initial_history = build_initial_history(activities, prior_messages)

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


# ── Chat ─────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str


@app.post("/api/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    backend = get_backend()
    memories = db.get_all_memories()
    profile = load_profile()
    system = build_system(profile, memories)

    token_queue: queue.SimpleQueue[str | None] = queue.SimpleQueue()

    def on_token(chunk: str) -> None:
        token_queue.put(chunk)

    def run_turn():
        try:
            response_text, memories_saved = backend.stream_turn(system, req.message, on_token)
            # Signal memories in a special SSE event
            if memories_saved:
                import json
                token_queue.put(
                    "\n\n[MEMORIES]"
                    + json.dumps([{"category": c, "content": t} for c, t in memories_saved])
                )
            db.save_message("user", req.message)
            db.save_message("assistant", response_text)
        finally:
            token_queue.put(None)  # sentinel

    threading.Thread(target=run_turn, daemon=True).start()

    async def event_stream() -> AsyncIterator[str]:
        while True:
            chunk = token_queue.get()
            if chunk is None:
                break
            yield f"data: {chunk}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ── Activities ────────────────────────────────────────────────────────────────

@app.get("/api/activities")
def activities():
    rows = db.get_all_activities()
    return [dict(r) for r in rows]


# ── Memories ──────────────────────────────────────────────────────────────────

@app.get("/api/memories")
def memories():
    return db.get_all_memories()


# ── Profile ───────────────────────────────────────────────────────────────────

class ProfileBody(BaseModel):
    fields: dict


@app.get("/api/profile")
def get_profile():
    raw = load_profile()
    if raw and not is_parseable(raw):
        return {"parseable": False, "fields": None}
    return {"parseable": True, "fields": parse_profile(raw) if raw else parse_profile("")}


@app.put("/api/profile")
def put_profile(body: ProfileBody):
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(serialize_profile(body.fields), encoding="utf-8")
    return {"status": "ok"}


@app.post("/api/profile/reset")
def reset_profile():
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(TEMPLATE, encoding="utf-8")
    return {"fields": parse_profile(TEMPLATE)}


# ── Sync ──────────────────────────────────────────────────────────────────────

@app.post("/api/sync")
def sync():
    import os
    from ..auth import get_access_token
    from ..sync import sync_activities

    client_id = os.environ.get("STRAVA_CLIENT_ID", "")
    client_secret = os.environ.get("STRAVA_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise HTTPException(status_code=500, detail="Strava credentials not configured")

    access_token = get_access_token(client_id, client_secret)
    new_count = sync_activities(access_token)
    return {"new_activities": new_count}


# ── Status ────────────────────────────────────────────────────────────────────

@app.get("/api/status")
def status():
    backend = get_backend()
    return {
        "backend": backend.label,
        "activities": len(db.get_all_activities()),
        "memories": len(db.get_all_memories()),
    }
