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

/** A token count, compact: 950 -> "950", 1_500 -> "1.5K", 12_400 -> "12K", 3_200_000 -> "3.2M". */
export function formatTokens(n: number | null | undefined, empty = "—"): string {
  if (n == null || !Number.isFinite(n) || n < 0) return empty;
  if (n < 1_000) return String(Math.round(n));
  if (n < 10_000) return `${(n / 1_000).toFixed(1)}K`;
  if (n < 999_500) return `${Math.round(n / 1_000)}K`;
  return `${(n / 1_000_000).toFixed(1)}M`;
}

/** US dollars: "$0.0042" under a cent, "$1.23" otherwise. Null (no estimate) returns `empty`. */
export function formatCost(usd: number | null | undefined, empty = "—"): string {
  if (usd == null || !Number.isFinite(usd) || usd < 0) return empty;
  if (usd === 0) return "$0.00";
  return usd < 0.01 ? `$${usd.toFixed(4)}` : `$${usd.toFixed(2)}`;
}
