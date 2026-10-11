// Date-range filter primitives shared by every charts page.

import type { ChartDataset } from "./api";

export type FilterPreset =
  | "this-month"
  | "last-month"
  | "ytd"
  | "last-3m"
  | "last-6m"
  | "last-year"
  | "all-time"
  | "custom";

export interface DateRange {
  since: string | null; // YYYY-MM-DD
  until: string | null;
}

export const PRESETS: { id: FilterPreset; label: string }[] = [
  { id: "this-month", label: "This Month" },
  { id: "last-month", label: "Last Month" },
  { id: "ytd", label: "Year to Date" },
  { id: "last-3m", label: "Last 3M" },
  { id: "last-6m", label: "Last 6M" },
  { id: "last-year", label: "Last Year" },
  { id: "all-time", label: "All Time" },
  { id: "custom", label: "Custom" },
];

export function getPresetRange(preset: FilterPreset): DateRange {
  if (preset === "all-time" || preset === "custom") return { since: null, until: null };
  const today = new Date();
  const y = today.getFullYear();
  const m = today.getMonth();
  const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  switch (preset) {
    case "this-month":
      return { since: iso(new Date(y, m, 1)), until: null };
    case "last-month":
      return { since: iso(new Date(y, m - 1, 1)), until: iso(new Date(y, m, 0)) };
    case "ytd":
      return { since: `${y}-01-01`, until: null };
    case "last-3m": {
      const d = new Date(today);
      d.setMonth(m - 3);
      return { since: iso(d), until: null };
    }
    case "last-6m": {
      const d = new Date(today);
      d.setMonth(m - 6);
      return { since: iso(d), until: null };
    }
    case "last-year": {
      const d = new Date(today);
      d.setFullYear(y - 1);
      return { since: iso(d), until: null };
    }
  }
}

export function filterByDate<T>(
  items: T[],
  key: keyof T,
  since: string | null,
  until: string | null,
): T[] {
  if (!since && !until) return items;
  return items.filter((item) => {
    const d = String(item[key] ?? "");
    if (since && d < since) return false;
    if (until && d > until) return false;
    return true;
  });
}

/**
 * Apply a date-range filter to any ChartDataset variant, trimming only what's DISPLAYED.
 * Rolling averages must already be computed server-side over full history — this never
 * re-derives them, it only slices which points are shown.
 */
// Include a week when any day overlaps the selected range. Weekly totals remain whole-week totals.
function filterWeeks<T extends { week: string }>(items: T[], since: string | null, until: string | null): T[] {
  return items.filter((item) => {
    const end = new Date(`${item.week}T12:00:00`);
    end.setDate(end.getDate() + 6);
    const endIso = `${end.getFullYear()}-${String(end.getMonth() + 1).padStart(2, "0")}-${String(end.getDate()).padStart(2, "0")}`;
    return (!since || endIso >= since) && (!until || item.week <= until);
  });
}

export function filterDatasetByRange(
  dataset: ChartDataset,
  since: string | null,
  until: string | null,
): ChartDataset {
  switch (dataset.chart_type) {
    case "weekly_bar":
      return { ...dataset, data: filterWeeks(dataset.data, since, until) };
    case "stacked_bar":
      return { ...dataset, data: filterWeeks(dataset.data, since, until) };
    case "atl_ctl":
      return { ...dataset, data: filterByDate(dataset.data, "date", since, until) };
    case "time_series":
      return { ...dataset, data: filterByDate(dataset.data, "date", since, until) };
    case "scatter":
      return {
        ...dataset,
        scatter: filterByDate(dataset.scatter, "date", since, until),
        rolling_avg: filterByDate(dataset.rolling_avg, "date", since, until),
      };
  }
}

/** Number of points currently visible after a range filter, for the "available but empty in
 * this range" distinction — independent of dataset.available (lifetime availability). */
export function visiblePointCount(dataset: ChartDataset): number {
  return dataset.chart_type === "scatter" ? dataset.scatter.length : dataset.data.length;
}
