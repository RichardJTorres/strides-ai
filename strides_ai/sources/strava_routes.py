"""Strava route data fetching (distinct from `strava.py`, which handles activity sync/deep-dive).

Unlike RideWithGPS's unauthenticated legacy endpoint, Strava's `/routes/{id}` requires an
authenticated request — but only the `read` scope this app already requests (see `auth.py`), and
it works for any *public* route regardless of which athlete owns it, not just the authenticated
athlete's own routes (confirmed against the live API).
"""

import re

import httpx

from ..auth import get_access_token
from ..config import get_settings
from .base import AuthError, ConfigurationError, NoDataError

ROUTE_ID_RE = re.compile(r"strava\.com/routes/(\d+)", re.IGNORECASE)
API_BASE = "https://www.strava.com/api/v3"

# Strava route `type`: 1 = Ride, 2 = Run, 3 = Walk/Hike (sub_type refines further; we only need
# the ride/run split for route-fit analysis context).
_ACTIVITY_TYPE_BY_CODE = {1: "Ride", 2: "Run", 3: "Walk/Hike"}


def extract_route_id(url: str) -> int:
    match = ROUTE_ID_RE.search(url)
    if not match:
        raise ValueError(f"Not a recognizable Strava route URL: {url}")
    return int(match.group(1))


def get_strava_access_token() -> str:
    settings = get_settings()
    if not settings.strava_client_id or not settings.strava_client_secret:
        raise ConfigurationError("Strava credentials not configured")
    try:
        return get_access_token(settings.strava_client_id, settings.strava_client_secret)
    except Exception as exc:
        raise AuthError(f"Could not get Strava token: {exc}") from exc


def _get(path: str, access_token: str) -> dict | list:
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(
                f"{API_BASE}{path}", headers={"Authorization": f"Bearer {access_token}"}
            )
    except Exception as exc:
        raise RuntimeError(f"Failed to reach Strava for {path}: {exc}") from exc

    if resp.status_code == 404:
        raise NoDataError(
            f"Strava route not found at {path} — it may be private. "
            "Only public routes can be analyzed."
        )
    if resp.status_code != 200:
        raise RuntimeError(f"Strava returned HTTP {resp.status_code} for {path}")

    return resp.json()


def _extract_summary_fields(raw: dict) -> dict:
    estimated_s = raw.get("estimated_moving_time")
    return {
        "name": raw.get("name"),
        "distance_m": raw.get("distance"),
        "elevation_gain_m": raw.get("elevation_gain"),
        "elevation_loss_m": None,  # Strava routes don't report loss separately
        "activity_type": _ACTIVITY_TYPE_BY_CODE.get(raw.get("type")),
        "duration_estimate_min": round(estimated_s / 60) if estimated_s else None,
    }


def fetch_route_summary(route_id: int, access_token: str) -> dict:
    raw = _get(f"/routes/{route_id}", access_token)
    return _extract_summary_fields(raw)


def fetch_route_detail(route_id: int, access_token: str) -> dict:
    raw = _get(f"/routes/{route_id}", access_token)
    streams = _get(f"/routes/{route_id}/streams", access_token)
    by_type = {s["type"]: s["data"] for s in streams if "type" in s and "data" in s}
    distances = by_type.get("distance") or []
    altitudes = by_type.get("altitude") or []
    track_points = [{"d": d, "e": e} for d, e in zip(distances, altitudes)]
    return {**_extract_summary_fields(raw), "track_points": track_points}
