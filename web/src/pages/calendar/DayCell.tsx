import type { KeyboardEvent } from "react";
import { formatDate } from "../../ui/format";
import {
  COMPLIANCE_DOT_COLORS, COMPLIANCE_STATUS_LABELS, FALLBACK_WORKOUT_COLOR, WORKOUT_COLORS,
} from "./constants";
import { dateToStr, dayCompliance, entriesOn, splitActivities as splitDay } from "./grid";
import type { GridCell, GridProps } from "./types";
import { useDistance } from "./useDistance";

/** One day in the month grid: its plan chip (draggable), activities, race and status marks. */
export default function DayCell({ cell, grid }: { cell: GridCell; grid: GridProps }) {
  const { units, fmtKm } = useDistance();
  const {
    plan, activities, compliance, prefs, todayStr, selectedDate, range, conflictByDate,
    dragFrom, dragOver, setDragFrom, setDragOver, movePending, handleDayClick, activateDay,
    moveWorkout,
  } = grid;
  const dateStr = cell.dateStr;
  const entries = entriesOn(plan, dateStr);
  const { byEntry, others: dayActivities } = splitDay(plan, activities, compliance, dateStr);
  const matchedActivities = Object.values(byEntry);
  const isToday = dateStr === todayStr;
  const isSelected = selectedDate === dateStr;
  const inRange = !!range && dateStr >= range.start && dateStr <= range.end;
  const isBlocked = prefs.blocked_days.includes(dateStr);
  const showMonthLabel = cell.dayNum === 1 && !cell.inCurrentMonth;
  const day = dayCompliance(plan, compliance, dateStr);
  const complianceStatus = day?.status;
  const dotColor = complianceStatus ? COMPLIANCE_DOT_COLORS[complianceStatus] : undefined;

  // What a screen reader hears for the cell: the day and everything marked on it.
  const label = [
    formatDate(dateStr, "weekday"),
    isToday && "today",
    ...entries.map(e => (e.kind === "race" ? `race: ${e.title || "Race"}` : `planned ${e.workout_type}`)),
    complianceStatus && complianceStatus !== "upcoming" && COMPLIANCE_STATUS_LABELS[complianceStatus],
    isBlocked && "blocked",
  ].filter(Boolean).join(", ");

  // Enter/Space opens the day, Shift+Enter extends the range, arrows move between days.
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.target !== e.currentTarget) return;
    const step = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[e.key];
    if (step !== undefined) {
      e.preventDefault();
      const d = cell.date;
      const target = dateToStr(new Date(d.getFullYear(), d.getMonth(), d.getDate() + step));
      document.querySelector<HTMLElement>(`[data-date="${target}"]`)?.focus();
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      activateDay(dateStr, e.shiftKey);
    }
  };

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={label}
      aria-pressed={isSelected}
      data-date={dateStr}
      onKeyDown={onKeyDown}
      onClick={e => handleDayClick(e, dateStr)}
      onMouseDown={e => { if (e.shiftKey) e.preventDefault(); }}
      onDragOver={e => {
        if (dragFrom == null) return;
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
        if (from != null) moveWorkout(from, dateStr);
      }}
      className={[
        dragOver === dateStr ? "ring-2 ring-inset ring-sky-400/80" : "",
        "flex-1 min-w-0 min-h-12 md:min-h-24 p-1 md:p-1.5 rounded cursor-pointer border transition-colors select-none",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400",
        inRange ? "border-green-500/70 bg-green-500/10" : isSelected ? "border-gray-400 bg-gray-700/60" : "border-gray-800 hover:border-gray-600",
        isToday ? "ring-2 ring-inset ring-green-400/80 border-green-400/60" : "",
        complianceStatus === "completed" && !inRange && !isSelected
          ? "border-green-500/50 bg-gradient-to-br from-green-500/20 to-transparent shadow-[0_0_12px_-3px_rgba(74,222,128,0.5)]"
          : "",
        isBlocked ? "opacity-40" : "",
        !cell.inCurrentMonth ? "opacity-55" : "",
        "bg-gray-800/20",
      ].join(" ")}
    >
      <div className={`text-xs font-medium mb-1 flex items-center gap-1 ${isToday ? "text-green-400" : cell.inCurrentMonth ? "text-gray-400" : "text-gray-600"}`}>
        {showMonthLabel
          ? `${cell.date.toLocaleString("default", { month: "short" })} ${cell.dayNum}`
          : cell.dayNum}
        {isToday && <span className="w-1.5 h-1.5 bg-green-400 rounded-full" />}
        {conflictByDate[dateStr] && (
          <span title={conflictByDate[dateStr]} className="text-amber-400 ml-auto">⚠</span>
        )}
        {complianceStatus === "completed" ? (
          <span
            title={day?.note}
            className="badge-pop ml-auto w-4 h-4 rounded-full bg-green-400 text-gray-900 text-[10px] font-bold leading-none flex items-center justify-center shadow-[0_0_8px_rgba(74,222,128,0.8)]"
          >✓</span>
        ) : dotColor && (
          <span
            title={day?.note}
            className={`w-1.5 h-1.5 rounded-full ml-auto ${dotColor}`}
          />
        )}
      </div>
      {/* Phones: no room for chips, so one dot per thing on the day. */}
      <div className="md:hidden flex flex-wrap gap-0.5" aria-hidden="true">
        {entries.map(e => (
          <span
            key={e.id}
            className={`w-2 h-2 rounded-full border ${WORKOUT_COLORS[e.workout_type] ?? FALLBACK_WORKOUT_COLOR}`}
          />
        ))}
        {[...matchedActivities, ...dayActivities].map(a => (
          <span key={a.id} className="w-2 h-2 rounded-full bg-gray-400" />
        ))}
      </div>
      {entries.map(entry => {
        const matched = byEntry[entry.id];
        const label = entry.kind === "race" ? `🏁 ${entry.title || "Race"}` : entry.kind === "workout" ? entry.workout_type : entry.title || entry.workout_type;
        return (
          <div
            key={entry.id}
            draggable
            onDragStart={e => {
              if (movePending.current) { e.preventDefault(); return; }
              e.dataTransfer.effectAllowed = "move";
              e.dataTransfer.setData("text/plain", String(entry.id));
              setDragFrom(entry.id);
            }}
            onDragEnd={() => { setDragFrom(null); setDragOver(null); }}
            className={`hidden md:block text-xs px-1 py-0.5 rounded border truncate mb-0.5 cursor-grab active:cursor-grabbing ${dragFrom === entry.id ? "opacity-40" : ""} ${WORKOUT_COLORS[entry.workout_type] ?? FALLBACK_WORKOUT_COLOR}`}>
            {matched && "✓ "}
            {label}
            {matched ? (
              <span className="ml-1 opacity-90">
                {units.fmt(matched.distance_m ?? 0, "distance", { decimals: 1 })}
                {entry.distance_km ? (
                  <span className="opacity-60"> / {fmtKm(entry.distance_km)}</span>
                ) : null}
              </span>
            ) : (
              entry.distance_km && entry.kind !== "rest" && (
                <span className="ml-1 opacity-70">{fmtKm(entry.distance_km)}</span>
              )
            )}
          </div>
        );
      })}
      {dayActivities.map(a => (
        <div key={a.id} className="hidden md:block text-xs px-1 py-0.5 rounded bg-gray-600/40 text-gray-300 border border-gray-600/40 truncate mb-0.5">
          ✓ {units.fmt(a.distance_m ?? 0, "distance", { decimals: 1 })} {a.sport_type}
        </div>
      ))}
    </div>
  );
}
