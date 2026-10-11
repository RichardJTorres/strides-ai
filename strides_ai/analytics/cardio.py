"""Pure cardio metric functions: list[CardioAnalyticsActivity] -> ChartDataset.

No DB access, provider parsing, or UI colors. Sport groupings come from the canonical taxonomy.

Every function takes `today: date` explicitly — never calls date.today() itself — so results are
fully deterministic in tests.
"""

import math
from collections import defaultdict
from datetime import date, timedelta

from ..activity_types import CYCLE_TYPES, RUN_TYPES
from .aggregation import (
    monday_of,
    pace_fade_to_unit,
    to_distance_unit,
    to_elevation_unit,
    to_hours,
    to_pace_unit,
    trailing_date_rolling_avg,
    trailing_weekly_rolling_avg,
    week_range,
)
from .models import (
    AtlCtlDataset,
    AtlCtlPoint,
    CardioAnalyticsActivity,
    RollingAvgPoint,
    ScatterPoint,
    ScatterTrendDataset,
    StackedBarDataset,
    StackedBarPoint,
    TimeSeriesDataset,
    TimeSeriesPoint,
    UnavailableReason,
    WeeklyBarDataset,
    WeeklyBarPoint,
)

WEEKLY_ROLLING_WINDOW = 4
ATL_TIME_CONSTANT_DAYS = 7
CTL_TIME_CONSTANT_DAYS = 42
AEROBIC_EFFICIENCY_MIN_QUALIFYING = 10
AEROBIC_EFFICIENCY_HR_LOW, AEROBIC_EFFICIENCY_HR_HIGH = 120, 155
HR_ZONE_MIN_QUALIFYING_WEEKS = 3
HR_ZONE_LABELS = ("Z1", "Z2", "Z3", "Z4", "Z5")
PER_ACTIVITY_TREND_MIN_QUALIFYING = 5
TREND_WINDOW_DAYS = 28


def _unit_label(unit: str) -> str:
    return "mi" if unit == "miles" else "km"


def _elevation_unit_label(unit: str) -> str:
    return "ft" if unit == "miles" else "m"


def _qualify_reason(total: int, qualifying: int) -> UnavailableReason:
    if total == 0:
        return UnavailableReason.NO_ACTIVITIES
    if qualifying == 0:
        return UnavailableReason.MISSING_REQUIRED_FIELD
    return UnavailableReason.INSUFFICIENT_QUALIFYING_COUNT


# ── Weekly distance (ported from charts_data.compute_weekly_mileage) ───────────


def compute_weekly_distance(
    activities: list[CardioAnalyticsActivity], unit: str, today: date
) -> WeeklyBarDataset:
    weekly: dict[date, float] = defaultdict(float)
    for a in activities:
        weekly[monday_of(a.date)] += to_distance_unit(a.distance_m, unit)

    base = dict(
        id="weekly_distance",
        metric_key="weekly_distance",
        title="Weekly Distance",
        unit=_unit_label(unit),
    )
    if not weekly:
        return WeeklyBarDataset(
            **base,
            available=False,
            unavailable_reason=UnavailableReason.NO_ACTIVITIES,
            qualifying_count=0,
            total_count=0,
            data=[],
        )

    current_week = monday_of(today)
    weeks = week_range(min(weekly), current_week)
    rolling = trailing_weekly_rolling_avg(weeks, weekly, WEEKLY_ROLLING_WINDOW)
    data = [
        WeeklyBarPoint(
            week=w.isoformat(),
            value=round(weekly.get(w, 0.0), 2),
            rolling_avg=round(rolling[w], 2),
            is_current=(w == current_week),
        )
        for w in weeks
    ]
    return WeeklyBarDataset(
        **base,
        available=True,
        qualifying_count=len(activities),
        total_count=len(activities),
        data=data,
    )


# ── ATL / CTL (ported from charts_data.compute_atl_ctl, unchanged math) ────────


def compute_atl_ctl(
    activities: list[CardioAnalyticsActivity], unit: str, today: date
) -> AtlCtlDataset:
    base = dict(
        id="atl_ctl",
        metric_key="atl_ctl",
        title="Training Load — ATL / CTL",
        unit=_unit_label(unit),
    )
    if not activities:
        return AtlCtlDataset(
            **base,
            available=False,
            unavailable_reason=UnavailableReason.NO_ACTIVITIES,
            qualifying_count=0,
            total_count=0,
            data=[],
        )

    daily: dict[date, float] = defaultdict(float)
    for a in activities:
        daily[a.date] += to_distance_unit(a.distance_m, unit)

    alpha_atl = 1 - math.exp(-1 / ATL_TIME_CONSTANT_DAYS)
    alpha_ctl = 1 - math.exp(-1 / CTL_TIME_CONSTANT_DAYS)
    atl = ctl = 0.0
    data = []
    cur = min(daily)
    while cur <= today:
        load = daily.get(cur, 0.0)
        atl += alpha_atl * (load - atl)
        ctl += alpha_ctl * (load - ctl)
        ratio = round(atl / ctl, 3) if ctl > 1e-3 else None
        data.append(
            AtlCtlPoint(date=cur.isoformat(), atl=round(atl, 3), ctl=round(ctl, 3), ratio=ratio)
        )
        cur += timedelta(days=1)

    return AtlCtlDataset(
        **base,
        available=True,
        qualifying_count=len(activities),
        total_count=len(activities),
        data=data,
    )


# ── Aerobic efficiency (ported, formula UNCHANGED — verified correctly oriented) ─


def compute_aerobic_efficiency(
    activities: list[CardioAnalyticsActivity], unit: str, today: date
) -> ScatterTrendDataset:
    ul = _unit_label(unit)
    qualifying = []
    for a in activities:
        if not a.avg_hr or not (
            AEROBIC_EFFICIENCY_HR_LOW <= a.avg_hr <= AEROBIC_EFFICIENCY_HR_HIGH
        ):
            continue
        if not a.avg_pace_s_per_km:
            continue
        pace_s = to_pace_unit(a.avg_pace_s_per_km, unit)
        if pace_s <= 0:
            continue
        eff = (3600.0 / pace_s) / a.avg_hr * 100.0
        qualifying.append(
            {
                "date": a.date,
                "value": round(eff, 3),
                "name": a.name or "",
                "hr": round(a.avg_hr, 1),
                "pace_s": round(pace_s),
            }
        )
    qualifying.sort(key=lambda x: x["date"])
    n = len(qualifying)

    base = dict(
        id="aerobic_efficiency",
        metric_key="aerobic_efficiency",
        title="Aerobic Efficiency",
        unit=f"{ul}/hr per bpm",
    )
    if n < AEROBIC_EFFICIENCY_MIN_QUALIFYING:
        return ScatterTrendDataset(
            **base,
            available=False,
            unavailable_reason=_qualify_reason(len(activities), n),
            qualifying_count=n,
            total_count=len(activities),
            scatter=[],
            rolling_avg=[],
            improving=False,
        )

    points = [(q["date"], q["value"]) for q in qualifying]
    rolling_values = trailing_date_rolling_avg(points, TREND_WINDOW_DAYS)
    rolling_avg = [
        RollingAvgPoint(date=q["date"].isoformat(), avg=round(r, 3))
        for q, r in zip(qualifying, rolling_values)
    ]
    scatter = [
        ScatterPoint(
            date=q["date"].isoformat(),
            value=q["value"],
            name=q["name"],
            hr=q["hr"],
            pace_s=q["pace_s"],
            ul=ul,
        )
        for q in qualifying
    ]

    last_4wk = [v for d, v in points if d >= today - timedelta(days=28)]
    prev_4wk = [
        v for d, v in points if today - timedelta(days=56) <= d < today - timedelta(days=28)
    ]
    improving = (
        len(last_4wk) >= 2
        and len(prev_4wk) >= 2
        and (sum(last_4wk) / len(last_4wk)) > (sum(prev_4wk) / len(prev_4wk))
    )

    return ScatterTrendDataset(
        **base,
        available=True,
        qualifying_count=n,
        total_count=len(activities),
        scatter=scatter,
        rolling_avg=rolling_avg,
        improving=improving,
    )


# ── HR zone distribution trend (new) ────────────────────────────────────────────


def compute_hr_zone_trend(
    activities: list[CardioAnalyticsActivity], unit: str, today: date
) -> StackedBarDataset:
    weighted_sum: dict[date, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    weighted_duration: dict[date, float] = defaultdict(float)
    qualifying_weeks: set[date] = set()
    qualifying_count = 0

    for a in activities:
        if a.hr_zone_pct is None:
            continue
        if not a.moving_time_s or a.moving_time_s <= 0:
            continue
        qualifying_count += 1
        week = monday_of(a.date)
        qualifying_weeks.add(week)
        weighted_duration[week] += a.moving_time_s
        for zone in HR_ZONE_LABELS:
            weighted_sum[week][zone] += a.hr_zone_pct[zone] * a.moving_time_s

    base = dict(
        id="hr_zone_trend",
        metric_key="hr_zone_trend",
        title="HR Zone Distribution",
        unit="%",
        count_unit="weeks",
    )
    if len(qualifying_weeks) < HR_ZONE_MIN_QUALIFYING_WEEKS:
        return StackedBarDataset(
            **base,
            available=False,
            unavailable_reason=_qualify_reason(len(activities), qualifying_count),
            qualifying_count=len(qualifying_weeks),
            total_count=None,
            data=[],
            categories=list(HR_ZONE_LABELS),
        )

    current_week = monday_of(today)
    data = [
        StackedBarPoint(
            week=w.isoformat(),
            is_current=(w == current_week),
            values={
                zone: round(weighted_sum[w][zone] / weighted_duration[w], 2)
                for zone in HR_ZONE_LABELS
            },
        )
        for w in sorted(qualifying_weeks)
    ]
    return StackedBarDataset(
        **base,
        available=True,
        qualifying_count=len(qualifying_weeks),
        total_count=None,
        data=data,
        categories=list(HR_ZONE_LABELS),
    )


# ── Per-activity trend metrics (new): decoupling, cadence, pace fade ───────────


def _per_activity_trend(
    activities: list[CardioAnalyticsActivity],
    today: date,
    *,
    metric_key: str,
    title: str,
    unit: str,
    extract,
) -> TimeSeriesDataset:
    points: list[tuple[date, float]] = []
    for a in activities:
        v = extract(a)
        if v is None:
            continue
        points.append((a.date, v))
    points.sort(key=lambda p: p[0])
    qualifying_count = len(points)

    base = dict(id=metric_key, metric_key=metric_key, title=title, unit=unit)
    if qualifying_count < PER_ACTIVITY_TREND_MIN_QUALIFYING:
        return TimeSeriesDataset(
            **base,
            available=False,
            unavailable_reason=_qualify_reason(len(activities), qualifying_count),
            qualifying_count=qualifying_count,
            total_count=len(activities),
            data=[],
        )

    rolling = trailing_date_rolling_avg(points, TREND_WINDOW_DAYS)
    data = [
        TimeSeriesPoint(date=d.isoformat(), value=round(v, 3), rolling_avg=round(r, 3))
        for (d, v), r in zip(points, rolling)
    ]
    return TimeSeriesDataset(
        **base,
        available=True,
        qualifying_count=qualifying_count,
        total_count=len(activities),
        data=data,
    )


def compute_cardiac_decoupling_trend(
    activities: list[CardioAnalyticsActivity], unit: str, today: date
) -> TimeSeriesDataset:
    return _per_activity_trend(
        activities,
        today,
        metric_key="cardiac_decoupling_trend",
        title="Cardiac Decoupling Trend",
        unit="%",
        extract=lambda a: a.cardiac_decoupling_pct,
    )


def compute_cadence_trend(
    activities: list[CardioAnalyticsActivity], unit: str, today: date
) -> TimeSeriesDataset:
    return _per_activity_trend(
        activities,
        today,
        metric_key="cadence_trend",
        title="Cadence Trend",
        unit="spm",
        extract=lambda a: a.avg_cadence if a.avg_cadence and a.avg_cadence > 0 else None,
    )


def compute_pace_fade_trend(
    activities: list[CardioAnalyticsActivity], unit: str, today: date
) -> TimeSeriesDataset:
    return _per_activity_trend(
        activities,
        today,
        metric_key="pace_fade_trend",
        title="Pace Fade Trend",
        unit=f"sec/{_unit_label(unit)}",
        extract=lambda a: (
            pace_fade_to_unit(a.pace_fade_seconds, unit)
            if a.pace_fade_seconds is not None
            else None
        ),
    )


# ── Weekly elevation (new, cycling-only) ────────────────────────────────────────


def compute_weekly_elevation(
    activities: list[CardioAnalyticsActivity], unit: str, today: date
) -> WeeklyBarDataset:
    weekly: dict[date, float] = defaultdict(float)
    for a in activities:
        weekly[monday_of(a.date)] += to_elevation_unit(a.elevation_gain_m, unit)

    base = dict(
        id="weekly_elevation",
        metric_key="weekly_elevation",
        title="Weekly Climbing",
        unit=_elevation_unit_label(unit),
    )
    if not weekly:
        return WeeklyBarDataset(
            **base,
            available=False,
            unavailable_reason=UnavailableReason.NO_ACTIVITIES,
            qualifying_count=0,
            total_count=0,
            data=[],
        )

    current_week = monday_of(today)
    weeks = week_range(min(weekly), current_week)
    rolling = trailing_weekly_rolling_avg(weeks, weekly, WEEKLY_ROLLING_WINDOW)
    data = [
        WeeklyBarPoint(
            week=w.isoformat(),
            value=round(weekly.get(w, 0.0), 1),
            rolling_avg=round(rolling[w], 1),
            is_current=(w == current_week),
        )
        for w in weeks
    ]
    return WeeklyBarDataset(
        **base,
        available=True,
        qualifying_count=len(activities),
        total_count=len(activities),
        data=data,
    )


# ── Training time allocation (new, hybrid-only; self-partitions run/ride) ──────


def compute_training_time_allocation(
    activities: list[CardioAnalyticsActivity], unit: str, today: date
) -> StackedBarDataset:
    weekly_run: dict[date, float] = defaultdict(float)
    weekly_ride: dict[date, float] = defaultdict(float)
    weeks_seen: set[date] = set()

    for a in activities:
        week = monday_of(a.date)
        hours = to_hours(a.moving_time_s)
        if a.sport_type in RUN_TYPES:
            weekly_run[week] += hours
            weeks_seen.add(week)
        elif a.sport_type in CYCLE_TYPES:
            weekly_ride[week] += hours
            weeks_seen.add(week)

    base = dict(
        id="training_time_allocation",
        metric_key="training_time_allocation",
        title="Training Time Allocation",
        unit="hours",
    )
    if not weeks_seen:
        return StackedBarDataset(
            **base,
            available=False,
            unavailable_reason=UnavailableReason.NO_ACTIVITIES,
            qualifying_count=0,
            total_count=0,
            data=[],
            categories=["Run", "Ride"],
        )

    current_week = monday_of(today)
    weeks = week_range(min(weeks_seen), current_week)
    data = [
        StackedBarPoint(
            week=w.isoformat(),
            is_current=(w == current_week),
            values={
                "Run": round(weekly_run.get(w, 0.0), 2),
                "Ride": round(weekly_ride.get(w, 0.0), 2),
            },
        )
        for w in weeks
    ]
    return StackedBarDataset(
        **base,
        available=True,
        qualifying_count=len(activities),
        total_count=len(activities),
        data=data,
        categories=["Run", "Ride"],
    )
