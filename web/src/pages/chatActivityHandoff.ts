/**
 * sessionStorage handoff for "Discuss in chat": the Activities panel sets this
 * key and navigates to #chat; Chat consumes and clears it on mount, same
 * pattern as Chat's own SCROLL_KEY.
 */
export const PENDING_CHAT_ACTIVITY_KEY = "pending_chat_activity_id";

/** Same handoff, for a drafted (never auto-sent) chat message, e.g. an Insights recommendation. */
export const PENDING_CHAT_DRAFT_KEY = "pending_chat_draft";
