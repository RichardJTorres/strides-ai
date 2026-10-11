"""Mode -> explicit, ordered chart set.

Each ChartSpec.key becomes its dataset's `id` (unique per instance). Each compute function sets
its own constant `metric_key` internally (shared across sport-specific variants of the same
metric, e.g. both "run_aerobic_efficiency" and "ride_aerobic_efficiency" carry
metric_key="aerobic_efficiency") — that's what the frontend card registry looks up on, while
React list keys use the unique `id`.
"""

import dataclasses
from dataclasses import dataclass
from datetime import date
from typing import Callable, Optional

from ..activity_types import CYCLE_TYPES, RUN_TYPES
from . import cardio
from .adapters import to_cardio_analytics
from .models import CardioAnalyticsActivity, ChartDataset


@dataclass(frozen=True)
class ChartSpec:
    key: str
    compute: Callable[[list[CardioAnalyticsActivity], str, date], ChartDataset]
    sport_filter: Optional[Callable[[CardioAnalyticsActivity], bool]] = None
    sport: Optional[str] = None


def is_run(activity: CardioAnalyticsActivity) -> bool:
    return activity.sport_type in RUN_TYPES


def is_ride(activity: CardioAnalyticsActivity) -> bool:
    return activity.sport_type in CYCLE_TYPES


RUNNING_CHARTS: list[ChartSpec] = [
    ChartSpec("weekly_distance", cardio.compute_weekly_distance),
    ChartSpec("atl_ctl", cardio.compute_atl_ctl),
    ChartSpec("aerobic_efficiency", cardio.compute_aerobic_efficiency),
    ChartSpec("cadence_trend", cardio.compute_cadence_trend),
    ChartSpec("pace_fade_trend", cardio.compute_pace_fade_trend),
    ChartSpec("hr_zone_trend", cardio.compute_hr_zone_trend),
    ChartSpec("cardiac_decoupling_trend", cardio.compute_cardiac_decoupling_trend),
]

CYCLING_CHARTS: list[ChartSpec] = [
    ChartSpec("weekly_distance", cardio.compute_weekly_distance),
    ChartSpec("atl_ctl", cardio.compute_atl_ctl),
    ChartSpec("aerobic_efficiency", cardio.compute_aerobic_efficiency),
    ChartSpec("weekly_elevation", cardio.compute_weekly_elevation),
    ChartSpec("hr_zone_trend", cardio.compute_hr_zone_trend),
    ChartSpec("cardiac_decoupling_trend", cardio.compute_cardiac_decoupling_trend),
]

# Reused as the sport-filtered halves of HYBRID_CHARTS below.
RUN_SPECIFIC = RUNNING_CHARTS[2:]
RIDE_SPECIFIC = CYCLING_CHARTS[2:]

HYBRID_CHARTS: list[ChartSpec] = [
    ChartSpec("weekly_distance", cardio.compute_weekly_distance),  # combined, unfiltered
    ChartSpec("atl_ctl", cardio.compute_atl_ctl),  # combined, unfiltered
    *[
        dataclasses.replace(spec, key=f"run_{spec.key}", sport_filter=is_run, sport="run")
        for spec in RUN_SPECIFIC
    ],
    *[
        dataclasses.replace(spec, key=f"ride_{spec.key}", sport_filter=is_ride, sport="ride")
        for spec in RIDE_SPECIFIC
    ],
    ChartSpec("training_time_allocation", cardio.compute_training_time_allocation),
]

_CHARTS_BY_MODE: dict[str, list[ChartSpec]] = {
    "running": RUNNING_CHARTS,
    "cycling": CYCLING_CHARTS,
    "hybrid": HYBRID_CHARTS,
}


def get_chart_datasets(
    rows: list[dict], mode: str, unit: str, today: date | None = None
) -> list[ChartDataset]:
    """The single entry point: DB rows + mode + unit -> ordered, typed chart datasets."""
    resolved_today = today or date.today()
    activities = to_cardio_analytics(rows)
    specs = _CHARTS_BY_MODE.get(mode, RUNNING_CHARTS)

    # Partition once per distinct sport filter rather than once per chart.
    partitions = {None: activities}
    datasets: list[ChartDataset] = []
    for spec in specs:
        if spec.sport_filter not in partitions:
            partitions[spec.sport_filter] = [a for a in activities if spec.sport_filter(a)]
        filtered = partitions[spec.sport_filter]
        dataset = spec.compute(filtered, unit, resolved_today)
        sport = spec.sport or {"running": "run", "cycling": "ride"}.get(mode)
        dataset = dataset.model_copy(update={"id": spec.key, "sport": sport})
        datasets.append(dataset)
    return datasets
