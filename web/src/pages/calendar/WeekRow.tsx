import DayCell from "./DayCell";
import { summarizeWeek } from "./grid";
import type { GridCell, GridProps } from "./types";
import { useDistance } from "./useDistance";

/** A week of day cells plus its clickable totals box. */
export default function WeekRow({ weekCells, grid }: { weekCells: GridCell[]; grid: GridProps }) {
  const { fmtKm, distLabel } = useDistance();
  const { plan, activities, compliance, trainingState } = grid;
  const weekCompliance = summarizeWeek(weekCells, plan, activities, compliance);
  const { plannedKm, actualKm } = weekCompliance;
  const weekDone = weekCompliance.completed + weekCompliance.modified;
  const weekPlannedWorkouts = weekDone + weekCompliance.missed + weekCompliance.upcoming;

  // Ramp vs the prior 4-week average for this row's week. Past weeks have no entry (the backend
  // only returns the current and upcoming weeks).
  const rampChip = (weekCells: GridCell[]) => {
    const w = trainingState?.weeks.find(x => x.week_start === weekCells[0].dateStr);
    if (!w || w.ramp_pct === null || !trainingState) return null;
    const t = trainingState.thresholds;
    const color =
      w.ramp_pct > t.ramp_high ? "text-red-400" : w.ramp_pct > t.ramp_elevated ? "text-amber-400" : "text-gray-500";
    const title = w.flags.length ? w.flags.join(", ").replace(/_/g, " ") : "vs prior 4-week average";
    return (
      <div className={`text-[10px] ${color}`} title={title}>
        {w.ramp_pct > 0 ? "+" : ""}{Math.round(w.ramp_pct)}% ramp{w.flags.includes("no_recovery_week") ? " ⚠" : ""}
      </div>
    );
  };

  return (
    <div className="flex gap-1 mb-3">
      {weekCells.map(cell => <DayCell key={cell.dateStr} cell={cell} grid={grid} />)}

      {/* Phones: the totals box does not fit, so a narrow button opens the same week breakdown. */}
      <button
        onClick={() => grid.openWeek(weekCells[0].dateStr)}
        aria-label="Week summary"
        className="md:hidden w-6 flex-shrink-0 rounded bg-gray-800/40 border border-gray-700/50 text-gray-400 text-sm"
      >›</button>

      {/* Weekly totals — clickable, opens a larger per-day breakdown pane */}
      <button
        onClick={() => grid.openWeek(weekCells[0].dateStr)}
        className="hidden md:flex w-20 flex-shrink-0 flex-col justify-center gap-3 px-3 ml-1 rounded bg-gray-800/40 border border-gray-700/50 hover:border-gray-500 hover:bg-gray-800/70 transition-colors text-left cursor-pointer"
      >
        <div>
          <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-0.5">Planned</div>
          <div className="text-sm text-gray-300 font-semibold">
            {plannedKm > 0 ? fmtKm(plannedKm, 1, false) : "—"}
          </div>
          {plannedKm > 0 && <div className="text-[10px] text-gray-500">{distLabel}</div>}
          {rampChip(weekCells)}
        </div>
        <div>
          <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-0.5">Actual</div>
          <div className={`text-sm font-semibold ${actualKm > 0 ? "text-green-400" : "text-gray-600"}`}>
            {actualKm > 0 ? fmtKm(actualKm, 1, false) : "—"}
          </div>
          {actualKm > 0 && <div className="text-[10px] text-gray-500">{distLabel}</div>}
        </div>
        {weekPlannedWorkouts > 0 && (
          <div>
            <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-0.5">Workouts</div>
            <div className={`text-sm font-semibold ${weekDone === weekPlannedWorkouts ? "text-green-400" : "text-gray-300"}`}>
              {weekDone} of {weekPlannedWorkouts}
            </div>
            <div className="text-[10px] text-gray-500">done</div>
          </div>
        )}
      </button>
    </div>
  );
}
