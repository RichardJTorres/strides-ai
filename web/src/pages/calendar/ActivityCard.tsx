import { useUnits } from "../../UnitsContext";
import { RUN_TYPES } from "./constants";
import type { Activity } from "./types";

function fmtDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}h ${m.toString().padStart(2, "0")}m`;
  return `${m}m ${s.toString().padStart(2, "0")}s`;
}

/** One recorded activity, as shown in the day panel. */
export default function ActivityCard({ activity: a }: { activity: Activity }) {
  const units = useUnits();
  const isRun = RUN_TYPES.has(a.sport_type);
  return (
<div className="bg-zinc-800/60 rounded p-2 border border-zinc-700/50 space-y-1">
  <div className="text-xs font-medium text-zinc-200 truncate">{a.name}</div>
  <div className="text-xs text-zinc-500">{a.sport_type}</div>
  <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs">
    <span className="text-zinc-500">Distance</span>
    <span className="text-zinc-300">{units.fmt(a.distance_m ?? 0, "distance")}</span>
    <span className="text-zinc-500">Duration</span>
    <span className="text-zinc-300">{fmtDuration(a.moving_time_s)}</span>
    {isRun && a.avg_pace_s_per_km && (
      <>
        <span className="text-zinc-500">Pace</span>
        <span className="text-zinc-300">{units.fmt(a.avg_pace_s_per_km, "pace")}</span>
      </>
    )}
    {a.avg_hr && (
      <>
        <span className="text-zinc-500">Avg HR</span>
        <span className="text-zinc-300">{Math.round(a.avg_hr)} bpm</span>
      </>
    )}
    {a.elevation_gain_m != null && (
      <>
        <span className="text-zinc-500">Elevation</span>
        <span className="text-zinc-300">{units.fmt(a.elevation_gain_m, "elevation")}</span>
      </>
    )}
  </div>
</div>
  );
}
