"""Memories route."""

from fastapi import APIRouter, Depends
from sqlmodel import Session

from ...db import memories as crud
from ...db.engine import get_session

router = APIRouter()


@router.get("/memories")
def get_memories(session: Session = Depends(get_session)):
    return [r.model_dump() for r in crud.get_all(session)]
