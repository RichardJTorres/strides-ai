"""Chart data computation: weekly mileage, ATL/CTL, and pace trends."""

import math
from collections import defaultdict
from datetime import date, timedelta

M_TO_MI = 0.000621371
M_TO_KM = 0.001


def _dist(distance_m: float, unit: str) -> float:
    return (distance_m or 0.0) * (M_TO_MI if unit == "miles" else M_TO_KM)


def _pace(avg_pace_s_per_km: float, unit: str) -> float:
    """Convert s/km → s/unit."""
    return avg_pace_s_per_km * (1.60934 if unit == "miles" else 1.0)


# ── Weekly mileage ────────────────────────────────────────────────────────────


def compute_weekly_mileage(activities: list[dict], unit: str) -> list[dict]:
    """Weekly totals (Mon–Sun) with 4-week trailing rolling average."""
    weekly: dict[date, float] = defaultdict(float)
    for act in activities:
        d = date.fromisoformat(act["date"])
        week_start = d - timedelta(days=d.weekday())  # Monday
        weekly[week_start] += _dist(act["distance_m"], unit)

    if not weekly:
        return []

    today = date.today()
    current_week = today - timedelta(days=today.weekday())

    # Fill every week from first run to current (including zero weeks)
    weeks: list[date] = []
    w = min(weekly)
    while w <= current_week:
        weeks.append(w)
        w += timedelta(weeks=1)

    result = []
    for i, w in enumerate(weeks):
        dist = weekly.get(w, 0.0)
        window = [weekly.get(weeks[j], 0.0) for j in range(max(0, i - 3), i + 1)]
        result.append(
            {
                "week": w.isoformat(),
                "distance": round(dist, 2),
                "rolling_avg": round(sum(window) / len(window), 2),
                "is_current": w == current_week,
            }
        )
    return result


# ── ATL / CTL ─────────────────────────────────────────────────────────────────


def compute_atl_ctl(activities: list[dict], unit: str) -> list[dict]:
    """Daily ATL (7-day EWA), CTL (42-day EWA), and their ratio."""
    if not activities:
        return []

    daily: dict[date, float] = defaultdict(float)
    for act in activities:
        daily[date.fromisoformat(act["date"])] += _dist(act["distance_m"], unit)

    alpha_atl = 1 - math.exp(-1 / 7)
    alpha_ctl = 1 - math.exp(-1 / 42)
    atl = ctl = 0.0

    result = []
    cur = min(daily)
    today = date.today()
    while cur <= today:
        load = daily.get(cur, 0.0)
        atl += alpha_atl * (load - atl)
        ctl += alpha_ctl * (load - ctl)
        ratio = round(atl / ctl, 3) if ctl > 1e-3 else None
        result.append(
            {
                "date": cur.isoformat(),
                "atl": round(atl, 3),
                "ctl": round(ctl, 3),
                "ratio": ratio,
            }
        )
        cur += timedelta(days=1)
    return result


# ── Aerobic efficiency ────────────────────────────────────────────────────────

MIN_QUALIFYING = 10
HR_LOW, HR_HIGH = 120, 155


def compute_aerobic_efficiency(activities: list[dict], unit: str) -> dict:
    """Aerobic efficiency = speed (unit/hr) / avg_HR × 100 for easy-effort runs.

    Filters to runs with avg HR between 120–155 bpm to exclude warm-ups,
    races, and HR sensor dropouts.  Higher value → fitter.
    """
    qualifying = []
    for act in activities:
        hr = act.get("avg_hr")
        if not hr or not (HR_LOW <= hr <= HR_HIGH):
            continue
        if not act.get("avg_pace_s_per_km"):
            continue
        pace_s = _pace(act["avg_pace_s_per_km"], unit)  # s/unit
        if pace_s <= 0:
            continue
        # efficiency: how fast per HR unit (higher = better)
        eff = (3600.0 / pace_s) / hr * 100.0
        qualifying.append(
            {
                "date": act["date"],
                "efficiency": round(eff, 3),
                "name": act.get("name") or "",
                "hr": round(hr, 1),
                "pace_s": round(pace_s),
            }
        )

    qualifying.sort(key=lambda x: x["date"])
    n = len(qualifying)

    if n < MIN_QUALIFYING:
        return {
            "has_enough_data": False,
            "qualifying_count": n,
            "scatter": qualifying,
            "rolling_avg": [],
            "improving": False,
        }

    # 4-week (28-day) rolling average at each qualifying run's date
    rolling_avg = []
    for pt in qualifying:
        d = date.fromisoformat(pt["date"])
        window_start = d - timedelta(days=27)
        window = [
            q["efficiency"]
            for q in qualifying
            if window_start <= date.fromisoformat(q["date"]) <= d
        ]
        rolling_avg.append(
            {
                "date": pt["date"],
                "avg": round(sum(window) / len(window), 3),
            }
        )

    # Improving: last 4 weeks avg vs previous 4 weeks avg
    today = date.today()
    last_4wk = [
        q["efficiency"]
        for q in qualifying
        if date.fromisoformat(q["date"]) >= today - timedelta(days=28)
    ]
    prev_4wk = [
        q["efficiency"]
        for q in qualifying
        if today - timedelta(days=56) <= date.fromisoformat(q["date"]) < today - timedelta(days=28)
    ]
    improving = (
        len(last_4wk) >= 2
        and len(prev_4wk) >= 2
        and (sum(last_4wk) / len(last_4wk)) > (sum(prev_4wk) / len(prev_4wk))
    )

    return {
        "has_enough_data": True,
        "qualifying_count": n,
        "scatter": qualifying,
        "rolling_avg": rolling_avg,
        "improving": improving,
    }


# ── Combined ──────────────────────────────────────────────────────────────────


def get_chart_data(activities, unit: str = "miles") -> dict:
    acts = [dict(a) for a in activities]
    return {
        "unit": unit,
        "weekly_mileage": compute_weekly_mileage(acts, unit),
        "atl_ctl": compute_atl_ctl(acts, unit),
        "aerobic_efficiency": compute_aerobic_efficiency(acts, unit),
    }
