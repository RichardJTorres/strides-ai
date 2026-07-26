"""Fetch all activities from Strava and persist them locally."""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Generator

import httpx

from . import db
from .activity_types import CardioActivity, SportType
from .analysis import RateLimitError, _fetch_streams, _process_streams, analyze_activity
from .db import get_stored_ids, upsert_activity, upsert_canonical_activity
from .db.models import RUN_TYPES

ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"
PAGE_SIZE = 100

log = logging.getLogger(__name__)


def _iter_activities(access_token: str) -> Generator[dict, None, None]:
    """Page through all Strava activities newest-first."""
    headers = {"Authorization": f"Bearer {access_token}"}
    page = 1
    with httpx.Client() as client:
        while True:
            resp = client.get(
                ACTIVITIES_URL,
                headers=headers,
                params={"per_page": PAGE_SIZE, "page": page},
            )
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            yield from batch
            if len(batch) < PAGE_SIZE:
                break
            page += 1


def _normalize_strava(raw: dict) -> CardioActivity:
    """Map a raw Strava API activity dict to a CardioActivity."""
    distance_m: float = raw.get("distance", 0)
    moving_time_s: int = raw.get("moving_time", 0)
    avg_pace_s_per_km = (
        moving_time_s / (distance_m / 1000) if distance_m > 0 and moving_time_s > 0 else None
    )
    sport = SportType.from_api(raw.get("sport_type", raw.get("type")))
    raw_cadence = raw.get("average_cadence")
    avg_cadence = (
        (raw_cadence * 2 if sport in RUN_TYPES else raw_cadence)
        if raw_cadence is not None
        else None
    )
    return CardioActivity(
        id=raw["id"],
        source="strava",
        sport_type=sport,
        name=raw.get("name"),
        date=raw.get("start_date_local", "")[:10],
        distance_m=distance_m,
        moving_time_s=moving_time_s,
        elapsed_time_s=raw.get("elapsed_time"),
        elevation_gain_m=raw.get("total_elevation_gain"),
        avg_pace_s_per_km=avg_pace_s_per_km,
        avg_hr=raw.get("average_heartrate"),
        max_hr=raw.get("max_heartrate"),
        avg_cadence=avg_cadence,
        suffer_score=raw.get("suffer_score"),
        perceived_exertion=raw.get("perceived_exertion"),
        raw_json=json.dumps(raw),
    )


def sync_activities(access_token: str, full: bool = False) -> int:
    """
    Sync all activities from Strava.

    If *full* is False (default), stops as soon as it encounters an activity
    already in the database — fast incremental sync.

    If *full* is True, re-fetches every page and upserts everything — use this
    to backfill or fix gaps.

    Returns the number of new/updated activities written.

    Performance: stream fetches (HTTP I/O) are parallelized across up to 5
    workers; metric computation and DB writes remain sequential to avoid SQLite
    write contention. renormalize_effort_efficiency() runs once at the end
    instead of once per activity.
    """
    stored_ids = get_stored_ids()
    max_hr = int(db.get_setting("max_hr", "190") or "190")
    count = 0

    # Phase 1: collect activities to upsert and analyze
    to_analyze: list[dict] = []
    for activity in _iter_activities(access_token):
        if not full and activity["id"] in stored_ids:
            # In incremental mode, once we hit a known activity we're up-to-date
            break

        upsert_canonical_activity(_normalize_strava(activity))
        count += 1

        # Skip analysis for already-analyzed activities during a full sync
        if full and activity["id"] in stored_ids:
            stored = db.get_activity(activity["id"])
            if stored and stored.get("analysis_status") == "done":
                continue

        to_analyze.append(activity)

    # Phase 2: parallel stream fetch (I/O-bound — safe to parallelize)
    any_analyzed = False
    rate_limited = False

    if to_analyze:
        fetch_results: dict[int, tuple[dict, dict | None, str]] = {}
        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_activity = {
                executor.submit(_fetch_streams, act["id"], access_token): act for act in to_analyze
            }
            for future in as_completed(future_to_activity):
                act = future_to_activity[future]
                streams, status = future.result()
                fetch_results[act["id"]] = (act, streams, status)

        # Phase 3: sequential processing (CPU + DB writes — avoids SQLite contention)
        for activity in to_analyze:  # preserve insertion order
            activity_id = activity["id"]
            act, streams, status = fetch_results[activity_id]

            if status == "pending":
                db.save_analysis(activity_id, {"analysis_status": "pending"})
                rate_limited = True
                log.warning("rate limited during sync — activity %s deferred", activity_id)
            elif status == "error":
                db.save_analysis(activity_id, {"analysis_status": "error"})
            else:
                result = _process_streams(act, streams, max_hr=max_hr)
                if result == "done":
                    any_analyzed = True

    # Phase 4: backfill pending activities (sequential; rate-limit awareness required)
    if not rate_limited:
        pending = db.get_activities_pending_analysis(limit=10)
        for act in pending:
            status = analyze_activity(act, access_token, max_hr=max_hr, renormalize=False)
            if status == "pending":
                log.warning("rate limited during backfill — stopping")
                break
            if status == "done":
                any_analyzed = True

    # Phase 5: renormalize once after all analyses complete (O(N) instead of O(N²))
    if any_analyzed:
        db.renormalize_effort_efficiency()

    return count
