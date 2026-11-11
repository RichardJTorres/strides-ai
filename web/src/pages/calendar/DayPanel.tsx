import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { navigate } from "../../nav";
import Button from "../../ui/Button";
import { formatDate, formatDuration } from "../../ui/format";
import { Notice } from "../../ui/states";
import { climbLabel, plannedClimbRate } from "../activityLabels";
import { PENDING_CHAT_ACTIVITY_KEY, PENDING_CHAT_DRAFT_KEY } from "../chatActivityHandoff";
import ActivityCard from "./ActivityCard";
import {
  DAY_NAMES, EMPTY_FORM, FALLBACK_WORKOUT_COLOR, INTENSITIES, NO_DISTANCE_WORKOUT_TYPES,
  ROUTE_CAPABLE_WORKOUT_TYPES, VERDICT_STYLES, WORKOUT_COLORS, WORKOUT_TYPE_GROUPS, keepsStructure,
} from "./constants";
import type {
  Activity, NutritionData, Prefs, RouteAnalysis, RoutePreview, SetPlan, Workout,
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

interface Props {
  selectedDate: string;
  selectedWorkout: Workout | null;
  /** The day's activities, already split into the one matched to the plan and the rest. */
  selectedSplit: { matched: Activity | undefined; others: Activity[] };
  prefs: Prefs;
  toggleBlocked: (date: string) => void;
  setPlan: SetPlan;
  editMode: boolean;
  setEditMode: Dispatch<SetStateAction<boolean>>;
  onClose: () => void;
}

/**
 * The selected day: its planned workout (view or edit form), route, activities and nutrition.
 * The page remounts it (by key) whenever a day is selected, which is what resets the form and
 * every transient flag below.
 */
export default function DayPanel({
  selectedDate, selectedWorkout, selectedSplit, prefs, toggleBlocked, setPlan, editMode,
  setEditMode, onClose,
}: Props) {
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
  const formFromWorkout = (w: Workout | null | undefined) => {
    const distance = distanceInput(w?.distance_km);
    const elevation = elevationInput(w?.elevation_m);
    formOrigin.current = {
      distance, distance_km: w?.distance_km ?? null, elevation, elevation_m: w?.elevation_m ?? null,
    };
    return {
      workout_type: w?.workout_type || "Easy Run",
      description: w?.description || "",
      distance,
      elevation,
      duration_min: w?.duration_min?.toString() || "",
      intensity: w?.intensity || "easy",
      route_url: w?.route_url || "",
      clear_structure: false,
    };
  };
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

  const [nutritionLoading, setNutritionLoading] = useState(false);
  const [nutritionError, setNutritionError] = useState<string | null>(null);
  const [routeAnalysisLoading, setRouteAnalysisLoading] = useState(false);
  const [routeAnalysisError, setRouteAnalysisError] = useState<string | null>(null);
  const [showRouteForm, setShowRouteForm] = useState(false);
  const [routeUrlDraft, setRouteUrlDraft] = useState("");
  const [savingRouteUrl, setSavingRouteUrl] = useState(false);
  const [routePreviewLoading, setRoutePreviewLoading] = useState(false);
  const [routePreviewNotice, setRoutePreviewNotice] = useState<string | null>(null);
  const [form, setForm] = useState(() =>
    selectedWorkout ? formFromWorkout(selectedWorkout) : EMPTY_FORM
  );
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // While the create/edit form is showing (either editing an existing workout, or adding a
  // brand-new one — which renders the same form without editMode ever becoming true), autofill
  // distance/elevation from a pasted RideWithGPS link.
  useEffect(() => {
    const existingWorkout = selectedWorkout;
    const formVisible = !!selectedDate && (!existingWorkout || editMode);
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
  }, [form.route_url, editMode, selectedDate, selectedWorkout]);

  const saveWorkout = async () => {
    if (!selectedDate) return;
    const noDistance = NO_DISTANCE_WORKOUT_TYPES.has(form.workout_type);
    const noRoute = !ROUTE_CAPABLE_WORKOUT_TYPES.has(form.workout_type);
    const body = {
      workout_type: form.workout_type,
      description: form.description || null,
      distance_km: noDistance ? null : kmFromInput(form.distance),
      elevation_m: noDistance ? null : mFromInput(form.elevation),
      duration_min: form.duration_min ? parseInt(form.duration_min) : null,
      intensity: form.intensity,
      route_url: !noRoute && form.route_url ? form.route_url : null,
      // Preserve the structure unless the athlete explicitly removes it.
      structure: keepsStructure(form.workout_type) && !form.clear_structure ? selectedWorkout?.structure ?? null : null,
    };
    setSaveError(null);
    try {
      const res = await fetch(`/api/calendar/plan/${selectedDate}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error();
      const saved = (await res.json().catch(() => null))?.workout;
      setPlan(prev => ({ ...prev, [selectedDate]: saved ?? { date: selectedDate, ...body } }));
      setEditMode(false);
    } catch {
      // The form stays open with what was typed, so nothing is lost.
      setSaveError("Couldn't save this workout. Check your connection and try again.");
    }
  };

  const deleteWorkout = async () => {
    if (!selectedDate) return;
    setSaveError(null);
    try {
      const res = await fetch(`/api/calendar/plan/${selectedDate}`, { method: "DELETE" });
      if (!res.ok) throw new Error();
      setPlan(prev => {
        const next = { ...prev };
        delete next[selectedDate];
        return next;
      });
      setEditMode(false);
    } catch {
      setSaveError("Couldn't delete this workout. Check your connection and try again.");
    } finally {
      setConfirmingDelete(false);
    }
  };

  const analyzeNutrition = async () => {
    if (!selectedDate) return;
    setNutritionLoading(true);
    setNutritionError(null);
    try {
      const res = await fetch(`/api/calendar/plan/${selectedDate}/nutrition`, { method: "POST" });
      if (!res.ok) throw new Error();
      const nutrition = await res.json();
      setPlan(prev => ({
        ...prev,
        [selectedDate]: { ...prev[selectedDate], nutrition_json: JSON.stringify(nutrition) },
      }));
    } catch {
      setNutritionError("Couldn't get nutrition advice. Try again.");
    } finally {
      setNutritionLoading(false);
    }
  };

  const analyzeRoute = async (force = false) => {
    if (!selectedDate) return;
    setRouteAnalysisLoading(true);
    setRouteAnalysisError(null);
    try {
      const res = await fetch(
        `/api/calendar/plan/${selectedDate}/analyze-route${force ? "?force=true" : ""}`,
        { method: "POST" }
      );
      const result = await res.json().catch(() => ({}));
      if (res.ok) {
        setPlan(prev => ({
          ...prev,
          [selectedDate]: {
            ...prev[selectedDate],
            route_analysis_json: JSON.stringify({
              verdict: result.verdict,
              explanation: result.explanation,
              suggestion: result.suggestion,
            }),
            route_analyzed_at: result.analyzed_at,
          },
        }));
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
    if (!selectedDate || !selectedWorkout) return;
    setSavingRouteUrl(true);
    setSaveError(null);
    try {
      const url = routeUrlDraft.trim();
      const preview = url && isRouteUrl(url) ? await fetchRoutePreview(url) : null;
      const body = {
        workout_type: selectedWorkout.workout_type,
        description: selectedWorkout.description ?? null,
        distance_km: preview?.distance_m
          ? Number((preview.distance_m / 1000).toFixed(1))
          : selectedWorkout.distance_km ?? null,
        elevation_m: preview?.elevation_gain_m
          ? Math.round(preview.elevation_gain_m)
          : selectedWorkout.elevation_m ?? null,
        duration_min: selectedWorkout.duration_min ?? null,
        intensity: selectedWorkout.intensity ?? null,
        route_url: url || null,
        structure: selectedWorkout.structure ?? null,
      };
      const res = await fetch(`/api/calendar/plan/${selectedDate}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error();
      const saved = (await res.json().catch(() => null))?.workout;
      setPlan(prev => ({ ...prev, [selectedDate]: saved ?? { date: selectedDate, ...body } }));
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
        selectedSplit.matched
          ? `How did ${what} go compared with the plan, and should anything change this week?`
          : `Tell me about ${what}: what is it for, and how should I approach it?`,
      );
      if (selectedSplit.matched) {
        sessionStorage.setItem(PENDING_CHAT_ACTIVITY_KEY, String(selectedSplit.matched.id));
      }
    } catch { /* best-effort handoff */ }
    navigate("chat");
  };

  const startEdit = () => {
    const existing = selectedWorkout;
    setForm(formFromWorkout(existing));
    setRoutePreviewNotice(null);
    setEditMode(true);
  };

  const hasFormStructure = !!selectedWorkout?.structure && keepsStructure(form.workout_type) && !form.clear_structure;
  const selectedActivities = selectedSplit.others;
  const selectedNutrition: NutritionData | null = selectedWorkout?.nutrition_json
    ? JSON.parse(selectedWorkout.nutrition_json)
    : null;
  const selectedRouteAnalysis: RouteAnalysis | null = selectedWorkout?.route_analysis_json
    ? JSON.parse(selectedWorkout.route_analysis_json)
    : null;

  const showNutritionCol = selectedWorkout && !editMode && selectedWorkout.workout_type !== "Rest";

  return (
    <div className="p-4 flex flex-col gap-6">

      {/* Col 1: date info + planned workout */}
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

        {saveError && <Notice tone="error">{saveError}</Notice>}

        {/* Planned workout: view or form */}
        {selectedWorkout && !editMode ? (
          <div className="space-y-2">
            <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Planned</h4>
            <div className={`px-3 py-2 rounded border ${WORKOUT_COLORS[selectedWorkout.workout_type] ?? FALLBACK_WORKOUT_COLOR}`}>
              <div className="font-medium text-sm">{selectedWorkout.workout_type}</div>
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
                  const group = WORKOUT_TYPE_GROUPS[0].types.includes(selectedWorkout.workout_type)
                    ? "run" : keepsStructure(selectedWorkout.workout_type) ? "ride" : "other";
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
            {selectedWorkout.description && (
              <p className="text-xs text-gray-400 leading-relaxed">{selectedWorkout.description}</p>
            )}
            {selectedSplit.matched && (
              <div className="space-y-2">
                <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Actual (Strava)</h4>
                <ActivityCard activity={selectedSplit.matched} />
              </div>
            )}
            {selectedWorkout.structure_text && (
              <div className="bg-gray-800/60 rounded p-2 text-xs space-y-1.5">
                <div className="text-gray-500">Structured workout (% FTP)</div>
                <div className="text-gray-300 leading-relaxed">{selectedWorkout.structure_text}</div>
                <a
                  href={`/api/calendar/plan/${selectedWorkout.date}/zwo`}
                  download
                  className="inline-block text-sky-400 hover:text-sky-300"
                >
                  Download .zwo for Zwift
                </a>
              </div>
            )}
            {ROUTE_CAPABLE_WORKOUT_TYPES.has(selectedWorkout.workout_type) && (
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
              <Button variant="ghost" onClick={askCoach}>Ask coach</Button>
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
              {selectedWorkout ? "Edit Planned Workout" : "Add Planned Workout"}
            </h4>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Type</label>
              <select
                value={form.workout_type}
                onChange={e => setForm(f => ({ ...f, workout_type: e.target.value }))}
                className="w-full text-sm bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-gray-200"
              >
                {WORKOUT_TYPE_GROUPS.map(group => (
                  <optgroup key={group.label} label={group.label}>
                    {group.types.map(t => <option key={t} value={t}>{t}</option>)}
                  </optgroup>
                ))}
              </select>
            </div>
            {selectedWorkout?.structure && keepsStructure(form.workout_type) && (
              <label className="flex items-center gap-2 text-xs text-gray-400">
                <input
                  type="checkbox"
                  checked={form.clear_structure}
                  onChange={e => setForm(f => ({ ...f, clear_structure: e.target.checked }))}
                />
                Remove structured workout
              </label>
            )}
            <div className="grid grid-cols-2 gap-2">
              {!NO_DISTANCE_WORKOUT_TYPES.has(form.workout_type) && (
              <div>
                <label className="text-xs text-gray-500 mb-1 block">Distance ({distLabel})</label>
                <input
                  type="number" step="0.1" placeholder="—"
                  value={form.distance}
                  onChange={e => setForm(f => ({ ...f, distance: e.target.value }))}
                  className="w-full text-sm bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-gray-200"
                />
              </div>
              )}
              {!NO_DISTANCE_WORKOUT_TYPES.has(form.workout_type) && (
              <div>
                <label className="text-xs text-gray-500 mb-1 block">Elevation ({units.label("elevation")})</label>
                <input
                  type="number" placeholder="—"
                  value={form.elevation}
                  onChange={e => setForm(f => ({ ...f, elevation: e.target.value }))}
                  className="w-full text-sm bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-gray-200"
                />
              </div>
              )}
              <div>
                <label className="text-xs text-gray-500 mb-1 block">Duration (min)</label>
                <input
                  type="number" placeholder="—"
                  value={hasFormStructure ? selectedWorkout?.duration_min?.toString() ?? "" : form.duration_min}
                  disabled={hasFormStructure}
                  aria-describedby={hasFormStructure ? "structured-duration-help" : undefined}
                  onChange={e => setForm(f => ({ ...f, duration_min: e.target.value }))}
                  className="w-full text-sm bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-gray-200 disabled:opacity-50"
                />
                {hasFormStructure && (
                  <p id="structured-duration-help" className="mt-1 text-xs text-gray-500">
                    Duration comes from the structure. Remove it to edit duration.
                  </p>
                )}
              </div>
              <div>
                <label className="text-xs text-gray-500 mb-1 block">Intensity</label>
                <select
                  value={form.intensity}
                  onChange={e => setForm(f => ({ ...f, intensity: e.target.value }))}
                  className="w-full text-sm bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-gray-200"
                >
                  {INTENSITIES.map(i => (
                    <option key={i} value={i}>{i.charAt(0).toUpperCase() + i.slice(1)}</option>
                  ))}
                </select>
              </div>
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Notes (optional)</label>
              <textarea
                rows={2}
                placeholder="What's the goal for this workout?"
                value={form.description}
                onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                className="w-full text-sm bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-gray-200 resize-none"
              />
            </div>
            {ROUTE_CAPABLE_WORKOUT_TYPES.has(form.workout_type) && (
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Route URL (optional)</label>
              <input
                type="url"
                placeholder="https://ridewithgps.com/routes/... or https://strava.com/routes/..."
                value={form.route_url}
                onChange={e => setForm(f => ({ ...f, route_url: e.target.value }))}
                className="w-full text-sm bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-gray-200"
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
                onClick={() => { setEditMode(false); if (!selectedWorkout) onClose(); }}
              >Cancel</Button>
            </div>
          </div>
        )}
      </div>

      {/* Col 2: Strava activities */}
      {selectedActivities.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Strava</h4>
          {selectedActivities.map(a => <ActivityCard key={a.id} activity={a} />)}
        </div>
      )}

      {/* Col 3: Nutrition */}
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
