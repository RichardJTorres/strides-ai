"""Typed models for the analytics layer.

CardioAnalyticsActivity is the source-independent analytics INPUT — normalized ingestion fields
(shared with activity_types.CardioActivity) plus derived analysis-pipeline fields, and nothing
persistence-specific (no id, raw_json, analysis_status, created_at, ...).

ChartDataset (a discriminated union) is the analytics OUTPUT and the API contract at the same
time — there is no separate conversion step between "what cardio.py computes" and "what the
router returns."
"""

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field

from ..activity_types import SportType


@dataclass
class CardioAnalyticsActivity:
    """Source-independent analytics input for running/cycling metrics."""

    source: str
    sport_type: SportType
    date: date
    name: Optional[str]
    moving_time_s: Optional[int]
    distance_m: Optional[float]
    elevation_gain_m: Optional[float]
    avg_pace_s_per_km: Optional[float]
    avg_hr: Optional[float]
    avg_cadence: Optional[float]
    hr_zone_pct: Optional[dict[str, float]]
    cardiac_decoupling_pct: Optional[float]
    pace_fade_seconds: Optional[float]  # stored unit: sec/mile, fixed by the analysis pipeline


class UnavailableReason(str, Enum):
    NO_ACTIVITIES = "no_activities"
    MISSING_REQUIRED_FIELD = "missing_required_field"
    INSUFFICIENT_QUALIFYING_COUNT = "insufficient_qualifying_count"


class ChartDatasetBase(BaseModel):
    id: str
    metric_key: str
    sport: Optional[Literal["run", "ride"]] = None
    title: str
    unit: Optional[str] = None
    available: bool
    unavailable_reason: Optional[UnavailableReason] = None
    qualifying_count: Optional[int] = None
    total_count: Optional[int] = None
    count_unit: Literal["activities", "weeks"] = "activities"


class WeeklyBarPoint(BaseModel):
    week: str
    value: float
    rolling_avg: float
    is_current: bool


class WeeklyBarDataset(ChartDatasetBase):
    chart_type: Literal["weekly_bar"] = "weekly_bar"
    data: list[WeeklyBarPoint]


class AtlCtlPoint(BaseModel):
    date: str
    atl: float
    ctl: float
    ratio: Optional[float]


class AtlCtlDataset(ChartDatasetBase):
    chart_type: Literal["atl_ctl"] = "atl_ctl"
    data: list[AtlCtlPoint]


class ScatterPoint(BaseModel):
    date: str
    value: float
    name: str
    hr: float
    pace_s: float
    ul: str  # unit label ("mi"/"km") — tooltip appends it to a formatted pace


class RollingAvgPoint(BaseModel):
    date: str
    avg: float


class ScatterTrendDataset(ChartDatasetBase):
    chart_type: Literal["scatter"] = "scatter"
    scatter: list[ScatterPoint]
    rolling_avg: list[RollingAvgPoint]
    improving: bool


class TimeSeriesPoint(BaseModel):
    date: str
    value: float
    rolling_avg: float


class TimeSeriesDataset(ChartDatasetBase):
    chart_type: Literal["time_series"] = "time_series"
    data: list[TimeSeriesPoint]


class StackedBarPoint(BaseModel):
    week: str
    is_current: bool
    values: dict[str, float]


class StackedBarDataset(ChartDatasetBase):
    chart_type: Literal["stacked_bar"] = "stacked_bar"
    data: list[StackedBarPoint]
    categories: list[str]


ChartDataset = Annotated[
    Union[
        WeeklyBarDataset,
        AtlCtlDataset,
        ScatterTrendDataset,
        TimeSeriesDataset,
        StackedBarDataset,
    ],
    Field(discriminator="chart_type"),
]
