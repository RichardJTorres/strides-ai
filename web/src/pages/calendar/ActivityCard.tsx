import { hrefFor } from "../../nav";
import { formatDuration } from "../../ui/format";
import { useUnits } from "../../UnitsContext";
import { RUN_TYPES } from "./constants";
import type { Activity } from "./types";

/** One recorded activity, as shown in the day panel. */
export default function ActivityCard({ activity: a }: { activity: Activity }) {
  const units = useUnits();
  const isRun = RUN_TYPES.has(a.sport_type);
  return (
<div className="bg-gray-800/60 rounded p-2 border border-gray-700/50 space-y-1">
  <a
    href={hrefFor("activities", a.id)}
    className="block text-xs font-medium text-gray-200 truncate hover:underline"
    title="Open in Activities"
  >{a.name}</a>
  <div className="text-xs text-gray-500">{a.sport_type}</div>
  <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs">
    <span className="text-gray-500">Distance</span>
    <span className="text-gray-300">{units.fmt(a.distance_m ?? 0, "distance")}</span>
    <span className="text-gray-500">Duration</span>
    <span className="text-gray-300">{formatDuration(a.moving_time_s)}</span>
    {isRun && a.avg_pace_s_per_km && (
      <>
        <span className="text-gray-500">Pace</span>
        <span className="text-gray-300">{units.fmt(a.avg_pace_s_per_km, "pace")}</span>
      </>
    )}
    {a.avg_hr && (
      <>
        <span className="text-gray-500">Avg HR</span>
        <span className="text-gray-300">{Math.round(a.avg_hr)} bpm</span>
      </>
    )}
    {a.elevation_gain_m != null && (
      <>
        <span className="text-gray-500">Elevation</span>
        <span className="text-gray-300">{units.fmt(a.elevation_gain_m, "elevation")}</span>
      </>
    )}
  </div>
</div>
  );
}
