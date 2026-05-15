import { useState, useEffect, type Dispatch, type SetStateAction } from "react";
import type { Mode, ThemeConfig } from "../App";

interface Provider {
  id: string;
  label: string;
  selected_model: string;
  configured: boolean;
  active: boolean;
  config_hint: string | null;
}

interface ProviderModel {
  id: string;
  display_name: string;
}

interface Props {
  mode: Mode;
  setMode: Dispatch<SetStateAction<Mode>>;
  theme: ThemeConfig;
  onProviderChanged: () => void;
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
  {
    id: "lifting",
    label: "Lifting",
    description: "Weightlifting sessions from HEVY. Coaching focused on volume, strength, and progressive overload.",
    accentClass: "text-orange-400",
    borderSelected: "border-orange-500",
    dotClass: "bg-orange-500",
  },
];

type SyncState = "idle" | "syncing" | "done" | "error";

const VOICE_OPTIONS: { value: string; label: string; description: string }[] = [
  { value: "", label: "Default", description: "Uses the mode's standard coaching style" },
  { value: "supportive", label: "Supportive", description: "Warm, encouraging, celebrates every win" },
  { value: "motivational", label: "Motivational", description: "High-energy, inspirational, pushes toward goals" },
  { value: "technical", label: "Technical", description: "Analytical, data-driven, metrics-focused" },
  { value: "aggressive", label: "Aggressive", description: "Direct, demanding, no sugarcoating" },
  { value: "beginner_friendly", label: "Beginner Friendly", description: "Patient, educational, jargon-free" },
  { value: "conversational", label: "Conversational", description: "Casual, relaxed, like a training buddy" },
  { value: "custom", label: "Custom", description: "Write your own coaching voice instruction" },
];

const PRESET_VOICE_VALUES = new Set(VOICE_OPTIONS.map((o) => o.value).filter((v) => v !== "custom"));

export default function Settings({ mode, setMode, theme, onProviderChanged }: Props) {
  const [syncState, setSyncState] = useState<SyncState>("idle");
  const [syncCount, setSyncCount] = useState<number | null>(null);
  const [hevySyncState, setHevySyncState] = useState<SyncState>("idle");
  const [hevySyncCount, setHevySyncCount] = useState<number | null>(null);
  const [templatesSyncState, setTemplatesSyncState] = useState<SyncState>("idle");
  const [templatesSynced, setTemplatesSynced] = useState<number | null>(null);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [switchingProvider, setSwitchingProvider] = useState(false);
  const [providerModels, setProviderModels] = useState<Record<string, ProviderModel[]>>({});
  const [changingModel, setChangingModel] = useState(false);
  const [voiceByMode, setVoiceByMode] = useState<Record<string, string>>({});
  const [customText, setCustomText] = useState<Record<string, string>>({});
  const [customSelected, setCustomSelected] = useState<Record<string, boolean>>({});
  const [voiceSaving, setVoiceSaving] = useState(false);
  const [weightUnit, setWeightUnit] = useState<"kg" | "lbs">("kg");

  useEffect(() => {
    const modes: Mode[] = ["running", "cycling", "hybrid", "lifting"];
    Promise.all(
      modes.map((m) =>
        fetch(`/api/profile?mode=${m}`)
          .then((r) => r.json())
          .then(({ fields }) => [m, (fields?.coach_voice as string) ?? ""] as [string, string])
          .catch(() => [m, ""] as [string, string])
      )
    ).then((entries) => {
      setVoiceByMode(Object.fromEntries(entries));
      const customEntries = entries.filter(([, v]) => v && !PRESET_VOICE_VALUES.has(v));
      setCustomText(Object.fromEntries(customEntries.map(([m, v]) => [m, v])));
      setCustomSelected(Object.fromEntries(customEntries.map(([m]) => [m, true])));
    });
  }, []);

  useEffect(() => {
    if (mode === "lifting") {
      fetch(`/api/profile?mode=lifting`)
        .then((r) => r.json())
        .then(({ fields }) => setWeightUnit((fields?.weight_unit as "kg" | "lbs") || "kg"))
        .catch(() => {});
    }
  }, [mode]);

  useEffect(() => {
    fetch("/api/providers")
      .then((r) => r.json())
      .then((data: Provider[]) => {
        setProviders(data);
        // Fetch models for every configured provider in parallel
        data
          .filter((p) => p.configured)
          .forEach((p) => {
            fetch(`/api/providers/${p.id}/models`)
              .then((r) => r.json())
              .then((models: ProviderModel[]) =>
                setProviderModels((prev) => ({ ...prev, [p.id]: models }))
              )
              .catch(() => {});
          });
      })
      .catch(() => {});
  }, []);

  async function handleVoiceChange(targetMode: Mode, voice: string) {
    setVoiceSaving(true);
    setVoiceByMode((prev) => ({ ...prev, [targetMode]: voice }));
    try {
      const { fields } = await fetch(`/api/profile?mode=${targetMode}`).then((r) => r.json());
      await fetch(`/api/profile?mode=${targetMode}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fields: { ...fields, coach_voice: voice } }),
      });
    } finally {
      setVoiceSaving(false);
    }
  }

  async function handleWeightUnitChange(unit: "kg" | "lbs") {
    setWeightUnit(unit);
    const { fields } = await fetch(`/api/profile?mode=lifting`).then((r) => r.json());
    await fetch(`/api/profile?mode=lifting`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fields: { ...fields, weight_unit: unit } }),
    });
  }

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
      onProviderChanged();
    } finally {
      setSwitchingProvider(false);
    }
  }

  async function handleModelChange(providerId: string, model: string) {
    setChangingModel(true);
    try {
      await fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: providerId, model }),
      });
      setProviders((ps) =>
        ps.map((p) => (p.id === providerId ? { ...p, selected_model: model } : p))
      );
    } finally {
      setChangingModel(false);
    }
  }

  async function handleHevySync(full: boolean) {
    setHevySyncState("syncing");
    setHevySyncCount(null);
    try {
      const res = await fetch(`/api/hevy/sync${full ? "?full=true" : ""}`, { method: "POST" });
      if (!res.ok) throw new Error();
      const { new_workouts } = await res.json();
      setHevySyncCount(new_workouts);
      setHevySyncState("done");
    } catch {
      setHevySyncState("error");
    }
  }

  async function handleTemplatesSync() {
    setTemplatesSyncState("syncing");
    setTemplatesSynced(null);
    try {
      const res = await fetch("/api/hevy/templates/sync", { method: "POST" });
      if (!res.ok) throw new Error();
      const { templates_synced } = await res.json();
      setTemplatesSynced(templates_synced);
      setTemplatesSyncState("done");
    } catch {
      setTemplatesSyncState("error");
    }
  }

  async function handleFullSync() {
    setSyncState("syncing");
    setSyncCount(null);
    try {
      const res = await fetch("/api/strava/sync?full=true", { method: "POST" });
      if (!res.ok) throw new Error();
      const { new_activities } = await res.json();
      setSyncCount(new_activities);
      setSyncState("done");
    } catch {
      setSyncState("error");
    }
  }

  return (
    <div className="h-full overflow-y-auto">
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
              Coach Voice
            </h3>
            <p className="text-xs text-gray-600 mb-3">
              Adjust how your coach communicates. Each mode can have a different voice.
            </p>
            {(() => {
              const card = MODE_CARDS.find((c) => c.id === mode)!;
              const stored = voiceByMode[card.id] ?? "";
              const isCustom = customSelected[card.id] ?? false;
              const selectValue = isCustom ? "custom" : stored;
              return (
                <div className="p-4 rounded-lg border border-gray-700 bg-gray-900">
                  <div className="flex items-center gap-2 mb-2">
                    <span className={`w-2 h-2 rounded-full shrink-0 ${card.dotClass}`} />
                    <span className={`text-xs font-medium ${card.accentClass}`}>{card.label}</span>
                  </div>
                  <select
                    value={selectValue}
                    onChange={(e) => {
                      if (e.target.value === "custom") {
                        setCustomSelected((prev) => ({ ...prev, [card.id]: true }));
                      } else {
                        setCustomSelected((prev) => ({ ...prev, [card.id]: false }));
                        handleVoiceChange(card.id, e.target.value);
                      }
                    }}
                    disabled={voiceSaving}
                    className="w-full bg-gray-800 text-gray-300 text-xs rounded px-2 py-1.5 border border-gray-700 focus:outline-none focus:border-gray-500 disabled:opacity-50"
                  >
                    {VOICE_OPTIONS.map((v) => (
                      <option key={v.value} value={v.value}>
                        {v.label}{v.description ? ` — ${v.description}` : ""}
                      </option>
                    ))}
                  </select>
                  {(selectValue === "custom") && (
                    <textarea
                      value={customText[card.id] ?? ""}
                      onChange={(e) =>
                        setCustomText((prev) => ({ ...prev, [card.id]: e.target.value }))
                      }
                      onBlur={() => handleVoiceChange(card.id, customText[card.id] ?? "")}
                      disabled={voiceSaving}
                      placeholder="Describe how your coach should communicate…"
                      rows={3}
                      className="mt-2 w-full bg-gray-800 text-gray-300 text-xs rounded px-2 py-1.5 border border-gray-700 focus:outline-none focus:border-gray-500 disabled:opacity-50 resize-none placeholder-gray-600"
                    />
                  )}
                </div>
              );
            })()}
          </section>

          {mode === "lifting" && (
            <section>
              <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-1">
                Weight Unit
              </h3>
              <p className="text-xs text-gray-600 mb-3">
                Unit used when the coach references weights in feedback and session breakdowns.
              </p>
              <div className="flex gap-2">
                {(["kg", "lbs"] as const).map((u) => (
                  <button
                    key={u}
                    onClick={() => handleWeightUnitChange(u)}
                    className={`px-4 py-1.5 rounded text-xs font-medium border transition-colors ${
                      weightUnit === u
                        ? "bg-orange-500 border-orange-500 text-white"
                        : "bg-gray-800 border-gray-700 text-gray-300 hover:border-gray-500"
                    }`}
                  >
                    {u}
                  </button>
                ))}
              </div>
            </section>
          )}

          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-1">
              LLM Provider
            </h3>
            <p className="text-xs text-gray-600 mb-3">
              Switch which AI model powers the coaching chat. Ollama is auto-detected when running
              locally; Claude and Gemini require API keys in{" "}
              <code className="text-gray-500">.env</code>.
            </p>
            <div className="space-y-3">
              {providers.map((provider) => {
                const isSelectable = provider.configured && !provider.active && !switchingProvider;
                return (
                  <div
                    key={provider.id}
                    className={`w-full text-left p-4 rounded-lg border-2 transition-colors bg-gray-900 ${
                      !provider.configured
                        ? "border-gray-800 opacity-50"
                        : provider.active
                        ? "border-gray-400"
                        : "border-gray-700 hover:border-gray-500 cursor-pointer"
                    }`}
                    onClick={() => isSelectable && handleProviderChange(provider.id)}
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
                    {provider.configured &&
                    (providerModels[provider.id] ?? []).length > 1 ? (
                      <select
                        value={provider.selected_model}
                        onChange={(e) => {
                          e.stopPropagation();
                          handleModelChange(provider.id, e.target.value);
                        }}
                        onClick={(e) => e.stopPropagation()}
                        disabled={changingModel}
                        className="mt-1 w-full bg-gray-800 text-gray-300 text-xs rounded px-2 py-1 border border-gray-700 focus:outline-none focus:border-gray-500 disabled:opacity-50"
                      >
                        {(providerModels[provider.id] ?? []).map((m) => (
                          <option key={m.id} value={m.id}>
                            {m.display_name}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <p className="text-xs text-gray-500">{provider.selected_model}</p>
                    )}
                    {!provider.configured && provider.config_hint && (
                      <p className="text-xs text-yellow-700/80 mt-1">{provider.config_hint}</p>
                    )}
                  </div>
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

          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-1">
              HEVY Sync
            </h3>
            <p className="text-xs text-gray-600 mb-3">
              Fetches your weightlifting sessions from HEVY. Requires a{" "}
              <span className="text-gray-400">Hevy Pro</span> subscription and{" "}
              <code className="text-gray-500">HEVY_API_KEY</code> in{" "}
              <code className="text-gray-500">.env</code> (get your key at{" "}
              <span className="text-gray-400">hevy.com/settings?developer</span>).
            </p>
            <div className="flex items-center gap-3">
              <button
                onClick={() => handleHevySync(false)}
                disabled={hevySyncState === "syncing"}
                className="px-4 py-2 rounded-lg text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed bg-orange-600 hover:bg-orange-500 text-white"
              >
                {hevySyncState === "syncing" ? "Syncing…" : "Sync New"}
              </button>
              <button
                onClick={() => handleHevySync(true)}
                disabled={hevySyncState === "syncing"}
                className="px-4 py-2 rounded-lg text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed bg-gray-700 hover:bg-gray-600 text-white"
              >
                Full Sync
              </button>
              {hevySyncState === "done" && (
                <span className="text-xs text-gray-400">
                  {hevySyncCount === 0
                    ? "Already up to date."
                    : `${hevySyncCount} new session${hevySyncCount === 1 ? "" : "s"} synced.`}
                </span>
              )}
              {hevySyncState === "error" && (
                <span className="text-xs text-red-400">Sync failed. Check your HEVY_API_KEY.</span>
              )}
            </div>
            <div className="mt-4 pt-4 border-t border-gray-800">
              <p className="text-xs text-gray-600 mb-2">
                Refresh the cached exercise-template catalogue (used by the Working Sets by Muscle
                Group chart). Re-run if you add custom exercises in HEVY or notice "Unknown" muscle
                groups.
              </p>
              <div className="flex items-center gap-3">
                <button
                  onClick={handleTemplatesSync}
                  disabled={templatesSyncState === "syncing"}
                  className="px-4 py-2 rounded-lg text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed bg-gray-700 hover:bg-gray-600 text-white"
                >
                  {templatesSyncState === "syncing" ? "Refreshing…" : "Refresh Templates"}
                </button>
                {templatesSyncState === "done" && (
                  <span className="text-xs text-gray-400">
                    {templatesSynced === 0
                      ? "No templates returned."
                      : `${templatesSynced} template${templatesSynced === 1 ? "" : "s"} cached.`}
                  </span>
                )}
                {templatesSyncState === "error" && (
                  <span className="text-xs text-red-400">
                    Refresh failed. Check your HEVY_API_KEY.
                  </span>
                )}
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
