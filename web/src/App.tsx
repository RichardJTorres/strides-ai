import { lazy, Suspense, useEffect, useState, type CSSProperties } from "react";
import Chat from "./pages/Chat";
import Activities from "./pages/Activities";
import Calendar from "./pages/Calendar";
import Profile from "./pages/profile/ProfilePage";
import Settings from "./pages/Settings";
import Memories from "./pages/Memories";
import { UnitsProvider } from "./UnitsContext";
import { DEFAULT_UNIT_SYSTEM, parseUnitSystem, type UnitSystem } from "./units";
import { navigate, parseHash, type Route, type Tab } from "./nav";
import { LoadingState } from "./ui/states";
import { ThemeProvider, THEMES, type Mode } from "./ui/theme";

const Charts = lazy(() => import("./pages/Charts"));

// Re-exported so pages can keep importing the theme types from the app root.
export { THEMES, type Mode, type ThemeConfig } from "./ui/theme";

const ICONS: Record<Tab, JSX.Element> = {
  chat: (
    <svg xmlns="http://www.w3.org/2000/svg" className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
    </svg>
  ),
  activities: (
    <svg xmlns="http://www.w3.org/2000/svg" className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
    </svg>
  ),
  analytics: (
    <svg xmlns="http://www.w3.org/2000/svg" className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
    </svg>
  ),
  calendar: (
    <svg xmlns="http://www.w3.org/2000/svg" className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
      <line x1="16" y1="2" x2="16" y2="6"/>
      <line x1="8" y1="2" x2="8" y2="6"/>
      <line x1="3" y1="10" x2="21" y2="10"/>
    </svg>
  ),
  profile: (
    <svg xmlns="http://www.w3.org/2000/svg" className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
      <circle cx="12" cy="7" r="4"/>
    </svg>
  ),
  memories: (
    <svg xmlns="http://www.w3.org/2000/svg" className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/>
      <polyline points="3.27 6.96 12 12.01 20.73 6.96"/>
      <line x1="12" y1="22.08" x2="12" y2="12"/>
    </svg>
  ),
  settings: (
    <svg xmlns="http://www.w3.org/2000/svg" className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3"/>
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
    </svg>
  ),
};

const TABS: { id: Tab; label: string }[] = [
  { id: "chat", label: "Coach" },
  { id: "activities", label: "Activities" },
  { id: "analytics", label: "Analytics" },
  { id: "calendar", label: "Calendar" },
  { id: "profile", label: "Profile" },
  { id: "memories", label: "Memories" },
];

// Tabs that fit in the phone's bottom bar; the rest sit behind "More".
const MOBILE_PRIMARY: Tab[] = ["chat", "activities", "analytics", "calendar"];

const MORE_ICON = (
  <svg xmlns="http://www.w3.org/2000/svg" className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>
  </svg>
);

type ModeMeta = { activity_label: string; hidden_tabs: string[]; has_analysis: boolean };

export default function App() {
  const [route, setRoute] = useState<Route>(() => parseHash(location.hash));
  const tab = route.tab;
  const [moreOpen, setMoreOpen] = useState(false);
  const [mode, setMode] = useState<Mode>("running");
  const [modeLoaded, setModeLoaded] = useState(false);
  const [initialUnits, setInitialUnits] = useState<UnitSystem>(DEFAULT_UNIT_SYSTEM);
  const [supportsAttachments, setSupportsAttachments] = useState(false);
  const [modeMeta, setModeMeta] = useState<Record<string, ModeMeta>>({});
  const [lastSyncAt, setLastSyncAt] = useState<string | null>(null);

  useEffect(() => {
    const onHashChange = () => {
      setRoute(parseHash(location.hash));
      setMoreOpen(false);
    };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  // Load persisted mode and mode metadata from server on mount
  useEffect(() => {
    Promise.all([
      fetch("/api/settings").then((r) => r.json()),
      fetch("/api/modes").then((r) => r.json()),
    ])
      .then(([settings, modes]: [{ mode: Mode; unit_system?: string }, Record<string, ModeMeta>]) => {
        if (settings.mode) setMode(settings.mode);
        setInitialUnits(parseUnitSystem(settings.unit_system));
        setModeMeta(modes);
      })
      .catch(() => {})
      .finally(() => setModeLoaded(true));
  }, []);

  function refreshStatus() {
    fetch("/api/status")
      .then((r) => r.json())
      .then((data: { supports_attachments?: boolean; last_sync_at?: string | null }) => {
        setSupportsAttachments(data.supports_attachments ?? false);
        setLastSyncAt(data.last_sync_at ?? null);
      })
      .catch(() => {});
  }

  // Load backend capabilities on mount
  useEffect(refreshStatus, []);

  // Replies still generating, or finished and not yet seen (turns outlive the Chat page).
  const [pendingModes, setPendingModes] = useState<string[]>([]);
  useEffect(() => {
    let live = true;
    const poll = () =>
      fetch("/api/chat/pending")
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => live && d && setPendingModes(d.modes ?? []))
        .catch(() => {});
    poll();
    const timer = setInterval(poll, 4000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, []);
  // The reply you are watching in the open Chat tab is not "away".
  const chatDot = pendingModes.some((m) => !(tab === "chat" && m === mode));

  const theme = THEMES[mode];

  const hiddenTabs = new Set<Tab>((modeMeta[mode]?.hidden_tabs ?? []) as Tab[]);

  // Redirect away from tabs that aren't available in the current mode
  useEffect(() => {
    if (hiddenTabs.has(tab)) {
      navigate("chat");
    }
  }, [mode]);

  if (!modeLoaded) {
    return (
      <div className="flex h-screen bg-gray-950 items-center justify-center">
        <LoadingState />
      </div>
    );
  }

  const visibleTabs = TABS.filter((t) => !hiddenTabs.has(t.id as Tab));
  const allNavTabs: { id: Tab; label: string }[] = [...visibleTabs, { id: "settings", label: "Settings" }];
  const mobilePrimary = allNavTabs.filter((t) => MOBILE_PRIMARY.includes(t.id));
  const mobileMore = allNavTabs.filter((t) => !MOBILE_PRIMARY.includes(t.id));
  const moreActive = mobileMore.some((t) => t.id === tab);

  return (
    <UnitsProvider initial={initialUnits}>
    <ThemeProvider mode={mode}>
    <div
      className="flex h-dvh bg-gray-950 text-gray-100"
      style={{ "--accent": theme.accentHex } as CSSProperties}
    >
      {/* Sidebar — desktop only */}
      <nav className="hidden md:flex w-48 shrink-0 bg-gray-900 border-r border-gray-800 flex-col">
        <div className="p-4 border-b border-gray-800">
          <h1 className={`font-bold ${theme.accentClass} text-lg`}>Strides AI</h1>
          <p className="text-xs text-gray-500 mt-0.5">{theme.label}</p>
        </div>
        <ul className="flex-1 p-2 space-y-1">
          {visibleTabs.map((t) => (
            <li key={t.id}>
              <button
                onClick={() => navigate(t.id)}
                className={`w-full text-left px-3 py-2 rounded-md text-sm transition-colors flex items-center gap-2 ${
                  tab === t.id
                    ? `${theme.accentActive} font-medium`
                    : "text-gray-400 hover:bg-gray-800 hover:text-gray-100"
                }`}
              >
                {ICONS[t.id]}
                {t.label}
                {t.id === "chat" && chatDot && (
                  <span
                    className="ml-auto h-2 w-2 rounded-full bg-[var(--accent)]"
                    title="A reply is in progress or waiting"
                    aria-label="Coach reply in progress or waiting"
                  />
                )}
              </button>
            </li>
          ))}
        </ul>
        <div className="p-2 border-t border-gray-800">
          <button
            onClick={() => navigate("settings")}
            className={`w-full text-left px-3 py-2 rounded-md text-sm transition-colors flex items-center gap-2 ${
              tab === "settings"
                ? `${theme.accentActive} font-medium`
                : "text-gray-400 hover:bg-gray-800 hover:text-gray-100"
            }`}
          >
            {ICONS.settings}
            Settings
          </button>
        </div>
      </nav>

      {/* Main content — shrinks on mobile to leave room for bottom nav */}
      <main className="flex-1 overflow-hidden pb-14 md:pb-0">
        {tab === "chat" && (
          <Chat
            key={mode}
            mode={mode}
            theme={theme}
            supportsAttachments={supportsAttachments}
            lastSyncAt={lastSyncAt}
            onSynced={refreshStatus}
          />
        )}
        {tab === "activities" && (
          <Activities
            mode={mode}
            theme={theme}
            lastSyncAt={lastSyncAt}
            onSynced={refreshStatus}
            routeParam={route.param}
          />
        )}
        {tab === "analytics" && (
          <Suspense fallback={<div role="status" className="p-6 text-gray-400">Loading analytics…</div>}>
            <Charts mode={mode} theme={theme} routeParam={route.param} />
          </Suspense>
        )}
        {tab === "calendar" && <Calendar routeParam={route.param} />}
        {tab === "profile" && <Profile mode={mode} theme={theme} />}
        {tab === "memories" && <Memories />}
        {tab === "settings" && <Settings mode={mode} setMode={setMode} theme={theme} onProviderChanged={refreshStatus} />}
      </main>

      {/* Bottom nav — mobile only */}
      {moreOpen && (
        <div className="md:hidden fixed inset-0 z-20" onClick={() => setMoreOpen(false)}>
          <ul
            id="more-menu"
            className="absolute bottom-14 right-2 w-44 rounded-lg border border-gray-800 bg-gray-900 p-1 shadow-xl"
          >
            {mobileMore.map((t) => (
              <li key={t.id}>
                <button
                  onClick={() => navigate(t.id)}
                  className={`w-full text-left px-3 py-2.5 rounded-md text-sm flex items-center gap-2 ${
                    tab === t.id ? `${theme.accentActive} font-medium` : "text-gray-300"
                  }`}
                >
                  {ICONS[t.id]}
                  {t.label}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      <nav className="md:hidden fixed bottom-0 inset-x-0 bg-gray-900 border-t border-gray-800 flex z-20">
        {mobilePrimary.map((t) => (
          <button
            key={t.id}
            onClick={() => navigate(t.id)}
            className={`flex-1 flex flex-col items-center justify-center gap-0.5 py-2.5 px-1 transition-colors ${
              tab === t.id ? `${theme.accentClass}` : "text-gray-500"
            }`}
          >
            <span className="relative">
              {ICONS[t.id]}
              {t.id === "chat" && chatDot && (
                <span
                  className="absolute -right-1 -top-0.5 h-2 w-2 rounded-full bg-[var(--accent)]"
                  aria-label="Coach reply in progress or waiting"
                />
              )}
            </span>
            <span className="text-[10px] leading-none mt-0.5">{t.label}</span>
          </button>
        ))}
        {mobileMore.length > 0 && (
          <button
            onClick={() => setMoreOpen((open) => !open)}
            aria-expanded={moreOpen}
            aria-controls="more-menu"
            className={`flex-1 flex flex-col items-center justify-center gap-0.5 py-2.5 px-1 transition-colors ${
              moreActive || moreOpen ? `${theme.accentClass}` : "text-gray-500"
            }`}
          >
            {MORE_ICON}
            <span className="text-[10px] leading-none mt-0.5">More</span>
          </button>
        )}
      </nav>
    </div>
    </ThemeProvider>
    </UnitsProvider>
  );
}
