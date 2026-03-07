"""Fetch runs and rides from Strava and persist them locally."""

from typing import Generator

import httpx

from .db import get_stored_ids, upsert_activity, RUN_TYPES, CYCLE_TYPES

ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"
ALL_SYNCED_TYPES = RUN_TYPES | CYCLE_TYPES
PAGE_SIZE = 100


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


def sync_activities(access_token: str, full: bool = False) -> int:
    """
    Sync run and cycling activities from Strava.

    If *full* is False (default), stops as soon as it encounters an activity
    already in the database — fast incremental sync.

    If *full* is True, re-fetches every page and upserts everything — use this
    to backfill or fix gaps.

    Returns the number of new/updated activities written.
    """
    stored_ids = get_stored_ids()
    count = 0

    for activity in _iter_activities(access_token):
        sport = activity.get("sport_type") or activity.get("type", "")
        if sport not in ALL_SYNCED_TYPES:
            continue

        if not full and activity["id"] in stored_ids:
            # In incremental mode, once we hit a known activity we're up-to-date
            break

        upsert_activity(activity)
        count += 1

    return count
