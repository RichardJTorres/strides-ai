import { COMPLIANCE_DOT_COLORS, FALLBACK_WORKOUT_COLOR, WORKOUT_COLORS } from "./constants";
import { splitActivities as splitDay } from "./grid";
import type { GridCell, GridProps } from "./types";
import { useDistance } from "./useDistance";

/** One day in the month grid: its plan chip (draggable), activities, race and status marks. */
export default function DayCell({ cell, grid }: { cell: GridCell; grid: GridProps }) {
  const { units, fmtKm } = useDistance();
  const {
    plan, activities, compliance, prefs, todayStr, selectedDate, range, conflictByDate,
    dragFrom, dragOver, setDragFrom, setDragOver, movePending, handleDayClick, moveWorkout,
  } = grid;
  const splitActivities = (date: string) => splitDay(plan, activities, compliance, date);
  const raceOnDate = (date: string) => prefs.races.find(r => r.date === date);

  const dateStr = cell.dateStr;
  const workout = plan[dateStr];
  const { matched: matchedActivity, others: dayActivities } = splitActivities(dateStr);
  const isToday = dateStr === todayStr;
  const isSelected = selectedDate === dateStr;
  const inRange = !!range && dateStr >= range.start && dateStr <= range.end;
  const isBlocked = prefs.blocked_days.includes(dateStr);
  const race = raceOnDate(dateStr);
  const showMonthLabel = cell.dayNum === 1 && !cell.inCurrentMonth;
  const complianceStatus = compliance[dateStr]?.status;
  const dotColor = complianceStatus ? COMPLIANCE_DOT_COLORS[complianceStatus] : undefined;

  return (
    <div
      key={dateStr}
      onClick={e => handleDayClick(e, dateStr)}
      onMouseDown={e => { if (e.shiftKey) e.preventDefault(); }}
      onDragOver={e => {
        if (!dragFrom || dragFrom === dateStr) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        if (dragOver !== dateStr) setDragOver(dateStr);
      }}
      onDragLeave={() => { if (dragOver === dateStr) setDragOver(null); }}
      onDrop={e => {
        e.preventDefault();
        const from = dragFrom;
        setDragFrom(null);
        setDragOver(null);
        if (from) moveWorkout(from, dateStr);
      }}
      className={[
        dragOver === dateStr ? "ring-2 ring-inset ring-sky-400/80" : "",
        "flex-1 min-w-0 min-h-16 p-1.5 rounded cursor-pointer border transition-colors select-none",
        inRange ? "border-green-500/70 bg-green-500/10" : isSelected ? "border-zinc-400 bg-zinc-700/60" : "border-zinc-800 hover:border-zinc-600",
        isToday ? "ring-2 ring-inset ring-green-400/80 border-green-400/60" : "",
        isBlocked ? "opacity-40" : "",
        !cell.inCurrentMonth ? "opacity-55" : "",
        "bg-zinc-800/20",
      ].join(" ")}
    >
      <div className={`text-xs font-medium mb-1 flex items-center gap-1 ${isToday ? "text-green-400" : cell.inCurrentMonth ? "text-zinc-400" : "text-zinc-600"}`}>
        {showMonthLabel
          ? `${cell.date.toLocaleString("default", { month: "short" })} ${cell.dayNum}`
          : cell.dayNum}
        {isToday && <span className="w-1.5 h-1.5 bg-green-400 rounded-full" />}
        {conflictByDate[dateStr] && (
          <span title={conflictByDate[dateStr]} className="text-amber-400 ml-auto">⚠</span>
        )}
        {dotColor && (
          <span
            title={compliance[dateStr]?.note}
            className={`w-1.5 h-1.5 rounded-full ml-auto ${dotColor}`}
          />
        )}
      </div>
      {race && (
        <div className="text-xs px-1 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/30 truncate mb-0.5">
          🏁 {race.name}
        </div>
      )}
      {workout && (
        <div
          draggable
          onDragStart={e => {
            if (movePending.current) { e.preventDefault(); return; }
            e.dataTransfer.effectAllowed = "move";
            e.dataTransfer.setData("text/plain", dateStr);
            setDragFrom(dateStr);
          }}
          onDragEnd={() => { setDragFrom(null); setDragOver(null); }}
          className={`text-xs px-1 py-0.5 rounded border truncate mb-0.5 cursor-grab active:cursor-grabbing ${dragFrom === dateStr ? "opacity-40" : ""} ${WORKOUT_COLORS[workout.workout_type] ?? FALLBACK_WORKOUT_COLOR}`}>
          {matchedActivity && "✓ "}
          {workout.workout_type}
          {matchedActivity ? (
            <span className="ml-1 opacity-90">
              {units.fmt(matchedActivity.distance_m ?? 0, "distance", { decimals: 1 })}
              {workout.distance_km ? (
                <span className="opacity-60"> / {fmtKm(workout.distance_km)}</span>
              ) : null}
            </span>
          ) : (
            workout.distance_km && (
              <span className="ml-1 opacity-70">{fmtKm(workout.distance_km)}</span>
            )
          )}
        </div>
      )}
      {dayActivities.map(a => (
        <div key={a.id} className="text-xs px-1 py-0.5 rounded bg-zinc-600/40 text-zinc-300 border border-zinc-600/40 truncate mb-0.5">
          ✓ {units.fmt(a.distance_m ?? 0, "distance", { decimals: 1 })} {a.sport_type}
        </div>
      ))}
    </div>
  );
}
