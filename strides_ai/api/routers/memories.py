"""Memories route."""

from fastapi import APIRouter

from ... import db

router = APIRouter()


@router.get("/memories")
def memories():
    return db.get_all_memories()
