import type { Dispatch, SetStateAction } from "react";
import { DAYS_OF_WEEK } from "./constants";
import type { Progress } from "../../progress/api";
import ProgressStrip from "../../progress/ProgressStrip";
import { useTheme } from "../../ui/theme";
import { LoadingState } from "../../ui/states";
import LoadStrip from "./LoadStrip";
import type { GridCell, GridProps, WeekStart } from "./types";
import WeekRow from "./WeekRow";

interface Props {
  currentMonth: Date;
  setCurrentMonth: Dispatch<SetStateAction<Date>>;
  goToToday: () => void;
  onGenerate: () => void;
  weekStart: WeekStart;
  weeks: GridCell[][];
  grid: GridProps;
  progress: Progress | null;
  loading: boolean;
}

/** Month header, load strip and the week rows. */
export default function MonthGrid({
  currentMonth, setCurrentMonth, goToToday, onGenerate, weekStart, weeks, grid, progress, loading,
}: Props) {
  const { trainingState } = grid;
  const theme = useTheme();
  return (
    <div className="flex-shrink-0">
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
        <div className="flex items-center gap-1">
          <button
            onClick={goToToday}
            className="text-xs bg-gray-800 hover:bg-gray-700 text-gray-300 rounded px-2 py-1 mr-1"
          >Today</button>
          <button
            onClick={() => setCurrentMonth(m => new Date(m.getFullYear(), m.getMonth() - 1, 1))}
            aria-label="Previous month"
            className="text-gray-400 hover:text-gray-200 px-2 text-lg"
          >‹</button>
        </div>
        <h2 className="text-sm font-semibold text-gray-200">
          {currentMonth.toLocaleString("default", { month: "long", year: "numeric" })}
        </h2>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setCurrentMonth(m => new Date(m.getFullYear(), m.getMonth() + 1, 1))}
            aria-label="Next month"
            className="text-gray-400 hover:text-gray-200 px-2 text-lg"
          >›</button>
          <button
            onClick={onGenerate}
            title="AI-suggested plan for a date range"
            className={`text-xs text-white rounded px-2 py-1 ml-1 transition-colors ${theme.accentButton}`}
          ><span aria-hidden="true">✨ </span>Generate block</button>
        </div>
      </div>

      {trainingState && <LoadStrip state={trainingState} />}
      {progress && <ProgressStrip progress={progress} />}
      {loading && <div className="px-4"><LoadingState label="Loading your calendar…" /></div>}

      <div className="p-1.5 md:p-3">
        {/* Day-of-week headers */}
        <div className="flex gap-1 mb-1">
          {DAYS_OF_WEEK[weekStart].map(d => (
            <div key={d} className="flex-1 min-w-0 text-center text-xs text-gray-500 font-medium py-1">{d}</div>
          ))}
          <div className="w-6 md:w-28 flex-shrink-0" />
        </div>

        {/* Week rows */}
        {weeks.map(weekCells => (
          <WeekRow key={weekCells[0].dateStr} weekCells={weekCells} grid={grid} />
        ))}
      </div>
    </div>
  );
}
