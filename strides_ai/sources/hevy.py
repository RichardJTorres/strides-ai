"""HEVY data source — weightlifting workouts."""

import json

from ..config import get_settings
from ..hevy_analysis import lifting_deep_dive_system_prompt
from ..hevy_sync import sync_exercise_templates, sync_hevy_workouts
from ..units import DEFAULT_UNIT_SYSTEM, Quantity, UnitSystem, format_value
from .base import ConfigurationError, NoDataError


class HevySource:
    """DataSource implementation backed by HEVY."""

    source_name = "hevy"

    def is_configured(self) -> bool:
        return bool(get_settings().hevy_api_key)

    def build_deep_dive_content(
        self, activity, backend, units: UnitSystem = DEFAULT_UNIT_SYSTEM
    ) -> tuple[str, str]:
        if not activity.exercises_json:
            raise NoDataError("No exercise data available for this session")

        try:
            exercises = json.loads(activity.exercises_json)
        except Exception as exc:
            raise ValueError("Could not parse exercise data") from exc

        lines = [f"Workout: {activity.name or 'Weight Training'}  |  Date: {activity.date}"]
        if activity.total_volume_kg:
            lines.append(
                f"Total volume: {activity.measurement('total_volume_kg', units).formatted}"
                f"  |  Sets: {activity.total_sets or '?'}"
            )
        lines.append("")
        for ex in exercises:
            lines.append(f"### {ex.get('title') or ex.get('name', 'Exercise')}")
            for s in ex.get("sets", []):
                weight = (
                    format_value(s["weight_kg"], Quantity.MASS, units, decimals=1)
                    if s.get("weight_kg") is not None
                    else "BW"
                )
                reps = f"x{s['reps']}" if s.get("reps") is not None else ""
                rpe = f"  RPE {s['rpe']}" if s.get("rpe") is not None else ""
                stype = f"[{s['type']}]" if s.get("type") and s["type"] != "normal" else ""
                lines.append(f"  {stype} {weight} {reps}{rpe}".strip())
            lines.append("")

        return lifting_deep_dive_system_prompt(units), "\n".join(lines)

    def sync(self, full: bool = False) -> int:
        settings = get_settings()
        if not settings.hevy_api_key:
            raise ConfigurationError("HEVY_API_KEY not configured")
        return sync_hevy_workouts(full=full)

    def sync_templates(self) -> int:
        settings = get_settings()
        if not settings.hevy_api_key:
            raise ConfigurationError("HEVY_API_KEY not configured")
        return sync_exercise_templates()
