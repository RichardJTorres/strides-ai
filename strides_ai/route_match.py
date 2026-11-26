"""Same-route matching from the GPS track Strava already sent with each activity.

Pure, no dependency: decode the activity summary's `map.summary_polyline` (Google's encoded
polyline), resample it to TRACK_POINTS points evenly spaced along its length, and score two
tracks by `overlap`: the smaller of the two shares of points lying within TOLERANCE_KM of the
other track. Taking the smaller share means a 20 mi loop is not "the same route" as the 40 mi
ride that contains it. Direction is ignored (a loop ridden backwards matches). Strava privacy
zones trim the ends near home, so overlap is a lower bound.

Start/end point and distance alone are not enough: most rides start and end at home, so loops
of similar length all look alike. The track shape is what tells routes apart.
"""

import json
import math
from typing import Optional

TRACK_POINTS = 80
TOLERANCE_KM = 0.25
_KM_PER_DEG_LAT = 111.32

Track = list[tuple[float, float]]  # (x, y) in km on a local plane


def decode_polyline(encoded: str) -> list[tuple[float, float]]:
    """Google encoded polyline -> [(lat, lng)] at 1e-5 precision. Malformed input -> []."""
    points: list[tuple[float, float]] = []
    index = lat = lng = 0
    try:
        while index < len(encoded):
            deltas = []
            for _ in range(2):
                shift = result = 0
                while True:
                    byte = ord(encoded[index]) - 63
                    index += 1
                    result |= (byte & 0x1F) << shift
                    shift += 5
                    if byte < 0x20:
                        break
                deltas.append(~(result >> 1) if result & 1 else result >> 1)
            lat += deltas[0]
            lng += deltas[1]
            points.append((lat / 1e5, lng / 1e5))
    except IndexError:
        return []
    return points


def _to_plane(points: list[tuple[float, float]], ref_lat: float) -> Track:
    """Equirectangular km around `ref_lat`: exact enough for 250 m at the scale of one ride."""
    k_lng = _KM_PER_DEG_LAT * math.cos(math.radians(ref_lat))
    return [(lng * k_lng, lat * _KM_PER_DEG_LAT) for lat, lng in points]


def resample(points: Track, n: int = TRACK_POINTS) -> Track:
    """`n` points evenly spaced along the track's length. A track with no length -> its start."""
    if not points:
        return []
    cum = [0.0]
    for a, b in zip(points, points[1:]):
        cum.append(cum[-1] + math.dist(a, b))
    total = cum[-1]
    if total == 0:
        return [points[0]]
    out: Track = []
    j = 0
    for k in range(n):
        target = total * k / (n - 1)
        while j < len(cum) - 2 and cum[j + 1] < target:
            j += 1
        seg = cum[j + 1] - cum[j]
        f = (target - cum[j]) / seg if seg else 0.0
        (x0, y0), (x1, y1) = points[j], points[j + 1]
        out.append((x0 + f * (x1 - x0), y0 + f * (y1 - y0)))
    return out


def _share_near(a: Track, b: Track, tol: float) -> float:
    return sum(any(math.dist(p, q) <= tol for q in b) for p in a) / len(a)


def overlap(a: Track, b: Track, tol: float = TOLERANCE_KM) -> float:
    """0..1: the smaller share of either track's points within `tol` km of the other."""
    if not a or not b:
        return 0.0
    # Cheap reject: tracks whose padded bounding boxes do not meet share nothing.
    ax, ay = zip(*a)
    bx, by = zip(*b)
    if (
        min(ax) - tol > max(bx)
        or min(bx) - tol > max(ax)
        or min(ay) - tol > max(by)
        or min(by) - tol > max(ay)
    ):
        return 0.0
    return min(_share_near(a, b, tol), _share_near(b, a, tol))


def polyline_of(row: dict) -> Optional[str]:
    """The activity's summary polyline from its stored Strava payload, or None."""
    raw = row.get("raw_json")
    if not raw:
        return None
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return None
    line = (
        ((data or {}).get("map") or {}).get("summary_polyline") if isinstance(data, dict) else None
    )
    return line or None


def track_of(row: dict, ref_lat: Optional[float] = None) -> Optional[Track]:
    """The activity's resampled track on a plane around `ref_lat` (default: its own start).

    Compare tracks only when they were projected around the same `ref_lat`.
    """
    line = polyline_of(row)
    points = decode_polyline(line) if line else []
    if len(points) < 2:
        return None
    return resample(_to_plane(points, points[0][0] if ref_lat is None else ref_lat))


def start_lat(row: dict) -> Optional[float]:
    line = polyline_of(row)
    points = decode_polyline(line) if line else []
    return points[0][0] if points else None
