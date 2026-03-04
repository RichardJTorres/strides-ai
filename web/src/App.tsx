import { useEffect, useState } from "react";
import Chat from "./pages/Chat";
import Activities from "./pages/Activities";
import Charts from "./pages/Charts";
import Profile from "./pages/Profile";

type Tab = "chat" | "activities" | "charts" | "profile";

const TABS: { id: Tab; label: string }[] = [
  { id: "chat", label: "Coach" },
  { id: "activities", label: "Activities" },
  { id: "charts", label: "Charts" },
  { id: "profile", label: "Profile" },
];

const VALID_TABS = new Set<string>(TABS.map((t) => t.id));

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
                className={`w-full text-left px-3 py-2 rounded-md text-sm transition-colors ${
                  tab === t.id
                    ? "bg-green-500/20 text-green-400 font-medium"
                    : "text-gray-400 hover:bg-gray-800 hover:text-gray-100"
                }`}
              >
                {t.label}
              </button>
            </li>
          ))}
        </ul>
      </nav>

      {/* Main content */}
      <main className="flex-1 overflow-hidden">
        {tab === "chat" && <Chat />}
        {tab === "activities" && <Activities />}
        {tab === "charts" && <Charts />}
        {tab === "profile" && <Profile />}
      </main>
    </div>
  );
}
