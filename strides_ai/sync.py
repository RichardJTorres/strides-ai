"""Fetch all activities from Strava and persist them locally."""

import json
import logging
from typing import Generator

import httpx

from . import db
from .activity_types import CardioActivity, SportType
from .analysis import RateLimitError, analyze_activity
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
    """
    stored_ids = get_stored_ids()
    max_hr = int(db.get_setting("max_hr", "190") or "190")
    count = 0
    rate_limited = False

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

        if not rate_limited:
            status = analyze_activity(activity, access_token, max_hr=max_hr)
            if status == "pending":
                log.warning("rate limited during sync — deferring remaining stream fetches")
                rate_limited = True

    # Backfill: process up to 10 pending/unanalyzed activities per sync cycle
    if not rate_limited:
        pending = db.get_activities_pending_analysis(limit=10)
        for act in pending:
            status = analyze_activity(act, access_token, max_hr=max_hr)
            if status == "pending":
                log.warning("rate limited during backfill — stopping")
                break

    return count
