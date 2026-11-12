"""The week_start display setting: defaults to Monday, persists, rejects unknown values.
Calls the route handlers directly with an explicit session (see test_charts_router.py)."""

import pytest
from fastapi import HTTPException
from sqlmodel import Session

from strides_ai.api.routers.settings import SettingsBody, get_api_settings, put_settings
from strides_ai.db.engine import get_engine


def test_defaults_to_monday(tmp_db):
    with Session(get_engine()) as session:
        assert get_api_settings(session=session)["week_start"] == "monday"


def test_persists_sunday(tmp_db):
    with Session(get_engine()) as session:
        out = put_settings(request=None, body=SettingsBody(week_start="sunday"), session=session)
        assert out["week_start"] == "sunday"
        assert get_api_settings(session=session)["week_start"] == "sunday"


def test_rejects_unknown_value(tmp_db):
    with Session(get_engine()) as session:
        with pytest.raises(HTTPException) as exc:
            put_settings(request=None, body=SettingsBody(week_start="friday"), session=session)
        assert exc.value.status_code == 400
