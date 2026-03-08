"""FastAPI application factory."""

import base64
import json
import os
import queue
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import db
from ..auth import get_access_token
from ..backends.claude import ClaudeBackend
from ..backends.gemini import GeminiBackend, DEFAULT_MODEL as GEMINI_DEFAULT_MODEL
from ..backends.ollama import OllamaBackend, DEFAULT_HOST
from ..charts_data import get_chart_data
from ..coach import build_initial_history, build_system, RECALL_MESSAGES
from ..profile import profile_to_text, get_default_fields
from ..sync import sync_activities

VALID_MODES = {"running", "cycling", "hybrid"}
UPLOADS_DIR = Path.home() / ".strides_ai" / "uploads"
SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_FILE_BYTES = 20 * 1024 * 1024  # 20 MB


VALID_PROVIDERS = {"claude", "gemini", "ollama"}

# Curated model lists for cloud providers
CLAUDE_MODELS = [
    {"id": "claude-sonnet-4-6", "display_name": "Claude Sonnet 4.6"},
    {"id": "claude-opus-4-6", "display_name": "Claude Opus 4.6"},
    {"id": "claude-haiku-4-5-20251001", "display_name": "Claude Haiku 4.5"},
]

GEMINI_MODELS = [
    {"id": "gemini-2.0-flash", "display_name": "Gemini 2.0 Flash (free)"},
    {"id": "gemini-2.0-flash-lite", "display_name": "Gemini 2.0 Flash Lite (free)"},
    {"id": "gemini-1.5-flash", "display_name": "Gemini 1.5 Flash (free)"},
    {"id": "gemini-1.5-flash-8b", "display_name": "Gemini 1.5 Flash-8B (free)"},
    {"id": "gemini-1.5-pro", "display_name": "Gemini 1.5 Pro"},
    {"id": "gemini-2.5-pro", "display_name": "Gemini 2.5 Pro"},
]


def _get_provider_models(provider_id: str) -> list[dict]:
    """Return available models for a provider."""
    if provider_id == "claude":
        return CLAUDE_MODELS
    if provider_id == "gemini":
        return GEMINI_MODELS
    if provider_id == "ollama":
        host = os.environ.get("OLLAMA_HOST", DEFAULT_HOST).rstrip("/")
        try:
            import httpx as _httpx

            resp = _httpx.get(f"{host}/api/tags", timeout=3)
            return [
                {"id": m["name"], "display_name": m["name"]} for m in resp.json().get("models", [])
            ]
        except Exception:
            return []
    return []


def _stored_model(provider_id: str, env_key: str, default: str) -> str:
    """Return the model stored in DB for this provider, falling back to env then default."""
    return db.get_setting(f"{provider_id}_model") or os.environ.get(env_key, default)


def _provider_statuses() -> list[dict]:
    """Return the list of providers with their configuration and active status."""
    current = db.get_setting("provider", os.environ.get("PROVIDER", "claude")) or "claude"

    # Probe Ollama once — reachable + has models == configured
    ollama_models = _get_provider_models("ollama")
    ollama_configured = len(ollama_models) > 0
    ollama_default = ollama_models[0]["id"] if ollama_models else "llama3.1"

    return [
        {
            "id": "claude",
            "label": "Claude",
            "selected_model": _stored_model("claude", "CLAUDE_MODEL", "claude-sonnet-4-6"),
            "configured": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "active": current == "claude",
            "config_hint": (
                "Set ANTHROPIC_API_KEY in .env" if not os.environ.get("ANTHROPIC_API_KEY") else None
            ),
        },
        {
            "id": "gemini",
            "label": "Gemini",
            "selected_model": _stored_model("gemini", "GEMINI_MODEL", GEMINI_DEFAULT_MODEL),
            "configured": bool(os.environ.get("GEMINI_API_KEY")),
            "active": current == "gemini",
            "config_hint": (
                "Set GEMINI_API_KEY in .env" if not os.environ.get("GEMINI_API_KEY") else None
            ),
        },
        {
            "id": "ollama",
            "label": "Ollama",
            "selected_model": _stored_model("ollama", "OLLAMA_MODEL", ollama_default),
            "configured": ollama_configured,
            "active": current == "ollama",
            "config_hint": (
                "Start Ollama and pull at least one model" if not ollama_configured else None
            ),
        },
    ]


def init_backend(app: FastAPI, mode: str | None = None, provider: str | None = None) -> None:
    """Called at server startup (and on mode/profile/provider changes) to build the LLM backend."""
    if mode is not None:
        app.state.mode = mode
    if provider is not None:
        app.state.provider = provider
    current_mode = getattr(app.state, "mode", "running")
    current_provider = (
        getattr(app.state, "provider", None) or os.environ.get("PROVIDER", "claude")
    ).lower()

    activities = db.get_activities_for_mode(current_mode)
    prior_messages = db.get_recent_messages(RECALL_MESSAGES, mode=current_mode)
    initial_history = build_initial_history(activities, prior_messages, mode=current_mode)

    if current_provider == "ollama":
        available = _get_provider_models("ollama")
        auto_default = available[0]["id"] if available else "llama3.1"
        model = _stored_model("ollama", "OLLAMA_MODEL", auto_default)
        host = os.environ.get("OLLAMA_HOST", DEFAULT_HOST)
        app.state.backend = OllamaBackend(model, initial_history, host)
    elif current_provider == "gemini":
        api_key = os.environ.get("GEMINI_API_KEY", "")
        model = _stored_model("gemini", "GEMINI_MODEL", GEMINI_DEFAULT_MODEL)
        app.state.backend = GeminiBackend(api_key, initial_history, model)
    else:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        model = _stored_model("claude", "CLAUDE_MODEL", "claude-sonnet-4-6")
        app.state.backend = ClaudeBackend(api_key, initial_history, model)


def get_backend(request: Request):
    backend = getattr(request.app.state, "backend", None)
    if backend is None:
        raise HTTPException(status_code=503, detail="Backend not initialised")
    return backend


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    saved_mode = db.get_setting("mode", "running")
    saved_provider = db.get_setting("provider", os.environ.get("PROVIDER", "claude"))
    init_backend(app, mode=saved_mode, provider=saved_provider)
    yield


app = FastAPI(title="Strides AI", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR), check_dir=False), name="uploads")


# ── Settings ──────────────────────────────────────────────────────────────────


class SettingsBody(BaseModel):
    mode: str | None = None
    provider: str | None = None
    model: str | None = None


@app.get("/api/settings")
def get_settings():
    return {
        "mode": db.get_setting("mode", "running"),
        "provider": db.get_setting("provider", os.environ.get("PROVIDER", "claude")),
    }


@app.put("/api/settings")
def put_settings(request: Request, body: SettingsBody):
    if body.mode is not None:
        if body.mode not in VALID_MODES:
            raise HTTPException(
                status_code=400, detail=f"mode must be one of {sorted(VALID_MODES)}"
            )
        db.set_setting("mode", body.mode)
    if body.provider is not None:
        if body.provider not in VALID_PROVIDERS:
            raise HTTPException(
                status_code=400, detail=f"provider must be one of {sorted(VALID_PROVIDERS)}"
            )
        db.set_setting("provider", body.provider)
    if body.model is not None:
        target = (
            body.provider
            or db.get_setting("provider", os.environ.get("PROVIDER", "claude"))
            or "claude"
        )
        db.set_setting(f"{target}_model", body.model)
    if body.mode is not None or body.provider is not None or body.model is not None:
        init_backend(request.app, mode=body.mode, provider=body.provider)
    return {
        "mode": db.get_setting("mode", "running"),
        "provider": db.get_setting("provider", os.environ.get("PROVIDER", "claude")),
    }


@app.get("/api/providers")
def get_providers():
    return _provider_statuses()


@app.get("/api/providers/{provider}/models")
def get_provider_models(provider: str):
    if provider not in VALID_PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")
    return _get_provider_models(provider)


# ── Chat ─────────────────────────────────────────────────────────────────────


@app.post("/api/chat")
async def chat(
    request: Request,
    message: str = Form(...),
    mode: str = Form("running"),
    files: list[UploadFile] = File(default=[]),
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

    memories = db.get_all_memories()
    profile_fields = db.get_profile_fields(mode)
    profile = profile_to_text(profile_fields, mode)
    system = build_system(profile, memories, mode=mode)

    token_queue: queue.SimpleQueue[str | None] = queue.SimpleQueue()

    def on_token(chunk: str) -> None:
        token_queue.put(chunk)

    def run_turn():
        try:
            response_text, memories_saved = backend.stream_turn(
                system, message, on_token, attachments=llm_blocks or None
            )
            if memories_saved:
                token_queue.put(
                    "[MEMORIES]"
                    + json.dumps([{"category": c, "content": t} for c, t in memories_saved])
                )
            db.save_message("user", saved_message, mode=mode)
            db.save_message("assistant", response_text, mode=mode, model=backend.label)
        except Exception as exc:
            token_queue.put(f"[ERROR]{exc}")
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
def get_profile(request: Request, mode: str | None = None):
    m = mode or request.app.state.mode
    fields = db.get_profile_fields(m) or get_default_fields(m)
    return {"fields": fields}


@app.put("/api/profile")
def put_profile(request: Request, body: ProfileBody, mode: str | None = None):
    m = mode or request.app.state.mode
    db.save_profile_fields(m, body.fields)
    init_backend(request.app)
    return {"status": "ok"}


@app.post("/api/profile/reset")
def reset_profile(request: Request, mode: str | None = None):
    m = mode or request.app.state.mode
    fields = get_default_fields(m)
    db.save_profile_fields(m, fields)
    init_backend(request.app)
    return {"fields": fields}


# ── Sync ──────────────────────────────────────────────────────────────────────


@app.post("/api/sync")
def sync(request: Request, full: bool = False):
    client_id = os.environ.get("STRAVA_CLIENT_ID", "")
    client_secret = os.environ.get("STRAVA_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise HTTPException(status_code=500, detail="Strava credentials not configured")

    access_token = get_access_token(client_id, client_secret)
    new_count = sync_activities(access_token, full=full)
    if new_count > 0:
        init_backend(request.app)
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


# ── Calendar ──────────────────────────────────────────────────────────────────


class CalendarPrefsBody(BaseModel):
    blocked_days: list[str] = []
    races: list[dict] = []


class WorkoutBody(BaseModel):
    workout_type: str
    description: str | None = None
    distance_km: float | None = None
    elevation_m: float | None = None
    duration_min: int | None = None
    intensity: str | None = None


@app.get("/api/calendar/prefs")
def get_calendar_prefs():
    return db.get_calendar_prefs()


@app.put("/api/calendar/prefs")
def put_calendar_prefs(body: CalendarPrefsBody):
    db.save_calendar_prefs(body.blocked_days, body.races)
    return {"status": "ok"}


@app.get("/api/calendar/plan")
def get_calendar_plan():
    return db.get_training_plan()


@app.put("/api/calendar/plan/{date}")
def put_planned_workout(date: str, body: WorkoutBody):
    db.save_planned_workout(
        date,
        body.workout_type,
        body.description,
        body.distance_km,
        body.elevation_m,
        body.duration_min,
        body.intensity,
    )
    return {"status": "ok", "date": date}


@app.delete("/api/calendar/plan/{date}")
def delete_planned_workout(date: str):
    db.delete_planned_workout(date)
    return {"status": "ok"}


@app.post("/api/calendar/plan/{date}/nutrition")
def analyze_workout_nutrition(date: str, request: Request):
    from ..schedule import analyze_nutrition

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not set")

    plan = db.get_training_plan()
    workout = next((w for w in plan if w["date"] == date), None)
    if not workout:
        raise HTTPException(status_code=404, detail="No planned workout found for this date")

    mode = getattr(request.app.state, "mode", "running")
    profile_fields = db.get_profile_fields(mode)
    profile_text = profile_to_text(profile_fields, mode)

    nutrition = analyze_nutrition(workout, profile_text, api_key)
    db.save_workout_nutrition(date, nutrition)
    return nutrition


# ── Status ────────────────────────────────────────────────────────────────────


@app.get("/api/status")
def status(request: Request, backend=Depends(get_backend)):
    return {
        "backend": backend.label,
        "activities": len(db.get_all_activities()),
        "memories": len(db.get_all_memories()),
        "mode": request.app.state.mode,
        "supports_attachments": backend.supports_attachments,
    }
