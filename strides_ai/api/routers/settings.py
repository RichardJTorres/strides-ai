"""Settings and provider routes."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session

from ...config import VALID_MODES, VALID_PROVIDERS, get_settings
from ...db import settings as crud
from ...db.engine import get_session
from ...units import UnitSystem
from ..deps import get_provider_models, provider_statuses, init_backend

router = APIRouter()


class SettingsBody(BaseModel):
    mode: str | None = None
    provider: str | None = None
    model: str | None = None
    unit_system: str | None = None


def _settings_payload(session: Session) -> dict:
    return {
        "mode": crud.get(session, "mode", "running"),
        "provider": crud.get(session, "provider", get_settings().provider),
        "unit_system": crud.get_unit_system(session).value,
    }


@router.get("/settings")
def get_api_settings(session: Session = Depends(get_session)):
    return _settings_payload(session)


@router.put("/settings")
def put_settings(
    request: Request,
    body: SettingsBody,
    session: Session = Depends(get_session),
):
    settings = get_settings()
    if body.mode is not None:
        if body.mode not in VALID_MODES:
            raise HTTPException(
                status_code=400, detail=f"mode must be one of {sorted(VALID_MODES)}"
            )
        crud.set(session, "mode", body.mode)
    if body.provider is not None:
        if body.provider not in VALID_PROVIDERS:
            raise HTTPException(
                status_code=400, detail=f"provider must be one of {sorted(VALID_PROVIDERS)}"
            )
        crud.set(session, "provider", body.provider)
    if body.model is not None:
        target = body.provider or crud.get(session, "provider", settings.provider) or "claude"
        crud.set(session, f"{target}_model", body.model)
    if body.unit_system is not None:
        valid = {u.value for u in UnitSystem}
        if body.unit_system not in valid:
            raise HTTPException(
                status_code=400, detail=f"unit_system must be one of {sorted(valid)}"
            )
        # No backend re-init needed: the system prompt is rebuilt from settings every turn.
        crud.set(session, crud.UNIT_SYSTEM_KEY, body.unit_system)
    if body.mode is not None or body.provider is not None or body.model is not None:
        init_backend(request.app, mode=body.mode, provider=body.provider)
    return _settings_payload(session)


@router.get("/providers")
def get_providers():
    return provider_statuses()


@router.get("/providers/{provider}/models")
def get_models_for_provider(provider: str):
    if provider not in VALID_PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")
    return get_provider_models(provider)
