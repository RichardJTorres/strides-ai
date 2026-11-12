import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { navigate } from "../../nav";
import Button from "../../ui/Button";
import { formatDate, formatDuration } from "../../ui/format";
import { Notice } from "../../ui/states";
import { climbLabel, plannedClimbRate } from "../activityLabels";
import { PENDING_CHAT_DRAFT_KEY, handOffActivity } from "../chatActivityHandoff";
import ActivityCard from "./ActivityCard";
import {
  DAY_NAMES, EMPTY_FORM, ENTRY_KINDS, FALLBACK_WORKOUT_COLOR, INTENSITIES, NO_DISTANCE_WORKOUT_TYPES,
  RACE_PRIORITIES, RACE_SPORTS, ROUTE_CAPABLE_WORKOUT_TYPES, VERDICT_STYLES, WORKOUT_COLORS,
  WORKOUT_TYPE_GROUPS, keepsStructure,
} from "./constants";
import { buildEntryBody, failureMessage, formatGoalTime, type EntryForm } from "./entryOps";
import type {
  Activity, ComplianceById, Entry, EntryKind, NutritionData, Prefs, RouteAnalysis, RoutePreview,
} from "./types";
import { useDistance } from "./useDistance";

const isRouteUrl = (url: string) => /(?:ridewithgps|strava)\.com\/routes\/\d+/i.test(url);

async function fetchRoutePreview(url: string): Promise<RoutePreview | null> {
  try {
    const res = await fetch(`/api/calendar/route-preview?url=${encodeURIComponent(url)}`);
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

const dowName = (dateStr: string) => DAY_NAMES[new Date(dateStr + "T12:00:00").getDay()];

const KIND_HEADINGS: Record<EntryKind, string> = {
  workout: "Planned", race: "Race", rest: "Rest day", travel: "Travel", other: "Other",
};

interface Props {
  selectedDate: string;
  /** Everything on the day, oldest first. */
  entries: Entry[];
  compliance: ComplianceById;
  /** The day's activities: the one matched to each entry, and the rest. */
  split: { byEntry: Record<number, Activity>; others: Activity[] };
  prefs: Prefs;
  toggleBlocked: (date: string) => void;
  reloadPlan: () => Promise<void>;
  editMode: boolean;
  setEditMode: Dispatch<SetStateAction<boolean>>;
  onClose: () => void;
}

/**
 * The selected day: a list of its entries (workouts, races, rest, travel), the one being viewed
 * or edited, and the day's activities. The page remounts it (by key) whenever a day is
 * selected, which is what resets every transient flag below.
 */
export default function DayPanel({
  selectedDate, entries, compliance, split, prefs, toggleBlocked, reloadPlan, editMode,
  setEditMode, onClose,
}: Props) {
  // Which entry is open: its id, "new" for the add form, or null when a busy day has none picked.
  const [active, setActive] = useState<number | "new" | null>(
    entries.length === 1 ? entries[0].id : entries.length === 0 ? "new" : null,
  );
  const [newKind, setNewKind] = useState<EntryKind>("workout");
  const activeEntry = typeof active === "number" ? entries.find(e => e.id === active) ?? null : null;
  // A deleted or vanished entry falls back to the day's list.
  useEffect(() => {
    if (typeof active === "number" && !activeEntry) {
      setActive(entries.length === 1 ? entries[0].id : entries.length === 0 ? "new" : null);
    }
  }, [active, activeEntry, entries]);

  return (
    <div className="p-4 flex flex-col gap-6">
      <div className="min-w-0 space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-sm font-semibold text-gray-200">{formatDate(selectedDate)}</div>
            <div className="text-xs text-gray-500">{dowName(selectedDate)}</div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close day"
            className="text-gray-500 hover:text-gray-300 text-xl leading-none"
          >×</button>
        </div>

        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={prefs.blocked_days.includes(selectedDate)}
            onChange={() => toggleBlocked(selectedDate)}
            className="accent-gray-500"
          />
          <span className="text-xs text-gray-400">Mark as blocked (unavailable)</span>
        </label>

        {(entries.length > 0) && (
          <div className="flex flex-wrap gap-1.5" role="list" aria-label="Entries on this day">
            {entries.map(e => (
              <button
                key={e.id}
                role="listitem"
                onClick={() => { setActive(e.id); setEditMode(false); }}
                aria-current={active === e.id}
                className={`text-xs px-2 py-1 rounded border ${WORKOUT_COLORS[e.workout_type] ?? FALLBACK_WORKOUT_COLOR} ${active === e.id ? "ring-2 ring-inset ring-sky-400/80" : "opacity-80 hover:opacity-100"}`}
              >
                {e.kind === "race" ? `🏁 ${e.title || "Race"}` : e.kind === "workout" ? e.workout_type : e.title || e.workout_type}
              </button>
            ))}
            <button
              onClick={() => { setActive("new"); setEditMode(false); }}
              className="text-xs px-2 py-1 rounded border border-dashed border-gray-600 text-gray-400 hover:text-gray-200"
            >+ Add</button>
          </div>
        )}

        {active === null && (
          <p className="text-xs text-gray-500">Pick an entry above to see or edit it.</p>
        )}
        {active === "new" && (
          <div>
            <label className="text-xs text-gray-500 mb-1 block" htmlFor="new-kind">What are you adding?</label>
            <select
              id="new-kind"
              value={newKind}
              onChange={e => setNewKind(e.target.value as EntryKind)}
              className="w-full text-sm bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-gray-200"
            >
              {ENTRY_KINDS.map(k => <option key={k.kind} value={k.kind}>{k.label}</option>)}
            </select>
          </div>
        )}
        {active !== null && (
          <EntryEditor
            key={`${active}:${newKind}`}
            selectedDate={selectedDate}
            entry={activeEntry}
            kind={activeEntry ? activeEntry.kind : newKind}
            matched={activeEntry ? split.byEntry[activeEntry.id] : undefined}
            dayActivities={split.others}
            reloadPlan={reloadPlan}
            editMode={editMode}
            setEditMode={setEditMode}
            hasOthers={entries.length > 0}
            onDone={() => setActive(entries.length > 1 ? null : active)}
            onCreated={id => setActive(id)}
            onDeleted={() => setActive(entries.length > 1 ? null : "new")}
            onCancelNew={() => { if (entries.length === 0) onClose(); else setActive(null); }}
          />
        )}
      </div>

      {split.others.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Strava</h4>
          {split.others.map(a => <ActivityCard key={a.id} activity={a} />)}
        </div>
      )}
    </div>
  );
}

interface EditorProps {
  selectedDate: string;
  /** The entry being viewed/edited; null while adding a new one. */
  entry: Entry | null;
  kind: EntryKind;
  matched: Activity | undefined;
  /** The day's activities not matched to a workout: candidates for a race result. */
  dayActivities: Activity[];
  reloadPlan: () => Promise<void>;
  editMode: boolean;
  setEditMode: Dispatch<SetStateAction<boolean>>;
  hasOthers: boolean;
  onDone: () => void;
  onCreated: (id: number) => void;
  onDeleted: () => void;
  onCancelNew: () => void;
}

/** View or edit one entry (or the add form for a new one), with its route and nutrition. */
function EntryEditor({
  selectedDate, entry: selectedWorkout, kind, matched, dayActivities, reloadPlan, editMode,
  setEditMode, onDone, onCreated, onDeleted, onCancelNew,
}: EditorProps) {
  const canHaveRoute = kind === "race"
    ? (selectedWorkout?.sport ?? "run") !== "other"
    : !!selectedWorkout && ROUTE_CAPABLE_WORKOUT_TYPES.has(selectedWorkout.workout_type);
  const { units, fmtKm, distLabel } = useDistance();
  // The values the edit form was opened with, so an untouched field saves its exact stored
  // number instead of a round-tripped conversion (10 km -> "6.21" mi -> 9.99 km).
  const formOrigin = useRef<{ distance: string; distance_km: number | null; elevation: string; elevation_m: number | null }>(
    { distance: "", distance_km: null, elevation: "", elevation_m: null },
  );
  const distanceInput = (km: number | null | undefined) =>
    km ? String(Number(units.convert(km * 1000, "distance")!.toFixed(2))) : "";
  const elevationInput = (m: number | null | undefined) =>
    m ? String(Math.round(units.convert(m, "elevation")!)) : "";
  const kmFromInput = (value: string): number | null => {
    if (!value) return null;
    if (value === formOrigin.current.distance) return formOrigin.current.distance_km;
    const meters = units.toSI(parseFloat(value), "distance");
    return meters == null ? null : meters / 1000;
  };
  const mFromInput = (value: string): number | null => {
    if (!value) return null;
    if (value === formOrigin.current.elevation) return formOrigin.current.elevation_m;
    const meters = units.toSI(parseFloat(value), "elevation");
    return meters == null ? null : Math.round(meters);
  };

  const formFromWorkout = (w: Entry | null | undefined): EntryForm => {
    const distance = distanceInput(w?.distance_km);
    const elevation = elevationInput(w?.elevation_m);
    formOrigin.current = {
      distance, distance_km: w?.distance_km ?? null, elevation, elevation_m: w?.elevation_m ?? null,
    };
    return {
      workout_type: w && w.kind === "workout" ? w.workout_type : "Easy Run",
      title: w?.title || "",
      sport: w?.sport || "run",
      goal_time: w?.goal_time_s ? formatGoalTime(w.goal_time_s) : w?.goal_text || "",
      priority: w?.priority || "",
      result_activity_id: w?.result_activity_id?.toString() || "",
      description: (w?.kind === "workout" ? w?.objective : w?.notes) || "",
      distance,
      elevation,
      duration_min: w?.duration_min?.toString() || "",
      intensity: w?.intensity && w.intensity !== "rest" ? w.intensity : "easy",
      route_url: w?.route_url || "",
      clear_structure: false,
    };
  };

  const [nutritionLoading, setNutritionLoading] = useState(false);
  const [nutritionError, setNutritionError] = useState<string | null>(null);
  const [routeAnalysisLoading, setRouteAnalysisLoading] = useState(false);
  const [routeAnalysisError, setRouteAnalysisError] = useState<string | null>(null);
  const [showRouteForm, setShowRouteForm] = useState(false);
  const [routeUrlDraft, setRouteUrlDraft] = useState("");
  const [savingRouteUrl, setSavingRouteUrl] = useState(false);
  const [routePreviewLoading, setRoutePreviewLoading] = useState(false);
  const [routePreviewNotice, setRoutePreviewNotice] = useState<string | null>(null);
  const [form, setForm] = useState<EntryForm>(() =>
    selectedWorkout ? formFromWorkout(selectedWorkout) : (EMPTY_FORM as EntryForm)
  );
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // While the create/edit form is showing (either editing an existing workout, or adding a
  // brand-new one — which renders the same form without editMode ever becoming true), autofill
  // distance/elevation from a pasted RideWithGPS link.
  useEffect(() => {
    const formVisible = !selectedWorkout || editMode;
    if (!formVisible) return;
    const url = form.route_url.trim();
    if (!isRouteUrl(url)) {
      setRoutePreviewNotice(null);
      return;
    }
    setRoutePreviewLoading(true);
    setRoutePreviewNotice(null);
    const timer = setTimeout(async () => {
      const preview = await fetchRoutePreview(url);
      setRoutePreviewLoading(false);
      if (!preview) {
        setRoutePreviewNotice("Couldn't fetch that route (it may be private or not exist).");
        return;
      }
      setForm(f => ({
        ...f,
        distance: preview.distance_m
          ? units.fmt(preview.distance_m, "distance", { decimals: 1, withLabel: false })
          : f.distance,
        elevation: preview.elevation_gain_m
          ? units.fmt(preview.elevation_gain_m, "elevation", { withLabel: false })
          : f.elevation,
      }));
      setRoutePreviewNotice(`Filled in distance/elevation from "${preview.name || "route"}".`);
    }, 600);
    return () => { clearTimeout(timer); setRoutePreviewLoading(false); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.route_url, editMode, selectedWorkout]);

  const writeEntry = async (url: string, method: "POST" | "PATCH", body: Record<string, unknown>) => {
    const res = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(await failureMessage(res, ""));
    return res.json().catch(() => null) as Promise<Entry | null>;
  };

  const saveWorkout = async () => {
    const body = buildEntryBody(kind, selectedDate, form, {
      existing: selectedWorkout,
      kmFromInput, mFromInput,
      routeCapable: t => ROUTE_CAPABLE_WORKOUT_TYPES.has(t),
      noDistance: t => NO_DISTANCE_WORKOUT_TYPES.has(t),
      keepsStructure,
    });
    setSaveError(null);
    try {
      const saved = selectedWorkout
        ? await writeEntry(`/api/calendar/entries/${selectedWorkout.id}`, "PATCH", body)
        : await writeEntry("/api/calendar/entries", "POST", body);
      await reloadPlan();
      setEditMode(false);
      if (!selectedWorkout && saved?.id != null) onCreated(saved.id);
      else onDone();
    } catch (e) {
      // The form stays open with what was typed, so nothing is lost.
      const why = e instanceof Error && e.message ? ` ${e.message}` : "";
      setSaveError(`Couldn't save this.${why || " Check your connection and try again."}`);
    }
  };

  const deleteWorkout = async () => {
    if (!selectedWorkout) return;
    setSaveError(null);
    try {
      const res = await fetch(`/api/calendar/entries/${selectedWorkout.id}`, { method: "DELETE" });
      if (!res.ok) throw new Error();
      await reloadPlan();
      setEditMode(false);
      onDeleted();
    } catch {
      setSaveError("Couldn't delete this. Check your connection and try again.");
    } finally {
      setConfirmingDelete(false);
    }
  };

  // Link (or unlink) the activity that was this race; races are never matched automatically.
  const linkResult = async (activityId: string) => {
    if (!selectedWorkout) return;
    setSaveError(null);
    try {
      await writeEntry(`/api/calendar/entries/${selectedWorkout.id}`, "PATCH", {
        result_activity_id: activityId ? Number(activityId) : null,
      });
      await reloadPlan();
    } catch {
      setSaveError("Couldn't link that result. Try again.");
    }
  };

  const analyzeNutrition = async () => {
    if (!selectedWorkout) return;
    setNutritionLoading(true);
    setNutritionError(null);
    try {
      const res = await fetch(`/api/calendar/entries/${selectedWorkout.id}/nutrition`, { method: "POST" });
      if (!res.ok) throw new Error();
      await reloadPlan();
    } catch {
      setNutritionError("Couldn't get nutrition advice. Try again.");
    } finally {
      setNutritionLoading(false);
    }
  };

  const analyzeRoute = async (force = false) => {
    if (!selectedWorkout) return;
    setRouteAnalysisLoading(true);
    setRouteAnalysisError(null);
    try {
      const res = await fetch(
        `/api/calendar/entries/${selectedWorkout.id}/analyze-route${force ? "?force=true" : ""}`,
        { method: "POST" }
      );
      const result = await res.json().catch(() => ({}));
      if (res.ok) {
        await reloadPlan();
      } else {
        setRouteAnalysisError(result.detail || "Failed to analyze route.");
      }
    } catch {
      setRouteAnalysisError("Failed to analyze route. Check your connection and try again.");
    } finally {
      setRouteAnalysisLoading(false);
    }
  };

  // Quick add/edit of just the route URL, without entering full edit mode. Also autofills
  // distance/elevation from the route when one is attached, same as the full edit form.
  const saveRouteUrl = async () => {
    if (!selectedWorkout) return;
    setSavingRouteUrl(true);
    setSaveError(null);
    try {
      const url = routeUrlDraft.trim();
      const preview = url && isRouteUrl(url) ? await fetchRoutePreview(url) : null;
      const patch: Record<string, unknown> = { route_url: url || null };
      if (preview?.distance_m) patch.distance_km = Number((preview.distance_m / 1000).toFixed(1));
      if (preview?.elevation_gain_m) patch.elevation_m = Math.round(preview.elevation_gain_m);
      await writeEntry(`/api/calendar/entries/${selectedWorkout.id}`, "PATCH", patch);
      await reloadPlan();
      setShowRouteForm(false);
    } catch {
      setSaveError("Couldn't save the route. Check your connection and try again.");
    } finally {
      setSavingRouteUrl(false);
    }
  };

  // Opens the chat with a drafted (never auto-sent) question about this day, and attaches the
  // activity that completed the workout when there is one.
  const askCoach = () => {
    const day = formatDate(selectedDate, "weekday");
    const what = selectedWorkout ? `my planned ${selectedWorkout.workout_type} on ${day}` : day;
    try {
      sessionStorage.setItem(
        PENDING_CHAT_DRAFT_KEY,
        matched
          ? `How did ${what} go compared with the plan, and should anything change this week?`
          : `Tell me about ${what}: what is it for, and how should I approach it?`,
      );
    } catch { /* best-effort handoff */ }
    if (matched) handOffActivity(matched);
    navigate("chat");
  };

  const startEdit = () => {
    setForm(formFromWorkout(selectedWorkout));
    setRoutePreviewNotice(null);
    setEditMode(true);
  };

  const hasFormStructure = !!selectedWorkout?.structure && keepsStructure(form.workout_type) && !form.clear_structure;
  const selectedNutrition: NutritionData | null = selectedWorkout?.nutrition_json
    ? JSON.parse(selectedWorkout.nutrition_json)
    : null;
  const selectedRouteAnalysis: RouteAnalysis | null = selectedWorkout?.route_analysis_json
    ? JSON.parse(selectedWorkout.route_analysis_json)
    : null;

  const showNutritionCol = selectedWorkout && !editMode && (kind === "workout" || kind === "race") && selectedWorkout.workout_type !== "Yoga";
  const field = "w-full text-sm bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-gray-200";
  const showDistance = kind === "race" || (kind === "workout" && !NO_DISTANCE_WORKOUT_TYPES.has(form.workout_type));
  const formRoute = kind === "race" ? form.sport !== "other" : kind === "workout" && ROUTE_CAPABLE_WORKOUT_TYPES.has(form.workout_type);

  return (
    <div className="space-y-3">
      {saveError && <Notice tone="error">{saveError}</Notice>}

        {selectedWorkout && !editMode ? (
          <div className="space-y-2">
            <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">{KIND_HEADINGS[kind]}</h4>
            <div className={`px-3 py-2 rounded border ${WORKOUT_COLORS[selectedWorkout.workout_type] ?? FALLBACK_WORKOUT_COLOR}`}>
              <div className="font-medium text-sm">
                {kind === "race" ? `🏁 ${selectedWorkout.title || "Race"}` : kind === "workout" || kind === "rest" ? selectedWorkout.workout_type : selectedWorkout.title || selectedWorkout.workout_type}
              </div>
              {kind === "race" && (
                <div className="text-xs opacity-80 mt-0.5">
                  {[
                    selectedWorkout.sport && selectedWorkout.sport !== "other" ? selectedWorkout.sport : null,
                    selectedWorkout.goal_time_s ? `goal ${formatGoalTime(selectedWorkout.goal_time_s)}` : selectedWorkout.goal_text ? `goal ${selectedWorkout.goal_text}` : null,
                    selectedWorkout.priority ? `priority ${selectedWorkout.priority}` : null,
                  ].filter(Boolean).join(" · ")}
                </div>
              )}
              {selectedWorkout.intensity && (
                <div className="text-xs opacity-70 capitalize mt-0.5">{selectedWorkout.intensity} intensity</div>
              )}
            </div>
            {(selectedWorkout.distance_km || selectedWorkout.elevation_m || selectedWorkout.duration_min) && (
              <div className="flex gap-2 flex-wrap">
                {selectedWorkout.distance_km && (
                  <div className="bg-gray-800 rounded p-2 text-xs">
                    <div className="text-gray-500">Distance</div>
                    <div className="text-gray-200 font-medium">{fmtKm(selectedWorkout.distance_km, 2)}</div>
                  </div>
                )}
                {selectedWorkout.duration_min && (
                  <div className="bg-gray-800 rounded p-2 text-xs">
                    <div className="text-gray-500">Duration</div>
                    <div className="text-gray-200 font-medium">{formatDuration(selectedWorkout.duration_min * 60)}</div>
                  </div>
                )}
                {selectedWorkout.elevation_m && (
                  <div className="bg-gray-800 rounded p-2 text-xs">
                    <div className="text-gray-500">Elevation</div>
                    <div className="text-gray-200 font-medium">{units.fmt(selectedWorkout.elevation_m, "elevation")}</div>
                  </div>
                )}
                {(() => {
                  const rate = plannedClimbRate(selectedWorkout.distance_km, selectedWorkout.elevation_m);
                  if (rate == null) return null;
                  const group = WORKOUT_TYPE_GROUPS[0].types.includes(selectedWorkout.workout_type) || selectedWorkout.sport === "run"
                    ? "run" : keepsStructure(selectedWorkout.workout_type) || selectedWorkout.sport === "ride" ? "ride" : "other";
                  const terrain = climbLabel(rate, group);
                  return (
                    <div className="bg-gray-800 rounded p-2 text-xs" title={terrain?.detail}>
                      <div className="text-gray-500">Climb ratio</div>
                      <div className="text-gray-200 font-medium">
                        {units.fmt(rate, "climb_rate")}
                        {terrain && <span className="ml-1 text-gray-400 font-normal">{terrain.text}</span>}
                      </div>
                    </div>
                  );
                })()}
              </div>
            )}
            {(selectedWorkout.objective || selectedWorkout.notes) && (
              <p className="text-xs text-gray-400 leading-relaxed">{selectedWorkout.objective || selectedWorkout.notes}</p>
            )}
            {kind === "race" && (
              <div className="space-y-1">
                <label className="text-xs text-gray-500 block" htmlFor="race-result">Race result</label>
                <select
                  id="race-result"
                  value={selectedWorkout.result_activity_id ?? ""}
                  onChange={e => linkResult(e.target.value)}
                  className="w-full text-xs bg-gray-800 border border-gray-700 rounded px-2 py-1 text-gray-200"
                >
                  <option value="">Not linked</option>
                  {dayActivities.map(a => (
                    <option key={a.id} value={a.id}>
                      {a.name} · {units.fmt(a.distance_m ?? 0, "distance", { decimals: 1 })}
                    </option>
                  ))}
                </select>
              </div>
            )}
            {matched && (
              <div className="space-y-2">
                <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Actual (Strava)</h4>
                <ActivityCard activity={matched} />
              </div>
            )}
            {selectedWorkout.structure_text && (
              <div className="bg-gray-800/60 rounded p-2 text-xs space-y-1.5">
                <div className="text-gray-500">Structured workout (% FTP)</div>
                <div className="text-gray-300 leading-relaxed">{selectedWorkout.structure_text}</div>
                <a
                  href={`/api/calendar/entries/${selectedWorkout.id}/zwo`}
                  download
                  className="inline-block text-sky-400 hover:text-sky-300"
                >
                  Download .zwo for Zwift
                </a>
              </div>
            )}
            {canHaveRoute && (
              showRouteForm ? (
              <div className="flex items-center gap-1.5">
                <input
                  type="url"
                  autoFocus
                  placeholder="RideWithGPS or Strava route URL"
                  value={routeUrlDraft}
                  onChange={e => setRouteUrlDraft(e.target.value)}
                  onKeyDown={e => { if (e.key === "Enter") saveRouteUrl(); if (e.key === "Escape") setShowRouteForm(false); }}
                  className="flex-1 text-xs bg-gray-800 border border-gray-700 rounded px-2 py-1 text-gray-200"
                />
                <Button size="sm" onClick={saveRouteUrl} loading={savingRouteUrl}>
                  {savingRouteUrl ? "Saving…" : "Save"}
                </Button>
                <button
                  onClick={() => setShowRouteForm(false)}
                  className="text-xs text-gray-500 hover:text-gray-300 px-1"
                >Cancel</button>
              </div>
            ) : selectedWorkout.route_url ? (
              <div className="space-y-1.5">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <a
                      href={selectedWorkout.route_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-xs text-cyan-400 hover:text-cyan-300 underline"
                    >View route ↗</a>
                    <button
                      onClick={() => { setRouteUrlDraft(selectedWorkout.route_url || ""); setShowRouteForm(true); }}
                      className="text-xs text-gray-500 hover:text-gray-300"
                    >Change</button>
                  </div>
                  <button
                    onClick={() => analyzeRoute(!!selectedRouteAnalysis)}
                    disabled={routeAnalysisLoading}
                    className="text-xs bg-gray-700 hover:bg-gray-600 disabled:opacity-50 text-gray-300 rounded px-2 py-0.5"
                  >
                    {routeAnalysisLoading ? "Analyzing…" : selectedRouteAnalysis ? "Refresh" : "Analyze Route"}
                  </button>
                </div>
                {routeAnalysisError && (
                  <Notice tone="error">{routeAnalysisError}</Notice>
                )}
                {selectedRouteAnalysis && (
                  <div className={`px-3 py-2 rounded border text-xs ${VERDICT_STYLES[selectedRouteAnalysis.verdict]?.cls ?? VERDICT_STYLES.needs_info.cls}`}>
                    <div className="font-medium mb-1">
                      {VERDICT_STYLES[selectedRouteAnalysis.verdict]?.label ?? selectedRouteAnalysis.verdict}
                    </div>
                    <p className="opacity-90 leading-relaxed">{selectedRouteAnalysis.explanation}</p>
                    {selectedRouteAnalysis.suggestion && (
                      <p className="opacity-90 leading-relaxed mt-1">
                        <span className="font-medium">Suggestion: </span>
                        {selectedRouteAnalysis.suggestion}
                      </p>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <button
                onClick={() => { setRouteUrlDraft(""); setShowRouteForm(true); }}
                className="text-xs text-gray-500 hover:text-gray-300"
              >+ Add route</button>
              )
            )}
            <div className="flex items-center gap-2">
              <Button variant="secondary" onClick={startEdit}>Edit</Button>
              {kind === "workout" && <Button variant="ghost" onClick={askCoach}>Ask coach</Button>}
              {confirmingDelete ? (
                <>
                  <Button variant="danger" size="sm" onClick={deleteWorkout}>Confirm delete</Button>
                  <button onClick={() => setConfirmingDelete(false)} className="text-xs text-gray-500 hover:text-gray-300 px-2 py-1.5">Cancel</button>
                </>
              ) : (
                <button onClick={() => setConfirmingDelete(true)} className="text-xs text-red-500 hover:text-red-400 px-2 py-1.5">Delete</button>
              )}
            </div>
          </div>
        ) : (
          <div className="space-y-2">
            <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
              {selectedWorkout ? `Edit ${KIND_HEADINGS[kind].toLowerCase()}` : `Add ${KIND_HEADINGS[kind].toLowerCase()}`}
            </h4>
            {kind === "workout" && (
              <div>
                <label className="text-xs text-gray-500 mb-1 block">Type</label>
                <select
                  value={form.workout_type}
                  onChange={e => setForm(f => ({ ...f, workout_type: e.target.value }))}
                  className={field}
                >
                  {WORKOUT_TYPE_GROUPS.map(group => (
                    <optgroup key={group.label} label={group.label}>
                      {group.types.map(t => <option key={t} value={t}>{t}</option>)}
                    </optgroup>
                  ))}
                </select>
              </div>
            )}
            {(kind === "race" || kind === "travel" || kind === "other") && (
              <div>
                <label className="text-xs text-gray-500 mb-1 block">{kind === "race" ? "Race name" : "Label"}</label>
                <input
                  type="text" value={form.title}
                  placeholder={kind === "race" ? "e.g. Fall Half Marathon" : "e.g. Flight to Denver"}
                  onChange={e => setForm(f => ({ ...f, title: e.target.value }))}
                  className={field}
                />
              </div>
            )}
            {kind === "race" && (
              <div className="grid grid-cols-3 gap-2">
                <div>
                  <label className="text-xs text-gray-500 mb-1 block">Sport</label>
                  <select value={form.sport} onChange={e => setForm(f => ({ ...f, sport: e.target.value }))} className={field}>
                    {RACE_SPORTS.map(s => <option key={s} value={s}>{s}</option>)}
                  </select>
                </div>
                <div>
                  <label className="text-xs text-gray-500 mb-1 block">Goal time</label>
                  <input
                    type="text" placeholder="1:45:00" value={form.goal_time}
                    onChange={e => setForm(f => ({ ...f, goal_time: e.target.value }))}
                    className={field}
                  />
                </div>
                <div>
                  <label className="text-xs text-gray-500 mb-1 block">Priority</label>
                  <select value={form.priority} onChange={e => setForm(f => ({ ...f, priority: e.target.value }))} className={field}>
                    <option value="">—</option>
                    {RACE_PRIORITIES.map(p => <option key={p} value={p}>{p}</option>)}
                  </select>
                </div>
              </div>
            )}
            {kind === "workout" && selectedWorkout?.structure && keepsStructure(form.workout_type) && (
              <label className="flex items-center gap-2 text-xs text-gray-400">
                <input
                  type="checkbox"
                  checked={form.clear_structure}
                  onChange={e => setForm(f => ({ ...f, clear_structure: e.target.checked }))}
                />
                Remove structured workout
              </label>
            )}
            {(showDistance || kind === "workout") && (
            <div className="grid grid-cols-2 gap-2">
              {showDistance && (
              <div>
                <label className="text-xs text-gray-500 mb-1 block">Distance ({distLabel})</label>
                <input
                  type="number" step="0.1" placeholder="—"
                  value={form.distance}
                  onChange={e => setForm(f => ({ ...f, distance: e.target.value }))}
                  className={field}
                />
              </div>
              )}
              {showDistance && (
              <div>
                <label className="text-xs text-gray-500 mb-1 block">Elevation ({units.label("elevation")})</label>
                <input
                  type="number" placeholder="—"
                  value={form.elevation}
                  onChange={e => setForm(f => ({ ...f, elevation: e.target.value }))}
                  className={field}
                />
              </div>
              )}
              {kind === "workout" && (
              <div>
                <label className="text-xs text-gray-500 mb-1 block">Duration (min)</label>
                <input
                  type="number" placeholder="—"
                  value={hasFormStructure ? selectedWorkout?.duration_min?.toString() ?? "" : form.duration_min}
                  disabled={hasFormStructure}
                  aria-describedby={hasFormStructure ? "structured-duration-help" : undefined}
                  onChange={e => setForm(f => ({ ...f, duration_min: e.target.value }))}
                  className={`${field} disabled:opacity-50`}
                />
                {hasFormStructure && (
                  <p id="structured-duration-help" className="mt-1 text-xs text-gray-500">
                    Duration comes from the structure. Remove it to edit duration.
                  </p>
                )}
              </div>
              )}
              {kind === "workout" && (
              <div>
                <label className="text-xs text-gray-500 mb-1 block">Intensity</label>
                <select
                  value={form.intensity}
                  onChange={e => setForm(f => ({ ...f, intensity: e.target.value }))}
                  className={field}
                >
                  {INTENSITIES.map(i => (
                    <option key={i} value={i}>{i.charAt(0).toUpperCase() + i.slice(1)}</option>
                  ))}
                </select>
              </div>
              )}
            </div>
            )}
            <div>
              <label className="text-xs text-gray-500 mb-1 block">
                {kind === "workout" ? "Goal (optional)" : "Notes (optional)"}
              </label>
              <textarea
                rows={2}
                placeholder={kind === "workout" ? "What's the goal for this workout?" : ""}
                value={form.description}
                onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                className={`${field} resize-none`}
              />
            </div>
            {formRoute && (
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Route URL (optional)</label>
              <input
                type="url"
                placeholder="https://ridewithgps.com/routes/... or https://strava.com/routes/..."
                value={form.route_url}
                onChange={e => setForm(f => ({ ...f, route_url: e.target.value }))}
                className={field}
              />
              {routePreviewLoading && (
                <p className="text-xs text-gray-500 mt-1">Fetching route details…</p>
              )}
              {!routePreviewLoading && routePreviewNotice && (
                <p className="text-xs text-gray-500 mt-1">{routePreviewNotice}</p>
              )}
            </div>
            )}
            <div className="flex gap-2">
              <Button className="flex-1" onClick={saveWorkout}>Save</Button>
              <Button
                variant="secondary"
                className="flex-1"
                onClick={() => { setEditMode(false); if (!selectedWorkout) onCancelNew(); }}
              >Cancel</Button>
            </div>
          </div>
        )}

      {showNutritionCol && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Nutrition</h4>
            <button
              onClick={analyzeNutrition}
              disabled={nutritionLoading}
              className="text-xs bg-gray-700 hover:bg-gray-600 disabled:opacity-50 text-gray-300 rounded px-2 py-0.5"
            >
              {nutritionLoading ? "Analyzing…" : selectedNutrition ? "Refresh" : "Get advice"}
            </button>
          </div>
          {nutritionError && <Notice tone="error">{nutritionError}</Notice>}
          {selectedNutrition ? (
            <>
              <div className="text-sm text-gray-400 font-medium">Calories (kcal)</div>
              <div className="grid grid-cols-3 gap-2 text-center">
                {(["pre", "during", "post"] as const).map(phase => (
                  <div key={phase} className="bg-gray-800 rounded p-2">
                    <div className="text-xs text-gray-500 capitalize mb-1">{phase}</div>
                    <div className="text-sm font-semibold text-gray-200">
                      {selectedNutrition[`calories_${phase}` as keyof NutritionData] as number}
                    </div>
                  </div>
                ))}
              </div>
              <div className="text-sm text-gray-400 font-medium">Hydration ({units.label("volume")})</div>
              <div className="grid grid-cols-3 gap-2 text-center">
                {(["pre", "during", "post"] as const).map(phase => (
                  <div key={phase} className="bg-gray-800/60 rounded p-2">
                    <div className="text-xs text-gray-500 capitalize mb-1">{phase}</div>
                    <div className="text-sm font-semibold text-blue-300">
                      {units.fmt(selectedNutrition[`hydration_${phase}_ml` as keyof NutritionData] as number, "volume", { withLabel: false })}
                    </div>
                  </div>
                ))}
              </div>
              <p className="text-sm text-gray-400 leading-relaxed">{selectedNutrition.notes}</p>
            </>
          ) : (
            <p className="text-sm text-gray-600 italic">
              Click "Get advice" for personalized calorie and hydration recommendations.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
