import { useCallback, useEffect, useState } from "react";

const DAYS_OF_WEEK = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

const WORKOUT_TYPES = [
  "Easy Run", "Long Run", "Tempo Run", "Intervals",
  "Race", "Cross-Training", "Rest",
];

const INTENSITIES = ["easy", "moderate", "hard", "rest"];

const WORKOUT_COLORS: Record<string, string> = {
  "Easy Run":       "bg-green-500/20 text-green-300 border-green-500/30",
  "Long Run":       "bg-purple-500/20 text-purple-300 border-purple-500/30",
  "Tempo Run":      "bg-orange-500/20 text-orange-300 border-orange-500/30",
  "Intervals":      "bg-red-500/20 text-red-300 border-red-500/30",
  "Race":           "bg-amber-500/20 text-amber-300 border-amber-500/30",
  "Cross-Training": "bg-blue-500/20 text-blue-300 border-blue-500/30",
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

interface Race {
  date: string;
  name: string;
  target_time?: string;
}

interface Prefs {
  blocked_days: string[];
  races: Race[];
}

const EMPTY_FORM = {
  workout_type: "Easy Run",
  description: "",
  distance_km: "",
  elevation_m: "",
  duration_min: "",
  intensity: "easy",
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
  const [form, setForm] = useState(EMPTY_FORM);
  const [showRaceForm, setShowRaceForm] = useState(false);
  const [raceForm, setRaceForm] = useState({ date: "", name: "", target_time: "" });
  const [confirmingDelete, setConfirmingDelete] = useState(false);

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

  const saveWorkout = async () => {
    if (!selectedDate) return;
    const body = {
      workout_type: form.workout_type,
      description: form.description || null,
      distance_km: form.distance_km ? parseFloat(form.distance_km) : null,
      elevation_m: form.elevation_m ? parseFloat(form.elevation_m) : null,
      duration_min: form.duration_min ? parseInt(form.duration_min) : null,
      intensity: form.intensity,
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

  const openDay = (date: string) => {
    if (selectedDate === date) {
      setSelectedDate(null);
      return;
    }
    setSelectedDate(date);
    setEditMode(false);
    setConfirmingDelete(false);
    const existing = plan[date];
    setForm(existing ? {
      workout_type: existing.workout_type || "Easy Run",
      description: existing.description || "",
      distance_km: existing.distance_km?.toString() || "",
      elevation_m: existing.elevation_m?.toString() || "",
      duration_min: existing.duration_min?.toString() || "",
      intensity: existing.intensity || "easy",
    } : EMPTY_FORM);
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
    });
    setEditMode(true);
  };

  // Calendar grid helpers
  const daysInMonth = new Date(currentMonth.getFullYear(), currentMonth.getMonth() + 1, 0).getDate();
  const firstDow = new Date(currentMonth.getFullYear(), currentMonth.getMonth(), 1).getDay();

  // Build week rows: arrays of 7 (day number | null for padding)
  const weeks: (number | null)[][] = [];
  {
    let week: (number | null)[] = Array(firstDow).fill(null);
    for (let day = 1; day <= daysInMonth; day++) {
      week.push(day);
      if (week.length === 7) { weeks.push(week); week = []; }
    }
    if (week.length > 0) {
      while (week.length < 7) week.push(null);
      weeks.push(week);
    }
  }

  const cellDateStr = (day: number) =>
    new Date(currentMonth.getFullYear(), currentMonth.getMonth(), day)
      .toISOString().slice(0, 10);

  const dowName = (dateStr: string) =>
    DAY_NAMES[new Date(dateStr + "T12:00:00").getDay()];

  const raceOnDate = (dateStr: string) => prefs.races.find(r => r.date === dateStr);

  const selectedWorkout = selectedDate ? plan[selectedDate] : null;
  const selectedActivities = selectedDate ? (activities[selectedDate] ?? []) : [];
  const selectedNutrition: NutritionData | null = selectedWorkout?.nutrition_json
    ? JSON.parse(selectedWorkout.nutrition_json)
    : null;

  const showNutritionCol = selectedWorkout && !editMode && selectedWorkout.workout_type !== "Rest";

  return (
    <div className="flex h-full bg-zinc-900 text-zinc-100 overflow-hidden">

      {/* ── Left sidebar ── */}
      <aside className="w-56 flex-shrink-0 border-r border-zinc-800 overflow-y-auto p-4 space-y-6">

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
          <div className="space-y-1 mb-3">
            {Object.entries(WORKOUT_COLORS).map(([type, cls]) => (
              <div key={type} className="flex items-center gap-2">
                <span className={`w-2 h-2 rounded-full ${cls.split(" ")[0]}`} />
                <span className="text-xs text-zinc-400">{type}</span>
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
      <div className="flex-1 flex flex-col overflow-hidden">

        {/* ── Calendar grid ── */}
        <div className="flex-shrink-0">
          <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-800">
            <button
              onClick={() => setCurrentMonth(m => new Date(m.getFullYear(), m.getMonth() - 1, 1))}
              className="text-zinc-400 hover:text-zinc-200 px-2 text-lg"
            >‹</button>
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
            {weeks.map((weekDays, wi) => {
              const plannedKm = weekDays.reduce<number>((sum, day) => {
                if (!day) return sum;
                const w = plan[cellDateStr(day)];
                return sum + (w && w.workout_type !== "Rest" ? (w.distance_km ?? 0) : 0);
              }, 0);
              const actualKm = weekDays.reduce<number>((sum, day) => {
                if (!day) return sum;
                return sum + (activities[cellDateStr(day)] ?? []).reduce<number>(
                  (s, a) => s + (a.distance_m ?? 0) / 1000, 0
                );
              }, 0);

              return (
                <div key={wi} className="flex gap-1 mb-3">
                  {weekDays.map((day, di) => {
                    if (!day) return <div key={`pad-${wi}-${di}`} className="flex-1" />;
                    const dateStr = cellDateStr(day);
                    const workout = plan[dateStr];
                    const dayActivities = activities[dateStr] ?? [];
                    const isToday = dateStr === todayStr;
                    const isSelected = selectedDate === dateStr;
                    const isBlocked = prefs.blocked_days.includes(dateStr);
                    const race = raceOnDate(dateStr);

                    return (
                      <div
                        key={dateStr}
                        onClick={() => openDay(dateStr)}
                        className={[
                          "flex-1 min-h-16 p-1.5 rounded cursor-pointer border transition-colors",
                          isSelected ? "border-zinc-400 bg-zinc-700/60" : "border-zinc-800 hover:border-zinc-600",
                          isBlocked ? "opacity-40" : "",
                          "bg-zinc-800/20",
                        ].join(" ")}
                      >
                        <div className={`text-xs font-medium mb-1 flex items-center gap-1 ${isToday ? "text-green-400" : "text-zinc-400"}`}>
                          {day}
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
          <div className="flex-1 border-t border-zinc-800 overflow-y-auto">
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
                        {WORKOUT_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                      </select>
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <label className="text-xs text-zinc-500 mb-1 block">Distance (km)</label>
                        <input
                          type="number" step="0.1" placeholder="—"
                          value={form.distance_km}
                          onChange={e => setForm(f => ({ ...f, distance_km: e.target.value }))}
                          className="w-full text-sm bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-zinc-200"
                        />
                      </div>
                      <div>
                        <label className="text-xs text-zinc-500 mb-1 block">Elevation (m)</label>
                        <input
                          type="number" placeholder="—"
                          value={form.elevation_m}
                          onChange={e => setForm(f => ({ ...f, elevation_m: e.target.value }))}
                          className="w-full text-sm bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-zinc-200"
                        />
                      </div>
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
    </div>
  );
}
