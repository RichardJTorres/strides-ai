import { useEffect, useState } from "react";
import Chat from "./pages/Chat";
import Activities from "./pages/Activities";
import Charts from "./pages/Charts";
import Profile from "./pages/Profile";
import Settings from "./pages/Settings";

type Tab = "chat" | "activities" | "charts" | "profile" | "settings";

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
  { id: "profile", label: "Profile" },
];

const VALID_TABS = new Set<string>([...TABS.map((t) => t.id), "settings"]);

function tabFromHash(): Tab {
  const hash = location.hash.slice(1);
  return VALID_TABS.has(hash) ? (hash as Tab) : "chat";
}

export default function App() {
  const [tab, setTab] = useState<Tab>(tabFromHash);

  useEffect(() => {
    const onHashChange = () => setTab(tabFromHash());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  function navigate(t: Tab) {
    location.hash = t;
  }

  return (
    <div className="flex h-screen bg-gray-950 text-gray-100">
      {/* Sidebar */}
      <nav className="w-48 shrink-0 bg-gray-900 border-r border-gray-800 flex flex-col">
        <div className="p-4 border-b border-gray-800">
          <h1 className="font-bold text-green-400 text-lg">Strides AI</h1>
          <p className="text-xs text-gray-500 mt-0.5">Running Coach</p>
        </div>
        <ul className="flex-1 p-2 space-y-1">
          {TABS.map((t) => (
            <li key={t.id}>
              <button
                onClick={() => navigate(t.id)}
                className={`w-full text-left px-3 py-2 rounded-md text-sm transition-colors flex items-center gap-2 ${
                  tab === t.id
                    ? "bg-green-500/20 text-green-400 font-medium"
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
                ? "bg-green-500/20 text-green-400 font-medium"
                : "text-gray-400 hover:bg-gray-800 hover:text-gray-100"
            }`}
          >
            {ICONS.settings}
            Settings
          </button>
        </div>
      </nav>

      {/* Main content */}
      <main className="flex-1 overflow-hidden">
        {tab === "chat" && <Chat />}
        {tab === "activities" && <Activities />}
        {tab === "charts" && <Charts />}
        {tab === "profile" && <Profile />}
        {tab === "settings" && <Settings />}
      </main>
    </div>
  );
}
