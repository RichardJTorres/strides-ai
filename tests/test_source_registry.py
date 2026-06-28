"""Tests for the data source registry and get_source_for_activity."""

from unittest.mock import MagicMock

import pytest

from strides_ai.sources import (
    get_source,
    get_source_for_activity,
    hevy_source,
    register_source,
    strava_source,
)


def _activity(source):
    act = MagicMock()
    act.source = source
    return act


def test_get_source_for_activity_strava():
    assert get_source_for_activity(_activity("strava")) is strava_source


def test_get_source_for_activity_hevy():
    assert get_source_for_activity(_activity("hevy")) is hevy_source


def test_get_source_for_activity_none_falls_back_to_strava():
    assert get_source_for_activity(_activity(None)) is strava_source


def test_get_source_for_activity_unknown_raises():
    with pytest.raises(ValueError, match="garmin"):
        get_source_for_activity(_activity("garmin"))


def test_get_source_by_name():
    assert get_source("strava") is strava_source
    assert get_source("hevy") is hevy_source


def test_get_source_unknown_raises():
    with pytest.raises(ValueError, match="unknown_source"):
        get_source("unknown_source")


def test_register_source_adds_to_registry():
    mock = MagicMock()
    mock.source_name = "_test_source_"
    register_source(mock)
    assert get_source("_test_source_") is mock


def test_strava_source_has_source_name():
    assert strava_source.source_name == "strava"


def test_hevy_source_has_source_name():
    assert hevy_source.source_name == "hevy"
