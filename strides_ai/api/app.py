"""FastAPI application factory."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .. import db
from ..config import UPLOADS_DIR, get_settings
from .deps import init_backend
from .routers import (
    activities,
    calendar,
    charts,
    chat,
    history,
    memories,
    profile,
    settings,
    status,
    sync,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    saved_mode = db.get_setting("mode", "running")
    saved_provider = db.get_setting("provider", get_settings().provider)
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

app.include_router(settings.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(activities.router, prefix="/api")
app.include_router(charts.router, prefix="/api")
app.include_router(memories.router, prefix="/api")
app.include_router(profile.router, prefix="/api")
app.include_router(sync.router, prefix="/api")
app.include_router(history.router, prefix="/api")
app.include_router(calendar.router, prefix="/api")
app.include_router(status.router, prefix="/api")
