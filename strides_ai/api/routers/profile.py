"""Profile routes."""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlmodel import Session

from ...db import profiles as crud
from ...db import settings as settings_crud
from ...db.engine import get_session
from ...profile import get_default_fields
from ..deps import init_backend

router = APIRouter()


class ProfileBody(BaseModel):
    fields: dict


@router.get("/profile")
def get_profile(
    request: Request,
    mode: str | None = None,
    session: Session = Depends(get_session),
):
    m = mode or request.app.state.mode
    fields = crud.get_fields(session, m) or get_default_fields(m)
    return {"fields": fields}


@router.put("/profile")
def put_profile(
    request: Request,
    body: ProfileBody,
    mode: str | None = None,
    session: Session = Depends(get_session),
):
    m = mode or request.app.state.mode
    crud.save_fields(session, m, body.fields)
    max_hr_val = str(body.fields.get("personal", {}).get("max_hr", "")).strip()
    if max_hr_val.isdigit():
        settings_crud.set(session, "max_hr", max_hr_val)
    init_backend(request.app)
    return {"status": "ok"}


@router.post("/profile/reset")
def reset_profile(
    request: Request,
    mode: str | None = None,
    session: Session = Depends(get_session),
):
    m = mode or request.app.state.mode
    fields = get_default_fields(m)
    crud.save_fields(session, m, fields)
    init_backend(request.app)
    return {"fields": fields}
