import DayCell from "./DayCell";
import { isPerfectWeek, summarizeWeek, weekLives } from "./grid";
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
  const perfect = isPerfectWeek(weekCompliance);
  // Hearts: shown once a miss has landed, or for the week in progress.
  const lives = weekLives(weekCompliance.missed, grid.maxMisses ?? 0);
  const showLives = grid.maxMisses !== null && weekPlannedWorkouts > 0 && (weekCompliance.missed > 0 || weekCells.some(c => c.dateStr === grid.todayStr));

  // Ramp vs the prior 4-week average for this row's week. Past weeks have no entry (the backend
  // only returns the current and upcoming weeks).
  const rampChip = (weekCells: GridCell[]) => {
    // The ramp belongs to the Monday-Sunday week, so use the row's Monday (a Sunday-first row
    // has it in its second column).
    const monday = weekCells.find(c => c.date.getDay() === 1);
    const w = monday && trainingState?.weeks.find(x => x.week_start === monday.dateStr);
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
    <div className="flex gap-1 mb-1.5">
      {weekCells.map(cell => <DayCell key={cell.dateStr} cell={cell} grid={grid} />)}

      {/* Phones: the totals box does not fit, so a narrow button opens the same week breakdown. */}
      <button
        onClick={() => grid.openWeek(weekCells[0].dateStr)}
        aria-label={perfect ? "Week summary, perfect week" : "Week summary"}
        className={`md:hidden w-6 flex-shrink-0 rounded border text-sm ${
          perfect ? "bg-amber-400/20 border-amber-400/60 text-amber-300" : "bg-gray-800/40 border-gray-700/50 text-gray-400"
        }`}
      >{perfect ? "★" : "›"}</button>

      {/* Weekly totals — clickable, opens a larger per-day breakdown pane */}
      <button
        onClick={() => grid.openWeek(weekCells[0].dateStr)}
        className={`hidden md:flex w-28 flex-shrink-0 flex-col justify-center gap-0.5 px-2 py-1 ml-1 rounded border transition-colors text-left cursor-pointer ${
          perfect
            ? "bg-gradient-to-br from-amber-400/25 to-amber-600/5 border-amber-400/60 hover:border-amber-300 shadow-[0_0_14px_-3px_rgba(251,191,36,0.55)]"
            : "bg-gray-800/40 border-gray-700/50 hover:border-gray-500 hover:bg-gray-800/70"
        }`}
      >
        {perfect && (
          <div className="badge-pop flex items-center gap-1 text-[11px] font-bold text-amber-300 leading-tight">
            <span aria-hidden="true">★</span>Perfect week
          </div>
        )}
        {showLives && (
          <div
            className="flex items-center gap-0.5 text-[11px] leading-tight"
            title={lives.lost ? "Too many misses: this week won't count toward the streak" : `${lives.left} of ${grid.maxMisses} misses left before this week stops counting`}
            role="img"
            aria-label={lives.lost ? "Week lost" : `${lives.left} of ${grid.maxMisses} lives left`}
          >
            {Array.from({ length: lives.left }, (_, i) => <span key={`l${i}`} aria-hidden="true" className="text-red-400">♥</span>)}
            {Array.from({ length: lives.spent }, (_, i) => <span key={`s${i}`} aria-hidden="true" className="badge-pop text-gray-600">♡</span>)}
            {lives.lost && <span className="ml-1 text-red-400 font-semibold">Week lost</span>}
          </div>
        )}
        <div className="flex items-baseline justify-between gap-1">
          <span className="text-[10px] text-gray-500 uppercase tracking-wider">Plan</span>
          <span className="text-xs text-gray-300 font-semibold">
            {plannedKm > 0 ? fmtKm(plannedKm, 1, false) : "—"}
            {plannedKm > 0 && <span className="text-[10px] text-gray-500 font-normal ml-0.5">{distLabel}</span>}
          </span>
        </div>
        <div className="flex items-baseline justify-between gap-1">
          <span className="text-[10px] text-gray-500 uppercase tracking-wider">Actual</span>
          <span className={`text-xs font-semibold ${actualKm > 0 ? "text-green-400" : "text-gray-600"}`}>
            {actualKm > 0 ? fmtKm(actualKm, 1, false) : "—"}
            {actualKm > 0 && <span className="text-[10px] text-gray-500 font-normal ml-0.5">{distLabel}</span>}
          </span>
        </div>
        {weekPlannedWorkouts > 0 && (
          <div className="flex items-baseline justify-between gap-1">
            <span className="text-[10px] text-gray-500 uppercase tracking-wider">Done</span>
            <span className={`text-xs font-semibold ${weekDone === weekPlannedWorkouts ? "text-green-400" : "text-gray-300"}`}>
              {weekDone} of {weekPlannedWorkouts}
            </span>
          </div>
        )}
        {rampChip(weekCells)}
      </button>
    </div>
  );
}
