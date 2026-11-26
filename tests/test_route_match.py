"""Same-route matching: polyline decoding, resampling and track overlap."""

import json

import pytest

from strides_ai import route_match as rm


def encode(points: list[tuple[float, float]]) -> str:
    """Google polyline encoder (the inverse of rm.decode_polyline), for building fixtures."""
    out, prev = [], (0, 0)
    for lat, lng in points:
        cur = (round(lat * 1e5), round(lng * 1e5))
        for delta in (cur[0] - prev[0], cur[1] - prev[1]):
            value = ~(delta << 1) if delta < 0 else delta << 1
            while value >= 0x20:
                out.append(chr((0x20 | (value & 0x1F)) + 63))
                value >>= 5
            out.append(chr(value + 63))
        prev = cur
    return "".join(out)


def row(points, **kw) -> dict:
    return {"raw_json": json.dumps({"map": {"summary_polyline": encode(points)}}), **kw}


# A 4 km eastward line at 47.5 N, sampled every ~400 m, and variants of it.
LINE = [(47.5, -122.0 + i * 0.0053) for i in range(11)]
REVERSED = list(reversed(LINE))
PARALLEL_1KM = [(lat + 0.009, lng) for lat, lng in LINE]  # ~1 km north
HALF = LINE[:6] + [(47.5 + 0.0045 * i, LINE[5][1]) for i in range(1, 6)]  # turns north halfway


def test_decodes_googles_reference_example():
    points = rm.decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@")
    assert points == [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]


def test_malformed_polyline_decodes_to_nothing():
    assert rm.decode_polyline("_p~iF~ps|U_") == []


def test_encoder_round_trips():
    assert rm.decode_polyline(encode(LINE)) == [(round(a, 5), round(b, 5)) for a, b in LINE]


def tracks(*point_lists):
    ref = point_lists[0][0][0]
    return [rm.track_of(row(p), ref) for p in point_lists]


def test_identical_and_reversed_tracks_overlap_fully():
    a, b, c = tracks(LINE, LINE, REVERSED)
    assert rm.overlap(a, b) == 1.0
    assert rm.overlap(a, c) == 1.0


def test_a_parallel_road_a_kilometre_away_shares_nothing():
    a, b = tracks(LINE, PARALLEL_1KM)
    assert rm.overlap(a, b) == 0.0


def test_half_a_shared_route_scores_about_half():
    a, b = tracks(LINE, HALF)
    assert rm.overlap(a, b) == pytest.approx(0.5, abs=0.1)


def test_a_short_loop_inside_a_long_ride_is_not_the_same_route():
    # Every point of the short track lies on the long one, but most of the long one does not.
    a, b = tracks(LINE, LINE[:4])
    assert rm.overlap(a, b) < 0.5


def test_resample_spacing_and_degenerate_tracks():
    track = rm.track_of(row(LINE))
    assert len(track) == rm.TRACK_POINTS
    assert rm.resample([]) == []
    assert rm.resample([(1.0, 2.0), (1.0, 2.0)]) == [(1.0, 2.0)]
    assert rm.overlap([], track) == 0.0


@pytest.mark.parametrize(
    "raw",
    [None, "", "not json", json.dumps({}), json.dumps({"map": None}), json.dumps({"map": {}})],
)
def test_activities_without_a_track(raw):
    assert rm.track_of({"raw_json": raw}) is None
    assert rm.start_lat({"raw_json": raw}) is None


def test_a_single_point_is_not_a_track():
    assert rm.track_of(row(LINE[:1])) is None
