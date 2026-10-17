/** Human-readable "time since last sync" shared by Chat and Activities. */
export function formatSyncFreshness(lastSyncAt: string | null): string {
  if (!lastSyncAt) return "Never synced";
  // The backend always writes an offset-aware ISO string (e.g. "...+00:00");
  // only bare/naive strings need "Z" appended to parse as UTC.
  const hasTimezone = /Z$|[+-]\d{2}:\d{2}$/.test(lastSyncAt);
  const then = new Date(hasTimezone ? lastSyncAt : lastSyncAt + "Z").getTime();
  if (Number.isNaN(then)) return "Never synced";
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 60) return "Synced just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `Synced ${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `Synced ${hours}h ago`;
  const days = Math.round(hours / 24);
  return `Synced ${days}d ago`;
}
