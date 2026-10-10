"""Unified route lookup — dispatches to RideWithGPS or Strava based on the URL.

The two source modules (`ridewithgps.py`, `strava_routes.py`) return the same normalized shape
(`name`, `distance_m`, `elevation_gain_m`, `elevation_loss_m`, plus source-specific optional
extras, and `track_points` for the detail variant), so callers never need to know which source a
given route came from.
"""

from . import ridewithgps, strava_routes


def _dispatch(url: str) -> str:
    if "ridewithgps.com" in url.lower():
        return "ridewithgps"
    if "strava.com" in url.lower():
        return "strava"
    raise ValueError(
        f"Not a recognized route URL — paste a Strava or RideWithGPS route link: {url}"
    )


def fetch_route_summary(url: str) -> dict:
    source = _dispatch(url)
    if source == "ridewithgps":
        return ridewithgps.fetch_route_summary(ridewithgps.extract_route_id(url))
    route_id = strava_routes.extract_route_id(url)
    token = strava_routes.get_strava_access_token()
    return strava_routes.fetch_route_summary(route_id, token)


def fetch_route_detail(url: str) -> dict:
    source = _dispatch(url)
    if source == "ridewithgps":
        return ridewithgps.fetch_route_detail(ridewithgps.extract_route_id(url))
    route_id = strava_routes.extract_route_id(url)
    token = strava_routes.get_strava_access_token()
    return strava_routes.fetch_route_detail(route_id, token)
