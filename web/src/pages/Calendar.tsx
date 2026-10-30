import { useCallback, useEffect, useRef, useState } from "react";
import { useUnits } from "../UnitsContext";
import { climbLabel, plannedClimbRate } from "./activityLabels";

const DAYS_OF_WEEK = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

// Mirrored in strides_ai/compliance.py (RUN_WORKOUT_TYPES/RIDE_WORKOUT_TYPES/
// UNSCORED_WORKOUT_TYPES) for plan-vs-actual compliance scoring — keep both in sync. If they
// drift, the backend falls back to treating an unrecognized type as sport-ambiguous rather
// than crashing or misclassifying, so drift degrades gracefully but should still be fixed.
const WORKOUT_TYPE_GROUPS: { label: string; types: string[] }[] = [
  { label: "Running", types: ["Easy Run", "Long Run", "Tempo Run", "Running Race"] },
  { label: "Cycling", types: ["Easy Ride", "Long Ride", "Tempo Ride", "Indoor Ride", "Cycling Race"] },
  // Generic "Race" kept for existing entries predating the sport-specific race types above;
  // left out of Running/Cycling since it can't be sport-categorized automatically.
  { label: "Other", types: ["Intervals", "Race", "Cross-Training", "Yoga", "Rest"] },
];
// Route (Strava or RideWithGPS) only makes sense for Running/Cycling types — a generic
// "Race"/"Intervals" could be either sport, so it's left out rather than guessing.
const ROUTE_CAPABLE_WORKOUT_TYPES = new Set([
  ...WORKOUT_TYPE_GROUPS[0].types,
  ...WORKOUT_TYPE_GROUPS[1].types,
]);
// Distance/elevation don't apply to these. Mirrored as UNSCORED_WORKOUT_TYPES in
// strides_ai/compliance.py — these are excluded from compliance scoring entirely.
const NO_DISTANCE_WORKOUT_TYPES = new Set(["Yoga", "Rest"]);
// Structured workouts are cycling-only. Mirrored by RIDE_WORKOUT_TYPES in strides_ai/compliance.py,
// which the server enforces.
const keepsStructure = (workoutType: string) => WORKOUT_TYPE_GROUPS[1].types.includes(workoutType);

const COMPLIANCE_DOT_COLORS: Record<string, string> = {
  completed: "bg-green-400",
  modified: "bg-amber-400",
  missed: "bg-red-400",
  // upcoming/unscored intentionally render nothing — never imply pass/fail on a day that
  // can't be judged yet (upcoming) or at all (rest/yoga).
};

const COMPLIANCE_STATUS_LABELS: Record<string, string> = {
  completed: "Completed",
  modified: "Modified",
  missed: "Missed",
  upcoming: "Upcoming",
  unscored: "Not scored",
};

const INTENSITIES = ["easy", "moderate", "hard", "rest"];

const WORKOUT_COLORS: Record<string, string> = {
  "Easy Run":       "bg-green-500/20 text-green-300 border-green-500/30",
  "Long Run":       "bg-purple-500/20 text-purple-300 border-purple-500/30",
  "Tempo Run":      "bg-orange-500/20 text-orange-300 border-orange-500/30",
  "Easy Ride":      "bg-teal-500/20 text-teal-300 border-teal-500/30",
  "Long Ride":      "bg-cyan-500/20 text-cyan-300 border-cyan-500/30",
  "Tempo Ride":     "bg-yellow-500/20 text-yellow-300 border-yellow-500/30",
  "Indoor Ride":    "bg-indigo-500/20 text-indigo-300 border-indigo-500/30",
  "Running Race":   "bg-amber-500/20 text-amber-300 border-amber-500/30",
  "Cycling Race":   "bg-amber-500/20 text-amber-300 border-amber-500/30",
  "Intervals":      "bg-red-500/20 text-red-300 border-red-500/30",
  "Race":           "bg-amber-500/20 text-amber-300 border-amber-500/30",
  "Cross-Training": "bg-blue-500/20 text-blue-300 border-blue-500/30",
  "Yoga":           "bg-pink-500/20 text-pink-300 border-pink-500/30",
  "Rest":           "bg-zinc-700/50 text-zinc-400 border-zinc-600/30",
};

interface Workout {
  date: string;
  workout_type: string;
  description?: string | null;
  distance_km?: number | null;
  elevation_m?: number | null;
  duration_min?: number | null;
  intensity?: string | null;
  nutrition_json?: string | null;
  route_url?: string | null;
  route_analysis_json?: string | null;
  route_analyzed_at?: string | null;
  // Structured (Zwift-style) workout, cycling types only; structure_text is the server's rendering.
  structure?: Record<string, unknown> | null;
  structure_text?: string | null;
}

interface RouteAnalysis {
  verdict: string;
  explanation: string;
  suggestion?: string | null;
}

interface ComplianceDay {
  date: string;
  workout_type: string;
  status: "completed" | "modified" | "missed" | "upcoming" | "unscored";
  planned_distance_km: number | null;
  actual_distance_km: number | null;
  matched_activity_id: number | null;
  note: string;
}

interface Activity {
  id: number;
  name: string;
  date: string;
  distance_m: number;
  moving_time_s: number;
  elevation_gain_m: number | null;
  avg_pace_s_per_km: number | null;
  avg_hr: number | null;
  sport_type: string;
}

interface NutritionData {
  calories_pre: number;
  calories_during: number;
  calories_post: number;
  hydration_pre_ml: number;
  hydration_during_ml: number;
  hydration_post_ml: number;
  notes: string;
}

interface RoutePreview {
  name?: string | null;
  distance_m?: number | null;
  elevation_gain_m?: number | null;
}

interface Race {
  date: string;
  name: string;
  target_time?: string;
}

interface Prefs {
  blocked_days: string[];
  races: Race[];
}

interface GeneratedWorkout {
  date: string;
  workout_type: string;
  description?: string | null;
  distance_km?: number | null;
  elevation_m?: number | null;
  duration_min?: number | null;
  intensity?: string | null;
  structure?: Record<string, unknown> | null;
  structure_text?: string | null;
}

const GEN_STAGES: { after: number; text: string }[] = [
  { after: 0, text: "Reviewing your profile, recent training and calendar…" },
  { after: 6, text: "Drafting the training block…" },
  { after: 20, text: "Balancing load, rest days and race constraints…" },
  { after: 40, text: "Finalizing workouts…" },
  { after: 70, text: "Still working — longer blocks can take a minute or two…" },
];

// Generation is one non-streaming request, so this shows liveness (spinner + elapsed time) and
// time-based stage hints rather than real server progress.
function GeneratingProgress() {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const t0 = Date.now();
    const id = window.setInterval(() => setElapsed(Math.floor((Date.now() - t0) / 1000)), 1000);
    return () => window.clearInterval(id);
  }, []);
  const stage = [...GEN_STAGES].reverse().find(s => elapsed >= s.after) ?? GEN_STAGES[0];
  return (
    <div role="status" aria-live="polite" className="flex items-center gap-3 rounded border border-zinc-700 bg-zinc-800/60 px-3 py-3">
      <span className="h-4 w-4 shrink-0 rounded-full border-2 border-zinc-600 border-t-green-400 animate-spin" />
      <div className="min-w-0 flex-1">
        <div className="text-sm text-zinc-200">{stage.text}</div>
        <div className="text-xs text-zinc-500">
          {elapsed}s elapsed · usually 15–45 seconds · keep this window open
        </div>
      </div>
    </div>
  );
}

interface GeneratePlanResult {
  workouts: GeneratedWorkout[];
  summary: string;
  warnings?: string[];
}

// strides_ai/training_state.py (GET /api/calendar/training-state). Volumes are in the athlete's
// display unit; ramp_pct is vs the prior 4-week average.
interface TrainingState {
  load: { ctl: number | null; atl: number | null; ratio: number | null };
  thresholds: { acwr_low: number; acwr_high: number; ramp_elevated: number; ramp_high: number };
  unit: string;
  weeks: { week_start: string; volume: number; ramp_pct: number | null; flags: string[] }[];
  conflicts: { kind: string; date: string; detail: string; hard: boolean }[];
}

interface GridCell {
  date: Date;
  dateStr: string;
  dayNum: number;
  inCurrentMonth: boolean;
}

interface WeekSummary {
  cells: GridCell[];
  plannedKm: number;
  actualKm: number;
  completed: number;
  modified: number;
  missed: number;
  consistencyPct: number | null;
  onTargetPct: number | null;
}

// distance/elevation hold what the athlete sees and types, in their unit system; they are
// converted back to the stored km / m on save (see kmFromInput / mFromInput).
const EMPTY_FORM = {
  workout_type: "Easy Run",
  description: "",
  distance: "",
  elevation: "",
  duration_min: "",
  intensity: "easy",
  route_url: "",
  clear_structure: false,
};

const VERDICT_STYLES: Record<string, { cls: string; label: string }> = {
  good_match: { cls: "bg-green-500/20 text-green-300 border-green-500/30", label: "✓ Good match" },
  too_hard: { cls: "bg-red-500/20 text-red-300 border-red-500/30", label: "⚠ Too hard" },
  too_easy: { cls: "bg-blue-500/20 text-blue-300 border-blue-500/30", label: "⚠ Too easy" },
  wrong_terrain: { cls: "bg-orange-500/20 text-orange-300 border-orange-500/30", label: "⚠ Wrong terrain" },
  needs_info: { cls: "bg-zinc-700/50 text-zinc-400 border-zinc-600/30", label: "? Needs info" },
};

function fmtDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}h ${m.toString().padStart(2, "0")}m`;
  return `${m}m ${s.toString().padStart(2, "0")}s`;
}

const RUN_TYPES = new Set(["Run", "TrailRun", "VirtualRun"]);

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

export default function Calendar() {
  const units = useUnits();
  // Planned distances are stored in km; activities in meters.
  const fmtKm = (km: number | null | undefined, decimals = 1, withLabel = true) =>
    units.fmt(km == null ? null : km * 1000, "distance", { decimals, withLabel });
  const distLabel = units.label("distance");
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
  const today = new Date();
  const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;

  const [currentMonth, setCurrentMonth] = useState(
    new Date(today.getFullYear(), today.getMonth(), 1)
  );
  const [prefs, setPrefs] = useState<Prefs>({ blocked_days: [], races: [] });
  const [plan, setPlan] = useState<Record<string, Workout>>({});
  const [activities, setActivities] = useState<Record<string, Activity[]>>({});
  const [compliance, setCompliance] = useState<Record<string, ComplianceDay>>({});
  const [trainingState, setTrainingState] = useState<TrainingState | null>(null);
  const [selectedWeek, setSelectedWeek] = useState<WeekSummary | null>(null);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [editMode, setEditMode] = useState(false);
  const [nutritionLoading, setNutritionLoading] = useState(false);
  const [routeAnalysisLoading, setRouteAnalysisLoading] = useState(false);
  const [routeAnalysisError, setRouteAnalysisError] = useState<string | null>(null);
  const [showRouteForm, setShowRouteForm] = useState(false);
  const [routeUrlDraft, setRouteUrlDraft] = useState("");
  const [savingRouteUrl, setSavingRouteUrl] = useState(false);
  const [routePreviewLoading, setRoutePreviewLoading] = useState(false);
  const [routePreviewNotice, setRoutePreviewNotice] = useState<string | null>(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [showRaceForm, setShowRaceForm] = useState(false);
  const [raceForm, setRaceForm] = useState({ date: "", name: "", target_time: "" });
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  const [range, setRange] = useState<{ start: string; end: string } | null>(null);
  const rangeAnchor = useRef<string | null>(null);
  const [genModalOpen, setGenModalOpen] = useState(false);
  const [genStart, setGenStart] = useState(todayStr);
  const [genEnd, setGenEnd] = useState(todayStr);
  const [genFreeform, setGenFreeform] = useState("");
  const [genLoading, setGenLoading] = useState(false);
  const [genAccepting, setGenAccepting] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);
  const [genResult, setGenResult] = useState<GeneratePlanResult | null>(null);

  useEffect(() => {
    if (!range) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !genModalOpen) setRange(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [range, genModalOpen]);

  // Load, projected ramp and plan conflicts depend on the plan and blocked days/races, so they
  // are refetched whenever either changes (the backend is the single source of these numbers).
  useEffect(() => {
    fetch("/api/calendar/training-state")
      .then(r => (r.ok ? r.json() : null))
      .then(setTrainingState)
      .catch(() => {});
  }, [plan, prefs, units.system]);

  useEffect(() => {
    fetch("/api/calendar/prefs")
      .then(r => r.json())
      .then(setPrefs)
      .catch(() => {});
    fetch("/api/calendar/plan")
      .then(r => r.json())
      .then((rows: Workout[]) => {
        const byDate: Record<string, Workout> = {};
        for (const w of rows) byDate[w.date] = w;
        setPlan(byDate);
      })
      .catch(() => {});
    fetch("/api/activities")
      .then(r => r.json())
      .then((rows: Activity[]) => {
        const byDate: Record<string, Activity[]> = {};
        for (const a of rows) {
          if (!byDate[a.date]) byDate[a.date] = [];
          byDate[a.date].push(a);
        }
        setActivities(byDate);
      })
      .catch(() => {});
  }, []);

  // Compliance (plan-vs-actual) is fetched per-visible-grid-range rather than once for all
  // time, matching how the grid itself is paginated by month.
  useEffect(() => {
    const daysInMonth = new Date(currentMonth.getFullYear(), currentMonth.getMonth() + 1, 0).getDate();
    const firstDow = new Date(currentMonth.getFullYear(), currentMonth.getMonth(), 1).getDay();
    const totalCells = Math.ceil((firstDow + daysInMonth) / 7) * 7;
    const gridStart = new Date(currentMonth.getFullYear(), currentMonth.getMonth(), 1 - firstDow);
    const gridEnd = new Date(gridStart.getFullYear(), gridStart.getMonth(), gridStart.getDate() + totalCells - 1);
    const fmt = (d: Date) =>
      `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

    fetch(`/api/calendar/compliance?start_date=${fmt(gridStart)}&end_date=${fmt(gridEnd)}`)
      .then(r => r.json())
      .then((res: { days: ComplianceDay[] }) => {
        const byDate: Record<string, ComplianceDay> = {};
        for (const d of res.days) byDate[d.date] = d;
        setCompliance(byDate);
      })
      .catch(() => {});
    // units.system: compliance notes are rendered server-side in the current units.
  }, [currentMonth, units.system]);

  // The modal snapshots a week's cells at click time; closing it on month navigation avoids
  // showing a stale week (whose GridCell objects belonged to a now-discarded `weeks` array).
  useEffect(() => {
    setSelectedWeek(null);
  }, [currentMonth]);

  const savePrefs = useCallback((updated: Prefs) => {
    fetch("/api/calendar/prefs", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updated),
    }).catch(() => {});
  }, []);

  const toggleBlocked = (date: string) => {
    const updated = {
      ...prefs,
      blocked_days: prefs.blocked_days.includes(date)
        ? prefs.blocked_days.filter(d => d !== date)
        : [...prefs.blocked_days, date],
    };
    setPrefs(updated);
    savePrefs(updated);
  };

  const addRace = () => {
    if (!raceForm.date || !raceForm.name) return;
    const race: Race = { date: raceForm.date, name: raceForm.name };
    if (raceForm.target_time) race.target_time = raceForm.target_time;
    const updated = {
      ...prefs,
      races: [...prefs.races, race].sort((a, b) => a.date.localeCompare(b.date)),
    };
    setPrefs(updated);
    savePrefs(updated);
    setRaceForm({ date: "", name: "", target_time: "" });
    setShowRaceForm(false);
  };

  const removeRace = (date: string) => {
    const updated = { ...prefs, races: prefs.races.filter(r => r.date !== date) };
    setPrefs(updated);
    savePrefs(updated);
  };

  // While the create/edit form is showing (either editing an existing workout, or adding a
  // brand-new one — which renders the same form without editMode ever becoming true), autofill
  // distance/elevation from a pasted RideWithGPS link.
  useEffect(() => {
    const existingWorkout = selectedDate ? plan[selectedDate] : null;
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
  }, [form.route_url, editMode, selectedDate, plan]);

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
    const res = await fetch(`/api/calendar/plan/${selectedDate}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (res.ok) {
      const saved = (await res.json().catch(() => null))?.workout;
      setPlan(prev => ({ ...prev, [selectedDate]: saved ?? { date: selectedDate, ...body } }));
      setEditMode(false);
    }
  };

  const deleteWorkout = async () => {
    if (!selectedDate) return;
    const res = await fetch(`/api/calendar/plan/${selectedDate}`, { method: "DELETE" });
    if (res.ok) {
      setPlan(prev => {
        const next = { ...prev };
        delete next[selectedDate];
        return next;
      });
      setEditMode(false);
    }
  };

  const analyzeNutrition = async () => {
    if (!selectedDate) return;
    setNutritionLoading(true);
    try {
      const res = await fetch(`/api/calendar/plan/${selectedDate}/nutrition`, { method: "POST" });
      if (res.ok) {
        const nutrition = await res.json();
        setPlan(prev => ({
          ...prev,
          [selectedDate]: { ...prev[selectedDate], nutrition_json: JSON.stringify(nutrition) },
        }));
      }
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
      if (res.ok) {
        const saved = (await res.json().catch(() => null))?.workout;
        setPlan(prev => ({ ...prev, [selectedDate]: saved ?? { date: selectedDate, ...body } }));
        setShowRouteForm(false);
      }
    } finally {
      setSavingRouteUrl(false);
    }
  };

  const openGenerateModal = (range?: { start: string; end: string }) => {
    setGenStart(range?.start ?? todayStr);
    setGenEnd(range?.end ?? todayStr);
    setGenFreeform("");
    setGenResult(null);
    setGenError(null);
    setGenModalOpen(true);
  };

  const generatePlan = async () => {
    if (!genStart || !genEnd) return;
    setGenLoading(true);
    setGenError(null);
    setGenResult(null);
    try {
      const res = await fetch("/api/calendar/generate-plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          start_date: genStart,
          end_date: genEnd,
          freeform_text: genFreeform,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        setGenError(err.detail || "Failed to generate training block.");
        return;
      }
      setGenResult(await res.json());
    } catch {
      setGenError("Failed to generate training block. Check your connection and try again.");
    } finally {
      setGenLoading(false);
    }
  };

  const acceptGeneratedPlan = async () => {
    if (!genResult || genResult.workouts.length === 0) return;
    setGenAccepting(true);
    setGenError(null);
    try {
      const res = await fetch("/api/calendar/plan/bulk", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ set: genResult.workouts }),
      });
      if (!res.ok) {
        setGenError("Failed to save the training block.");
        return;
      }
      setPlan(prev => {
        const next = { ...prev };
        for (const w of genResult.workouts) next[w.date] = w;
        return next;
      });
      setGenModalOpen(false);
    } finally {
      setGenAccepting(false);
    }
  };

  const selectDate = (date: string) => {
    setSelectedDate(date);
    setEditMode(false);
    setConfirmingDelete(false);
    setRouteAnalysisError(null);
    setShowRouteForm(false);
    setRoutePreviewNotice(null);
    const existing = plan[date];
    setForm(existing ? formFromWorkout(existing) : EMPTY_FORM);
  };

  // Shift-click extends a range from the last plainly-clicked day (the anchor); a plain click
  // moves the anchor and clears any range. The range feeds "Generate plan" for those days.
  const handleDayClick = (e: React.MouseEvent, date: string) => {
    if (e.shiftKey) {
      const anchor = rangeAnchor.current ?? selectedDate ?? date;
      rangeAnchor.current = anchor;
      setRange(anchor <= date ? { start: anchor, end: date } : { start: date, end: anchor });
      return;
    }
    rangeAnchor.current = date;
    setRange(null);
    openDay(date);
  };

  // Drag a planned workout onto another day. An occupied target swaps the two workouts. Bulk
  // upsert both days (no deletes needed); optimistic, reverted if the save fails.
  const [dragFrom, setDragFrom] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState<string | null>(null);
  const movePending = useRef(false);

  const moveWorkout = async (from: string, to: string) => {
    const moving = plan[from];
    if (!moving || from === to || movePending.current) return;
    movePending.current = true;
    const displaced = plan[to];
    const entry = (w: Workout, date: string) => ({
      date,
      workout_type: w.workout_type,
      description: w.description ?? null,
      distance_km: w.distance_km ?? null,
      elevation_m: w.elevation_m ?? null,
      duration_min: w.duration_min ?? null,
      intensity: w.intensity ?? null,
      route_url: w.route_url ?? null,
      structure: w.structure ?? null,
    });
    const set = [entry(moving, to), ...(displaced ? [entry(displaced, from)] : [])];
    const moved = { ...moving, date: to, nutrition_json: null, route_analysis_json: null };
    const swapped = displaced
      ? { ...displaced, date: from, nutrition_json: null, route_analysis_json: null }
      : undefined;
    const rollback = () => setPlan(prev => {
      const next = { ...prev };
      // Keep any edits made while the move was saving, including on unrelated days.
      if (prev[from] === swapped) next[from] = moving;
      if (prev[to] === moved) {
        if (displaced) next[to] = displaced;
        else delete next[to];
      }
      return next;
    });
    setPlan(prev => {
      const next = { ...prev };
      delete next[from];
      next[to] = moved;
      if (swapped) next[from] = swapped;
      return next;
    });
    if (selectedDate === from || selectedDate === to) {
      setSelectedDate(null);
      setEditMode(false);
    }
    try {
      const res = await fetch("/api/calendar/plan/bulk", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ set, delete: displaced ? [] : [from] }),
      });
      if (!res.ok) rollback();
    } catch {
      rollback();
    } finally {
      movePending.current = false;
    }
  };

  const openDay = (date: string) => {
    if (selectedDate === date) {
      setSelectedDate(null);
      return;
    }
    selectDate(date);
  };

  const goToToday = () => {
    setCurrentMonth(new Date(today.getFullYear(), today.getMonth(), 1));
    selectDate(todayStr);
  };

  const startEdit = () => {
    const existing = selectedDate ? plan[selectedDate] : null;
    setForm(formFromWorkout(existing));
    setRoutePreviewNotice(null);
    setEditMode(true);
  };

  // Calendar grid helpers — always render full weeks, including the leading/trailing
  // days of the adjacent months, so a training week is never cut off mid-row.
  const daysInMonth = new Date(currentMonth.getFullYear(), currentMonth.getMonth() + 1, 0).getDate();
  const firstDow = new Date(currentMonth.getFullYear(), currentMonth.getMonth(), 1).getDay();
  const totalCells = Math.ceil((firstDow + daysInMonth) / 7) * 7;
  const gridStart = new Date(currentMonth.getFullYear(), currentMonth.getMonth(), 1 - firstDow);

  const dateToStr = (d: Date) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

  const gridCells: GridCell[] = Array.from({ length: totalCells }, (_, i) => {
    const d = new Date(gridStart.getFullYear(), gridStart.getMonth(), gridStart.getDate() + i);
    return {
      date: d,
      dateStr: dateToStr(d),
      dayNum: d.getDate(),
      inCurrentMonth: d.getMonth() === currentMonth.getMonth(),
    };
  });

  const weeks: GridCell[][] = [];
  for (let i = 0; i < gridCells.length; i += 7) weeks.push(gridCells.slice(i, i + 7));

  const rangeDays = range
    ? Math.round(
        (new Date(range.end + "T12:00:00").getTime() - new Date(range.start + "T12:00:00").getTime()) /
          86_400_000
      ) + 1
    : 0;

  const dowName = (dateStr: string) =>
    DAY_NAMES[new Date(dateStr + "T12:00:00").getDay()];

  const raceOnDate = (dateStr: string) => prefs.races.find(r => r.date === dateStr);

  const selectedWorkout = selectedDate ? plan[selectedDate] : null;
  const hasFormStructure = !!selectedWorkout?.structure && keepsStructure(form.workout_type) && !form.clear_structure;
  // Split a day's activities into the one matched to its planned workout (merged into the
  // workout in the UI) and the rest. Without a plan nothing is matched.
  const splitActivities = (dateStr: string) => {
    const all = activities[dateStr] ?? [];
    const matchedId = plan[dateStr] ? compliance[dateStr]?.matched_activity_id : null;
    const matched = matchedId != null ? all.find(a => a.id === matchedId) : undefined;
    return { matched, others: matched ? all.filter(a => a !== matched) : all };
  };
  const renderActivityCard = (a: Activity) => {
    const isRun = RUN_TYPES.has(a.sport_type);
    return (
      <div key={a.id} className="bg-zinc-800/60 rounded p-2 border border-zinc-700/50 space-y-1">
        <div className="text-xs font-medium text-zinc-200 truncate">{a.name}</div>
        <div className="text-xs text-zinc-500">{a.sport_type}</div>
        <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs">
          <span className="text-zinc-500">Distance</span>
          <span className="text-zinc-300">{units.fmt(a.distance_m ?? 0, "distance")}</span>
          <span className="text-zinc-500">Duration</span>
          <span className="text-zinc-300">{fmtDuration(a.moving_time_s)}</span>
          {isRun && a.avg_pace_s_per_km && (
            <>
              <span className="text-zinc-500">Pace</span>
              <span className="text-zinc-300">{units.fmt(a.avg_pace_s_per_km, "pace")}</span>
            </>
          )}
          {a.avg_hr && (
            <>
              <span className="text-zinc-500">Avg HR</span>
              <span className="text-zinc-300">{Math.round(a.avg_hr)} bpm</span>
            </>
          )}
          {a.elevation_gain_m != null && (
            <>
              <span className="text-zinc-500">Elevation</span>
              <span className="text-zinc-300">{units.fmt(a.elevation_gain_m, "elevation")}</span>
            </>
          )}
        </div>
      </div>
    );
  };
  const selectedSplit = selectedDate ? splitActivities(selectedDate) : { matched: undefined, others: [] };
  const selectedActivities = selectedSplit.others;
  const selectedNutrition: NutritionData | null = selectedWorkout?.nutrition_json
    ? JSON.parse(selectedWorkout.nutrition_json)
    : null;
  const selectedRouteAnalysis: RouteAnalysis | null = selectedWorkout?.route_analysis_json
    ? JSON.parse(selectedWorkout.route_analysis_json)
    : null;

  const showNutritionCol = selectedWorkout && !editMode && selectedWorkout.workout_type !== "Rest";

  // First conflict per date (blocked-day / race-day) for the ⚠ badge on a day cell.
  const conflictByDate: Record<string, string> = {};
  for (const c of trainingState?.conflicts ?? []) {
    if (c.hard && !conflictByDate[c.date]) conflictByDate[c.date] = c.detail;
  }

  // Ramp vs the prior 4-week average for the ISO week (Mon-Sun) shown in this Sunday-start row.
  // Past weeks have no entry (the backend only returns the current and upcoming weeks).
  const rampChip = (weekCells: GridCell[]) => {
    const monday = weekCells.find(c => c.date.getDay() === 1);
    const w = monday && trainingState?.weeks.find(x => x.week_start === monday.dateStr);
    if (!w || w.ramp_pct === null || !trainingState) return null;
    const t = trainingState.thresholds;
    const color =
      w.ramp_pct > t.ramp_high ? "text-red-400" : w.ramp_pct > t.ramp_elevated ? "text-amber-400" : "text-zinc-500";
    const title = w.flags.length ? w.flags.join(", ").replace(/_/g, " ") : "vs prior 4-week average";
    return (
      <div className={`text-[10px] ${color}`} title={title}>
        {w.ramp_pct > 0 ? "+" : ""}{Math.round(w.ramp_pct)}% ramp{w.flags.includes("no_recovery_week") ? " ⚠" : ""}
      </div>
    );
  };

  return (
    <div className="flex h-full bg-zinc-900 text-zinc-100 overflow-hidden">

      {/* ── Left sidebar ── */}
      <aside className="w-56 flex-shrink-0 border-r border-zinc-800 overflow-y-auto p-4 space-y-6">

        <div>
          <button
            onClick={() => openGenerateModal()}
            className="w-full text-left bg-gradient-to-br from-green-700/90 to-green-800/90 hover:from-green-600/90 hover:to-green-700/90 text-white rounded-lg px-3 py-2.5 flex items-center gap-2.5 transition-colors border border-green-600/40"
          >
            <span className="text-lg leading-none">✨</span>
            <span className="min-w-0">
              <div className="text-sm font-semibold leading-tight">Generate Training Block</div>
              <div className="text-[11px] text-green-100/75 leading-tight">AI-suggested plan for a date range</div>
            </span>
          </button>
        </div>

        <div>
          <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2">Races</h3>
          <div className="space-y-2 mb-2">
            {prefs.races.map(race => (
              <div key={race.date} className="flex items-start justify-between gap-1">
                <div className="text-xs">
                  <div className="text-amber-300 font-medium">{race.name}</div>
                  <div className="text-zinc-500">
                    {race.date}{race.target_time ? ` · ${race.target_time}` : ""}
                  </div>
                </div>
                <button
                  onClick={() => removeRace(race.date)}
                  className="text-zinc-600 hover:text-zinc-300 text-xs mt-0.5 leading-none"
                >✕</button>
              </div>
            ))}
          </div>
          {showRaceForm ? (
            <div className="space-y-1">
              <input
                type="date" value={raceForm.date}
                onChange={e => setRaceForm(f => ({ ...f, date: e.target.value }))}
                className="w-full text-xs bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-zinc-200"
              />
              <input
                type="text" placeholder="Race name" value={raceForm.name}
                onChange={e => setRaceForm(f => ({ ...f, name: e.target.value }))}
                className="w-full text-xs bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-zinc-200"
              />
              <input
                type="text" placeholder="Target time (optional)" value={raceForm.target_time}
                onChange={e => setRaceForm(f => ({ ...f, target_time: e.target.value }))}
                className="w-full text-xs bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-zinc-200"
              />
              <div className="flex gap-1">
                <button onClick={addRace} className="flex-1 text-xs bg-amber-600 hover:bg-amber-500 text-white rounded px-2 py-1">Add</button>
                <button onClick={() => setShowRaceForm(false)} className="flex-1 text-xs bg-zinc-700 hover:bg-zinc-600 text-zinc-300 rounded px-2 py-1">Cancel</button>
              </div>
            </div>
          ) : (
            <button onClick={() => setShowRaceForm(true)} className="text-xs text-zinc-500 hover:text-zinc-300">
              + Add race
            </button>
          )}
        </div>

        <div>
          <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2">Legend</h3>
          <div className="space-y-2 mb-3">
            {WORKOUT_TYPE_GROUPS.map(group => (
              <div key={group.label}>
                <div className="text-[10px] text-zinc-600 uppercase tracking-wider mb-0.5">{group.label}</div>
                <div className="space-y-1">
                  {group.types.map(type => (
                    <div key={type} className="flex items-center gap-2">
                      <span className={`w-2 h-2 rounded-full ${WORKOUT_COLORS[type].split(" ")[0]}`} />
                      <span className="text-xs text-zinc-400">{type}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-zinc-500" />
            <span className="text-xs text-zinc-400">Strava activity</span>
          </div>
          <div className="mt-3 pt-3 border-t border-zinc-800 space-y-1">
            <div className="text-[10px] text-zinc-600 uppercase tracking-wider mb-0.5">Plan compliance</div>
            <div className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-green-400" />
              <span className="text-xs text-zinc-400">Completed as planned</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
              <span className="text-xs text-zinc-400">Modified (fell short of target)</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-red-400" />
              <span className="text-xs text-zinc-400">Missed</span>
            </div>
            <div className="text-[10px] text-zinc-600">No dot = upcoming or not scorable (rest/yoga)</div>
          </div>
        </div>
      </aside>

      {/* ── Main column ── */}
      <div className="flex-1 flex min-w-0 overflow-hidden">
      <div className="flex-1 min-w-0 flex flex-col overflow-y-auto">

        {/* ── Calendar grid ── */}
        <div className="flex-shrink-0">
          <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-800">
            <div className="flex items-center gap-1">
              <button
                onClick={goToToday}
                className="text-xs bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded px-2 py-1 mr-1"
              >Today</button>
              <button
                onClick={() => setCurrentMonth(m => new Date(m.getFullYear(), m.getMonth() - 1, 1))}
                className="text-zinc-400 hover:text-zinc-200 px-2 text-lg"
              >‹</button>
            </div>
            <h2 className="text-sm font-semibold text-zinc-200">
              {currentMonth.toLocaleString("default", { month: "long", year: "numeric" })}
            </h2>
            <button
              onClick={() => setCurrentMonth(m => new Date(m.getFullYear(), m.getMonth() + 1, 1))}
              className="text-zinc-400 hover:text-zinc-200 px-2 text-lg"
            >›</button>
          </div>

          {trainingState && <LoadStrip state={trainingState} />}

          <div className="p-3">
            {/* Day-of-week headers */}
            <div className="flex gap-1 mb-1">
              {DAYS_OF_WEEK.map(d => (
                <div key={d} className="flex-1 min-w-0 text-center text-xs text-zinc-500 font-medium py-1">{d}</div>
              ))}
              <div className="w-20 flex-shrink-0" />
            </div>

            {/* Week rows */}
            {weeks.map((weekCells, wi) => {
              const plannedKm = weekCells.reduce<number>((sum, cell) => {
                const w = plan[cell.dateStr];
                return sum + (w && w.workout_type !== "Rest" ? (w.distance_km ?? 0) : 0);
              }, 0);
              const actualKm = weekCells.reduce<number>((sum, cell) => {
                return sum + (activities[cell.dateStr] ?? []).reduce<number>(
                  (s, a) => s + (a.distance_m ?? 0) / 1000, 0
                );
              }, 0);
              // Weekly consistency/on-target %: counts the already-backend-computed per-day
              // statuses and reapplies the same two formulas strides_ai/compliance.py uses —
              // duplicates two arithmetic lines only, never the matching/tolerance logic.
              const weekCompliance = weekCells.reduce(
                (acc, cell) => {
                  const status = compliance[cell.dateStr]?.status;
                  if (status === "completed") acc.completed++;
                  else if (status === "modified") acc.modified++;
                  else if (status === "missed") acc.missed++;
                  return acc;
                },
                { completed: 0, modified: 0, missed: 0 }
              );
              const weekScored = weekCompliance.completed + weekCompliance.modified + weekCompliance.missed;
              const consistencyPct = weekScored > 0
                ? Math.round((100 * (weekCompliance.completed + weekCompliance.modified)) / weekScored)
                : null;
              const onTargetPct = weekScored > 0
                ? Math.round((100 * weekCompliance.completed) / weekScored)
                : null;

              return (
                <div key={wi} className="flex gap-1 mb-3">
                  {weekCells.map(cell => {
                    const dateStr = cell.dateStr;
                    const workout = plan[dateStr];
                    const { matched: matchedActivity, others: dayActivities } = splitActivities(dateStr);
                    const isToday = dateStr === todayStr;
                    const isSelected = selectedDate === dateStr;
                    const inRange = !!range && dateStr >= range.start && dateStr <= range.end;
                    const isBlocked = prefs.blocked_days.includes(dateStr);
                    const race = raceOnDate(dateStr);
                    const showMonthLabel = cell.dayNum === 1 && !cell.inCurrentMonth;
                    const complianceStatus = compliance[dateStr]?.status;
                    const dotColor = complianceStatus ? COMPLIANCE_DOT_COLORS[complianceStatus] : undefined;

                    return (
                      <div
                        key={dateStr}
                        onClick={e => handleDayClick(e, dateStr)}
                        onMouseDown={e => { if (e.shiftKey) e.preventDefault(); }}
                        onDragOver={e => {
                          if (!dragFrom || dragFrom === dateStr) return;
                          e.preventDefault();
                          e.dataTransfer.dropEffect = "move";
                          if (dragOver !== dateStr) setDragOver(dateStr);
                        }}
                        onDragLeave={() => { if (dragOver === dateStr) setDragOver(null); }}
                        onDrop={e => {
                          e.preventDefault();
                          const from = dragFrom;
                          setDragFrom(null);
                          setDragOver(null);
                          if (from) moveWorkout(from, dateStr);
                        }}
                        className={[
                          dragOver === dateStr ? "ring-2 ring-inset ring-sky-400/80" : "",
                          "flex-1 min-w-0 min-h-16 p-1.5 rounded cursor-pointer border transition-colors select-none",
                          inRange ? "border-green-500/70 bg-green-500/10" : isSelected ? "border-zinc-400 bg-zinc-700/60" : "border-zinc-800 hover:border-zinc-600",
                          isToday ? "ring-2 ring-inset ring-green-400/80 border-green-400/60" : "",
                          isBlocked ? "opacity-40" : "",
                          !cell.inCurrentMonth ? "opacity-55" : "",
                          "bg-zinc-800/20",
                        ].join(" ")}
                      >
                        <div className={`text-xs font-medium mb-1 flex items-center gap-1 ${isToday ? "text-green-400" : cell.inCurrentMonth ? "text-zinc-400" : "text-zinc-600"}`}>
                          {showMonthLabel
                            ? `${cell.date.toLocaleString("default", { month: "short" })} ${cell.dayNum}`
                            : cell.dayNum}
                          {isToday && <span className="w-1.5 h-1.5 bg-green-400 rounded-full" />}
                          {conflictByDate[dateStr] && (
                            <span title={conflictByDate[dateStr]} className="text-amber-400 ml-auto">⚠</span>
                          )}
                          {dotColor && (
                            <span
                              title={compliance[dateStr]?.note}
                              className={`w-1.5 h-1.5 rounded-full ml-auto ${dotColor}`}
                            />
                          )}
                        </div>
                        {race && (
                          <div className="text-xs px-1 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/30 truncate mb-0.5">
                            🏁 {race.name}
                          </div>
                        )}
                        {workout && (
                          <div
                            draggable
                            onDragStart={e => {
                              if (movePending.current) { e.preventDefault(); return; }
                              e.dataTransfer.effectAllowed = "move";
                              e.dataTransfer.setData("text/plain", dateStr);
                              setDragFrom(dateStr);
                            }}
                            onDragEnd={() => { setDragFrom(null); setDragOver(null); }}
                            className={`text-xs px-1 py-0.5 rounded border truncate mb-0.5 cursor-grab active:cursor-grabbing ${dragFrom === dateStr ? "opacity-40" : ""} ${WORKOUT_COLORS[workout.workout_type] ?? "bg-zinc-700/50 text-zinc-400 border-zinc-600/30"}`}>
                            {matchedActivity && "✓ "}
                            {workout.workout_type}
                            {matchedActivity ? (
                              <span className="ml-1 opacity-90">
                                {units.fmt(matchedActivity.distance_m ?? 0, "distance", { decimals: 1 })}
                                {workout.distance_km ? (
                                  <span className="opacity-60"> / {fmtKm(workout.distance_km)}</span>
                                ) : null}
                              </span>
                            ) : (
                              workout.distance_km && (
                                <span className="ml-1 opacity-70">{fmtKm(workout.distance_km)}</span>
                              )
                            )}
                          </div>
                        )}
                        {dayActivities.map(a => (
                          <div key={a.id} className="text-xs px-1 py-0.5 rounded bg-zinc-600/40 text-zinc-300 border border-zinc-600/40 truncate mb-0.5">
                            ✓ {units.fmt(a.distance_m ?? 0, "distance", { decimals: 1 })} {a.sport_type}
                          </div>
                        ))}
                      </div>
                    );
                  })}

                  {/* Weekly totals — clickable, opens a larger per-day breakdown pane */}
                  <button
                    onClick={() =>
                      setSelectedWeek({
                        cells: weekCells,
                        plannedKm,
                        actualKm,
                        completed: weekCompliance.completed,
                        modified: weekCompliance.modified,
                        missed: weekCompliance.missed,
                        consistencyPct,
                        onTargetPct,
                      })
                    }
                    className="w-20 flex-shrink-0 flex flex-col justify-center gap-3 px-3 ml-1 rounded bg-zinc-800/40 border border-zinc-700/50 hover:border-zinc-500 hover:bg-zinc-800/70 transition-colors text-left cursor-pointer"
                  >
                    <div>
                      <div className="text-[10px] text-zinc-500 uppercase tracking-wider mb-0.5">Planned</div>
                      <div className="text-sm text-zinc-300 font-semibold">
                        {plannedKm > 0 ? fmtKm(plannedKm, 1, false) : "—"}
                      </div>
                      {plannedKm > 0 && <div className="text-[10px] text-zinc-500">{distLabel}</div>}
                      {rampChip(weekCells)}
                    </div>
                    <div>
                      <div className="text-[10px] text-zinc-500 uppercase tracking-wider mb-0.5">Actual</div>
                      <div className={`text-sm font-semibold ${actualKm > 0 ? "text-green-400" : "text-zinc-600"}`}>
                        {actualKm > 0 ? fmtKm(actualKm, 1, false) : "—"}
                      </div>
                      {actualKm > 0 && <div className="text-[10px] text-zinc-500">{distLabel}</div>}
                    </div>
                    {weekScored > 0 && (
                      <div>
                        <div className="text-[10px] text-zinc-500 uppercase tracking-wider mb-0.5">On-Target</div>
                        <div className="text-sm font-semibold text-zinc-300">{onTargetPct}%</div>
                        <div className="text-[10px] text-zinc-500">{consistencyPct}% did something</div>
                      </div>
                    )}
                  </button>
                </div>
              );
            })}
          </div>
        </div>

      </div>

        {/* ── Side panel: range actions or the selected day. A fixed overlay below lg so it never
            pushes the grid; docked beside the grid on wide screens so the calendar stays in view. ── */}
        {(range || selectedDate) && (
          <aside className="fixed inset-y-0 right-0 z-30 w-full sm:w-96 lg:static lg:z-auto lg:w-80 lg:flex-shrink-0 border-l border-zinc-800 bg-zinc-900 overflow-y-auto shadow-2xl lg:shadow-none">
            {range ? (
              <div className="p-4 space-y-4">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm font-semibold text-zinc-200">
                      {rangeDays} day{rangeDays === 1 ? "" : "s"} selected
                    </div>
                    <div className="text-xs text-zinc-500">{range.start} → {range.end}</div>
                  </div>
                  <button
                    onClick={() => setRange(null)}
                    className="text-zinc-500 hover:text-zinc-300 text-xl leading-none"
                  >×</button>
                </div>
                <button
                  onClick={() => openGenerateModal(range)}
                  className="w-full bg-green-600 hover:bg-green-500 text-white rounded px-3 py-2 text-sm font-medium"
                >
                  Generate plan for selection
                </button>
                <p className="text-xs text-zinc-600">
                  Shift-click another day to adjust the range. Click a day or press Esc to clear it.
                </p>
              </div>
            ) : selectedDate && (
            <div className="p-4 flex flex-col gap-6">

              {/* Col 1: date info + planned workout */}
              <div className="min-w-0 space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm font-semibold text-zinc-200">{selectedDate}</div>
                    <div className="text-xs text-zinc-500">{dowName(selectedDate)}</div>
                  </div>
                  <button
                    onClick={() => setSelectedDate(null)}
                    className="text-zinc-500 hover:text-zinc-300 text-xl leading-none"
                  >×</button>
                </div>

                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={prefs.blocked_days.includes(selectedDate)}
                    onChange={() => toggleBlocked(selectedDate)}
                    className="accent-zinc-500"
                  />
                  <span className="text-xs text-zinc-400">Mark as blocked (unavailable)</span>
                </label>

                {/* Planned workout: view or form */}
                {selectedWorkout && !editMode ? (
                  <div className="space-y-2">
                    <h4 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Planned</h4>
                    <div className={`px-3 py-2 rounded border ${WORKOUT_COLORS[selectedWorkout.workout_type] ?? "bg-zinc-700/50 text-zinc-400 border-zinc-600/30"}`}>
                      <div className="font-medium text-sm">{selectedWorkout.workout_type}</div>
                      {selectedWorkout.intensity && (
                        <div className="text-xs opacity-70 capitalize mt-0.5">{selectedWorkout.intensity} intensity</div>
                      )}
                    </div>
                    {(selectedWorkout.distance_km || selectedWorkout.elevation_m || selectedWorkout.duration_min) && (
                      <div className="flex gap-2 flex-wrap">
                        {selectedWorkout.distance_km && (
                          <div className="bg-zinc-800 rounded p-2 text-xs">
                            <div className="text-zinc-500">Distance</div>
                            <div className="text-zinc-200 font-medium">{fmtKm(selectedWorkout.distance_km, 2)}</div>
                          </div>
                        )}
                        {selectedWorkout.duration_min && (
                          <div className="bg-zinc-800 rounded p-2 text-xs">
                            <div className="text-zinc-500">Duration</div>
                            <div className="text-zinc-200 font-medium">{selectedWorkout.duration_min} min</div>
                          </div>
                        )}
                        {selectedWorkout.elevation_m && (
                          <div className="bg-zinc-800 rounded p-2 text-xs">
                            <div className="text-zinc-500">Elevation</div>
                            <div className="text-zinc-200 font-medium">{units.fmt(selectedWorkout.elevation_m, "elevation")}</div>
                          </div>
                        )}
                        {(() => {
                          const rate = plannedClimbRate(selectedWorkout.distance_km, selectedWorkout.elevation_m);
                          if (rate == null) return null;
                          const group = WORKOUT_TYPE_GROUPS[0].types.includes(selectedWorkout.workout_type)
                            ? "run" : keepsStructure(selectedWorkout.workout_type) ? "ride" : "other";
                          const terrain = climbLabel(rate, group);
                          return (
                            <div className="bg-zinc-800 rounded p-2 text-xs" title={terrain?.detail}>
                              <div className="text-zinc-500">Climb ratio</div>
                              <div className="text-zinc-200 font-medium">
                                {units.fmt(rate, "climb_rate")}
                                {terrain && <span className="ml-1 text-zinc-400 font-normal">{terrain.text}</span>}
                              </div>
                            </div>
                          );
                        })()}
                      </div>
                    )}
                    {selectedWorkout.description && (
                      <p className="text-xs text-zinc-400 leading-relaxed">{selectedWorkout.description}</p>
                    )}
                    {selectedSplit.matched && (
                      <div className="space-y-2">
                        <h4 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Actual (Strava)</h4>
                        {renderActivityCard(selectedSplit.matched)}
                      </div>
                    )}
                    {selectedWorkout.structure_text && (
                      <div className="bg-zinc-800/60 rounded p-2 text-xs space-y-1.5">
                        <div className="text-zinc-500">Structured workout (% FTP)</div>
                        <div className="text-zinc-300 leading-relaxed">{selectedWorkout.structure_text}</div>
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
                          className="flex-1 text-xs bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-zinc-200"
                        />
                        <button
                          onClick={saveRouteUrl}
                          disabled={savingRouteUrl}
                          className="text-xs bg-green-700 hover:bg-green-600 disabled:opacity-50 text-white rounded px-2 py-1"
                        >{savingRouteUrl ? "Saving…" : "Save"}</button>
                        <button
                          onClick={() => setShowRouteForm(false)}
                          className="text-xs text-zinc-500 hover:text-zinc-300 px-1"
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
                              className="text-xs text-zinc-500 hover:text-zinc-300"
                            >Change</button>
                          </div>
                          <button
                            onClick={() => analyzeRoute(!!selectedRouteAnalysis)}
                            disabled={routeAnalysisLoading}
                            className="text-xs bg-zinc-700 hover:bg-zinc-600 disabled:opacity-50 text-zinc-300 rounded px-2 py-0.5"
                          >
                            {routeAnalysisLoading ? "Analyzing…" : selectedRouteAnalysis ? "Refresh" : "Analyze Route"}
                          </button>
                        </div>
                        {routeAnalysisError && (
                          <p className="text-xs text-red-400">{routeAnalysisError}</p>
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
                        className="text-xs text-zinc-500 hover:text-zinc-300"
                      >+ Add route</button>
                      )
                    )}
                    <div className="flex items-center gap-2">
                      <button onClick={startEdit} className="text-sm bg-zinc-700 hover:bg-zinc-600 text-zinc-200 rounded px-4 py-2">Edit</button>
                      {confirmingDelete ? (
                        <>
                          <button onClick={deleteWorkout} className="text-xs bg-red-700 hover:bg-red-600 text-white rounded px-3 py-1.5">Confirm delete</button>
                          <button onClick={() => setConfirmingDelete(false)} className="text-xs text-zinc-500 hover:text-zinc-300 px-2 py-1.5">Cancel</button>
                        </>
                      ) : (
                        <button onClick={() => setConfirmingDelete(true)} className="text-xs text-red-500 hover:text-red-400 px-2 py-1.5">Delete</button>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="space-y-2">
                    <h4 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">
                      {selectedWorkout ? "Edit Planned Workout" : "Add Planned Workout"}
                    </h4>
                    <div>
                      <label className="text-xs text-zinc-500 mb-1 block">Type</label>
                      <select
                        value={form.workout_type}
                        onChange={e => setForm(f => ({ ...f, workout_type: e.target.value }))}
                        className="w-full text-sm bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-zinc-200"
                      >
                        {WORKOUT_TYPE_GROUPS.map(group => (
                          <optgroup key={group.label} label={group.label}>
                            {group.types.map(t => <option key={t} value={t}>{t}</option>)}
                          </optgroup>
                        ))}
                      </select>
                    </div>
                    {selectedWorkout?.structure && keepsStructure(form.workout_type) && (
                      <label className="flex items-center gap-2 text-xs text-zinc-400">
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
                        <label className="text-xs text-zinc-500 mb-1 block">Distance ({distLabel})</label>
                        <input
                          type="number" step="0.1" placeholder="—"
                          value={form.distance}
                          onChange={e => setForm(f => ({ ...f, distance: e.target.value }))}
                          className="w-full text-sm bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-zinc-200"
                        />
                      </div>
                      )}
                      {!NO_DISTANCE_WORKOUT_TYPES.has(form.workout_type) && (
                      <div>
                        <label className="text-xs text-zinc-500 mb-1 block">Elevation ({units.label("elevation")})</label>
                        <input
                          type="number" placeholder="—"
                          value={form.elevation}
                          onChange={e => setForm(f => ({ ...f, elevation: e.target.value }))}
                          className="w-full text-sm bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-zinc-200"
                        />
                      </div>
                      )}
                      <div>
                        <label className="text-xs text-zinc-500 mb-1 block">Duration (min)</label>
                        <input
                          type="number" placeholder="—"
                          value={hasFormStructure ? selectedWorkout?.duration_min?.toString() ?? "" : form.duration_min}
                          disabled={hasFormStructure}
                          aria-describedby={hasFormStructure ? "structured-duration-help" : undefined}
                          onChange={e => setForm(f => ({ ...f, duration_min: e.target.value }))}
                          className="w-full text-sm bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-zinc-200 disabled:opacity-50"
                        />
                        {hasFormStructure && (
                          <p id="structured-duration-help" className="mt-1 text-xs text-zinc-500">
                            Duration comes from the structure. Remove it to edit duration.
                          </p>
                        )}
                      </div>
                      <div>
                        <label className="text-xs text-zinc-500 mb-1 block">Intensity</label>
                        <select
                          value={form.intensity}
                          onChange={e => setForm(f => ({ ...f, intensity: e.target.value }))}
                          className="w-full text-sm bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-zinc-200"
                        >
                          {INTENSITIES.map(i => (
                            <option key={i} value={i}>{i.charAt(0).toUpperCase() + i.slice(1)}</option>
                          ))}
                        </select>
                      </div>
                    </div>
                    <div>
                      <label className="text-xs text-zinc-500 mb-1 block">Notes (optional)</label>
                      <textarea
                        rows={2}
                        placeholder="What's the goal for this workout?"
                        value={form.description}
                        onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                        className="w-full text-sm bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-zinc-200 resize-none"
                      />
                    </div>
                    {ROUTE_CAPABLE_WORKOUT_TYPES.has(form.workout_type) && (
                    <div>
                      <label className="text-xs text-zinc-500 mb-1 block">Route URL (optional)</label>
                      <input
                        type="url"
                        placeholder="https://ridewithgps.com/routes/... or https://strava.com/routes/..."
                        value={form.route_url}
                        onChange={e => setForm(f => ({ ...f, route_url: e.target.value }))}
                        className="w-full text-sm bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-zinc-200"
                      />
                      {routePreviewLoading && (
                        <p className="text-xs text-zinc-500 mt-1">Fetching route details…</p>
                      )}
                      {!routePreviewLoading && routePreviewNotice && (
                        <p className="text-xs text-zinc-500 mt-1">{routePreviewNotice}</p>
                      )}
                    </div>
                    )}
                    <div className="flex gap-2">
                      <button
                        onClick={saveWorkout}
                        className="flex-1 text-sm bg-green-700 hover:bg-green-600 text-white rounded px-3 py-1.5"
                      >Save</button>
                      <button
                        onClick={() => { setEditMode(false); if (!selectedWorkout) setSelectedDate(null); }}
                        className="flex-1 text-sm bg-zinc-700 hover:bg-zinc-600 text-zinc-300 rounded px-3 py-1.5"
                      >Cancel</button>
                    </div>
                  </div>
                )}
              </div>

              {/* Col 2: Strava activities */}
              {selectedActivities.length > 0 && (
                <div className="space-y-2">
                  <h4 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Strava</h4>
                  {selectedActivities.map(renderActivityCard)}
                </div>
              )}

              {/* Col 3: Nutrition */}
              {showNutritionCol && (
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <h4 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Nutrition</h4>
                    <button
                      onClick={analyzeNutrition}
                      disabled={nutritionLoading}
                      className="text-xs bg-zinc-700 hover:bg-zinc-600 disabled:opacity-50 text-zinc-300 rounded px-2 py-0.5"
                    >
                      {nutritionLoading ? "Analyzing…" : selectedNutrition ? "Refresh" : "Get advice"}
                    </button>
                  </div>
                  {selectedNutrition ? (
                    <>
                      <div className="text-sm text-zinc-400 font-medium">Calories (kcal)</div>
                      <div className="grid grid-cols-3 gap-2 text-center">
                        {(["pre", "during", "post"] as const).map(phase => (
                          <div key={phase} className="bg-zinc-800 rounded p-2">
                            <div className="text-xs text-zinc-500 capitalize mb-1">{phase}</div>
                            <div className="text-sm font-semibold text-zinc-200">
                              {selectedNutrition[`calories_${phase}` as keyof NutritionData] as number}
                            </div>
                          </div>
                        ))}
                      </div>
                      <div className="text-sm text-zinc-400 font-medium">Hydration ({units.label("volume")})</div>
                      <div className="grid grid-cols-3 gap-2 text-center">
                        {(["pre", "during", "post"] as const).map(phase => (
                          <div key={phase} className="bg-zinc-800/60 rounded p-2">
                            <div className="text-xs text-zinc-500 capitalize mb-1">{phase}</div>
                            <div className="text-sm font-semibold text-blue-300">
                              {units.fmt(selectedNutrition[`hydration_${phase}_ml` as keyof NutritionData] as number, "volume", { withLabel: false })}
                            </div>
                          </div>
                        ))}
                      </div>
                      <p className="text-sm text-zinc-400 leading-relaxed">{selectedNutrition.notes}</p>
                    </>
                  ) : (
                    <p className="text-sm text-zinc-600 italic">
                      Click "Get advice" for personalized calorie and hydration recommendations.
                    </p>
                  )}
                </div>
              )}
            </div>
            )}
          </aside>
        )}
      </div>

      {/* ── Generate training block modal ── */}
      {genModalOpen && (
        <>
          <div
            className="fixed inset-0 z-40 bg-black/60"
            onClick={() => !genLoading && !genAccepting && setGenModalOpen(false)}
          />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 pointer-events-none">
            <div className="pointer-events-auto bg-zinc-900 border border-zinc-700 rounded-lg w-full max-w-lg max-h-[85vh] overflow-y-auto shadow-2xl">
              <div className="px-5 py-4 border-b border-zinc-800 flex items-center justify-between">
                <h3 className="text-sm font-semibold text-zinc-200">Generate Training Block</h3>
                <button
                  onClick={() => setGenModalOpen(false)}
                  className="text-zinc-500 hover:text-zinc-300 text-xl leading-none"
                >×</button>
              </div>

              <div className="p-5 space-y-4">
                {!genResult ? (
                  <>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="text-xs text-zinc-500 mb-1 block">Start date</label>
                        <input
                          type="date" value={genStart}
                          onChange={e => setGenStart(e.target.value)}
                          className="w-full text-sm bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-zinc-200"
                        />
                      </div>
                      <div>
                        <label className="text-xs text-zinc-500 mb-1 block">End date</label>
                        <input
                          type="date" value={genEnd}
                          onChange={e => setGenEnd(e.target.value)}
                          className="w-full text-sm bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-zinc-200"
                        />
                      </div>
                    </div>
                    {genStart && genEnd && genStart > genEnd && (
                      <p className="text-xs text-red-400">Start date must be on or before end date.</p>
                    )}
                    <div>
                      <label className="text-xs text-zinc-500 mb-1 block">Notes (optional)</label>
                      <textarea
                        rows={3}
                        placeholder={'e.g. "I have a century ride Nov 15, focus on climbing" or "I\'m traveling Oct 10-12, keep it light"'}
                        value={genFreeform}
                        onChange={e => setGenFreeform(e.target.value)}
                        className="w-full text-sm bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-zinc-200 resize-none"
                      />
                    </div>
                    {genLoading && <GeneratingProgress />}
                    {genError && <p className="text-xs text-red-400">{genError}</p>}
                    <button
                      onClick={generatePlan}
                      disabled={genLoading || !genStart || !genEnd || genStart > genEnd}
                      className="w-full text-sm bg-green-700 hover:bg-green-600 disabled:opacity-50 text-white rounded px-3 py-2 font-medium"
                    >
                      {genLoading ? "Generating…" : "Generate"}
                    </button>
                  </>
                ) : (
                  <>
                    {genResult.summary && (
                      <p className="text-sm text-zinc-300 leading-relaxed">{genResult.summary}</p>
                    )}
                    {(genResult.warnings ?? []).map((w, i) => (
                      <p key={i} className="text-xs text-amber-400">⚠ {w}</p>
                    ))}
                    {genResult.workouts.length === 0 ? (
                      <p className="text-sm text-zinc-500 italic">No workouts suggested for this range.</p>
                    ) : (
                      <div className="space-y-1.5 max-h-72 overflow-y-auto">
                        {genResult.workouts.map(w => (
                          <div
                            key={w.date}
                            className={`px-3 py-2 rounded border text-sm ${WORKOUT_COLORS[w.workout_type] ?? "bg-zinc-700/50 text-zinc-400 border-zinc-600/30"}`}
                          >
                            <div className="flex items-center justify-between gap-2">
                              <span className="font-medium">{w.date} — {w.workout_type}</span>
                              <span className="text-xs opacity-70 text-right">
                                {[
                                  w.distance_km ? fmtKm(w.distance_km) : null,
                                  w.duration_min ? `${w.duration_min}min` : null,
                                  w.intensity,
                                ].filter(Boolean).join(" · ")}
                              </span>
                            </div>
                            {(w.elevation_m || w.structure_text) && (
                              <div className="text-xs opacity-80 mt-0.5">
                                {w.elevation_m ? `${units.fmt(w.elevation_m, "elevation")} gain` : null}
                                {(() => {
                                  const rate = plannedClimbRate(w.distance_km, w.elevation_m);
                                  return rate == null ? null : ` · ${units.fmt(rate, "climb_rate")}`;
                                })()}
                                {w.structure_text && <div className="font-mono opacity-90">{w.structure_text}</div>}
                              </div>
                            )}
                            {w.description && (
                              <div className="text-xs opacity-80 mt-0.5">{w.description}</div>
                            )}
                            {plan[w.date] && (
                              <div className="text-xs text-amber-400 mt-0.5">
                                ⚠ replaces existing "{plan[w.date].workout_type}"
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                    {genLoading && <GeneratingProgress />}
                    {genError && <p className="text-xs text-red-400">{genError}</p>}
                    <div className="flex gap-2 pt-1">
                      <button
                        onClick={acceptGeneratedPlan}
                        disabled={genAccepting || genResult.workouts.length === 0}
                        className="flex-1 text-sm bg-green-700 hover:bg-green-600 disabled:opacity-50 text-white rounded px-3 py-2 font-medium"
                      >
                        {genAccepting ? "Adding…" : "Accept & Add to Calendar"}
                      </button>
                      <button
                        onClick={generatePlan}
                        disabled={genLoading || genAccepting}
                        className="text-sm bg-zinc-700 hover:bg-zinc-600 disabled:opacity-50 text-zinc-300 rounded px-3 py-2"
                      >
                        {genLoading ? "Regenerating…" : "Regenerate"}
                      </button>
                      <button
                        onClick={() => setGenModalOpen(false)}
                        className="text-sm bg-zinc-800 hover:bg-zinc-700 text-zinc-400 rounded px-3 py-2"
                      >
                        Discard
                      </button>
                    </div>
                  </>
                )}
              </div>
            </div>
          </div>
        </>
      )}

      {/* ── Weekly summary pane (click a week's Planned/Actual box) ── */}
      {selectedWeek && (
        <>
          <div
            className="fixed inset-0 z-40 bg-black/60"
            onClick={() => setSelectedWeek(null)}
          />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 pointer-events-none">
            <div className="pointer-events-auto bg-zinc-900 border border-zinc-700 rounded-lg w-full max-w-lg max-h-[85vh] overflow-y-auto shadow-2xl">
              <div className="px-5 py-4 border-b border-zinc-800 flex items-center justify-between">
                <h3 className="text-sm font-semibold text-zinc-200">
                  Week of{" "}
                  {new Date(selectedWeek.cells[0].dateStr + "T12:00:00").toLocaleDateString("default", {
                    month: "short",
                    day: "numeric",
                  })}
                  {" – "}
                  {new Date(selectedWeek.cells[6].dateStr + "T12:00:00").toLocaleDateString("default", {
                    month: "short",
                    day: "numeric",
                  })}
                </h3>
                <button
                  onClick={() => setSelectedWeek(null)}
                  className="text-zinc-500 hover:text-zinc-300 text-xl leading-none"
                >×</button>
              </div>

              <div className="p-5 space-y-4">
                <div className="grid grid-cols-2 gap-3">
                  <div className="bg-zinc-800/40 rounded p-3">
                    <div className="text-[10px] text-zinc-500 uppercase tracking-wider mb-1">Distance</div>
                    <div className="text-sm text-zinc-200">
                      {fmtKm(selectedWeek.plannedKm)} planned · {fmtKm(selectedWeek.actualKm)} actual
                    </div>
                  </div>
                  <div className="bg-zinc-800/40 rounded p-3">
                    <div className="text-[10px] text-zinc-500 uppercase tracking-wider mb-1">Compliance</div>
                    {selectedWeek.onTargetPct !== null ? (
                      <div className="text-sm text-zinc-200">
                        {selectedWeek.onTargetPct}% on-target · {selectedWeek.consistencyPct}% did something
                      </div>
                    ) : (
                      <div className="text-sm text-zinc-500">No scorable planned days this week</div>
                    )}
                  </div>
                </div>

                <div>
                  <div className="text-[10px] text-zinc-500 uppercase tracking-wider mb-2">Day by day</div>
                  <div className="space-y-2">
                    {selectedWeek.cells.map(cell => {
                      const dateStr = cell.dateStr;
                      const workout = plan[dateStr];
                      const { matched: matchedActivity, others: dayActivities } = splitActivities(dateStr);
                      const complianceDay = compliance[dateStr];
                      return (
                        <div
                          key={dateStr}
                          className="flex gap-3 items-start border border-zinc-800 rounded px-3 py-2"
                        >
                          <div className="w-16 flex-shrink-0 text-xs text-zinc-500">
                            {new Date(dateStr + "T12:00:00").toLocaleDateString("default", {
                              weekday: "short",
                              month: "short",
                              day: "numeric",
                            })}
                          </div>
                          <div className="flex-1 min-w-0 space-y-1">
                            {workout ? (
                              <div
                                className={`inline-block text-xs px-1.5 py-0.5 rounded border ${WORKOUT_COLORS[workout.workout_type] ?? "bg-zinc-700/50 text-zinc-400 border-zinc-600/30"}`}
                              >
                                {workout.workout_type}
                                {matchedActivity
                                  ? ` · ✓ ${units.fmt(matchedActivity.distance_m ?? 0, "distance", { decimals: 1 })}${workout.distance_km ? ` / ${fmtKm(workout.distance_km)}` : ""}`
                                  : workout.distance_km ? ` · ${fmtKm(workout.distance_km)}` : ""}
                              </div>
                            ) : (
                              <div className="text-xs text-zinc-600 italic">No planned workout</div>
                            )}
                            {dayActivities.map(a => (
                              <div key={a.id} className="text-xs text-zinc-400">
                                ✓ {units.fmt(a.distance_m ?? 0, "distance", { decimals: 1 })} {a.sport_type}
                              </div>
                            ))}
                            {complianceDay && (
                              <div className="flex items-center gap-1.5 text-xs">
                                {COMPLIANCE_DOT_COLORS[complianceDay.status] && (
                                  <span
                                    className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${COMPLIANCE_DOT_COLORS[complianceDay.status]}`}
                                  />
                                )}
                                <span className="text-zinc-300 font-medium">
                                  {COMPLIANCE_STATUS_LABELS[complianceDay.status]}
                                </span>
                                <span className="text-zinc-500 truncate">— {complianceDay.note}</span>
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}


function LoadStrip({ state }: { state: TrainingState }) {
  const { ctl, atl, ratio } = state.load;
  if (ctl === null || atl === null) return null;
  const t = state.thresholds;
  const zone =
    ratio === null ? null
    : ratio > t.acwr_high ? { label: "High fatigue", color: "text-red-400" }
    : ratio < t.acwr_low ? { label: "Fresh / detraining", color: "text-zinc-400" }
    : { label: "Optimal", color: "text-green-400" };
  const ul = state.unit === "miles" ? "mi" : "km";
  const hard = state.conflicts.filter(c => c.hard).length;
  const soft = state.conflicts.filter(c => !c.hard);
  return (
    <div className="px-4 py-2 border-b border-zinc-800 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-zinc-400">
      <span>CTL <b className="text-blue-400">{ctl.toFixed(1)}</b> {ul}/d</span>
      <span>ATL <b className="text-red-400">{atl.toFixed(1)}</b> {ul}/d</span>
      {zone && ratio !== null && (
        <span>Ratio <b className={zone.color}>{ratio.toFixed(2)}</b> · {zone.label}</span>
      )}
      {hard > 0 && <span className="text-amber-400">⚠ {hard} workout(s) on blocked/race days</span>}
      {soft.slice(0, 2).map((c, i) => (
        <span key={i} className="text-amber-400" title={c.detail}>⚠ {c.detail}</span>
      ))}
      <a href="#analytics" className="ml-auto text-zinc-500 hover:text-zinc-300">Analytics →</a>
    </div>
  );
}
