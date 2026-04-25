"""Fetch workouts from HEVY and persist them locally."""

import json
import logging
from datetime import datetime, timezone

import httpx

from . import db
from .config import get_settings
from .hevy_analysis import analyze_hevy_workout

HEVY_API_BASE = "https://api.hevyapp.com"
PAGE_SIZE = 10  # HEVY max page size for workouts
TEMPLATE_PAGE_SIZE = 100  # HEVY max page size for /v1/exercise_templates

log = logging.getLogger(__name__)


def _get_headers() -> dict[str, str]:
    return {"api-key": get_settings().hevy_api_key}


def _parse_dt(iso: str | None) -> datetime | None:
    if not iso:
        return None
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _compute_volume(exercises: list[dict]) -> tuple[float, int]:
    """Return (total_volume_kg, total_sets) across all exercises."""
    volume = 0.0
    sets = 0
    for ex in exercises:
        for s in ex.get("sets", []):
            if s.get("type") == "warmup":
                continue
            sets += 1
            w = s.get("weight_kg") or 0.0
            r = s.get("reps") or 0
            volume += w * r
    return round(volume, 2), sets


def _transform_workout(w: dict) -> dict:
    """Map a HEVY workout dict → Activity-compatible row dict."""
    start = _parse_dt(w.get("start_time"))
    end = _parse_dt(w.get("end_time"))

    moving_time_s: int | None = None
    if start and end:
        moving_time_s = max(0, int((end - start).total_seconds()))

    exercises = w.get("exercises", [])
    total_volume_kg, total_sets = _compute_volume(exercises)

    # Use a stable integer ID derived from the HEVY UUID for the PK.
    # We take the last 9 hex digits of the UUID and parse as int.
    hevy_id: str = w["id"]
    numeric_id = int(hevy_id.replace("-", "")[-9:], 16)

    date_str = ""
    if start:
        date_str = start.astimezone(timezone.utc).strftime("%Y-%m-%d")

    return {
        "id": numeric_id,
        "hevy_workout_id": hevy_id,
        "name": w.get("title") or "Weight Training",
        "date": date_str,
        "moving_time_s": moving_time_s,
        "elapsed_time_s": moving_time_s,
        "perceived_exertion": None,
        "exercises_json": json.dumps(exercises),
        "total_volume_kg": total_volume_kg,
        "total_sets": total_sets,
        "raw_json": json.dumps(w),
    }


def _get_last_sync_timestamp() -> str | None:
    """Return the ISO timestamp of the most recent HEVY workout in the DB."""
    latest_date = db.get_latest_hevy_date()
    return latest_date


def sync_hevy_workouts(full: bool = False) -> int:
    """
    Sync weightlifting workouts from HEVY.

    If *full* is False (default), uses /v1/workouts/events?since=<last_sync>
    for an incremental update. If *full* is True, pages through all workouts.

    Also seeds the exercise-template cache on first sync (when the local
    table is empty), so the muscle-group chart can resolve template ids
    without requiring the user to click the manual refresh button first.

    Returns the number of new/updated workouts written.
    """
    settings = get_settings()
    if not settings.hevy_api_key:
        raise ValueError("HEVY_API_KEY not configured")

    headers = _get_headers()
    count = 0

    if db.get_exercise_template_count() == 0:
        try:
            sync_exercise_templates(headers=headers)
        except Exception as exc:
            log.warning("initial exercise-template sync failed: %s", exc)

    since = db.get_latest_hevy_date()
    if not full and since:
        count = _sync_events(headers, since)
    else:
        count = _sync_full(headers)

    return count


def sync_exercise_templates(headers: dict | None = None) -> int:
    """Page through /v1/exercise_templates and cache each row locally.

    Re-running upserts so renamed templates or changed muscle groups are
    refreshed. Custom templates added by the user in HEVY are picked up
    automatically since the endpoint returns them too.

    Returns the number of templates written.
    """
    settings = get_settings()
    if not settings.hevy_api_key:
        raise ValueError("HEVY_API_KEY not configured")

    if headers is None:
        headers = _get_headers()

    count = 0
    page = 1
    with httpx.Client(timeout=30) as client:
        while True:
            resp = client.get(
                f"{HEVY_API_BASE}/v1/exercise_templates",
                headers=headers,
                params={"page": page, "pageSize": TEMPLATE_PAGE_SIZE},
            )
            resp.raise_for_status()
            data = resp.json()
            templates = data.get("exercise_templates", [])
            if not templates:
                break

            for t in templates:
                if not t.get("id"):
                    continue
                db.upsert_exercise_template(t)
                count += 1

            if page >= data.get("page_count", 1):
                break
            page += 1

    log.info("synced %d HEVY exercise templates", count)
    return count


def _sync_events(headers: dict, since: str | None) -> int:
    """Incremental sync via /v1/workouts/events."""
    params: dict = {}
    if since:
        params["since"] = since

    count = 0
    with httpx.Client(timeout=30) as client:
        resp = client.get(f"{HEVY_API_BASE}/v1/workouts/events", headers=headers, params=params)
        if resp.status_code == 404:
            # Endpoint not available; fall back to full page sync
            log.info("events endpoint unavailable, falling back to full sync")
            return _sync_full(headers)
        resp.raise_for_status()
        data = resp.json()
        events = data.get("workouts", data.get("events", []))
        for event in events:
            workout = event.get("workout")
            if not workout:
                continue
            row = _transform_workout(workout)
            db.upsert_hevy_workout(row)
            analyze_hevy_workout(row)
            count += 1

    return count


def _sync_full(headers: dict) -> int:
    """Full paginated sync through all workouts."""
    count = 0
    page = 1

    with httpx.Client(timeout=30) as client:
        while True:
            resp = client.get(
                f"{HEVY_API_BASE}/v1/workouts",
                headers=headers,
                params={"page": page, "pageSize": PAGE_SIZE},
            )
            resp.raise_for_status()
            data = resp.json()
            workouts = data.get("workouts", [])
            if not workouts:
                break

            for w in workouts:
                row = _transform_workout(w)
                db.upsert_hevy_workout(row)
                analyze_hevy_workout(row)
                count += 1

            if page >= data.get("page_count", 1):
                break
            page += 1

    return count
