import { useEffect, useRef, useState } from "react";
import DayPanel from "./DayPanel";
import GenerateModal from "./GenerateModal";
import { buildGrid, chunkWeeks, dateToStr, rangeLength, splitActivities } from "./grid";
import MonthGrid from "./MonthGrid";
import Sidebar from "./Sidebar";
import type { DateRange, GridProps, Workout } from "./types";
import { useCalendarData } from "./useCalendarData";
import WeekModal from "./WeekModal";

export default function Calendar() {
  const today = new Date();
  const todayStr = dateToStr(today);

  const [currentMonth, setCurrentMonth] = useState(
    new Date(today.getFullYear(), today.getMonth(), 1)
  );
  const {
    prefs, plan, setPlan, activities, compliance, trainingState, toggleBlocked, addRace, removeRace,
  } = useCalendarData(currentMonth);
  // First day of the week whose breakdown is open.
  const [selectedWeek, setSelectedWeek] = useState<string | null>(null);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  // Bumped on every selection so the day panel remounts (and so resets) even for the same day.
  const [panelNonce, setPanelNonce] = useState(0);
  const [editMode, setEditMode] = useState(false);

  const [range, setRange] = useState<DateRange | null>(null);
  const rangeAnchor = useRef<string | null>(null);
  // The range the generate modal was opened for; null while it is closed.
  const [genRange, setGenRange] = useState<DateRange | null>(null);
  const genModalOpen = genRange !== null;

  useEffect(() => {
    if (!range) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !genModalOpen) setRange(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [range, genModalOpen]);

  // Close the week breakdown on month navigation, so it never shows a week that is off screen.
  useEffect(() => {
    setSelectedWeek(null);
  }, [currentMonth]);

  const openGenerateModal = (range?: DateRange) => {
    setGenRange({ start: range?.start ?? todayStr, end: range?.end ?? todayStr });
  };

  const selectDate = (date: string) => {
    setSelectedDate(date);
    setEditMode(false);
    setPanelNonce(n => n + 1);
  };

  // Shift-click extends a range from the last plainly-clicked day (the anchor); a plain click
  // moves the anchor and clears any range. The range feeds "Generate plan" for those days.
  const handleDayClick = (e: React.MouseEvent, date: string) => {
    if (e.shiftKey) {
      const anchor = rangeAnchor.current ?? selectedDate ?? date;
      rangeAnchor.current = anchor;
      setRange(anchor <= date ? { start: anchor, end: date } : { start: date, end: anchor });
      return;
    }
    rangeAnchor.current = date;
    setRange(null);
    openDay(date);
  };

  // Drag a planned workout onto another day. An occupied target swaps the two workouts. Bulk
  // upsert both days (no deletes needed); optimistic, reverted if the save fails.
  const [dragFrom, setDragFrom] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState<string | null>(null);
  const movePending = useRef(false);

  const moveWorkout = async (from: string, to: string) => {
    const moving = plan[from];
    if (!moving || from === to || movePending.current) return;
    movePending.current = true;
    const displaced = plan[to];
    const entry = (w: Workout, date: string) => ({
      date,
      workout_type: w.workout_type,
      description: w.description ?? null,
      distance_km: w.distance_km ?? null,
      elevation_m: w.elevation_m ?? null,
      duration_min: w.duration_min ?? null,
      intensity: w.intensity ?? null,
      route_url: w.route_url ?? null,
      structure: w.structure ?? null,
    });
    const set = [entry(moving, to), ...(displaced ? [entry(displaced, from)] : [])];
    const moved = { ...moving, date: to, nutrition_json: null, route_analysis_json: null };
    const swapped = displaced
      ? { ...displaced, date: from, nutrition_json: null, route_analysis_json: null }
      : undefined;
    const rollback = () => setPlan(prev => {
      const next = { ...prev };
      // Keep any edits made while the move was saving, including on unrelated days.
      if (prev[from] === swapped) next[from] = moving;
      if (prev[to] === moved) {
        if (displaced) next[to] = displaced;
        else delete next[to];
      }
      return next;
    });
    setPlan(prev => {
      const next = { ...prev };
      delete next[from];
      next[to] = moved;
      if (swapped) next[from] = swapped;
      return next;
    });
    if (selectedDate === from || selectedDate === to) {
      setSelectedDate(null);
      setEditMode(false);
    }
    try {
      const res = await fetch("/api/calendar/plan/bulk", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ set, delete: displaced ? [] : [from] }),
      });
      if (!res.ok) rollback();
    } catch {
      rollback();
    } finally {
      movePending.current = false;
    }
  };

  const openDay = (date: string) => {
    if (selectedDate === date) {
      setSelectedDate(null);
      return;
    }
    selectDate(date);
  };

  const goToToday = () => {
    setCurrentMonth(new Date(today.getFullYear(), today.getMonth(), 1));
    selectDate(todayStr);
  };

  const weeks = chunkWeeks(buildGrid(currentMonth));
  const rangeDays = range ? rangeLength(range) : 0;
  const selectedWorkout = selectedDate ? plan[selectedDate] : null;

  // First conflict per date (blocked-day / race-day) for the ⚠ badge on a day cell.
  const conflictByDate: Record<string, string> = {};
  for (const c of trainingState?.conflicts ?? []) {
    if (c.hard && !conflictByDate[c.date]) conflictByDate[c.date] = c.detail;
  }

  const grid: GridProps = {
    plan, activities, compliance, prefs, trainingState, todayStr, selectedDate, range,
    conflictByDate, dragFrom, dragOver, setDragFrom, setDragOver, movePending, handleDayClick,
    moveWorkout, openWeek: setSelectedWeek,
  };

  return (
    <div className="flex h-full bg-zinc-900 text-zinc-100 overflow-hidden">

      <Sidebar
        prefs={prefs}
        onGenerate={() => openGenerateModal()}
        onAddRace={addRace}
        removeRace={removeRace}
      />

      {/* ── Main column ── */}
      <div className="flex-1 flex min-w-0 overflow-hidden">
      <div className="flex-1 min-w-0 flex flex-col overflow-y-auto">
        <MonthGrid
          currentMonth={currentMonth}
          setCurrentMonth={setCurrentMonth}
          goToToday={goToToday}
          weeks={weeks}
          grid={grid}
        />
      </div>

      {/* ── Side panel: range actions or the selected day. A fixed overlay below lg so it never
          pushes the grid; docked beside the grid on wide screens so the calendar stays in view. ── */}
      {(range || selectedDate) && (
        <aside className="fixed inset-y-0 right-0 z-30 w-full sm:w-96 lg:static lg:z-auto lg:w-80 lg:flex-shrink-0 border-l border-zinc-800 bg-zinc-900 overflow-y-auto shadow-2xl lg:shadow-none">
          {range && (
            <div className="p-4 space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm font-semibold text-zinc-200">
                    {rangeDays} day{rangeDays === 1 ? "" : "s"} selected
                  </div>
                  <div className="text-xs text-zinc-500">{range.start} → {range.end}</div>
                </div>
                <button
                  onClick={() => setRange(null)}
                  className="text-zinc-500 hover:text-zinc-300 text-xl leading-none"
                >×</button>
              </div>
              <button
                onClick={() => openGenerateModal(range)}
                className="w-full bg-green-600 hover:bg-green-500 text-white rounded px-3 py-2 text-sm font-medium"
              >
                Generate plan for selection
              </button>
              <p className="text-xs text-zinc-600">
                Shift-click another day to adjust the range. Click a day or press Esc to clear it.
              </p>
            </div>
          )}
          {/* Hidden, not unmounted, while a range is showing: the panel owns the edit form, so
              unmounting it would throw away whatever the athlete had typed. */}
          {selectedDate && (
            <div className={range ? "hidden" : undefined}>
            <DayPanel
              key={`${selectedDate}:${panelNonce}`}
              selectedDate={selectedDate}
              selectedWorkout={selectedWorkout}
              selectedSplit={splitActivities(plan, activities, compliance, selectedDate)}
              prefs={prefs}
              toggleBlocked={toggleBlocked}
              setPlan={setPlan}
              editMode={editMode}
              setEditMode={setEditMode}
              onClose={() => setSelectedDate(null)}
            />
            </div>
          )}
          </aside>
        )}
      </div>

      {genRange && (
        <GenerateModal
          initialStart={genRange.start}
          initialEnd={genRange.end}
          plan={plan}
          setPlan={setPlan}
          onClose={() => setGenRange(null)}
        />
      )}

      {selectedWeek && (
        <WeekModal
          weekStart={selectedWeek}
          plan={plan}
          activities={activities}
          compliance={compliance}
          onClose={() => setSelectedWeek(null)}
        />
      )}
    </div>
  );
}
