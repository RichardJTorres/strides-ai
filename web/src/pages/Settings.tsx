import { useState, useEffect, type Dispatch, type SetStateAction } from "react";
import type { Mode, ThemeConfig } from "../App";

interface Provider {
  id: string;
  label: string;
  default_model: string;
  configured: boolean;
  active: boolean;
  config_hint: string | null;
}

interface Props {
  mode: Mode;
  setMode: Dispatch<SetStateAction<Mode>>;
  theme: ThemeConfig;
}

const MODE_CARDS: {
  id: Mode;
  label: string;
  description: string;
  accentClass: string;
  borderSelected: string;
  dotClass: string;
}[] = [
  {
    id: "running",
    label: "Running",
    description: "Running activities only. Coaching focused on pace, cadence, and running load.",
    accentClass: "text-green-400",
    borderSelected: "border-green-500",
    dotClass: "bg-green-500",
  },
  {
    id: "cycling",
    label: "Cycling",
    description: "Cycling activities only. Coaching focused on speed, power, and ride load.",
    accentClass: "text-blue-400",
    borderSelected: "border-blue-500",
    dotClass: "bg-blue-500",
  },
  {
    id: "hybrid",
    label: "Hybrid",
    description: "All activities. Cross-training coaching across running and cycling.",
    accentClass: "text-purple-400",
    borderSelected: "border-purple-500",
    dotClass: "bg-purple-500",
  },
];

type SyncState = "idle" | "syncing" | "done" | "error";

export default function Settings({ mode, setMode, theme }: Props) {
  const [syncState, setSyncState] = useState<SyncState>("idle");
  const [syncCount, setSyncCount] = useState<number | null>(null);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [switchingProvider, setSwitchingProvider] = useState(false);

  useEffect(() => {
    fetch("/api/providers")
      .then((r) => r.json())
      .then((data: Provider[]) => setProviders(data))
      .catch(() => {});
  }, []);

  async function handleModeChange(newMode: Mode) {
    try {
      await fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: newMode }),
      });
    } catch {
      // best-effort; switch mode locally regardless
    }
    setMode(newMode);
    location.hash = "chat";
  }

  async function handleProviderChange(providerId: string) {
    setSwitchingProvider(true);
    try {
      await fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: providerId }),
      });
      setProviders((ps) => ps.map((p) => ({ ...p, active: p.id === providerId })));
    } finally {
      setSwitchingProvider(false);
    }
  }

  async function handleFullSync() {
    setSyncState("syncing");
    setSyncCount(null);
    try {
      const res = await fetch("/api/sync?full=true", { method: "POST" });
      if (!res.ok) throw new Error();
      const { new_activities } = await res.json();
      setSyncCount(new_activities);
      setSyncState("done");
    } catch {
      setSyncState("error");
    }
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-2xl mx-auto px-6 py-10">
        <h2 className="text-xl font-semibold text-gray-100 mb-1">Settings</h2>
        <p className="text-sm text-gray-500 mb-8">Configure your Strides AI preferences.</p>

        <div className="space-y-8">
          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-1">
              Mode
            </h3>
            <p className="text-xs text-gray-600 mb-3">
              Switching mode changes which activities are loaded into context and the coaching
              style. Each mode keeps its own conversation history.
            </p>
            <div className="space-y-3">
              {MODE_CARDS.map((card) => {
                const selected = mode === card.id;
                return (
                  <button
                    key={card.id}
                    onClick={() => handleModeChange(card.id)}
                    className={`w-full text-left p-4 rounded-lg border-2 transition-colors bg-gray-900 ${
                      selected ? card.borderSelected : "border-gray-700 hover:border-gray-500"
                    }`}
                  >
                    <div className="flex items-center gap-3 mb-1">
                      <span className={`w-2 h-2 rounded-full shrink-0 ${card.dotClass}`} />
                      <span
                        className={`font-medium text-sm ${selected ? card.accentClass : "text-gray-200"}`}
                      >
                        {card.label}
                      </span>
                      {selected && (
                        <span className={`ml-auto text-xs ${card.accentClass}`}>Active</span>
                      )}
                    </div>
                    <p className="text-xs text-gray-500 pl-5">{card.description}</p>
                  </button>
                );
              })}
            </div>
          </section>

          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-1">
              LLM Provider
            </h3>
            <p className="text-xs text-gray-600 mb-3">
              Switch which AI model powers the coaching chat. Only providers configured in{" "}
              <code className="text-gray-500">.env</code> can be selected.
            </p>
            <div className="space-y-3">
              {providers.map((provider) => {
                const isSelectable = provider.configured && !provider.active && !switchingProvider;
                return (
                  <button
                    key={provider.id}
                    onClick={() => isSelectable && handleProviderChange(provider.id)}
                    disabled={!isSelectable}
                    className={`w-full text-left p-4 rounded-lg border-2 transition-colors bg-gray-900 ${
                      !provider.configured
                        ? "border-gray-800 opacity-50 cursor-not-allowed"
                        : provider.active
                        ? "border-gray-400"
                        : "border-gray-700 hover:border-gray-500 cursor-pointer"
                    }`}
                  >
                    <div className="flex items-center gap-3 mb-1">
                      <span className="font-medium text-sm text-gray-200">{provider.label}</span>
                      {provider.active && (
                        <span className="ml-auto text-xs text-gray-400">Active</span>
                      )}
                      {!provider.configured && (
                        <span className="ml-auto text-xs text-yellow-600">Not configured</span>
                      )}
                    </div>
                    <p className="text-xs text-gray-500">{provider.default_model}</p>
                    {!provider.configured && provider.config_hint && (
                      <p className="text-xs text-yellow-700/80 mt-1">{provider.config_hint}</p>
                    )}
                  </button>
                );
              })}
            </div>
          </section>

          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-1">
              Strava Sync
            </h3>
            <p className="text-xs text-gray-600 mb-3">
              Re-fetches your complete Strava activity history. Use this after switching modes for
              the first time, or to rehydrate the database after moving to a new machine.
            </p>
            <div className="flex items-center gap-4">
              <button
                onClick={handleFullSync}
                disabled={syncState === "syncing"}
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${theme.accentButton} text-white`}
              >
                {syncState === "syncing" ? "Syncing…" : "Full Sync"}
              </button>
              {syncState === "done" && (
                <span className="text-xs text-gray-400">
                  {syncCount === 0
                    ? "Already up to date."
                    : `${syncCount} new activit${syncCount === 1 ? "y" : "ies"} synced.`}
                </span>
              )}
              {syncState === "error" && (
                <span className="text-xs text-red-400">Sync failed. Check your Strava credentials.</span>
              )}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
