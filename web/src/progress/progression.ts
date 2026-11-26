// GET /api/progress/months — mirrors Progression / MonthRow / Peak in strides_ai/progress.py.
// Keep in sync. Values are SI (meters); convert with units.ts before showing them.
// Pure and import-free on purpose: web/progression.test.mjs loads this file on its own.

export interface ProgressionPeak {
  activity_id: number;
  date: string;
  name: string;
  value: number;
}

export interface ProgressionMonth {
  month: string; // "YYYY-MM"
  activities: number;
  hours: number;
  distance_m: number;
  climb_m: number;
  climb_m_per_km: number | null;
  longest: ProgressionPeak | null;
  most_climb: ProgressionPeak | null;
  in_progress: boolean;
}

export interface Progression {
  sport: "run" | "ride";
  as_of: string;
  first_date: string | null;
  omitted: number;
  months: ProgressionMonth[]; // newest first
}

export type PeakMetric = "longest" | "most_climb";

export interface ProgressionChartRow {
  month: string;
  label: string;
  hours: number;
  /** The month's peak in display units; null when the month has none. */
  peak: number | null;
  peakName: string | null;
  peakDate: string | null;
  peakId: number | null;
  inProgress: boolean;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-11" -> "Nov '26". Not locale-formatted, so it is the same everywhere and testable. */
export function monthLabel(month: string): string {
  const [year, mm] = month.split("-");
  const name = MONTHS[Number(mm) - 1];
  return name && year ? `${name} '${year.slice(2)}` : month;
}

/** Oldest first for the chart's x-axis. `toDisplay` converts the peak's SI value. */
export function chartRows(
  p: Progression,
  metric: PeakMetric,
  toDisplay: (si: number) => number,
): ProgressionChartRow[] {
  return [...p.months].reverse().map((m) => {
    const pk = m[metric];
    return {
      month: m.month,
      label: monthLabel(m.month),
      hours: m.hours,
      peak: pk ? toDisplay(pk.value) : null,
      peakName: pk ? pk.name : null,
      peakDate: pk ? pk.date : null,
      peakId: pk ? pk.activity_id : null,
      inProgress: m.in_progress,
    };
  });
}

/** A drafted (never auto-sent) question about the months the chart shows. */
export function coachDraft(sport: "run" | "ride", rows: ProgressionChartRow[]): string {
  const noun = sport === "run" ? "running" : "riding";
  const span = rows.length ? ` (${rows[0].label} to ${rows[rows.length - 1].label})` : "";
  return (
    `Looking at my monthly ${noun} progression${span}: how have I grown as an athlete? ` +
    "Compare my capacity and how hard comparable sessions were then and now."
  );
}
