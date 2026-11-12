// Shared display formatting for things that are not measurements (those live in units.ts).

export type DateStyle = "short" | "long" | "weekday";

const DATE_STYLES: Record<DateStyle, Intl.DateTimeFormatOptions> = {
  short: { month: "short", day: "numeric" },
  long: { month: "short", day: "numeric", year: "numeric" },
  weekday: { weekday: "short", month: "short", day: "numeric" },
};

/**
 * "YYYY-MM-DD" (or an ISO timestamp) -> a date in the reader's locale. A date-only string is a
 * calendar day, so it is read as local midnight — `new Date("2026-06-01")` would be UTC and show
 * the previous day west of Greenwich. Empty or unparseable input returns `empty`.
 */
export function formatDate(
  iso: string | null | undefined,
  style: DateStyle = "long",
  locale?: string,
  empty = "—",
): string {
  if (!iso) return empty;
  const d = new Date(/^\d{4}-\d{2}-\d{2}$/.test(iso) ? `${iso}T00:00:00` : iso);
  if (Number.isNaN(d.getTime())) return empty;
  return d.toLocaleDateString(locale, DATE_STYLES[style]);
}

/** Seconds -> "1h 05m", "45m" or "50s". Null, negative or non-finite input returns `empty`. */
export function formatDuration(seconds: number | null | undefined, empty = "—"): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return empty;
  const total = Math.round(seconds);
  if (total < 60) return `${total}s`;
  const minutes = Math.round(total / 60);
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h > 0 ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m`;
}
