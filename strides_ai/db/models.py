"""SQLModel table definitions."""

from typing import Any, ClassVar, Optional

import sqlalchemy as sa
from sqlmodel import Column, Field, SQLModel

# Re-export groupings for existing callers; the canonical taxonomy is source-independent.
from ..activity_types import CYCLE_TYPES, LIFT_TYPES, RUN_TYPES, SportType
from ..units import Measurement, Quantity, UnitSystem, measure

# field name -> (quantity, scale from the stored value to the quantity's canonical SI unit)
MeasurementSpec = dict[str, tuple[Quantity, float]]


class MeasuredModel:
    """Mixin for models that store measurements.

    Each subclass declares ``__measurements__`` so its own fields say what unit they hold.
    The helpers work on model instances and, via the classmethods, on plain row dicts (the
    coach formatters pass ``model_dump()`` dicts around).
    """

    __measurements__: ClassVar[MeasurementSpec] = {}

    @classmethod
    def measure_field(
        cls, row: dict[str, Any], field: str, system: UnitSystem
    ) -> Measurement | None:
        qty, scale = cls.__measurements__[field]
        return measure(row.get(field), qty, system, scale=scale)

    @classmethod
    def measure_row(cls, row: dict[str, Any], system: UnitSystem) -> dict[str, Measurement]:
        return {
            f: m
            for f in cls.__measurements__
            if (m := cls.measure_field(row, f, system)) is not None
        }

    def measurement(self, field: str, system: UnitSystem) -> Measurement | None:
        return self.measure_field({field: getattr(self, field)}, field, system)

    def measurements(self, system: UnitSystem) -> dict[str, Measurement]:
        return self.measure_row({f: getattr(self, f) for f in self.__measurements__}, system)


class Activity(MeasuredModel, SQLModel, table=True):
    __tablename__ = "activities"
    __measurements__: ClassVar[MeasurementSpec] = {
        "distance_m": (Quantity.DISTANCE, 1.0),
        "elevation_gain_m": (Quantity.ELEVATION, 1.0),
        "avg_pace_s_per_km": (Quantity.PACE, 1.0),
        "pace_fade_s_per_km": (Quantity.PACE_DELTA, 1.0),
        "climb_m_per_km": (Quantity.CLIMB_RATE, 1.0),
        "total_volume_kg": (Quantity.MASS, 1.0),
    }

    id: int = Field(primary_key=True)
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
    sport_type: Optional[str] = None
    source: Optional[str] = None
    raw_json: Optional[str] = None

    # Analysis columns (populated by analysis pipeline)
    cardiac_decoupling_pct: Optional[float] = None
    hr_zone_1_pct: Optional[float] = None
    hr_zone_2_pct: Optional[float] = None
    hr_zone_3_pct: Optional[float] = None
    hr_zone_4_pct: Optional[float] = None
    hr_zone_5_pct: Optional[float] = None
    pace_fade_s_per_km: Optional[float] = None
    cadence_std_dev: Optional[float] = None
    effort_efficiency_raw: Optional[float] = None
    effort_efficiency_score: Optional[float] = None
    climb_m_per_km: Optional[float] = None
    high_elevation_flag: Optional[int] = None
    suffer_score_mismatch_flag: Optional[int] = None
    analysis_summary: Optional[str] = None
    deep_dive_report: Optional[str] = None
    deep_dive_completed_at: Optional[str] = None
    deep_dive_model: Optional[str] = None
    analysis_status: Optional[str] = None
    user_notes: Optional[str] = None

    # HEVY (weightlifting) columns
    external_id: Optional[str] = None
    exercises_json: Optional[str] = None
    total_volume_kg: Optional[float] = None
    total_sets: Optional[int] = None


class Conversation(SQLModel, table=True):
    __tablename__ = "conversations"

    id: Optional[int] = Field(default=None, primary_key=True)
    role: str
    content: str
    mode: str = Field(default="running")
    model: Optional[str] = None
    created_at: Optional[str] = Field(
        default=None,
        sa_column=Column(sa.Text, server_default=sa.text("datetime('now')")),
    )


class Memory(SQLModel, table=True):
    __tablename__ = "memories"

    id: Optional[int] = Field(default=None, primary_key=True)
    category: str
    content: str = Field(sa_column=Column(sa.Text, unique=True, nullable=False))
    status: str = "current"
    topic: Optional[str] = None
    effective_from: Optional[str] = None
    effective_until: Optional[str] = None
    created_at: Optional[str] = Field(
        default=None,
        sa_column=Column(sa.Text, server_default=sa.text("datetime('now')")),
    )


class Setting(SQLModel, table=True):
    __tablename__ = "settings"

    key: str = Field(primary_key=True)
    value: str


class Profile(SQLModel, table=True):
    __tablename__ = "profiles"

    mode: str = Field(primary_key=True)
    fields_json: str
    updated_at: Optional[str] = Field(
        default=None,
        sa_column=Column(sa.Text, server_default=sa.text("datetime('now')")),
    )


class CalendarPref(SQLModel, table=True):
    __tablename__ = "calendar_prefs"

    id: int = Field(
        default=1,
        sa_column=Column(sa.Integer, sa.CheckConstraint("id = 1"), primary_key=True),
    )
    rest_days: str = Field(
        default="[]",
        sa_column=Column(sa.Text, nullable=False, server_default="'[]'"),
    )
    long_run_days: str = Field(
        default="[]",
        sa_column=Column(sa.Text, nullable=False, server_default="'[]'"),
    )
    frequency: int = Field(
        default=4,
        sa_column=Column(sa.Integer, nullable=False, server_default="4"),
    )
    blocked_days: str = Field(
        default="[]",
        sa_column=Column(sa.Text, nullable=False, server_default="'[]'"),
    )
    races: str = Field(
        default="[]",
        sa_column=Column(sa.Text, nullable=False, server_default="'[]'"),
    )


class TrainingPlan(MeasuredModel, SQLModel, table=True):
    __tablename__ = "training_plan"
    __measurements__: ClassVar[MeasurementSpec] = {
        "distance_km": (Quantity.DISTANCE, 1000.0),
        "elevation_m": (Quantity.ELEVATION, 1.0),
    }

    date: str = Field(primary_key=True)
    workout_type: Optional[str] = None
    description: Optional[str] = None
    distance_km: Optional[float] = None
    elevation_m: Optional[float] = None
    duration_min: Optional[int] = None
    intensity: Optional[str] = None
    nutrition_json: Optional[str] = None
    route_url: Optional[str] = None
    route_analysis_json: Optional[str] = None
    route_analyzed_at: Optional[str] = None
    route_analysis_model: Optional[str] = None
    structure_json: Optional[str] = None
    created_at: Optional[str] = Field(
        default=None,
        sa_column=Column(sa.Text, server_default=sa.text("datetime('now')")),
    )


class ExerciseTemplate(SQLModel, table=True):
    """HEVY exercise template metadata (cached locally).

    Workouts only carry ``exercise_template_id``; the muscle group lives on
    the template. Refreshable via /api/hevy/templates/sync.
    """

    __tablename__ = "exercise_templates"

    id: str = Field(primary_key=True)  # HEVY template UUID/hex string
    title: Optional[str] = None
    type: Optional[str] = None
    primary_muscle_group: Optional[str] = None
    secondary_muscle_groups: Optional[str] = None  # JSON-encoded list
    is_custom: Optional[int] = None
    updated_at: Optional[str] = Field(
        default=None,
        sa_column=Column(sa.Text, server_default=sa.text("datetime('now')")),
    )
