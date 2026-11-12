import { useEffect, useMemo, useRef, useState } from "react";
import { navigate } from "../../nav";
import { useProgress } from "../../progress/api";
import Button from "../../ui/Button";
import { formatDate } from "../../ui/format";
import { ErrorState, Notice } from "../../ui/states";

import DayPanel from "./DayPanel";
import GenerateModal from "./GenerateModal";
import { buildGrid, chunkWeeks, dateToStr, rangeLength, splitActivities } from "./grid";
import { applyMove, datePatch, failureMessage, findEntry } from "./entryOps";
import MonthGrid from "./MonthGrid";
import type { DateRange, GridProps } from "./types";
import { useCalendarData } from "./useCalendarData";
import WeekModal from "./WeekModal";

/** "YYYY-MM-DD" that is a real calendar day, else null (the route only checks the shape). */
function validDate(value: string | null | undefined): string | null {
  if (!value) return null;
  const [y, m, d] = value.split("-").map(Number);
  return dateToStr(new Date(y, m - 1, d)) === value ? value : null;
}

/** `routeParam` is the selected day from the URL (`#calendar/2026-11-10`), or null. */
export default function Calendar({ routeParam }: { routeParam?: string | null }) {

  const today = new Date();
  const todayStr = dateToStr(today);

  const [currentMonth, setCurrentMonth] = useState(
    new Date(today.getFullYear(), today.getMonth(), 1)
  );
  const {
    prefs, plan, setPlan, reloadPlan, activities, compliance, trainingState, toggleBlocked, weekStart,
    loading, loadError, prefsError, reload, confirmed, refreshDerived,
  } = useCalendarData(currentMonth);
  // The streak is computed from the plan and activities, so refetch when the plan changes.
  const progressKey = useMemo(() => ({ plan, confirmed }), [plan, confirmed]);
  const progress = useProgress(progressKey).data;
  // First day of the week whose breakdown is open.
  const [selectedWeek, setSelectedWeek] = useState<string | null>(null);
  // The URL is the selection, so a day can be linked to and Back closes the panel. Moving
  // between days replaces the history entry instead of stacking one per click.
  const selectedDate = validDate(routeParam);
  const setSelectedDate = (date: string | null) =>
    navigate("calendar", date, { replace: selectedDate !== null });
  // Arriving on a day that is not on screen (a link, or Back) brings its month into view.
  useEffect(() => {
    if (!selectedDate) return;
    setCurrentMonth(month =>
      buildGrid(month, weekStart).some(c => c.dateStr === selectedDate)
        ? month
        : new Date(Number(selectedDate.slice(0, 4)), Number(selectedDate.slice(5, 7)) - 1, 1)
    );
  }, [selectedDate, weekStart]);
  // A failed drag-to-move (the grid is rolled back).
  const [moveError, setMoveError] = useState<string | null>(null);
  // Bumped on every selection so the day panel remounts (and so resets) even for the same day.
  const [panelNonce, setPanelNonce] = useState(0);
  const [editMode, setEditMode] = useState(false);
  // A day reached by Back/Forward (not a click) must not open mid-edit from the previous day.
  useEffect(() => setEditMode(false), [selectedDate]);

  const [range, setRange] = useState<DateRange | null>(null);
  const rangeAnchor = useRef<string | null>(null);
  // The range the generate modal was opened for; null while it is closed.
  const [genRange, setGenRange] = useState<DateRange | null>(null);
  const genModalOpen = genRange !== null;

  useEffect(() => {
    if (!range) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !genModalOpen && !selectedWeek) setRange(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [range, genModalOpen, selectedWeek]);

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
  const activateDay = (date: string, extend: boolean) => {
    if (extend) {
      const anchor = rangeAnchor.current ?? selectedDate ?? date;
      rangeAnchor.current = anchor;
      setRange(anchor <= date ? { start: anchor, end: date } : { start: date, end: anchor });
      return;
    }
    rangeAnchor.current = date;
    setRange(null);
    openDay(date);
  };
  const handleDayClick = (e: React.MouseEvent, date: string) => activateDay(date, e.shiftKey);

  // Drag an entry onto another day: a date-only PATCH. Entries coexist, so nothing is swapped.
  // Optimistic; if the server refuses (e.g. a second scored workout of the same sport that day)
  // the grid is reloaded to what it actually has and the reason is shown.
  const [dragFrom, setDragFrom] = useState<number | null>(null);
  const [dragOver, setDragOver] = useState<string | null>(null);
  const movePending = useRef(false);

  const moveWorkout = async (entryId: number, to: string) => {
    const moving = findEntry(plan, entryId);
    if (!moving || moving.date === to || movePending.current) return;
    movePending.current = true;
    setMoveError(null);
    setPlan(prev => applyMove(prev, entryId, to));
    if (selectedDate === moving.date || selectedDate === to) {
      setSelectedDate(null);
      setEditMode(false);
    }
    try {
      const res = await fetch(`/api/calendar/entries/${entryId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(datePatch(to)),
      });
      if (!res.ok) throw new Error(await failureMessage(res, ""));
      reloadPlan();
    } catch (e) {
      await reloadPlan();
      setMoveError(`Couldn't move that, so it was put back. ${e instanceof Error ? e.message : ""}`.trim());
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

  const weeks = chunkWeeks(buildGrid(currentMonth, weekStart));
  const rangeDays = range ? rangeLength(range) : 0;
  const selectedEntries = selectedDate ? plan[selectedDate] ?? [] : [];

  // First conflict per date (blocked-day / race-day) for the ⚠ badge on a day cell.
  const conflictByDate: Record<string, string> = {};
  for (const c of trainingState?.conflicts ?? []) {
    if (c.hard && !conflictByDate[c.date]) conflictByDate[c.date] = c.detail;
  }

  const grid: GridProps = {
    plan, activities, compliance, prefs, trainingState, todayStr, selectedDate, range,
    conflictByDate, dragFrom, dragOver, setDragFrom, setDragOver, movePending, handleDayClick,
    activateDay, moveWorkout, openWeek: setSelectedWeek,
  };

  return (
    <div className="flex flex-col md:flex-row h-full bg-gray-950 text-gray-100 overflow-hidden">

      {/* ── Main column ── */}
      <div className="flex-1 flex min-w-0 min-h-0 overflow-hidden">
      <div className="flex-1 min-w-0 flex flex-col overflow-y-auto">
        {loadError ? (
          <div className="p-4"><ErrorState message={loadError} onRetry={reload} /></div>
        ) : (
          <>
            {(prefsError || moveError) && (
              <div className="px-4 pt-3 space-y-2">
                {prefsError && <Notice tone="error">{prefsError}</Notice>}
                {moveError && <Notice tone="error">{moveError}</Notice>}
              </div>
            )}
            <MonthGrid
              currentMonth={currentMonth}
              setCurrentMonth={setCurrentMonth}
              goToToday={goToToday}
              onGenerate={() => openGenerateModal()}
              weekStart={weekStart}
              weeks={weeks}
              grid={grid}
              progress={progress}
              loading={loading}
            />
          </>
        )}
      </div>

      {/* ── Side panel: range actions or the selected day. A fixed overlay below lg so it never
          pushes the grid; docked beside the grid on wide screens so the calendar stays in view. ── */}
      {(range || selectedDate) && (
        <aside className="fixed inset-y-0 right-0 z-30 w-full sm:w-96 lg:static lg:z-auto lg:w-80 lg:flex-shrink-0 border-l border-gray-800 bg-gray-900 overflow-y-auto shadow-2xl lg:shadow-none">
          {range && (
            <div className="p-4 space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm font-semibold text-gray-200">
                    {rangeDays} day{rangeDays === 1 ? "" : "s"} selected
                  </div>
                  <div className="text-xs text-gray-500">{formatDate(range.start)} → {formatDate(range.end)}</div>
                </div>
                <button
                  onClick={() => setRange(null)}
                  aria-label="Clear selection"
                  className="text-gray-500 hover:text-gray-300 text-xl leading-none"
                >×</button>
              </div>
              <Button className="w-full" onClick={() => openGenerateModal(range)}>
                Generate plan for selection
              </Button>
              <p className="text-xs text-gray-600">
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
              entries={selectedEntries}
              compliance={compliance}
              split={splitActivities(plan, activities, compliance, selectedDate)}
              prefs={prefs}
              toggleBlocked={toggleBlocked}
              reloadPlan={reloadPlan}
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
          reloadPlan={reloadPlan}
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
