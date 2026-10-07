"""Unit tests for strides_ai.sources.ridewithgps."""

from unittest.mock import MagicMock, patch

import pytest

from strides_ai.sources.base import NoDataError
from strides_ai.sources.ridewithgps import (
    condense_elevation_profile,
    extract_route_id,
    fetch_route_detail,
    fetch_route_summary,
)

SAMPLE_ROUTE = {
    "name": "Walnut - Via Verde",
    "distance": 45595.8,
    "elevation_gain": 712.046,
    "elevation_loss": 714.697,
    "surface": "paved",
    "pavement_type": "mostly paved",
    "terrain": "climbing",
    "difficulty": "moderate",
    "track_type": "loop",
    "unpaved_pct": 0,
    "track_points": [
        {"x": -117.834518, "y": 33.991461, "e": 314.0, "d": 0},
        {"x": -117.8342, "y": 33.99137, "e": 302.0, "d": 32.9},
    ],
}


# ── extract_route_id ─────────────────────────────────────────────────────────


def test_extract_route_id_plain_url():
    assert extract_route_id("https://ridewithgps.com/routes/12345") == 12345


def test_extract_route_id_with_slug():
    assert extract_route_id("https://ridewithgps.com/routes/12345-walnut-via-verde") == 12345


def test_extract_route_id_with_www():
    assert extract_route_id("https://www.ridewithgps.com/routes/12345") == 12345


def test_extract_route_id_no_protocol():
    assert extract_route_id("ridewithgps.com/routes/12345") == 12345


def test_extract_route_id_invalid_url_raises():
    with pytest.raises(ValueError):
        extract_route_id("https://strava.com/activities/999")


def test_extract_route_id_trips_url_raises():
    """Trip (recorded ride) URLs are out of scope for this feature — routes only."""
    with pytest.raises(ValueError):
        extract_route_id("https://ridewithgps.com/trips/12345")


# ── fetch_route_summary / fetch_route_detail ────────────────────────────────


def _mock_response(json_data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    return resp


def test_fetch_route_summary_returns_expected_fields():
    with patch("strides_ai.sources.ridewithgps.httpx.Client") as MockClient:
        MockClient.return_value.__enter__.return_value.get.return_value = _mock_response(
            SAMPLE_ROUTE
        )
        result = fetch_route_summary(12345)

    assert result["name"] == "Walnut - Via Verde"
    assert result["distance_m"] == 45595.8
    assert result["elevation_gain_m"] == 712.046
    assert result["terrain"] == "climbing"
    assert "track_points" not in result


def test_fetch_route_summary_requests_no_track_points():
    with patch("strides_ai.sources.ridewithgps.httpx.Client") as MockClient:
        mock_get = MockClient.return_value.__enter__.return_value.get
        mock_get.return_value = _mock_response(SAMPLE_ROUTE)
        fetch_route_summary(12345)

    _, kwargs = mock_get.call_args
    assert kwargs["params"] == {"no_track_points": "true"}


def test_fetch_route_detail_includes_track_points():
    with patch("strides_ai.sources.ridewithgps.httpx.Client") as MockClient:
        MockClient.return_value.__enter__.return_value.get.return_value = _mock_response(
            SAMPLE_ROUTE
        )
        result = fetch_route_detail(12345)

    assert result["track_points"] == SAMPLE_ROUTE["track_points"]


def test_fetch_route_summary_404_raises_no_data_error():
    with patch("strides_ai.sources.ridewithgps.httpx.Client") as MockClient:
        MockClient.return_value.__enter__.return_value.get.return_value = _mock_response(
            {}, status_code=404
        )
        with pytest.raises(NoDataError):
            fetch_route_summary(99999999)


def test_fetch_route_summary_other_error_raises_runtime_error():
    with patch("strides_ai.sources.ridewithgps.httpx.Client") as MockClient:
        MockClient.return_value.__enter__.return_value.get.return_value = _mock_response(
            {}, status_code=500
        )
        with pytest.raises(RuntimeError):
            fetch_route_summary(12345)


def test_fetch_route_summary_network_failure_raises_runtime_error():
    with patch("strides_ai.sources.ridewithgps.httpx.Client") as MockClient:
        MockClient.return_value.__enter__.return_value.get.side_effect = Exception("timeout")
        with pytest.raises(RuntimeError):
            fetch_route_summary(12345)


# ── condense_elevation_profile ───────────────────────────────────────────────


def test_condense_elevation_profile_empty():
    assert condense_elevation_profile([]) == []


def test_condense_elevation_profile_short_track_keeps_all_points():
    points = [{"x": 0, "y": 0, "e": 100.0, "d": 0}, {"x": 0, "y": 0, "e": 110.0, "d": 100}]
    profile = condense_elevation_profile(points, target_points=24)
    assert len(profile) == 2
    assert profile[0]["distance_km"] == 0.0
    assert profile[0]["elevation_m"] == 100.0
    assert profile[1]["grade_pct"] == 10.0  # +10m over 100m run = 10%


def test_condense_elevation_profile_downsamples_long_track():
    points = [{"x": 0, "y": 0, "e": float(i), "d": float(i * 100)} for i in range(200)]
    profile = condense_elevation_profile(points, target_points=20)
    assert len(profile) <= 22  # ~target_points, allowing for the final-point guarantee
    assert profile[0]["distance_km"] == 0.0
    # Last sampled point must reach (or very nearly reach) the true end of the route.
    assert profile[-1]["distance_km"] == pytest.approx(19.9, abs=0.1)


def test_condense_elevation_profile_includes_last_point():
    points = [{"x": 0, "y": 0, "e": float(i), "d": float(i * 50)} for i in range(100)]
    profile = condense_elevation_profile(points, target_points=10)
    assert profile[-1]["distance_km"] == pytest.approx(99 * 50 / 1000)
