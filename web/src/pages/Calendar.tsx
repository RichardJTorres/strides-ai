import { useEffect, useRef, useState } from "react";

// ── Types ──────────────────────────────────────────────────────────────────

interface Race {
  date: string;
  name: string;
  target_time?: string;
}

interface CalendarPrefs {
  rest_days: string[];
  long_run_days: string[];
  frequency: number;
  blocked_days: string[];
  races: Race[];
}

interface Workout {
  date: string;
  workout_type: string;
  description: string;
  distance_km: number | null;
  duration_min: number | null;
  intensity: string;
}

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTHS = ["January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December"];

const WORKOUT_COLORS: Record<string, string> = {
  "Easy Run":      "bg-green-500/20 text-green-300 border-green-500/30",
  "Long Run":      "bg-purple-500/20 text-purple-300 border-purple-500/30",
  "Tempo Run":     "bg-orange-500/20 text-orange-300 border-orange-500/30",
  "Interval":      "bg-red-500/20 text-red-300 border-red-500/30",
  "Race":          "bg-amber-500/20 text-amber-300 border-amber-500/30",
  "Cross-Training":"bg-blue-500/20 text-blue-300 border-blue-500/30",
  "Rest":          "",
};

function toDateStr(y: number, m: number, d: number): string {
  return `${y}-${String(m + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

function todayStr(): string {
  return new Date().toISOString().slice(0, 10);
}

// ── Pref save helpers ──────────────────────────────────────────────────────

async function savePrefs(prefs: CalendarPrefs) {
  await fetch("/api/calendar/prefs", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(prefs),
  });
}

// ── Day Cell ──────────────────────────────────────────────────────────────

function DayCell({
  dateStr,
  prefs,
  workout,
  isToday,
  isSelected,
  onClick,
}: {
  dateStr: string;
  prefs: CalendarPrefs;
  workout: Workout | undefined;
  isToday: boolean;
  isSelected: boolean;
  onClick: () => void;
}) {
  const day = parseInt(dateStr.slice(8), 10);
  const dowIndex = new Date(dateStr + "T12:00:00").getDay();
  const dowName = DAY_NAMES[dowIndex];

  const isBlocked = prefs.blocked_days.includes(dateStr);
  const isRestPref = prefs.rest_days.includes(dowName);
  const isLongRunPref = prefs.long_run_days.includes(dowName);
  const isRace = prefs.races.some((r) => r.date === dateStr);

  let bg = "bg-gray-900 hover:bg-gray-800";
  if (isBlocked) bg = "bg-gray-950 opacity-50 cursor-pointer";
  else if (isRestPref && !workout) bg = "bg-indigo-950/40";
  else if (isLongRunPref && !workout) bg = "bg-purple-950/40";

  const colorClass = workout ? (WORKOUT_COLORS[workout.workout_type] ?? "") : "";

  return (
    <button
      onClick={onClick}
      className={`relative min-h-[72px] rounded-lg border text-left p-1.5 transition-colors ${
        isSelected ? "border-green-500/60" : "border-gray-800"
      } ${bg}`}
    >
      <span
        className={`text-xs font-medium block mb-1 ${
          isToday
            ? "text-green-400 font-bold"
            : "text-gray-500"
        }`}
      >
        {day}
      </span>

      {isBlocked && (
        <span className="text-xs text-gray-600 italic">blocked</span>
      )}

      {isRace && !workout && (
        <span className="text-[10px] px-1 py-0.5 rounded border bg-amber-500/20 text-amber-300 border-amber-500/30 block truncate">
          Race
        </span>
      )}

      {workout && workout.workout_type !== "Rest" && (
        <span className={`text-[10px] px-1 py-0.5 rounded border block truncate ${colorClass}`}>
          {workout.workout_type}
          {workout.distance_km ? ` · ${workout.distance_km}km` : ""}
        </span>
      )}
    </button>
  );
}

// ── Main Component ─────────────────────────────────────────────────────────

export default function Calendar() {
  const today = new Date();
  const [currentYear, setCurrentYear] = useState(today.getFullYear());
  const [currentMonth, setCurrentMonth] = useState(today.getMonth());

  const [prefs, setPrefs] = useState<CalendarPrefs>({
    rest_days: [],
    long_run_days: [],
    frequency: 4,
    blocked_days: [],
    races: [],
  });
  const [plan, setPlan] = useState<Record<string, Workout>>({});
  const [selectedDay, setSelectedDay] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [revising, setRevising] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [hasPlan, setHasPlan] = useState(false);

  // Add race form
  const [showRaceForm, setShowRaceForm] = useState(false);
  const [newRace, setNewRace] = useState<Race>({ date: "", name: "", target_time: "" });

  const saveTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Load on mount ────────────────────────────────────────────────────────

  useEffect(() => {
    Promise.all([
      fetch("/api/calendar/prefs").then((r) => r.json()),
      fetch("/api/calendar/plan").then((r) => r.json()),
    ]).then(([p, plan]) => {
      setPrefs(p);
      if (Array.isArray(plan) && plan.length > 0) {
        const map: Record<string, Workout> = {};
        for (const w of plan) map[w.date] = w;
        setPlan(map);
        setHasPlan(true);
      }
    });
  }, []);

  // ── Debounced pref save ───────────────────────────────────────────────────

  function updatePrefs(updated: CalendarPrefs) {
    setPrefs(updated);
    if (saveTimeout.current) clearTimeout(saveTimeout.current);
    saveTimeout.current = setTimeout(() => savePrefs(updated), 600);
  }

  // ── Day click ────────────────────────────────────────────────────────────

  function handleDayClick(dateStr: string) {
    if (selectedDay === dateStr) {
      setSelectedDay(null);
      return;
    }
    setSelectedDay(dateStr);

    // Toggle blocked (only if no workout or already blocked)
    const workout = plan[dateStr];
    if (!workout || workout.workout_type === "Rest") {
      const isBlocked = prefs.blocked_days.includes(dateStr);
      const blocked = isBlocked
        ? prefs.blocked_days.filter((d) => d !== dateStr)
        : [...prefs.blocked_days, dateStr];
      updatePrefs({ ...prefs, blocked_days: blocked });
    }
  }

  // ── Generate ─────────────────────────────────────────────────────────────

  async function handleGenerate() {
    setGenerating(true);
    setSelectedDay(null);
    try {
      const res = await fetch("/api/calendar/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(prefs),
      });
      if (!res.ok) throw new Error(await res.text());
      const workouts: Workout[] = await res.json();
      const map: Record<string, Workout> = {};
      for (const w of workouts) map[w.date] = w;
      setPlan(map);
      setHasPlan(true);
    } finally {
      setGenerating(false);
    }
  }

  // ── Revise ───────────────────────────────────────────────────────────────

  async function handleRevise() {
    if (!feedback.trim()) return;
    setRevising(true);
    try {
      const res = await fetch("/api/calendar/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ feedback }),
      });
      if (!res.ok) throw new Error(await res.text());
      const workouts: Workout[] = await res.json();
      const map: Record<string, Workout> = {};
      for (const w of workouts) map[w.date] = w;
      setPlan(map);
      setFeedback("");
    } finally {
      setRevising(false);
    }
  }

  // ── Calendar grid helpers ─────────────────────────────────────────────────

  function prevMonth() {
    if (currentMonth === 0) { setCurrentMonth(11); setCurrentYear(y => y - 1); }
    else setCurrentMonth(m => m - 1);
  }

  function nextMonth() {
    if (currentMonth === 11) { setCurrentMonth(0); setCurrentYear(y => y + 1); }
    else setCurrentMonth(m => m + 1);
  }

  const firstDow = new Date(currentYear, currentMonth, 1).getDay();
  const daysInMonth = new Date(currentYear, currentMonth + 1, 0).getDate();
  const cells: (string | null)[] = [
    ...Array(firstDow).fill(null),
    ...Array.from({ length: daysInMonth }, (_, i) => toDateStr(currentYear, currentMonth, i + 1)),
  ];
  // Pad to complete last row
  while (cells.length % 7 !== 0) cells.push(null);

  const selectedWorkout = selectedDay ? plan[selectedDay] : null;

  // ── Day-of-week checkbox helpers ─────────────────────────────────────────

  function toggleDow(field: "rest_days" | "long_run_days", day: string) {
    const list = prefs[field];
    const updated = list.includes(day) ? list.filter((d) => d !== day) : [...list, day];
    updatePrefs({ ...prefs, [field]: updated });
  }

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="flex h-full overflow-hidden">

      {/* Left panel */}
      <aside className="w-56 shrink-0 bg-gray-900 border-r border-gray-800 flex flex-col overflow-y-auto">
        <div className="p-4 space-y-6">

          {/* Frequency */}
          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-2">Weekly runs</h3>
            <div className="flex items-center gap-2">
              <button
                onClick={() => updatePrefs({ ...prefs, frequency: Math.max(1, prefs.frequency - 1) })}
                className="w-7 h-7 rounded bg-gray-800 text-gray-300 hover:bg-gray-700 text-sm font-bold"
              >−</button>
              <span className="text-gray-100 font-semibold w-4 text-center">{prefs.frequency}</span>
              <button
                onClick={() => updatePrefs({ ...prefs, frequency: Math.min(7, prefs.frequency + 1) })}
                className="w-7 h-7 rounded bg-gray-800 text-gray-300 hover:bg-gray-700 text-sm font-bold"
              >+</button>
              <span className="text-xs text-gray-500">days/week</span>
            </div>
          </section>

          {/* Rest days */}
          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-2">Rest days</h3>
            <div className="space-y-1">
              {DAY_NAMES.map((d) => (
                <label key={d} className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={prefs.rest_days.includes(d)}
                    onChange={() => toggleDow("rest_days", d)}
                    className="accent-indigo-500"
                  />
                  <span className="text-sm text-gray-300">{d}</span>
                </label>
              ))}
            </div>
          </section>

          {/* Long run days */}
          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-2">Long run day</h3>
            <div className="space-y-1">
              {DAY_NAMES.map((d) => (
                <label key={d} className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={prefs.long_run_days.includes(d)}
                    onChange={() => toggleDow("long_run_days", d)}
                    className="accent-purple-500"
                  />
                  <span className="text-sm text-gray-300">{d}</span>
                </label>
              ))}
            </div>
          </section>

          {/* Races */}
          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-2">Races</h3>
            <div className="space-y-1 mb-2">
              {prefs.races.length === 0 && (
                <p className="text-xs text-gray-600 italic">No races added</p>
              )}
              {prefs.races.map((r, i) => (
                <div key={i} className="flex items-start justify-between gap-1 bg-gray-800 rounded px-2 py-1.5">
                  <div>
                    <p className="text-xs text-amber-300 font-medium">{r.name}</p>
                    <p className="text-[11px] text-gray-500">{r.date}{r.target_time ? ` · ${r.target_time}` : ""}</p>
                  </div>
                  <button
                    onClick={() => updatePrefs({ ...prefs, races: prefs.races.filter((_, j) => j !== i) })}
                    className="text-gray-600 hover:text-red-400 text-xs mt-0.5"
                  >✕</button>
                </div>
              ))}
            </div>

            {showRaceForm ? (
              <div className="space-y-1.5">
                <input
                  type="text"
                  placeholder="Race name"
                  value={newRace.name}
                  onChange={(e) => setNewRace({ ...newRace, name: e.target.value })}
                  className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-gray-100 placeholder-gray-600 focus:outline-none focus:border-amber-500/50"
                />
                <input
                  type="date"
                  value={newRace.date}
                  onChange={(e) => setNewRace({ ...newRace, date: e.target.value })}
                  className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-gray-100 focus:outline-none focus:border-amber-500/50"
                />
                <input
                  type="text"
                  placeholder="Target time (optional)"
                  value={newRace.target_time}
                  onChange={(e) => setNewRace({ ...newRace, target_time: e.target.value })}
                  className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-gray-100 placeholder-gray-600 focus:outline-none focus:border-amber-500/50"
                />
                <div className="flex gap-1">
                  <button
                    onClick={() => {
                      if (!newRace.date || !newRace.name) return;
                      updatePrefs({ ...prefs, races: [...prefs.races, newRace] });
                      setNewRace({ date: "", name: "", target_time: "" });
                      setShowRaceForm(false);
                    }}
                    className="flex-1 text-xs bg-amber-600 hover:bg-amber-500 text-white rounded py-1 transition-colors"
                  >Add</button>
                  <button
                    onClick={() => setShowRaceForm(false)}
                    className="text-xs text-gray-500 hover:text-gray-300 px-2"
                  >Cancel</button>
                </div>
              </div>
            ) : (
              <button
                onClick={() => setShowRaceForm(true)}
                className="text-xs text-amber-400 hover:text-amber-300 transition-colors"
              >+ Add race</button>
            )}
          </section>

          {/* Legend */}
          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-2">Legend</h3>
            <div className="space-y-1 text-[11px]">
              {Object.entries(WORKOUT_COLORS).filter(([, v]) => v).map(([type, cls]) => (
                <div key={type} className="flex items-center gap-1.5">
                  <span className={`px-1.5 py-0.5 rounded border text-[10px] ${cls}`}>{type}</span>
                </div>
              ))}
              <div className="flex items-center gap-1.5 mt-1">
                <span className="w-3 h-3 rounded bg-indigo-950/60 border border-indigo-800/40 inline-block" />
                <span className="text-gray-500">Rest pref</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="w-3 h-3 rounded bg-purple-950/60 border border-purple-800/40 inline-block" />
                <span className="text-gray-500">Long run pref</span>
              </div>
            </div>
          </section>
        </div>
      </aside>

      {/* Main area */}
      <div className="flex-1 flex flex-col overflow-hidden">

        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-800 flex items-center justify-between shrink-0">
          <div>
            <h2 className="text-lg font-semibold text-gray-100">Training Calendar</h2>
            <p className="text-xs text-gray-500 mt-0.5">
              Click days to block them · Configure preferences on the left
            </p>
          </div>
          <button
            onClick={handleGenerate}
            disabled={generating}
            className="flex items-center gap-2 px-4 py-2 bg-green-600 hover:bg-green-500 text-white text-sm font-medium rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {generating ? (
              <>
                <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/>
                </svg>
                Generating…
              </>
            ) : (
              <>
                <svg xmlns="http://www.w3.org/2000/svg" className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
                </svg>
                {hasPlan ? "Regenerate" : "Generate Schedule"}
              </>
            )}
          </button>
        </div>

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto px-6 py-4">

          {/* Month nav */}
          <div className="flex items-center justify-between mb-4">
            <button onClick={prevMonth} className="p-1.5 rounded hover:bg-gray-800 text-gray-400 hover:text-gray-100 transition-colors">
              <svg xmlns="http://www.w3.org/2000/svg" className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="15 18 9 12 15 6"/>
              </svg>
            </button>
            <h3 className="text-base font-semibold text-gray-100">
              {MONTHS[currentMonth]} {currentYear}
            </h3>
            <button onClick={nextMonth} className="p-1.5 rounded hover:bg-gray-800 text-gray-400 hover:text-gray-100 transition-colors">
              <svg xmlns="http://www.w3.org/2000/svg" className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="9 18 15 12 9 6"/>
              </svg>
            </button>
          </div>

          {/* Day headers */}
          <div className="grid grid-cols-7 gap-1 mb-1">
            {DAYS.map((d) => (
              <div key={d} className="text-center text-xs font-medium text-gray-600 py-1">{d}</div>
            ))}
          </div>

          {/* Calendar cells */}
          <div className="grid grid-cols-7 gap-1">
            {cells.map((dateStr, i) =>
              dateStr === null ? (
                <div key={`empty-${i}`} />
              ) : (
                <DayCell
                  key={dateStr}
                  dateStr={dateStr}
                  prefs={prefs}
                  workout={plan[dateStr]}
                  isToday={dateStr === todayStr()}
                  isSelected={selectedDay === dateStr}
                  onClick={() => handleDayClick(dateStr)}
                />
              )
            )}
          </div>

          {/* Workout detail */}
          {selectedDay && (
            <div className="mt-4 bg-gray-900 border border-gray-800 rounded-xl p-4">
              <div className="flex items-start justify-between mb-2">
                <div>
                  <span className="text-xs text-gray-500">{selectedDay}</span>
                  {selectedWorkout ? (
                    <h4 className={`text-sm font-semibold mt-0.5 ${
                      selectedWorkout.workout_type === "Rest" ? "text-gray-500" : "text-gray-100"
                    }`}>
                      {selectedWorkout.workout_type}
                      {selectedWorkout.distance_km ? ` · ${selectedWorkout.distance_km} km` : ""}
                      {selectedWorkout.duration_min ? ` · ${selectedWorkout.duration_min} min` : ""}
                    </h4>
                  ) : (
                    <h4 className="text-sm font-semibold text-gray-400 mt-0.5">
                      {prefs.blocked_days.includes(selectedDay) ? "Blocked" : "No workout planned"}
                    </h4>
                  )}
                </div>
                <button onClick={() => setSelectedDay(null)} className="text-gray-600 hover:text-gray-400 text-sm">✕</button>
              </div>
              {selectedWorkout?.description && (
                <p className="text-sm text-gray-400 leading-relaxed">{selectedWorkout.description}</p>
              )}
              {!prefs.blocked_days.includes(selectedDay) && !selectedWorkout && (
                <p className="text-xs text-gray-600 italic mt-1">Click again to block this day from training.</p>
              )}
              {prefs.blocked_days.includes(selectedDay) && (
                <p className="text-xs text-gray-600 italic mt-1">This day is blocked. Click again to unblock it.</p>
              )}
            </div>
          )}

          {/* Feedback panel */}
          {hasPlan && (
            <div className="mt-6 bg-gray-900 border border-gray-800 rounded-xl p-4">
              <h4 className="text-sm font-semibold text-gray-200 mb-1">Adjust your schedule</h4>
              <p className="text-xs text-gray-600 mb-3">
                e.g. "Move the long run to Friday", "Make week 3 easier", "Add more tempo work"
              </p>
              <div className="flex gap-2">
                <textarea
                  value={feedback}
                  onChange={(e) => setFeedback(e.target.value)}
                  placeholder="Give feedback to your coach…"
                  rows={2}
                  className="flex-1 resize-none bg-gray-800 border border-gray-700/60 rounded-lg px-3 py-2 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-green-500/40 transition-colors"
                />
                <button
                  onClick={handleRevise}
                  disabled={revising || !feedback.trim()}
                  className="px-4 py-2 bg-green-600 hover:bg-green-500 text-white text-sm font-medium rounded-lg disabled:opacity-40 disabled:cursor-not-allowed transition-colors self-end"
                >
                  {revising ? "Revising…" : "Revise"}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
