"""Unit tests for strides_ai.sources.routes (source dispatch)."""

from unittest.mock import patch

import pytest

from strides_ai.sources.routes import fetch_route_detail, fetch_route_summary


def test_fetch_route_summary_dispatches_to_ridewithgps():
    with patch("strides_ai.sources.routes.ridewithgps.fetch_route_summary") as mock_fetch:
        mock_fetch.return_value = {"name": "RWGPS route"}
        result = fetch_route_summary("https://ridewithgps.com/routes/12345")

    mock_fetch.assert_called_once_with(12345)
    assert result == {"name": "RWGPS route"}


def test_fetch_route_summary_dispatches_to_strava():
    with patch("strides_ai.sources.routes.strava_routes.get_strava_access_token") as mock_token:
        mock_token.return_value = "tok"
        with patch("strides_ai.sources.routes.strava_routes.fetch_route_summary") as mock_fetch:
            mock_fetch.return_value = {"name": "Strava route"}
            result = fetch_route_summary("https://www.strava.com/routes/999")

    mock_fetch.assert_called_once_with(999, "tok")
    assert result == {"name": "Strava route"}


def test_fetch_route_detail_dispatches_to_ridewithgps():
    with patch("strides_ai.sources.routes.ridewithgps.fetch_route_detail") as mock_fetch:
        mock_fetch.return_value = {"track_points": []}
        result = fetch_route_detail("https://ridewithgps.com/routes/12345-some-slug")

    mock_fetch.assert_called_once_with(12345)
    assert result == {"track_points": []}


def test_fetch_route_detail_dispatches_to_strava():
    with patch("strides_ai.sources.routes.strava_routes.get_strava_access_token") as mock_token:
        mock_token.return_value = "tok"
        with patch("strides_ai.sources.routes.strava_routes.fetch_route_detail") as mock_fetch:
            mock_fetch.return_value = {"track_points": []}
            result = fetch_route_detail("https://strava.com/routes/999")

    mock_fetch.assert_called_once_with(999, "tok")
    assert result == {"track_points": []}


def test_fetch_route_summary_unrecognized_url_raises_value_error():
    with pytest.raises(ValueError):
        fetch_route_summary("https://example.com/not-a-route")


def test_fetch_route_detail_unrecognized_url_raises_value_error():
    with pytest.raises(ValueError):
        fetch_route_detail("https://komoot.com/routes/1")
