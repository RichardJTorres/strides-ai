"""Canonical activity type definitions.

The application owns these models. Every data source sync function must
normalize its raw API data into one of these types before persisting.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SportType(str, Enum):
    """Known sport types across all data sources.

    Inherits from str so SQLAlchemy can store/compare the enum value as TEXT
    without any custom type adapter.
    """

    RUN = "Run"
    TRAIL_RUN = "TrailRun"
    VIRTUAL_RUN = "VirtualRun"
    RIDE = "Ride"
    VIRTUAL_RIDE = "VirtualRide"
    GRAVEL_RIDE = "GravelRide"
    WEIGHT_TRAINING = "WeightTraining"
    UNKNOWN = "Unknown"

    @classmethod
    def from_api(cls, value: str | None) -> "SportType":
        """Parse a raw API string into a SportType, falling back to UNKNOWN."""
        try:
            return cls(value)
        except (ValueError, TypeError):
            return cls.UNKNOWN


@dataclass
class CardioActivity:
    """Canonical model for running and cycling activities (Strava et al.)."""

    id: int
    source: str
    sport_type: Optional[SportType] = None
    name: Optional[str] = None
    date: Optional[str] = None
    distance_m: Optional[float] = None
    moving_time_s: Optional[int] = None
    elapsed_time_s: Optional[int] = None
    elevation_gain_m: Optional[float] = None
    avg_pace_s_per_km: Optional[float] = None
    avg_hr: Optional[float] = None
    max_hr: Optional[int] = None
    avg_cadence: Optional[float] = None
    suffer_score: Optional[int] = None
    perceived_exertion: Optional[float] = None
    raw_json: Optional[str] = None


@dataclass
class StrengthActivity:
    """Canonical model for weightlifting workouts (HEVY et al.)."""

    id: int
    source: str
    sport_type: SportType = field(default=SportType.WEIGHT_TRAINING)
    name: Optional[str] = None
    date: Optional[str] = None
    moving_time_s: Optional[int] = None
    elapsed_time_s: Optional[int] = None
    perceived_exertion: Optional[float] = None
    external_id: Optional[str] = None
    exercises_json: Optional[str] = None
    total_volume_kg: Optional[float] = None
    total_sets: Optional[int] = None
    raw_json: Optional[str] = None


CanonicalActivity = CardioActivity | StrengthActivity
