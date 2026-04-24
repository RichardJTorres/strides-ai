"""Analysis pipeline for HEVY (weightlifting) workouts."""

import json
import logging
from collections import defaultdict

log = logging.getLogger(__name__)

# Epley 1RM formula: weight * (1 + reps / 30)
# Only meaningful for sets with reps <= 12 (higher rep sets yield unreliable estimates)
_EPLEY_MAX_REPS = 12


def estimate_1rm(weight_kg: float, reps: int) -> float | None:
    """Epley 1RM estimate. Returns None for invalid inputs."""
    if weight_kg <= 0 or reps <= 0 or reps > _EPLEY_MAX_REPS:
        return None
    return round(weight_kg * (1 + reps / 30), 1)


def compute_hevy_metrics(exercises_json: str | None) -> dict:
    """
    Derive lifting metrics from the HEVY exercises JSON blob.

    Returns a dict suitable for passing to db.save_analysis():
      - total_volume_kg
      - total_sets
      - avg_rpe
      - estimated_1rms: {exercise_title: best_1rm_kg}
      - muscle_volume: {muscle_group: volume_kg}
      - analysis_summary: human-readable NL string
    """
    if not exercises_json:
        return {}

    try:
        exercises: list[dict] = json.loads(exercises_json)
    except (json.JSONDecodeError, TypeError):
        log.warning("could not parse exercises_json")
        return {}

    total_volume = 0.0
    total_sets = 0
    rpe_values: list[float] = []
    best_1rms: dict[str, float] = {}
    muscle_volume: dict[str, float] = defaultdict(float)

    exercise_summaries: list[str] = []

    for ex in exercises:
        title = ex.get("title", "Unknown")
        muscle = ex.get("primary_muscle_group") or "Unknown"
        working_sets = [s for s in ex.get("sets", []) if s.get("type") != "warmup"]

        ex_volume = 0.0
        ex_sets = 0

        for s in working_sets:
            weight = s.get("weight_kg") or 0.0
            reps = s.get("reps") or 0
            rpe = s.get("rpe")

            ex_volume += weight * reps
            ex_sets += 1

            if rpe is not None:
                rpe_values.append(float(rpe))

            one_rm = estimate_1rm(weight, reps)
            if one_rm is not None:
                if title not in best_1rms or one_rm > best_1rms[title]:
                    best_1rms[title] = one_rm

        total_volume += ex_volume
        total_sets += ex_sets
        muscle_volume[muscle] += ex_volume

        if ex_sets > 0:
            # Summarise as "Bench Press: 4×8 @ 80 kg"
            # Use the most common rep count for brevity
            all_reps = [s.get("reps") or 0 for s in working_sets]
            rep_str = str(all_reps[0]) if all_reps else "?"
            weight_vals = [s.get("weight_kg") or 0 for s in working_sets if s.get("weight_kg")]
            weight_str = f"{max(weight_vals):.1f} kg" if weight_vals else "BW"
            exercise_summaries.append(f"{title}: {ex_sets}×{rep_str} @ {weight_str}")

    avg_rpe = round(sum(rpe_values) / len(rpe_values), 1) if rpe_values else None

    # Build NL summary
    parts: list[str] = []
    if exercise_summaries:
        parts.append(", ".join(exercise_summaries[:4]))
        if len(exercise_summaries) > 4:
            parts[-1] += f" (+{len(exercise_summaries) - 4} more)"
    parts.append(f"{total_sets} working sets")
    parts.append(f"{total_volume:.0f} kg total volume")
    if avg_rpe is not None:
        parts.append(f"avg RPE {avg_rpe}")

    top_muscles = sorted(muscle_volume.items(), key=lambda x: x[1], reverse=True)[:3]
    if top_muscles:
        muscle_str = "/".join(m for m, _ in top_muscles if m != "Unknown")
        if muscle_str:
            parts.append(f"primary: {muscle_str}")

    summary = " | ".join(parts)

    return {
        "total_volume_kg": round(total_volume, 2),
        "total_sets": total_sets,
        "avg_rpe": avg_rpe,
        "estimated_1rms": best_1rms,
        "muscle_volume": dict(muscle_volume),
        "analysis_summary": summary,
    }


def analyze_hevy_workout(row: dict) -> None:
    """
    Compute metrics for a HEVY workout row and persist them.

    *row* is the dict returned by hevy_sync._transform_workout().
    Updates the activity in the DB with analysis_summary and analysis_status.
    """
    from . import db

    activity_id = row.get("id")
    if activity_id is None:
        return

    metrics = compute_hevy_metrics(row.get("exercises_json"))
    if not metrics:
        db.save_analysis(
            activity_id, {"analysis_status": "done", "analysis_summary": "No exercise data"}
        )
        return

    db.save_analysis(
        activity_id,
        {
            "total_volume_kg": metrics["total_volume_kg"],
            "total_sets": metrics["total_sets"],
            "analysis_summary": metrics["analysis_summary"],
            "analysis_status": "done",
        },
    )


LIFTING_DEEP_DIVE_SYSTEM_PROMPT = """\
You are a strength and conditioning coach performing a detailed analysis of a single weight training session.

The workout data below lists each exercise with its sets, showing: set type (normal/warmup/dropset/failure), weight (kg), reps, and RPE (rate of perceived exertion, 6–10 scale) where recorded.

Do not ask follow-up questions. Analyse only the data provided and write your report now.

Cover each of these dimensions:
1. **Volume and intensity**: Was the total load appropriate? How does RPE track across the session?
2. **Exercise selection and order**: Does the sequencing make sense (compound lifts first, isolation after)?
3. **Set quality**: Were there any sets that look like outliers — unexpectedly light, unusually heavy, or inconsistent reps?
4. **Estimated 1RM trends**: For main compound lifts (squat, bench, deadlift, press), note the estimated 1RM.
5. **Fatigue signs**: Did performance drop across sets within an exercise, suggesting insufficient rest or high fatigue?

End with 3–5 specific, actionable coaching notes the athlete can apply to their next session.\
"""
