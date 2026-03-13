"""Status route."""

from fastapi import APIRouter, Depends, Request

from ... import db
from ..deps import get_backend

router = APIRouter()


@router.get("/status")
def status(request: Request, backend=Depends(get_backend)):
    return {
        "backend": backend.label,
        "activities": len(db.get_all_activities()),
        "memories": len(db.get_all_memories()),
        "mode": request.app.state.mode,
        "supports_attachments": backend.supports_attachments,
    }
