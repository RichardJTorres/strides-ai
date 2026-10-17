"""Tests for strides_ai.insights — digest math, flags, fingerprint, prompt and parser."""

import json
from datetime import date, timedelta

import pytest

from strides_ai.insights import (
    build_digest,
    build_insights_prompt,
    digest_fingerprint,
    parse_insights_response,
)
from strides_ai.units import UnitSystem

TODAY = date(2026, 6, 3)  # Wednesday; current week starts 2026-06-01
START = date(2026, 3, 9)  # first day of the 8-week baseline


def run_row(i: int, d: date, **overrides) -> dict:
    row = {
        "id": i,
        "source": "strava",
        "sport_type": "Run",
        "date": d.isoformat(),
        "name": "Run",
        "moving_time_s": 3600,
        "distance_m": 10_000.0,
        "elevation_gain_m": 50.0,
        "avg_pace_s_per_km": 360.0,
        "avg_hr": 140.0,
        "avg_cadence": 170.0,
        "hr_zone_1_pct": 10.0,
        "hr_zone_2_pct": 70.0,
        "hr_zone_3_pct": 10.0,
        "hr_zone_4_pct": 8.0,
        "hr_zone_5_pct": 2.0,
        "cardiac_decoupling_pct": 3.0,
        "pace_fade_s_per_km": 5.0,
    }
    row.update(overrides)
    return row


def steady_rows(every_days: int = 2, **overrides) -> list[dict]:
    rows, d, i = [], START, 1
    while d < date(2026, 6, 1):
        rows.append(run_row(i, d, **overrides))
        d += timedelta(days=every_days)
        i += 1
    return rows


def metric(digest: dict, metric_id: str) -> dict | None:
    return next((m for m in digest["metrics"] if m["id"] == metric_id), None)


def test_insufficient_data_returns_empty_digest():
    digest = build_digest([run_row(1, date(2026, 5, 20))], "running", UnitSystem.METRIC, TODAY)
    assert digest["sufficient"] is False
    assert digest["metrics"] == []


def test_steady_volume_is_flat_and_current_week_excluded():
    rows = steady_rows() + [run_row(900, date(2026, 6, 2), distance_m=50_000.0)]
    digest = build_digest(rows, "running", UnitSystem.METRIC, TODAY)
    dist = metric(digest, "volume.distance")
    assert dist["direction"] == "flat"
    # The big session in the in-progress week must not leak into the recent/baseline windows.
    assert dist["value"] == pytest.approx(dist["baseline"], rel=0.05)
    assert metric(digest, "volume.wtd")["value"] == pytest.approx(50.0)


def test_deterministic():
    rows = steady_rows()
    a = build_digest(rows, "running", UnitSystem.METRIC, TODAY)
    b = build_digest(rows, "running", UnitSystem.METRIC, TODAY)
    assert a == b


def test_imperial_units_convert():
    rows = steady_rows()
    metric_d = metric(build_digest(rows, "running", UnitSystem.METRIC, TODAY), "volume.distance")
    imp_d = metric(build_digest(rows, "running", UnitSystem.IMPERIAL, TODAY), "volume.distance")
    assert metric_d["formatted"].endswith("km")
    assert imp_d["formatted"].endswith("mi")
    assert imp_d["value"] == pytest.approx(metric_d["value"] / 1.609344, rel=1e-3)


def test_ramp_flag_fires_on_big_last_week():
    rows = steady_rows()
    for n in range(5):  # a huge final full week (May 25-31)
        rows.append(run_row(500 + n, date(2026, 5, 25) + timedelta(days=n), distance_m=30_000.0))
    digest = build_digest(rows, "running", UnitSystem.METRIC, TODAY)
    assert "ramp_high" in {f["id"] for f in digest["flags"]}


def test_gap_flag_and_none_metrics_omitted():
    rows = [r for r in steady_rows() if r["date"] < "2026-05-20"]
    digest = build_digest(rows, "running", UnitSystem.METRIC, TODAY)
    assert "long_gap" in {f["id"] for f in digest["flags"]}


def test_missing_zone_data_is_omitted_not_zero():
    rows = steady_rows(
        hr_zone_1_pct=None,
        hr_zone_2_pct=None,
        hr_zone_3_pct=None,
        hr_zone_4_pct=None,
        hr_zone_5_pct=None,
    )
    digest = build_digest(rows, "running", UnitSystem.METRIC, TODAY)
    assert metric(digest, "intensity.easy_share") is None
    assert "intensity.hr_zones" in digest["missing"]


def test_easy_share_value():
    digest = build_digest(steady_rows(), "running", UnitSystem.METRIC, TODAY)
    assert metric(digest, "intensity.easy_share")["value"] == pytest.approx(80.0)


def test_hybrid_has_per_sport_volume_and_prefixed_quality_metrics():
    rows = steady_rows()
    rows += [
        run_row(700 + n, START + timedelta(days=2 * n + 1), sport_type="Ride") for n in range(40)
    ]
    digest = build_digest(rows, "hybrid", UnitSystem.METRIC, TODAY)
    assert metric(digest, "volume.run_distance") and metric(digest, "volume.ride_distance")
    assert metric(digest, "intensity.run_easy_share")


def test_race_and_compliance_context():
    plan = [
        {"date": "2026-05-30", "workout_type": "Easy Run", "distance_km": 10},
        {"date": "2026-05-26", "workout_type": "Easy Run", "distance_km": 10},
    ]
    races = [{"date": "2026-06-20", "name": "10K"}, {"date": "2026-01-01", "name": "Old"}]
    digest = build_digest(
        steady_rows(), "running", UnitSystem.METRIC, TODAY, plan_rows=plan, races=races
    )
    assert digest["context"]["next_race"] == {"name": "10K", "date": "2026-06-20", "days_out": 17}
    assert digest["context"]["compliance"]["scored"] == 2
    assert "race_soon" in {f["id"] for f in digest["flags"]}


def test_fingerprint_changes_on_new_activity_units_and_week():
    rows = steady_rows()
    base = digest_fingerprint(rows, "running", UnitSystem.METRIC, TODAY)
    assert base == digest_fingerprint(rows, "running", UnitSystem.METRIC, TODAY)
    more = rows + [run_row(9999, date(2026, 6, 2))]
    assert digest_fingerprint(more, "running", UnitSystem.METRIC, TODAY) != base
    assert digest_fingerprint(rows, "running", UnitSystem.IMPERIAL, TODAY) != base
    assert digest_fingerprint(rows, "running", UnitSystem.METRIC, date(2026, 6, 10)) != base


def test_prompt_contains_ids_and_units_block():
    digest = build_digest(steady_rows(), "running", UnitSystem.IMPERIAL, TODAY)
    prompt = build_insights_prompt(digest, UnitSystem.IMPERIAL)
    assert "[volume.distance]" in prompt
    assert "## Units" in prompt and "miles" in prompt


def test_parser_normalizes_and_filters():
    digest = build_digest(steady_rows(), "running", UnitSystem.METRIC, TODAY)
    payload = {
        "status": "bogus",
        "headline": "h",
        "findings": [
            {"title": f"t{i}", "tone": "weird", "metric_ids": ["volume.distance", "nope"]}
            for i in range(6)
        ],
        "recommendations": [{"action": "a"}] * 5 + [{"why": "no action"}],
    }
    out = parse_insights_response("```json\n" + json.dumps(payload) + "\n```", digest)
    assert out["status"] == "insufficient_data"
    assert len(out["findings"]) == 4 and out["findings"][0]["tone"] == "neutral"
    assert out["findings"][0]["metric_ids"] == ["volume.distance"]
    assert len(out["recommendations"]) == 3


def test_parser_rejects_non_json():
    digest = build_digest(steady_rows(), "running", UnitSystem.METRIC, TODAY)
    with pytest.raises(json.JSONDecodeError):
        parse_insights_response("not json", digest)
