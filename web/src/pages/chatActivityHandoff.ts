/**
 * sessionStorage handoffs into the chat. A page writes one and navigates to #chat; Chat consumes
 * and clears it on mount. One-shot on purpose: unlike a URL it cannot re-fire on reload.
 */
export const PENDING_CHAT_ACTIVITY_KEY = "pending_chat_activity";

/** A drafted (never auto-sent) chat message, e.g. an Insights recommendation. */
export const PENDING_CHAT_DRAFT_KEY = "pending_chat_draft";

/** What the chat needs to show an attached activity, so it does not have to fetch the list. */
export interface ActivityHandoff {
  id: number;
  name: string | null;
  date: string | null;
  sport_type: string | null;
  deep_dive_report: string | null;
}

/** Queue an activity to be attached to the next chat message. Best-effort. */
export function handOffActivity(
  a: Omit<ActivityHandoff, "deep_dive_report"> & { deep_dive_report?: string | null },
): void {
  try {
    const { id, name, date, sport_type } = a;
    sessionStorage.setItem(
      PENDING_CHAT_ACTIVITY_KEY,
      // Only whether a deep dive exists matters to the chat; the report itself can be large.
      JSON.stringify({ id, name, date, sport_type, deep_dive_report: a.deep_dive_report ? "1" : null }),
    );
  } catch { /* storage unavailable: the chat simply opens without the attachment */ }
}

/** Take (and clear) the queued activity; null when there is none or it is unreadable. */
export function takeActivityHandoff(): ActivityHandoff | null {
  try {
    const raw = sessionStorage.getItem(PENDING_CHAT_ACTIVITY_KEY);
    if (!raw) return null;
    sessionStorage.removeItem(PENDING_CHAT_ACTIVITY_KEY);
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed.id === "number" ? (parsed as ActivityHandoff) : null;
  } catch {
    return null;
  }
}
