import { useState, useEffect, type Dispatch, type SetStateAction } from "react";
import { fetchJson, jsonBody } from "../ui/api";
import Button from "../ui/Button";
import PageHeader from "../ui/PageHeader";
import { Notice } from "../ui/states";
import { MODES, THEMES, type Mode, type ThemeConfig } from "../ui/theme";
import { useUnits } from "../UnitsContext";
import UsagePanel from "./UsagePanel";
import type { UnitSystem } from "../units";

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

const MODE_DESCRIPTIONS: Record<Mode, string> = {
  running: "Running activities only. Coaching focused on pace, cadence, and running load.",
  cycling: "Cycling activities only. Coaching focused on speed, power, and ride load.",
  hybrid: "All activities. Cross-training coaching across running and cycling.",
  lifting:
    "Weightlifting sessions from HEVY. Coaching focused on volume, strength, and progressive overload.",
};

// Colours come from the shared theme, so a mode looks the same here as everywhere else.
const MODE_CARDS = MODES.map((id) => ({
  id,
  label: THEMES[id].name,
  description: MODE_DESCRIPTIONS[id],
  accentClass: THEMES[id].accentClass,
  borderSelected: THEMES[id].accentBorderSelected,
  dotClass: THEMES[id].accentSolid,
}));

type SyncState = "idle" | "syncing" | "done" | "error";

const UNIT_CARDS: { id: UnitSystem; label: string; description: string }[] = [
  { id: "metric", label: "Metric", description: "km, min/km, km/h, m, kg, ml" },
  { id: "imperial", label: "Imperial", description: "mi, min/mi, mph, ft, lb, fl oz" },
];

type WeekStart = "monday" | "sunday";
const WEEK_START_CARDS: { id: WeekStart; label: string; description: string }[] = [
  { id: "monday", label: "Monday", description: "Weeks run Monday to Sunday" },
  { id: "sunday", label: "Sunday", description: "Weeks run Sunday to Saturday" },
];

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
  const units = useUnits();
  const [unitsError, setUnitsError] = useState(false);
  const [modeError, setModeError] = useState(false);

  const [weekStart, setWeekStart] = useState<WeekStart | null>(null);
  const [weekStartError, setWeekStartError] = useState(false);

  useEffect(() => {
    fetch("/api/settings")
      .then((r) => {
        if (!r.ok) throw new Error(String(r.status));
        return r.json();
      })
      .then((s) => setWeekStart(s.week_start === "sunday" ? "sunday" : "monday"))
      .catch(() => setWeekStartError(true));
  }, []);

  async function handleWeekStartChange(next: WeekStart) {
    setWeekStartError(false);
    try {
      const res = await fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ week_start: next }),
      });
      if (!res.ok) throw new Error(String(res.status));
      setWeekStart(next);
    } catch {
      setWeekStartError(true);
    }
  }

  async function handleUnitsChange(next: UnitSystem) {
    setUnitsError(false);
    try {
      await units.setSystem(next);
    } catch {
      setUnitsError(true);
    }
  }

  // The coach voice is part of the shared profile, so it is the same in every mode.
  useEffect(() => {
    const modes: Mode[] = ["running", "cycling", "hybrid", "lifting"];
    fetch("/api/profile")
      .then((r) => r.json())
      .then(({ fields }) => {
        const voice = (fields?.coach_voice as string) ?? "";
        setVoiceByMode(Object.fromEntries(modes.map((m) => [m, voice])));
        if (voice && !PRESET_VOICE_VALUES.has(voice)) {
          setCustomText(Object.fromEntries(modes.map((m) => [m, voice])));
          setCustomSelected(Object.fromEntries(modes.map((m) => [m, true])));
        }
      })
      .catch(() => {});
  }, []);

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

  async function handleVoiceChange(_targetMode: Mode, voice: string) {
    setVoiceSaving(true);
    const modes: Mode[] = ["running", "cycling", "hybrid", "lifting"];
    setVoiceByMode(Object.fromEntries(modes.map((m) => [m, voice])));
    try {
      // Only the voice is sent; the server merges it so other profile fields are untouched.
      await fetch("/api/profile/shared", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fields: { coach_voice: voice } }),
      });
    } finally {
      setVoiceSaving(false);
    }
  }

  async function handleModeChange(newMode: Mode) {
    setModeError(false);
    try {
      await fetchJson("/api/settings", jsonBody("PUT", { mode: newMode }));
      setMode(newMode);
    } catch {
      // Stay on the current mode: switching only locally would be undone by the next reload.
      setModeError(true);
    }
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
        <PageHeader title="Settings" subtitle="Configure your Strides AI preferences." />

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
            {modeError && (
              <Notice tone="error" className="mt-2">
                Couldn't switch mode. Check the server is running and try again.
              </Notice>
            )}
          </section>

          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-1">
              Units
            </h3>
            <p className="text-xs text-gray-600 mb-3">
              Applies everywhere: activities, calendar, analytics, and the coach. Your data is stored
              once and converted for display, so switching never changes it. Past chat messages
              keep the units they were written in.
            </p>
            <div className="grid grid-cols-2 gap-3">
              {UNIT_CARDS.map((card) => {
                const selected = units.system === card.id;
                return (
                  <button
                    key={card.id}
                    onClick={() => handleUnitsChange(card.id)}
                    aria-pressed={selected}
                    className={`text-left p-4 rounded-lg border-2 transition-colors bg-gray-900 ${
                      selected ? "border-gray-300" : "border-gray-700 hover:border-gray-500"
                    }`}
                  >
                    <div className="flex items-center gap-3 mb-1">
                      <span
                        className={`font-medium text-sm ${selected ? theme.accentClass : "text-gray-200"}`}
                      >
                        {card.label}
                      </span>
                      {selected && (
                        <span className={`ml-auto text-xs ${theme.accentClass}`}>Active</span>
                      )}
                    </div>
                    <p className="text-xs text-gray-500">{card.description}</p>
                  </button>
                );
              })}
            </div>
            {unitsError && (
              <p className="text-xs text-red-400 mt-2">Couldn't save the unit setting. Try again.</p>
            )}
          </section>

          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-1">
              Calendar Week Start
            </h3>
            <p className="text-xs text-gray-600 mb-3">
              Which day each row of the Calendar starts on. Training weeks, streaks and ramp are
              always counted Monday to Sunday.
            </p>
            <div className="grid grid-cols-2 gap-3">
              {WEEK_START_CARDS.map((card) => {
                const selected = weekStart === card.id;
                return (
                  <button
                    key={card.id}
                    onClick={() => handleWeekStartChange(card.id)}
                    aria-pressed={selected}
                    className={`text-left p-4 rounded-lg border-2 transition-colors bg-gray-900 ${
                      selected ? "border-gray-300" : "border-gray-700 hover:border-gray-500"
                    }`}
                  >
                    <div className="flex items-center gap-3 mb-1">
                      <span
                        className={`font-medium text-sm ${selected ? theme.accentClass : "text-gray-200"}`}
                      >
                        {card.label}
                      </span>
                      {selected && (
                        <span className={`ml-auto text-xs ${theme.accentClass}`}>Active</span>
                      )}
                    </div>
                    <p className="text-xs text-gray-500">{card.description}</p>
                  </button>
                );
              })}
            </div>
            {weekStartError && (
              <p className="text-xs text-red-400 mt-2">
                Couldn't load or save the week start. Try again.
              </p>
            )}
          </section>

          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-1">
              Coach Voice
            </h3>
            <p className="text-xs text-gray-600 mb-3">
              Adjust how your coach communicates. This applies to every mode.
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
                        setCustomSelected(Object.fromEntries((["running", "cycling", "hybrid", "lifting"] as Mode[]).map((m) => [m, true])));
                      } else {
                        setCustomSelected(Object.fromEntries((["running", "cycling", "hybrid", "lifting"] as Mode[]).map((m) => [m, false])));
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
                        setCustomText(Object.fromEntries((["running", "cycling", "hybrid", "lifting"] as Mode[]).map((m) => [m, e.target.value])))
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
              <Button onClick={handleFullSync} loading={syncState === "syncing"}>
                {syncState === "syncing" ? "Syncing…" : "Full Sync"}
              </Button>
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
              <Button onClick={() => handleHevySync(false)} loading={hevySyncState === "syncing"}>
                {hevySyncState === "syncing" ? "Syncing…" : "Sync New"}
              </Button>
              <Button
                variant="secondary"
                onClick={() => handleHevySync(true)}
                disabled={hevySyncState === "syncing"}
              >
                Full Sync
              </Button>
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
                <Button
                  variant="secondary"
                  onClick={handleTemplatesSync}
                  loading={templatesSyncState === "syncing"}
                >
                  {templatesSyncState === "syncing" ? "Refreshing…" : "Refresh Templates"}
                </Button>
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

          <UsagePanel />
        </div>
      </div>
    </div>
  );
}
