"""RideWithGPS route data fetching.

Uses the legacy, unauthenticated `ridewithgps.com/routes/{id}.json` endpoint rather than the
official versioned `/api/v1/` API — the latter requires an API key issued by
developers@ridewithgps.com and is meant for account-linked read/write access. The legacy endpoint
returns full route data (distance, elevation, surface, track points) for any *public* route with
no authentication at all, which covers the common case of a shared route link. Private routes
404. Since it's not the documented API, RideWithGPS could change or remove it without notice.
"""

import re

import httpx

from .base import NoDataError

ROUTE_ID_RE = re.compile(r"ridewithgps\.com/routes/(\d+)", re.IGNORECASE)
ROUTE_JSON_URL = "https://ridewithgps.com/routes/{id}.json"


def extract_route_id(url: str) -> int:
    """Parse a RideWithGPS route URL (with or without a trailing -slug) into its numeric id."""
    match = ROUTE_ID_RE.search(url)
    if not match:
        raise ValueError(f"Not a recognizable RideWithGPS route URL: {url}")
    return int(match.group(1))


def _fetch(route_id: int, include_track_points: bool) -> dict:
    url = ROUTE_JSON_URL.format(id=route_id)
    params = {} if include_track_points else {"no_track_points": "true"}
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(url, params=params)
    except Exception as exc:
        raise RuntimeError(f"Failed to reach RideWithGPS for route {route_id}: {exc}") from exc

    if resp.status_code == 404:
        raise NoDataError(
            f"RideWithGPS route {route_id} not found — it may be private. "
            "Only public routes can be analyzed."
        )
    if resp.status_code != 200:
        raise RuntimeError(f"RideWithGPS returned HTTP {resp.status_code} for route {route_id}")

    return resp.json()


def _extract_summary_fields(raw: dict) -> dict:
    return {
        "name": raw.get("name"),
        "distance_m": raw.get("distance"),
        "elevation_gain_m": raw.get("elevation_gain"),
        "elevation_loss_m": raw.get("elevation_loss"),
        "surface": raw.get("surface"),
        "pavement_type": raw.get("pavement_type"),
        "terrain": raw.get("terrain"),
        "difficulty": raw.get("difficulty"),
        "track_type": raw.get("track_type"),
        "unpaved_pct": raw.get("unpaved_pct"),
    }


def fetch_route_summary(route_id: int) -> dict:
    """Fetch headline route stats (no track points) — distance, elevation, surface, terrain."""
    raw = _fetch(route_id, include_track_points=False)
    return _extract_summary_fields(raw)


def fetch_route_detail(route_id: int) -> dict:
    """Fetch full route data including the track_points elevation profile."""
    raw = _fetch(route_id, include_track_points=True)
    return {**_extract_summary_fields(raw), "track_points": raw.get("track_points") or []}


def condense_elevation_profile(track_points: list[dict], target_points: int = 24) -> list[dict]:
    """
    Downsample a route's track_points (each {"x": lng, "y": lat, "e": elevation_m, "d":
    cumulative_distance_m}) into ~target_points evenly-spaced-by-distance samples with grade,
    compact enough to embed in an LLM prompt.
    """
    if not track_points:
        return []

    total_distance = track_points[-1].get("d", 0) or 0
    if total_distance <= 0 or len(track_points) <= target_points:
        samples = track_points
    else:
        step = total_distance / (target_points - 1)
        samples = []
        next_target = 0.0
        for point in track_points:
            if point.get("d", 0) >= next_target or point is track_points[-1]:
                samples.append(point)
                next_target += step

    profile = []
    prev = None
    for point in samples:
        distance_m = point.get("d", 0) or 0
        elevation_m = point.get("e", 0) or 0
        grade_pct = None
        if prev is not None:
            run = distance_m - prev["d"]
            if run > 0:
                grade_pct = round((elevation_m - prev["e"]) / run * 100, 1)
        profile.append(
            {
                "distance_km": round(distance_m / 1000, 2),
                "elevation_m": round(elevation_m, 1),
                "grade_pct": grade_pct,
            }
        )
        prev = {"d": distance_m, "e": elevation_m}
    return profile
