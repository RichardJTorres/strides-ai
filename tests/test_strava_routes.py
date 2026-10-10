"""Unit tests for strides_ai.sources.strava_routes."""

from unittest.mock import MagicMock, patch

import pytest

from strides_ai.sources.base import AuthError, ConfigurationError, NoDataError
from strides_ai.sources.strava_routes import (
    extract_route_id,
    fetch_route_detail,
    fetch_route_summary,
    get_strava_access_token,
)

SAMPLE_ROUTE = {
    "name": "Southeast 208th Street-Holder Creek Trail-Brew Road",
    "distance": 31222.02,
    "elevation_gain": 897.85,
    "type": 1,
    "estimated_moving_time": 6811,
}

SAMPLE_STREAMS = [
    {"type": "latlng", "data": [[47.4, -121.9], [47.41, -121.91]]},
    {"type": "distance", "data": [0.0, 10.0]},
    {"type": "altitude", "data": [274.3, 273.7]},
]


# ── extract_route_id ─────────────────────────────────────────────────────────


def test_extract_route_id_plain_url():
    assert (
        extract_route_id("https://www.strava.com/routes/3524119254599348698") == 3524119254599348698
    )


def test_extract_route_id_invalid_url_raises():
    with pytest.raises(ValueError):
        extract_route_id("https://ridewithgps.com/routes/12345")


def test_extract_route_id_activities_url_raises():
    """Strava activity links are out of scope for this feature — routes only."""
    with pytest.raises(ValueError):
        extract_route_id("https://www.strava.com/activities/999")


# ── get_strava_access_token ─────────────────────────────────────────────────


def test_get_strava_access_token_missing_config_raises():
    mock_settings = MagicMock(strava_client_id="", strava_client_secret="")
    with patch("strides_ai.sources.strava_routes.get_settings", return_value=mock_settings):
        with pytest.raises(ConfigurationError):
            get_strava_access_token()


def test_get_strava_access_token_auth_failure_raises():
    mock_settings = MagicMock(strava_client_id="id", strava_client_secret="secret")
    with patch("strides_ai.sources.strava_routes.get_settings", return_value=mock_settings):
        with patch(
            "strides_ai.sources.strava_routes.get_access_token", side_effect=Exception("boom")
        ):
            with pytest.raises(AuthError):
                get_strava_access_token()


def test_get_strava_access_token_returns_token():
    mock_settings = MagicMock(strava_client_id="id", strava_client_secret="secret")
    with patch("strides_ai.sources.strava_routes.get_settings", return_value=mock_settings):
        with patch("strides_ai.sources.strava_routes.get_access_token", return_value="tok-123"):
            assert get_strava_access_token() == "tok-123"


# ── fetch_route_summary / fetch_route_detail ────────────────────────────────


def _mock_response(json_data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    return resp


def test_fetch_route_summary_returns_expected_fields():
    with patch("strides_ai.sources.strava_routes.httpx.Client") as MockClient:
        MockClient.return_value.__enter__.return_value.get.return_value = _mock_response(
            SAMPLE_ROUTE
        )
        result = fetch_route_summary(3524119254599348698, "tok")

    assert result["name"] == SAMPLE_ROUTE["name"]
    assert result["distance_m"] == SAMPLE_ROUTE["distance"]
    assert result["elevation_gain_m"] == SAMPLE_ROUTE["elevation_gain"]
    assert result["activity_type"] == "Ride"
    assert result["duration_estimate_min"] == 114  # 6811s / 60, rounded
    assert "track_points" not in result


def test_fetch_route_summary_sends_bearer_token():
    with patch("strides_ai.sources.strava_routes.httpx.Client") as MockClient:
        mock_get = MockClient.return_value.__enter__.return_value.get
        mock_get.return_value = _mock_response(SAMPLE_ROUTE)
        fetch_route_summary(1, "my-token")

    _, kwargs = mock_get.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer my-token"


def test_fetch_route_summary_run_type():
    run_route = {**SAMPLE_ROUTE, "type": 2}
    with patch("strides_ai.sources.strava_routes.httpx.Client") as MockClient:
        MockClient.return_value.__enter__.return_value.get.return_value = _mock_response(run_route)
        result = fetch_route_summary(1, "tok")
    assert result["activity_type"] == "Run"


def test_fetch_route_detail_builds_track_points_from_streams():
    with patch("strides_ai.sources.strava_routes.httpx.Client") as MockClient:
        mock_get = MockClient.return_value.__enter__.return_value.get
        mock_get.side_effect = [
            _mock_response(SAMPLE_ROUTE),
            _mock_response(SAMPLE_STREAMS),
        ]
        result = fetch_route_detail(1, "tok")

    assert result["track_points"] == [
        {"d": 0.0, "e": 274.3},
        {"d": 10.0, "e": 273.7},
    ]


def test_fetch_route_summary_404_raises_no_data_error():
    with patch("strides_ai.sources.strava_routes.httpx.Client") as MockClient:
        MockClient.return_value.__enter__.return_value.get.return_value = _mock_response(
            {}, status_code=404
        )
        with pytest.raises(NoDataError):
            fetch_route_summary(99999999, "tok")


def test_fetch_route_summary_other_error_raises_runtime_error():
    with patch("strides_ai.sources.strava_routes.httpx.Client") as MockClient:
        MockClient.return_value.__enter__.return_value.get.return_value = _mock_response(
            {}, status_code=500
        )
        with pytest.raises(RuntimeError):
            fetch_route_summary(1, "tok")


def test_fetch_route_summary_network_failure_raises_runtime_error():
    with patch("strides_ai.sources.strava_routes.httpx.Client") as MockClient:
        MockClient.return_value.__enter__.return_value.get.side_effect = Exception("timeout")
        with pytest.raises(RuntimeError):
            fetch_route_summary(1, "tok")
