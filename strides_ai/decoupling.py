"""When a stored cardiac-decoupling value is a valid drift signal, and when it is not.

Decoupling here is the change in HR per unit of *speed* between the two halves of an activity
(`analysis._cardiac_decoupling`). It only measures cardiovascular drift when speed tracks effort:

- **Cycling** (including Zwift): speed is set by grade, wind, drafting and coasting, not by
  effort, and on Zwift by the virtual gradient. On this athlete's data the value spans -21% to
  +192% even on flat outdoor rides, so a power-based measure is needed before it means anything.
- **Hilly runs**: a climb-then-descend profile changes speed at constant effort, so the value
  reflects the course. Same threshold as the "Hilly course" flag in the analysis summary.
- **Short activities**: too little time for drift to exceed noise.

The check reads only stored columns, so it applies to historical rows without refetching streams.
Where a raw value remains stored, callers show "n/a" with the reason instead. Hilly-course
values are no longer computed, and migration 020 clears historical hilly values.

Effort efficiency (pace per heartbeat, `analysis._effort_efficiency_raw`) is speed-based for the
same reason and is gated by `efficiency_validity`: never on a ride (on this athlete's data, rides
got steeper and slower at the same heart rate while their capacity grew, so the score read as
decline), never on a hilly course. Duration does not matter for an average. Its 0-100 score is
min-max scaled over valid activities only (`db.activities.renormalize_effort_efficiency`).
"""

from .activity_types import CYCLE_TYPES
from .units import FEET_PER_METER, KM_PER_MILE

# Thresholds are stored in SI. Originally tuned in imperial, so each is the conversion of that
# original number.
HIGH_CLIMB_M_PER_KM = 100 / (FEET_PER_METER * KM_PER_MILE)  # 100 ft/mi
DECOUPLING_MIN_MOVING_S = 20 * 60

NA_LABELS = {
    "cycling": "speed-based drift is unreliable for cycling (grade, wind, coasting)",
    "hilly": "hilly course, so speed changes reflect terrain rather than heart-rate drift",
    "short": "under 20 minutes",
}


EFFICIENCY_NA_LABELS = {
    "cycling": "pace per heartbeat is unreliable for cycling (grade, wind, drafting set speed)",
    "hilly": "hilly course, so pace reflects terrain rather than fitness",
}


def _climb_m_per_km(row: dict) -> float | None:
    """The stored climb ratio, or (rows analysed before it was stored) one from the summary."""
    climb = row.get("climb_m_per_km")
    if climb is None:
        gain, metres = row.get("elevation_gain_m"), row.get("distance_m")
        if gain is not None and metres and metres > 0:
            climb = gain / (metres / 1000)
    return climb


def decoupling_validity(row: dict) -> tuple[bool, str | None]:
    """(True, None) when no exclusion is detected, else (False, reason).

    Passing does not establish a steady aerobic effort. Intervals, progressions and other
    changes in effort must be ruled out before interpreting this as aerobic fitness.

    `reason` is a key of `NA_LABELS`. A missing climb ratio (with no elevation and distance to
    derive it from) or moving time never invalidates a value on its own: no evidence against is
    not evidence of a problem.
    """
    if (row.get("sport_type") or "") in CYCLE_TYPES:
        return False, "cycling"
    moving_s = row.get("moving_time_s")
    if moving_s is not None and moving_s < DECOUPLING_MIN_MOVING_S:
        return False, "short"
    climb = _climb_m_per_km(row)
    if climb is not None and climb > HIGH_CLIMB_M_PER_KM:
        return False, "hilly"
    return True, None


def efficiency_validity(row: dict) -> tuple[bool, str | None]:
    """(True, None) when pace per heartbeat can mean anything for `row`, else (False, reason).

    `reason` is a key of `EFFICIENCY_NA_LABELS`. As for decoupling, a missing climb ratio never
    invalidates on its own.
    """
    if (row.get("sport_type") or "") in CYCLE_TYPES:
        return False, "cycling"
    climb = _climb_m_per_km(row)
    if climb is not None and climb > HIGH_CLIMB_M_PER_KM:
        return False, "hilly"
    return True, None


def gate_efficiency(row: dict) -> dict:
    """`row` with an invalid efficiency score replaced by None and `efficiency_na_reason` set.

    Only a row that has an efficiency value (raw or score) is gated; others return `row` itself.
    Never mutates its argument. The stored score is already NULL for invalid rows once
    `renormalize_effort_efficiency` has run; this also covers rows scored before that.
    """
    if row.get("effort_efficiency_score") is None and row.get("effort_efficiency_raw") is None:
        return row
    ok, reason = efficiency_validity(row)
    if ok:
        return row
    return {**row, "effort_efficiency_score": None, "efficiency_na_reason": reason}


def gate_decoupling(row: dict) -> dict:
    """`row` with an invalid decoupling value replaced by None and `decoupling_na_reason` set.

    A valid value, or no value at all, returns `row` itself. Never mutates its argument.
    """
    if row.get("cardiac_decoupling_pct") is None:
        return row
    ok, reason = decoupling_validity(row)
    if ok:
        return row
    return {**row, "cardiac_decoupling_pct": None, "decoupling_na_reason": reason}


def na_text(row: dict) -> str | None:
    """ "n/a (reason)" for a row whose stored value was gated, else None."""
    reason = row.get("decoupling_na_reason")
    return f"n/a ({NA_LABELS[reason]})" if reason in NA_LABELS else None
