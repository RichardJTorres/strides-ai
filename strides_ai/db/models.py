"""SQLModel table definitions."""

from typing import Optional

import sqlalchemy as sa
from sqlmodel import Column, Field, SQLModel

# Activity type sets — used by sync.py and query filters
RUN_TYPES = {"Run", "TrailRun", "VirtualRun"}
CYCLE_TYPES = {"Ride", "VirtualRide", "GravelRide"}


class Activity(SQLModel, table=True):
    __tablename__ = "activities"

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
    raw_json: Optional[str] = None

    # Analysis columns (populated by analysis pipeline)
    cardiac_decoupling_pct: Optional[float] = None
    hr_zone_1_pct: Optional[float] = None
    hr_zone_2_pct: Optional[float] = None
    hr_zone_3_pct: Optional[float] = None
    hr_zone_4_pct: Optional[float] = None
    hr_zone_5_pct: Optional[float] = None
    pace_fade_seconds: Optional[float] = None
    cadence_std_dev: Optional[float] = None
    effort_efficiency_raw: Optional[float] = None
    effort_efficiency_score: Optional[float] = None
    elevation_per_mile: Optional[float] = None
    high_elevation_flag: Optional[int] = None
    suffer_score_mismatch_flag: Optional[int] = None
    analysis_summary: Optional[str] = None
    deep_dive_report: Optional[str] = None
    deep_dive_completed_at: Optional[str] = None
    deep_dive_model: Optional[str] = None
    analysis_status: Optional[str] = None
    user_notes: Optional[str] = None


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


class TrainingPlan(SQLModel, table=True):
    __tablename__ = "training_plan"

    date: str = Field(primary_key=True)
    workout_type: Optional[str] = None
    description: Optional[str] = None
    distance_km: Optional[float] = None
    elevation_m: Optional[float] = None
    duration_min: Optional[int] = None
    intensity: Optional[str] = None
    nutrition_json: Optional[str] = None
    created_at: Optional[str] = Field(
        default=None,
        sa_column=Column(sa.Text, server_default=sa.text("datetime('now')")),
    )
