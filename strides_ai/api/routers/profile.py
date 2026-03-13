"""Profile routes."""

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ... import db
from ...profile import get_default_fields
from ..deps import init_backend

router = APIRouter()


class ProfileBody(BaseModel):
    fields: dict


@router.get("/profile")
def get_profile(request: Request, mode: str | None = None):
    m = mode or request.app.state.mode
    fields = db.get_profile_fields(m) or get_default_fields(m)
    return {"fields": fields}


@router.put("/profile")
def put_profile(request: Request, body: ProfileBody, mode: str | None = None):
    m = mode or request.app.state.mode
    db.save_profile_fields(m, body.fields)
    init_backend(request.app)
    return {"status": "ok"}


@router.post("/profile/reset")
def reset_profile(request: Request, mode: str | None = None):
    m = mode or request.app.state.mode
    fields = get_default_fields(m)
    db.save_profile_fields(m, fields)
    init_backend(request.app)
    return {"fields": fields}
