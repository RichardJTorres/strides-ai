import { useEffect, useState } from "react";
import Chat from "./pages/Chat";
import Activities from "./pages/Activities";
import Charts from "./pages/Charts";
import Calendar from "./pages/Calendar";
import Profile from "./pages/Profile";
import Settings from "./pages/Settings";

type Tab = "chat" | "activities" | "charts" | "calendar" | "profile" | "settings";
export type Mode = "running" | "cycling" | "hybrid" | "lifting";

export interface ThemeConfig {
  accentClass: string;
  accentBg: string;
  accentBorder: string;
  accentButton: string;
  accentFocus: string;
  accentActive: string;
  label: string;
}

// All Tailwind class strings are written as complete literals so JIT scanner picks them up
export const THEMES: Record<Mode, ThemeConfig> = {
  running: {
    accentClass: "text-green-400",
    accentBg: "bg-green-500/20",
    accentBorder: "border-green-500/30",
    accentButton: "bg-green-600 hover:bg-green-500",
    accentFocus: "focus:border-green-500/40 focus:ring-green-500/10",
    accentActive: "bg-green-500/20 text-green-400",
    label: "Running Coach",
  },
  cycling: {
    accentClass: "text-blue-400",
    accentBg: "bg-blue-500/20",
    accentBorder: "border-blue-500/30",
    accentButton: "bg-blue-600 hover:bg-blue-500",
    accentFocus: "focus:border-blue-500/40 focus:ring-blue-500/10",
    accentActive: "bg-blue-500/20 text-blue-400",
    label: "Cycling Coach",
  },
  hybrid: {
    accentClass: "text-purple-400",
    accentBg: "bg-purple-500/20",
    accentBorder: "border-purple-500/30",
    accentButton: "bg-purple-600 hover:bg-purple-500",
    accentFocus: "focus:border-purple-500/40 focus:ring-purple-500/10",
    accentActive: "bg-purple-500/20 text-purple-400",
    label: "Hybrid Coach",
  },
  lifting: {
    accentClass: "text-orange-400",
    accentBg: "bg-orange-500/20",
    accentBorder: "border-orange-500/30",
    accentButton: "bg-orange-600 hover:bg-orange-500",
    accentFocus: "focus:border-orange-500/40 focus:ring-orange-500/10",
    accentActive: "bg-orange-500/20 text-orange-400",
    label: "Lifting Coach",
  },
};

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
  charts: (
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
  { id: "charts", label: "Charts" },
  { id: "calendar", label: "Calendar" },
  { id: "profile", label: "Profile" },
];

const VALID_TABS = new Set<string>([...TABS.map((t) => t.id), "settings"]);

function tabFromHash(): Tab {
  const hash = location.hash.slice(1);
  return VALID_TABS.has(hash) ? (hash as Tab) : "chat";
}

type ModeMeta = { activity_label: string; hidden_tabs: string[]; has_analysis: boolean };

export default function App() {
  const [tab, setTab] = useState<Tab>(tabFromHash);
  const [mode, setMode] = useState<Mode>("running");
  const [modeLoaded, setModeLoaded] = useState(false);
  const [supportsAttachments, setSupportsAttachments] = useState(false);
  const [modeMeta, setModeMeta] = useState<Record<string, ModeMeta>>({});

  useEffect(() => {
    const onHashChange = () => setTab(tabFromHash());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  // Load persisted mode and mode metadata from server on mount
  useEffect(() => {
    Promise.all([
      fetch("/api/settings").then((r) => r.json()),
      fetch("/api/modes").then((r) => r.json()),
    ])
      .then(([settings, modes]: [{ mode: Mode }, Record<string, ModeMeta>]) => {
        if (settings.mode) setMode(settings.mode);
        setModeMeta(modes);
      })
      .catch(() => {})
      .finally(() => setModeLoaded(true));
  }, []);

  function refreshStatus() {
    fetch("/api/status")
      .then((r) => r.json())
      .then((data: { supports_attachments?: boolean }) => {
        setSupportsAttachments(data.supports_attachments ?? false);
      })
      .catch(() => {});
  }

  // Load backend capabilities on mount
  useEffect(refreshStatus, []);

  function navigate(t: Tab) {
    location.hash = t;
  }

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
      <div className="flex h-screen bg-gray-950 items-center justify-center text-gray-500 text-sm">
        Loading…
      </div>
    );
  }

  const visibleTabs = TABS.filter((t) => !hiddenTabs.has(t.id as Tab));
  const allNavTabs: { id: Tab; label: string }[] = [...visibleTabs, { id: "settings", label: "Settings" }];
  const mobileNavTabs = allNavTabs.filter((t) => t.id !== "calendar");

  return (
    <div className="flex h-dvh bg-gray-950 text-gray-100">
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
        {tab === "chat" && <Chat mode={mode} theme={theme} supportsAttachments={supportsAttachments} />}
        {tab === "activities" && <Activities mode={mode} theme={theme} />}
        {tab === "charts" && <Charts mode={mode} theme={theme} />}
        {tab === "calendar" && <Calendar />}
        {tab === "profile" && <Profile mode={mode} theme={theme} />}
        {tab === "settings" && <Settings mode={mode} setMode={setMode} theme={theme} onProviderChanged={refreshStatus} />}
      </main>

      {/* Bottom nav — mobile only */}
      <nav className="md:hidden fixed bottom-0 inset-x-0 bg-gray-900 border-t border-gray-800 flex z-20">
        {mobileNavTabs.map((t) => (
          <button
            key={t.id}
            onClick={() => navigate(t.id)}
            className={`flex-1 flex flex-col items-center justify-center gap-0.5 py-2.5 px-1 transition-colors ${
              tab === t.id ? `${theme.accentClass}` : "text-gray-500"
            }`}
          >
            {ICONS[t.id]}
            <span className="text-[9px] leading-none mt-0.5">{t.label}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}
