// Date-range filter primitives shared by every charts page.

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
  const iso = (d: Date) => d.toISOString().slice(0, 10);
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
