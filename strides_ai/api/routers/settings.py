"""Settings and provider routes."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ... import db
from ...config import VALID_MODES, VALID_PROVIDERS, get_settings
from ..deps import _get_provider_models, _provider_statuses, init_backend

router = APIRouter()


class SettingsBody(BaseModel):
    mode: str | None = None
    provider: str | None = None
    model: str | None = None


@router.get("/settings")
def get_api_settings():
    return {
        "mode": db.get_setting("mode", "running"),
        "provider": db.get_setting("provider", get_settings().provider),
    }


@router.put("/settings")
def put_settings(request: Request, body: SettingsBody):
    settings = get_settings()
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
        target = body.provider or db.get_setting("provider", settings.provider) or "claude"
        db.set_setting(f"{target}_model", body.model)
    if body.mode is not None or body.provider is not None or body.model is not None:
        init_backend(request.app, mode=body.mode, provider=body.provider)
    return {
        "mode": db.get_setting("mode", "running"),
        "provider": db.get_setting("provider", settings.provider),
    }


@router.get("/providers")
def get_providers():
    return _provider_statuses()


@router.get("/providers/{provider}/models")
def get_provider_models(provider: str):
    if provider not in VALID_PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")
    return _get_provider_models(provider)
