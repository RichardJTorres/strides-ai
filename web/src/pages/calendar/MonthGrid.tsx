import type { Dispatch, SetStateAction } from "react";
import { DAYS_OF_WEEK } from "./constants";
import LoadStrip from "./LoadStrip";
import type { GridCell, GridProps } from "./types";
import WeekRow from "./WeekRow";

interface Props {
  currentMonth: Date;
  setCurrentMonth: Dispatch<SetStateAction<Date>>;
  goToToday: () => void;
  weeks: GridCell[][];
  grid: GridProps;
}

/** Month header, load strip and the week rows. */
export default function MonthGrid({ currentMonth, setCurrentMonth, goToToday, weeks, grid }: Props) {
  const { trainingState } = grid;
  return (
    <div className="flex-shrink-0">
      <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-800">
        <div className="flex items-center gap-1">
          <button
            onClick={goToToday}
            className="text-xs bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded px-2 py-1 mr-1"
          >Today</button>
          <button
            onClick={() => setCurrentMonth(m => new Date(m.getFullYear(), m.getMonth() - 1, 1))}
            className="text-zinc-400 hover:text-zinc-200 px-2 text-lg"
          >‹</button>
        </div>
        <h2 className="text-sm font-semibold text-zinc-200">
          {currentMonth.toLocaleString("default", { month: "long", year: "numeric" })}
        </h2>
        <button
          onClick={() => setCurrentMonth(m => new Date(m.getFullYear(), m.getMonth() + 1, 1))}
          className="text-zinc-400 hover:text-zinc-200 px-2 text-lg"
        >›</button>
      </div>

      {trainingState && <LoadStrip state={trainingState} />}

      <div className="p-3">
        {/* Day-of-week headers */}
        <div className="flex gap-1 mb-1">
          {DAYS_OF_WEEK.map(d => (
            <div key={d} className="flex-1 min-w-0 text-center text-xs text-zinc-500 font-medium py-1">{d}</div>
          ))}
          <div className="w-20 flex-shrink-0" />
        </div>

        {/* Week rows */}
        {weeks.map(weekCells => (
          <WeekRow key={weekCells[0].dateStr} weekCells={weekCells} grid={grid} />
        ))}
      </div>
    </div>
  );
}
