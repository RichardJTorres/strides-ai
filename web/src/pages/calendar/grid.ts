// Pure calendar-grid maths: no React, no fetching.
import type { Activity, ComplianceDay, GridCell, Plan, WeekStart, WeekSummary } from "./types";

export const dateToStr = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/** The month as full weeks, including the leading/trailing days of the adjacent months, so a
 *  week is never cut off mid-row. Monday-first (the default) matches every weekly figure the
 *  backend computes (ramp, streak), so a row is exactly one of its weeks; Sunday-first
 *  is a display preference. */
export function buildGrid(month: Date, weekStart: WeekStart = "monday"): GridCell[] {
  const daysInMonth = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
  // Days between the first row's start and the 1st (getDay(): Sunday = 0).
  const firstDow =
    (new Date(month.getFullYear(), month.getMonth(), 1).getDay() + (weekStart === "monday" ? 6 : 0)) % 7;
  const totalCells = Math.ceil((firstDow + daysInMonth) / 7) * 7;
  const gridStart = new Date(month.getFullYear(), month.getMonth(), 1 - firstDow);
  return Array.from({ length: totalCells }, (_, i) => {
    const d = new Date(gridStart.getFullYear(), gridStart.getMonth(), gridStart.getDate() + i);
    return {
      date: d,
      dateStr: dateToStr(d),
      dayNum: d.getDate(),
      inCurrentMonth: d.getMonth() === month.getMonth(),
    };
  });
}

export function chunkWeeks(cells: GridCell[]): GridCell[][] {
  const weeks: GridCell[][] = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
  return weeks;
}

/** The seven days starting at `startStr` ("YYYY-MM-DD"). */
export function weekFrom(startStr: string): GridCell[] {
  const [y, m, d] = startStr.split("-").map(Number);
  return Array.from({ length: 7 }, (_, i) => {
    const date = new Date(y, m - 1, d + i);
    return { date, dateStr: dateToStr(date), dayNum: date.getDate(), inCurrentMonth: true };
  });
}

/** Split a day's activities into the one matched to its planned workout (merged into the
 *  workout in the UI) and the rest. Without a plan nothing is matched. */
export function splitActivities(
  plan: Plan,
  activities: Record<string, Activity[]>,
  compliance: Record<string, ComplianceDay>,
  dateStr: string,
): { matched: Activity | undefined; others: Activity[] } {
  const all = activities[dateStr] ?? [];
  const matchedId = plan[dateStr] ? compliance[dateStr]?.matched_activity_id : null;
  const matched = matchedId != null ? all.find(a => a.id === matchedId) : undefined;
  return { matched, others: matched ? all.filter(a => a !== matched) : all };
}

/** Week totals. The workout counts only tally the backend-computed per-day statuses
 *  (strides_ai/compliance.py) — no matching/tolerance logic lives here. */
export function summarizeWeek(
  cells: GridCell[],
  plan: Plan,
  activities: Record<string, Activity[]>,
  compliance: Record<string, ComplianceDay>,
): WeekSummary {
  const summary: WeekSummary = {
    cells, plannedKm: 0, actualKm: 0, completed: 0, modified: 0, missed: 0, upcoming: 0,
  };
  for (const cell of cells) {
    const w = plan[cell.dateStr];
    summary.plannedKm += w && w.workout_type !== "Rest" ? (w.distance_km ?? 0) : 0;
    for (const a of activities[cell.dateStr] ?? []) summary.actualKm += (a.distance_m ?? 0) / 1000;
    const status = compliance[cell.dateStr]?.status;
    if (status === "completed") summary.completed++;
    else if (status === "modified") summary.modified++;
    else if (status === "missed") summary.missed++;
    else if (status === "upcoming") summary.upcoming++;
  }
  return summary;
}

/** A perfect week: at least one scored workout, and every one of them completed as planned,
 *  so nothing shortened, missed or still upcoming. */
export function isPerfectWeek(w: { completed: number; modified: number; missed: number; upcoming: number }): boolean {
  return w.completed > 0 && w.modified === 0 && w.missed === 0 && w.upcoming === 0;
}

/** "3 as planned · 1 shortened · 1 missed" — only the non-zero parts. "Done" elsewhere means
 *  completed + shortened; "shortened" is the UI name for the API status `modified`. */
export function weekBreakdown(w: { completed: number; modified: number; missed: number }): string {
  return [
    w.completed > 0 && `${w.completed} as planned`,
    w.modified > 0 && `${w.modified} shortened`,
    w.missed > 0 && `${w.missed} missed`,
  ].filter(Boolean).join(" · ");
}

/** Days in an inclusive "YYYY-MM-DD" range. */
export function rangeLength(range: { start: string; end: string }): number {
  return Math.round(
    (new Date(range.end + "T12:00:00").getTime() - new Date(range.start + "T12:00:00").getTime()) /
      86_400_000
  ) + 1;
}
