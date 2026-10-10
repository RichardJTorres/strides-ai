import { useCallback, useEffect, useRef, useState } from "react";

const DAYS_OF_WEEK = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

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
// Distance/elevation don't apply to these.
const NO_DISTANCE_WORKOUT_TYPES = new Set(["Yoga", "Rest"]);

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
}

interface RouteAnalysis {
  verdict: string;
  explanation: string;
  suggestion?: string | null;
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
}

interface GeneratePlanResult {
  workouts: GeneratedWorkout[];
  summary: string;
}

interface GridCell {
  date: Date;
  dateStr: string;
  dayNum: number;
  inCurrentMonth: boolean;
}

const EMPTY_FORM = {
  workout_type: "Easy Run",
  description: "",
  distance_km: "",
  elevation_m: "",
  duration_min: "",
  intensity: "easy",
  route_url: "",
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

function fmtPace(sPerKm: number | null): string {
  if (!sPerKm) return "—";
  const m = Math.floor(sPerKm / 60);
  const s = Math.round(sPerKm % 60);
  return `${m}:${s.toString().padStart(2, "0")}/km`;
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
  const today = new Date();
  const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;

  const [currentMonth, setCurrentMonth] = useState(
    new Date(today.getFullYear(), today.getMonth(), 1)
  );
  const [prefs, setPrefs] = useState<Prefs>({ blocked_days: [], races: [] });
  const [plan, setPlan] = useState<Record<string, Workout>>({});
  const [activities, setActivities] = useState<Record<string, Activity[]>>({});
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
  const detailPanelRef = useRef<HTMLDivElement>(null);

  const [genModalOpen, setGenModalOpen] = useState(false);
  const [genStart, setGenStart] = useState(todayStr);
  const [genEnd, setGenEnd] = useState(todayStr);
  const [genFreeform, setGenFreeform] = useState("");
  const [genLoading, setGenLoading] = useState(false);
  const [genAccepting, setGenAccepting] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);
  const [genResult, setGenResult] = useState<GeneratePlanResult | null>(null);

  // On small/short screens the detail panel can render below the fold once a day
  // is selected — scroll it into view so it's never left invisible off-screen.
  useEffect(() => {
    if (selectedDate) {
      detailPanelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [selectedDate]);

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
        distance_km: preview.distance_m ? (preview.distance_m / 1000).toFixed(1) : f.distance_km,
        elevation_m: preview.elevation_gain_m
          ? Math.round(preview.elevation_gain_m).toString()
          : f.elevation_m,
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
      distance_km: !noDistance && form.distance_km ? parseFloat(form.distance_km) : null,
      elevation_m: !noDistance && form.elevation_m ? parseFloat(form.elevation_m) : null,
      duration_min: form.duration_min ? parseInt(form.duration_min) : null,
      intensity: form.intensity,
      route_url: !noRoute && form.route_url ? form.route_url : null,
    };
    const res = await fetch(`/api/calendar/plan/${selectedDate}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (res.ok) {
      setPlan(prev => ({ ...prev, [selectedDate]: { date: selectedDate, ...body } }));
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
      };
      const res = await fetch(`/api/calendar/plan/${selectedDate}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        setPlan(prev => ({ ...prev, [selectedDate]: { date: selectedDate, ...body } }));
        setShowRouteForm(false);
      }
    } finally {
      setSavingRouteUrl(false);
    }
  };

  const openGenerateModal = () => {
    setGenStart(todayStr);
    setGenEnd(todayStr);
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
    setForm(existing ? {
      workout_type: existing.workout_type || "Easy Run",
      description: existing.description || "",
      distance_km: existing.distance_km?.toString() || "",
      elevation_m: existing.elevation_m?.toString() || "",
      duration_min: existing.duration_min?.toString() || "",
      intensity: existing.intensity || "easy",
      route_url: existing.route_url || "",
    } : EMPTY_FORM);
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
    setForm({
      workout_type: existing?.workout_type || "Easy Run",
      description: existing?.description || "",
      distance_km: existing?.distance_km?.toString() || "",
      elevation_m: existing?.elevation_m?.toString() || "",
      duration_min: existing?.duration_min?.toString() || "",
      intensity: existing?.intensity || "easy",
      route_url: existing?.route_url || "",
    });
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

  const dowName = (dateStr: string) =>
    DAY_NAMES[new Date(dateStr + "T12:00:00").getDay()];

  const raceOnDate = (dateStr: string) => prefs.races.find(r => r.date === dateStr);

  const selectedWorkout = selectedDate ? plan[selectedDate] : null;
  const selectedActivities = selectedDate ? (activities[selectedDate] ?? []) : [];
  const selectedNutrition: NutritionData | null = selectedWorkout?.nutrition_json
    ? JSON.parse(selectedWorkout.nutrition_json)
    : null;
  const selectedRouteAnalysis: RouteAnalysis | null = selectedWorkout?.route_analysis_json
    ? JSON.parse(selectedWorkout.route_analysis_json)
    : null;

  const showNutritionCol = selectedWorkout && !editMode && selectedWorkout.workout_type !== "Rest";

  return (
    <div className="flex h-full bg-zinc-900 text-zinc-100 overflow-hidden">

      {/* ── Left sidebar ── */}
      <aside className="w-56 flex-shrink-0 border-r border-zinc-800 overflow-y-auto p-4 space-y-6">

        <div>
          <button
            onClick={openGenerateModal}
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
        </div>
      </aside>

      {/* ── Main column ── */}
      <div className="flex-1 flex flex-col overflow-y-auto">

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

          <div className="p-3">
            {/* Day-of-week headers */}
            <div className="flex gap-1 mb-1">
              {DAYS_OF_WEEK.map(d => (
                <div key={d} className="flex-1 text-center text-xs text-zinc-500 font-medium py-1">{d}</div>
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

              return (
                <div key={wi} className="flex gap-1 mb-3">
                  {weekCells.map(cell => {
                    const dateStr = cell.dateStr;
                    const workout = plan[dateStr];
                    const dayActivities = activities[dateStr] ?? [];
                    const isToday = dateStr === todayStr;
                    const isSelected = selectedDate === dateStr;
                    const isBlocked = prefs.blocked_days.includes(dateStr);
                    const race = raceOnDate(dateStr);
                    const showMonthLabel = cell.dayNum === 1 && !cell.inCurrentMonth;

                    return (
                      <div
                        key={dateStr}
                        onClick={() => openDay(dateStr)}
                        className={[
                          "flex-1 min-h-16 p-1.5 rounded cursor-pointer border transition-colors",
                          isSelected ? "border-zinc-400 bg-zinc-700/60" : "border-zinc-800 hover:border-zinc-600",
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
                        </div>
                        {race && (
                          <div className="text-xs px-1 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/30 truncate mb-0.5">
                            🏁 {race.name}
                          </div>
                        )}
                        {workout && (
                          <div className={`text-xs px-1 py-0.5 rounded border truncate mb-0.5 ${WORKOUT_COLORS[workout.workout_type] ?? "bg-zinc-700/50 text-zinc-400 border-zinc-600/30"}`}>
                            {workout.workout_type}
                            {workout.distance_km && (
                              <span className="ml-1 opacity-70">{workout.distance_km}k</span>
                            )}
                          </div>
                        )}
                        {dayActivities.map(a => (
                          <div key={a.id} className="text-xs px-1 py-0.5 rounded bg-zinc-600/40 text-zinc-300 border border-zinc-600/40 truncate mb-0.5">
                            ✓ {((a.distance_m ?? 0) / 1000).toFixed(1)}k {a.sport_type}
                          </div>
                        ))}
                      </div>
                    );
                  })}

                  {/* Weekly totals */}
                  <div className="w-20 flex-shrink-0 flex flex-col justify-center gap-3 px-3 ml-1 rounded bg-zinc-800/40 border border-zinc-700/50">
                    <div>
                      <div className="text-[10px] text-zinc-500 uppercase tracking-wider mb-0.5">Planned</div>
                      <div className="text-sm text-zinc-300 font-semibold">
                        {plannedKm > 0 ? `${plannedKm.toFixed(1)}` : "—"}
                      </div>
                      {plannedKm > 0 && <div className="text-[10px] text-zinc-500">km</div>}
                    </div>
                    <div>
                      <div className="text-[10px] text-zinc-500 uppercase tracking-wider mb-0.5">Actual</div>
                      <div className={`text-sm font-semibold ${actualKm > 0 ? "text-green-400" : "text-zinc-600"}`}>
                        {actualKm > 0 ? `${actualKm.toFixed(1)}` : "—"}
                      </div>
                      {actualKm > 0 && <div className="text-[10px] text-zinc-500">km</div>}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* ── Detail panel (below calendar) ── */}
        {selectedDate && (
          <div ref={detailPanelRef} className="border-t border-zinc-800">
            <div className="p-4 flex gap-6 items-start">

              {/* Col 1: date info + planned workout */}
              <div className="flex-1 min-w-0 space-y-3">
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
                            <div className="text-zinc-200 font-medium">{selectedWorkout.distance_km} km</div>
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
                            <div className="text-zinc-200 font-medium">{selectedWorkout.elevation_m} m</div>
                          </div>
                        )}
                      </div>
                    )}
                    {selectedWorkout.description && (
                      <p className="text-xs text-zinc-400 leading-relaxed">{selectedWorkout.description}</p>
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
                    <div className="grid grid-cols-2 gap-2">
                      {!NO_DISTANCE_WORKOUT_TYPES.has(form.workout_type) && (
                      <div>
                        <label className="text-xs text-zinc-500 mb-1 block">Distance (km)</label>
                        <input
                          type="number" step="0.1" placeholder="—"
                          value={form.distance_km}
                          onChange={e => setForm(f => ({ ...f, distance_km: e.target.value }))}
                          className="w-full text-sm bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-zinc-200"
                        />
                      </div>
                      )}
                      {!NO_DISTANCE_WORKOUT_TYPES.has(form.workout_type) && (
                      <div>
                        <label className="text-xs text-zinc-500 mb-1 block">Elevation (m)</label>
                        <input
                          type="number" placeholder="—"
                          value={form.elevation_m}
                          onChange={e => setForm(f => ({ ...f, elevation_m: e.target.value }))}
                          className="w-full text-sm bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-zinc-200"
                        />
                      </div>
                      )}
                      <div>
                        <label className="text-xs text-zinc-500 mb-1 block">Duration (min)</label>
                        <input
                          type="number" placeholder="—"
                          value={form.duration_min}
                          onChange={e => setForm(f => ({ ...f, duration_min: e.target.value }))}
                          className="w-full text-sm bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-zinc-200"
                        />
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
                <div className="w-44 flex-shrink-0 space-y-2">
                  <h4 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Strava</h4>
                  {selectedActivities.map(a => {
                    const distKm = ((a.distance_m ?? 0) / 1000).toFixed(2);
                    const isRun = RUN_TYPES.has(a.sport_type);
                    return (
                      <div key={a.id} className="bg-zinc-800/60 rounded p-2 border border-zinc-700/50 space-y-1">
                        <div className="text-xs font-medium text-zinc-200 truncate">{a.name}</div>
                        <div className="text-xs text-zinc-500">{a.sport_type}</div>
                        <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs">
                          <span className="text-zinc-500">Distance</span>
                          <span className="text-zinc-300">{distKm} km</span>
                          <span className="text-zinc-500">Duration</span>
                          <span className="text-zinc-300">{fmtDuration(a.moving_time_s)}</span>
                          {isRun && a.avg_pace_s_per_km && (
                            <>
                              <span className="text-zinc-500">Pace</span>
                              <span className="text-zinc-300">{fmtPace(a.avg_pace_s_per_km)}</span>
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
                              <span className="text-zinc-300">{Math.round(a.elevation_gain_m)} m</span>
                            </>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}

              {/* Col 3: Nutrition */}
              {showNutritionCol && (
                <div className="w-96 flex-shrink-0 space-y-2">
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
                      <div className="text-sm text-zinc-400 font-medium">Hydration (ml)</div>
                      <div className="grid grid-cols-3 gap-2 text-center">
                        {(["pre", "during", "post"] as const).map(phase => (
                          <div key={phase} className="bg-zinc-800/60 rounded p-2">
                            <div className="text-xs text-zinc-500 capitalize mb-1">{phase}</div>
                            <div className="text-sm font-semibold text-blue-300">
                              {selectedNutrition[`hydration_${phase}_ml` as keyof NutritionData] as number}
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
          </div>
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
                                  w.distance_km ? `${w.distance_km}km` : null,
                                  w.duration_min ? `${w.duration_min}min` : null,
                                  w.intensity,
                                ].filter(Boolean).join(" · ")}
                              </span>
                            </div>
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
    </div>
  );
}
