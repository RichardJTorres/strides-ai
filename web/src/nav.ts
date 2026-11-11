// Hash routing with one optional parameter: `#<tab>[/<param>]`.
//   #activities/123        an activity's detail panel
//   #calendar/2026-11-10   a calendar day
//   #analytics/progress    an Analytics tab
// The URL is the selection state, so links are shareable and Back closes a panel.

export const TABS = [
  "chat",
  "activities",
  "analytics",
  "calendar",
  "profile",
  "memories",
  "settings",
] as const;
export type Tab = (typeof TABS)[number];

export interface Route {
  tab: Tab;
  param: string | null;
}

// What each tab accepts as its parameter; anything else is dropped rather than passed on.
const PARAM_PATTERNS: Partial<Record<Tab, RegExp>> = {
  activities: /^\d+$/,
  calendar: /^\d{4}-\d{2}-\d{2}$/,
  analytics: /^[a-z][a-z0-9_-]*$/,
};

export function parseHash(hash: string): Route {
  const [rawTab = "", ...rest] = hash.replace(/^#/, "").split("/");
  const name = rawTab === "charts" ? "analytics" : rawTab; // legacy #charts links
  if (!(TABS as readonly string[]).includes(name)) return { tab: "chat", param: null };
  const tab = name as Tab;
  const param = rest.join("/");
  return { tab, param: PARAM_PATTERNS[tab]?.test(param) ? param : null };
}

export function hrefFor(tab: Tab, param?: string | number | null): string {
  return param == null || param === "" ? `#${tab}` : `#${tab}/${param}`;
}

/**
 * Go to a route. `replace` swaps the current history entry instead of adding one — for changing
 * a selection within a page (day to day), so Back leaves the page rather than replaying clicks.
 */
export function navigate(
  tab: Tab,
  param?: string | number | null,
  opts: { replace?: boolean } = {},
): void {
  const href = hrefFor(tab, param);
  if (!opts.replace) {
    location.hash = href;
    return;
  }
  if (location.hash === href) return;
  history.replaceState(null, "", href);
  // replaceState does not fire hashchange, which is what the app listens to.
  window.dispatchEvent(new HashChangeEvent("hashchange"));
}
