// Pure calendar-grid maths: no React, no fetching.
import type { Activity, ComplianceById, ComplianceDay, Entry, GridCell, Plan, WeekStart, WeekSummary } from "./types";

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

/** Entries on a date, oldest first. */
export const entriesOn = (plan: Plan, dateStr: string): Entry[] => plan[dateStr] ?? [];

/** Group a flat entry list by date (the API returns it ordered by date, then id). */
export function groupByDate(entries: Entry[]): Plan {
  const plan: Plan = {};
  for (const e of entries) (plan[e.date] ??= []).push(e);
  return plan;
}

const SCORED_STATUSES = ["completed", "modified", "missed", "upcoming"];

/** One status for a whole day, from its scored entries: any miss makes the day a miss, then a
 *  shortened one, then upcoming; "completed" only when every scored entry was. Races, rest and
 *  yoga are never scored, so a day with only those has no status. */
export function dayCompliance(plan: Plan, compliance: ComplianceById, dateStr: string): ComplianceDay | undefined {
  const scored = entriesOn(plan, dateStr)
    .map(e => compliance[e.id])
    .filter((d): d is ComplianceDay => !!d && SCORED_STATUSES.includes(d.status));
  for (const status of ["missed", "modified", "upcoming"]) {
    const hit = scored.find(d => d.status === status);
    if (hit) return hit;
  }
  return scored[0];
}

/** Split a day's activities into those matched to one of its entries (shown merged into that
 *  entry in the UI) and the rest. Without a plan nothing is matched. */
export function splitActivities(
  plan: Plan,
  activities: Record<string, Activity[]>,
  compliance: ComplianceById,
  dateStr: string,
): { byEntry: Record<number, Activity>; others: Activity[] } {
  const all = activities[dateStr] ?? [];
  const byEntry: Record<number, Activity> = {};
  const used = new Set<number>();
  for (const e of entriesOn(plan, dateStr)) {
    const id = compliance[e.id]?.matched_activity_id;
    const hit = id != null ? all.find(a => a.id === id) : undefined;
    if (hit) { byEntry[e.id] = hit; used.add(hit.id); }
  }
  return { byEntry, others: all.filter(a => !used.has(a.id)) };
}

/** Week totals. Planned distance counts workouts only (a race is shown on its own, not as
 *  training volume). The workout counts only tally the backend-computed per-entry statuses
 *  (strides_ai/compliance.py) — no matching/tolerance logic lives here. */
export function summarizeWeek(
  cells: GridCell[],
  plan: Plan,
  activities: Record<string, Activity[]>,
  compliance: ComplianceById,
): WeekSummary {
  const summary: WeekSummary = {
    cells, plannedKm: 0, actualKm: 0, completed: 0, modified: 0, missed: 0, upcoming: 0,
  };
  for (const cell of cells) {
    for (const e of entriesOn(plan, cell.dateStr)) {
      if (e.kind === "workout") summary.plannedKm += e.distance_km ?? 0;
      const status = compliance[e.id]?.status;
      if (status === "completed") summary.completed++;
      else if (status === "modified") summary.modified++;
      else if (status === "missed") summary.missed++;
      else if (status === "upcoming") summary.upcoming++;
    }
    for (const a of activities[cell.dateStr] ?? []) summary.actualKm += (a.distance_m ?? 0) / 1000;
  }
  return summary;
}

/** A perfect week: at least one scored workout, and every one of them completed as planned,
 *  so nothing shortened, missed or still upcoming. */
export function isPerfectWeek(w: { completed: number; modified: number; missed: number; upcoming: number }): boolean {
  return w.completed > 0 && w.modified === 0 && w.missed === 0 && w.upcoming === 0;
}

/** The streak allows `maxMisses` misses a week: each is a heart. Misses spend them; one past
 *  the last heart loses the week. */
export function weekLives(missed: number, maxMisses: number): { left: number; spent: number; lost: boolean } {
  const spent = Math.min(missed, maxMisses);
  return { left: maxMisses - spent, spent, lost: missed > maxMisses };
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
