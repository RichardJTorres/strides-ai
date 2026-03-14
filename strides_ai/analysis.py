"""Run analysis pipeline — stream fetching, metric computation, NL summary, deep-dive."""

import logging
import statistics
from datetime import datetime, timezone

import httpx

from . import db

log = logging.getLogger(__name__)

STRAVA_STREAMS_URL = "https://www.strava.com/api/v3/activities/{id}/streams"
STREAM_KEYS = "time,heartrate,velocity_smooth,cadence,altitude,watts"

DEEP_DIVE_SYSTEM_PROMPT = (
    "You are analyzing a single training activity in detail. "
    "Stream data is sampled at 60-second intervals with key inflection points included. "
    "Analyze: pacing strategy, HR drift, cadence patterns, elevation impact, and fatigue signs. "
    "Be specific, cite elapsed times, and provide 3-5 actionable coaching notes in 4-6 paragraphs."
)


class RateLimitError(Exception):
    """Raised when Strava returns HTTP 429."""


# ── Stream fetching ───────────────────────────────────────────────────────────


def fetch_activity_streams(activity_id: int, access_token: str) -> dict[str, list]:
    """
    Fetch time-series streams for an activity from Strava.

    Returns a dict of stream_name -> list of values.
    Returns {} when the activity has no stream data (404).
    Raises RateLimitError on HTTP 429.
    """
    url = STRAVA_STREAMS_URL.format(id=activity_id)
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"keys": STREAM_KEYS, "key_by_type": "true"}

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.get(url, headers=headers, params=params)
    except Exception as exc:
        log.warning("stream fetch error for activity %s: %s", activity_id, exc)
        return {}

    if resp.status_code == 429:
        raise RateLimitError(f"Rate limited fetching streams for activity {activity_id}")

    if resp.status_code == 404:
        return {}

    if resp.status_code != 200:
        log.warning("stream fetch HTTP %s for activity %s", resp.status_code, activity_id)
        return {}

    raw = resp.json()
    # Strava returns key_by_type as a dict of stream_name -> {data: [...], ...}
    return {name: stream_obj["data"] for name, stream_obj in raw.items()}


# ── Metric helpers ────────────────────────────────────────────────────────────


def _cardiac_decoupling(hr: list, velocity: list) -> float | None:
    """
    Cardiac decoupling = ((second-half HR/velocity ratio - first-half ratio) / first-half ratio) * 100.
    Filters out samples where velocity < 0.5 m/s (stops/walking).
    """
    try:
        if not hr or not velocity or len(hr) != len(velocity):
            return None

        # Filter moving samples
        pairs = [(h, v) for h, v in zip(hr, velocity) if v is not None and v >= 0.5 and h]
        if len(pairs) < 10:
            return None

        mid = len(pairs) // 2
        first_half = pairs[:mid]
        second_half = pairs[mid:]

        ratio1 = statistics.mean(h / v for h, v in first_half)
        ratio2 = statistics.mean(h / v for h, v in second_half)

        if ratio1 == 0:
            return None

        return ((ratio2 - ratio1) / ratio1) * 100
    except Exception:
        return None


def _hr_zones(hr: list, max_hr: int) -> dict[str, float] | None:
    """
    Compute HR zone distribution as percentages.
    Zones: Z1 <60%, Z2 60-70%, Z3 70-80%, Z4 80-90%, Z5 >90% of max_hr.
    """
    try:
        valid = [h for h in hr if h and h > 0]
        if not valid:
            return None

        total = len(valid)
        counts = [0, 0, 0, 0, 0]

        for h in valid:
            pct = h / max_hr
            if pct < 0.60:
                counts[0] += 1
            elif pct < 0.70:
                counts[1] += 1
            elif pct < 0.80:
                counts[2] += 1
            elif pct < 0.90:
                counts[3] += 1
            else:
                counts[4] += 1

        return {
            "hr_zone_1_pct": round(counts[0] / total * 100, 2),
            "hr_zone_2_pct": round(counts[1] / total * 100, 2),
            "hr_zone_3_pct": round(counts[2] / total * 100, 2),
            "hr_zone_4_pct": round(counts[3] / total * 100, 2),
            "hr_zone_5_pct": round(counts[4] / total * 100, 2),
        }
    except Exception:
        return None


def _pace_fade_seconds(velocity: list) -> float | None:
    """
    Pace fade = last-third avg pace (s/mile) minus first-third avg pace (s/mile).
    Positive = slowing, negative = negative split.
    Filters near-zero velocity (< 0.5 m/s).
    """
    try:
        moving = [v for v in velocity if v is not None and v >= 0.5]
        if len(moving) < 9:
            return None

        third = len(moving) // 3
        first_third = moving[:third]
        last_third = moving[-third:]

        METERS_PER_MILE = 1609.34

        def avg_pace_s_per_mile(velocities: list) -> float:
            return statistics.mean(METERS_PER_MILE / v for v in velocities)

        return round(avg_pace_s_per_mile(last_third) - avg_pace_s_per_mile(first_third), 2)
    except Exception:
        return None


def _cadence_stats(cadence: list, is_run: bool) -> tuple[float | None, float | None]:
    """
    Compute mean and std dev of cadence.
    Doubles raw values for runs (Strava sends half-cadence for running).
    """
    try:
        multiplier = 2 if is_run else 1
        valid = [c * multiplier for c in cadence if c and c > 0]
        if not valid:
            return None, None
        mean = round(statistics.mean(valid), 2)
        std = round(statistics.stdev(valid), 2) if len(valid) >= 2 else None
        return mean, std
    except Exception:
        return None, None


def _effort_efficiency_raw(avg_pace_s_per_km: float | None, avg_hr: float | None) -> float | None:
    """
    Raw efficiency = avg_pace_s_per_km / avg_hr.
    Lower = more efficient (faster pace at lower HR).
    """
    try:
        if avg_pace_s_per_km is None or avg_hr is None or avg_hr <= 0:
            return None
        return round(avg_pace_s_per_km / avg_hr, 4)
    except Exception:
        return None


def _elevation_metrics(altitude: list, distance_m: float) -> tuple[float | None, int | None]:
    """
    Compute elevation gain per mile (ft/mile) and high-elevation flag.
    Elevation gain = sum of positive altitude deltas.
    """
    try:
        if not altitude or distance_m <= 0:
            return None, None

        gain_m = sum(max(0, altitude[i] - altitude[i - 1]) for i in range(1, len(altitude)))
        gain_ft = gain_m * 3.28084
        distance_miles = distance_m / 1609.34
        per_mile = round(gain_ft / distance_miles, 2)
        flag = 1 if per_mile > 100 else 0
        return per_mile, flag
    except Exception:
        return None, None


def _suffer_mismatch(
    suffer_score: int | None, z4_pct: float | None, z5_pct: float | None
) -> int | None:
    """
    Flag potential HR data unreliability by comparing suffer score to Z4+Z5 time.
    """
    try:
        if suffer_score is None or z4_pct is None or z5_pct is None:
            return None
        high_intensity_pct = (z4_pct + z5_pct) / 100
        if suffer_score > 50 and high_intensity_pct < 0.15:
            return 1
        if suffer_score < 20 and high_intensity_pct > 0.30:
            return 1
        return 0
    except Exception:
        return None


# ── Metric computation ────────────────────────────────────────────────────────


def compute_metrics(streams: dict[str, list], activity: dict, max_hr: int = 190) -> dict:
    """
    Compute all derived metrics from stream data and the stored activity record.
    Returns a dict of column_name -> value ready for db.save_analysis().
    Each metric is computed independently; failures return None for that metric.
    """
    hr = streams.get("heartrate")
    velocity = streams.get("velocity_smooth")
    cadence = streams.get("cadence")
    altitude = streams.get("altitude")

    sport_type = activity.get("sport_type", "")
    is_run = sport_type in db.RUN_TYPES
    distance_m = activity.get("distance_m") or 0

    metrics: dict = {}

    # Cardiac decoupling
    metrics["cardiac_decoupling_pct"] = (
        _cardiac_decoupling(hr, velocity) if hr and velocity else None
    )

    # HR zones
    zones = _hr_zones(hr, max_hr) if hr else None
    if zones:
        metrics.update(zones)
    else:
        for z in range(1, 6):
            metrics[f"hr_zone_{z}_pct"] = None

    # Pace fade
    metrics["pace_fade_seconds"] = _pace_fade_seconds(velocity) if velocity else None

    # Cadence stats — note: key "avg_cadence" maps to existing DB column
    cadence_mean, cadence_std = _cadence_stats(cadence, is_run) if cadence else (None, None)
    metrics["avg_cadence"] = cadence_mean
    metrics["cadence_std_dev"] = cadence_std

    # Effort efficiency (uses stored values from activity record)
    metrics["effort_efficiency_raw"] = _effort_efficiency_raw(
        activity.get("avg_pace_s_per_km"), activity.get("avg_hr")
    )

    # Elevation
    elev_per_mile, elev_flag = (
        _elevation_metrics(altitude, distance_m) if altitude and distance_m else (None, None)
    )
    metrics["elevation_per_mile"] = elev_per_mile
    metrics["high_elevation_flag"] = elev_flag

    # Suffer score mismatch
    metrics["suffer_score_mismatch_flag"] = _suffer_mismatch(
        activity.get("suffer_score"),
        metrics.get("hr_zone_4_pct"),
        metrics.get("hr_zone_5_pct"),
    )

    return metrics


# ── Natural language summary ──────────────────────────────────────────────────


def build_analysis_summary(metrics: dict) -> str:
    """
    Generate a rule-based 1-3 sentence natural language summary of a run.
    Does not call any LLM.
    """
    parts = []

    # Lead with cardiac decoupling
    cd = metrics.get("cardiac_decoupling_pct")
    if cd is not None:
        if cd < 5:
            parts.append(f"Strong aerobic run — {cd:.1f}% cardiac decoupling.")
        elif cd < 10:
            parts.append(f"Moderate aerobic stress — {cd:.1f}% cardiac decoupling.")
        else:
            parts.append(f"High cardiac stress — {cd:.1f}% cardiac decoupling.")
    else:
        parts.append("Analysis limited — HR/velocity data unavailable.")

    # HR zone distribution
    z1 = metrics.get("hr_zone_1_pct")
    z2 = metrics.get("hr_zone_2_pct")
    z4 = metrics.get("hr_zone_4_pct")
    z5 = metrics.get("hr_zone_5_pct")

    if z1 is not None and z2 is not None:
        z12 = z1 + z2
        zones_available = [
            (1, z1),
            (2, z2),
            (3, metrics.get("hr_zone_3_pct") or 0),
            (4, z4 or 0),
            (5, z5 or 0),
        ]
        dominant = max(zones_available, key=lambda x: x[1])
        zone_msg = f"{z12:.0f}% time in Z1/Z2"
        if z4 is not None and z5 is not None and z4 + z5 > 30:
            zone_msg += f", {z4 + z5:.0f}% in Z4/Z5 (high intensity)"
        elif dominant[0] >= 3:
            zone_msg = f"Dominant effort Z{dominant[0]} ({dominant[1]:.0f}%)"
        parts.append(zone_msg + ".")

    # Pace fade
    pf = metrics.get("pace_fade_seconds")
    if pf is not None and abs(pf) > 15:
        if pf > 0:
            parts.append(f"Positive pace fade of {pf:.0f}s/mile in final third.")
        else:
            parts.append(f"Negative split — improved {abs(pf):.0f}s/mile in final third.")

    # Elevation
    if metrics.get("high_elevation_flag"):
        elev = metrics.get("elevation_per_mile")
        if elev is not None:
            parts.append(f"Hilly course ({elev:.0f} ft/mile elevation gain).")

    # Suffer score mismatch
    if metrics.get("suffer_score_mismatch_flag"):
        parts.append("Note: HR data may be unreliable for this run.")

    return " ".join(parts)


# ── Top-level orchestrator ────────────────────────────────────────────────────


def analyze_activity(activity: dict, access_token: str, max_hr: int = 190) -> str:
    """
    Fetch streams, compute metrics, generate summary, and persist to the DB.

    Returns:
        'done'    — analysis completed successfully
        'pending' — Strava rate limit hit; activity marked for retry
        'skipped' — no stream data available (manual entry)
        'error'   — unexpected failure
    """
    activity_id = activity["id"]

    try:
        streams = fetch_activity_streams(activity_id, access_token)
    except RateLimitError:
        log.warning("rate limited — marking activity %s as pending", activity_id)
        db.save_analysis(activity_id, {"analysis_status": "pending"})
        return "pending"
    except Exception as exc:
        log.error("stream fetch failed for activity %s: %s", activity_id, exc)
        db.save_analysis(activity_id, {"analysis_status": "error"})
        return "error"

    if not streams:
        db.save_analysis(
            activity_id,
            {
                "analysis_status": "skipped",
                "analysis_summary": "Manual activity — no stream data available.",
            },
        )
        return "skipped"

    try:
        metrics = compute_metrics(streams, activity, max_hr=max_hr)
        summary = build_analysis_summary(metrics)
        metrics["analysis_summary"] = summary
        metrics["analysis_status"] = "done"

        # Remove None values so we don't overwrite existing data with NULL
        metrics = {k: v for k, v in metrics.items() if v is not None}

        db.save_analysis(activity_id, metrics)
        db.renormalize_effort_efficiency()

        computed = [
            k
            for k, v in metrics.items()
            if v is not None and k not in ("analysis_status", "analysis_summary")
        ]
        log.info("activity %s analyzed — %d metrics computed", activity_id, len(computed))
        return "done"

    except Exception as exc:
        log.error("analysis failed for activity %s: %s", activity_id, exc, exc_info=True)
        db.save_analysis(activity_id, {"analysis_status": "error"})
        return "error"


# ── Deep-dive stream condensation ─────────────────────────────────────────────


def condense_streams_for_deep_dive(
    streams: dict[str, list], activity: dict, interval_s: int = 60
) -> str:
    """
    Format stream data as a compact text table for LLM deep-dive analysis.
    Downsamples to ~60s intervals plus inflection points where any metric
    changes by > 10% within a 2-minute window.
    Targets < 2000 tokens for Ollama compatibility.
    """
    time_stream = streams.get("time", [])
    hr_stream = streams.get("heartrate", [])
    velocity_stream = streams.get("velocity_smooth", [])
    cadence_stream = streams.get("cadence", [])
    altitude_stream = streams.get("altitude", [])

    n = len(time_stream)
    if n == 0:
        return "No stream data available."

    METERS_PER_MILE = 1609.34
    sport_type = activity.get("sport_type", "")
    is_run = sport_type in db.RUN_TYPES

    def safe_get(lst: list, i: int):
        return lst[i] if lst and i < len(lst) else None

    def fmt_pace(v):
        if v is None or v <= 0:
            return "—"
        pace_s = METERS_PER_MILE / v
        m, s = divmod(int(pace_s), 60)
        return f"{m}:{s:02d}/mi"

    def fmt_speed(v):
        if v is None or v <= 0:
            return "—"
        return f"{v * 3.6:.1f}km/h"

    def fmt_cadence(c):
        if c is None:
            return "—"
        val = c * 2 if is_run else c
        return str(int(val))

    # Build row indices: always include 60s-interval samples
    sample_indices = set()
    last_t = -interval_s
    for i, t in enumerate(time_stream):
        if t - last_t >= interval_s:
            sample_indices.add(i)
            last_t = t

    # Add inflection points — indices where HR or pace changes > 10% over 2-min window
    window = 120  # seconds
    for i in range(n):
        t_i = time_stream[i]
        # Find index ~2 minutes earlier
        j = i
        while j > 0 and time_stream[j] > t_i - window:
            j -= 1

        hr_i = safe_get(hr_stream, i)
        hr_j = safe_get(hr_stream, j)
        v_i = safe_get(velocity_stream, i)
        v_j = safe_get(velocity_stream, j)

        if hr_i and hr_j and hr_j > 0 and abs(hr_i - hr_j) / hr_j > 0.10:
            sample_indices.add(i)
        if v_i and v_j and v_j > 0 and abs(v_i - v_j) / v_j > 0.10:
            sample_indices.add(i)

    rows = sorted(sample_indices)

    # Build header
    pace_col = "PACE" if is_run else "SPEED"
    lines = [
        f"Activity: {activity.get('name', 'Unknown')} | {activity.get('date', '')} | "
        f"Distance: {(activity.get('distance_m') or 0) / 1609.34:.2f} mi",
        "",
        f"{'ELAPSED':>8} | {pace_col:>9} | {'HR':>5} | {'CAD':>5} | {'ALT(m)':>7}",
        "-" * 46,
    ]

    for i in rows:
        t = time_stream[i]
        elapsed = f"{t // 3600:02d}:{(t % 3600) // 60:02d}:{t % 60:02d}"
        v = safe_get(velocity_stream, i)
        hr = safe_get(hr_stream, i)
        cad = safe_get(cadence_stream, i)
        alt = safe_get(altitude_stream, i)

        pace_str = fmt_pace(v) if is_run else fmt_speed(v)
        hr_str = str(int(hr)) if hr else "—"
        cad_str = fmt_cadence(cad)
        alt_str = f"{alt:.0f}" if alt is not None else "—"

        lines.append(f"{elapsed:>8} | {pace_str:>9} | {hr_str:>5} | {cad_str:>5} | {alt_str:>7}")

    return "\n".join(lines)
