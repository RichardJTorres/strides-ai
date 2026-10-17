import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Mode, ThemeConfig } from "../App";
import { formatSyncFreshness } from "./syncFreshness";
import { PENDING_CHAT_ACTIVITY_KEY } from "./chatActivityHandoff";
import { useUnits } from "../UnitsContext";
import {
  buildBaselines,
  labelsFor,
  sportGroup,
  type ActivityLabels,
  type FieldLabel,
  type LabelTone,
} from "./activityLabels";

// Mirrors strides_ai/analysis.py: pace-fade threshold, stored in s/km (= 15 s/mi).
const PACE_FADE_NOTABLE_S_PER_KM = 15 / 1.609344;

interface Activity {
  id: number;
  name: string;
  date: string;
  distance_m: number;
  moving_time_s: number;
  avg_pace_s_per_km: number | null;
  avg_hr: number | null;
  max_hr: number | null;
  elevation_gain_m: number | null;
  sport_type: string | null;
  suffer_score: number | null;
  avg_cadence: number | null;
  // Analysis fields
  analysis_summary: string | null;
  analysis_status: string | null;
  cardiac_decoupling_pct: number | null;
  effort_efficiency_score: number | null;
  effort_efficiency_raw: number | null;
  hr_zone_1_pct: number | null;
  hr_zone_2_pct: number | null;
  hr_zone_3_pct: number | null;
  hr_zone_4_pct: number | null;
  hr_zone_5_pct: number | null;
  pace_fade_s_per_km: number | null;
  cadence_std_dev: number | null;
  climb_m_per_km: number | null;
  high_elevation_flag: number | null;
  suffer_score_mismatch_flag: number | null;
  deep_dive_report: string | null;
  deep_dive_completed_at: string | null;
  deep_dive_model: string | null;
  user_notes: string | null;
  // Lifting fields
  exercises_json?: string | null;
  total_volume_kg?: number | null;
  total_sets?: number | null;
}

interface Props {
  mode: Mode;
  theme: ThemeConfig;
  lastSyncAt: string | null;
  onSynced: () => void;
}

type SortKey =
  | "date" | "name" | "distance_m" | "moving_time_s" | "avg_pace_s_per_km" | "avg_hr" | "elevation_gain_m"
  | "climb_m_per_km" | "total_volume_kg" | "total_sets";
type SortDir = "asc" | "desc";

function formatDuration(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h) return `${h}h${String(m).padStart(2, "0")}m`;
  return `${m}m${String(sec).padStart(2, "0")}s`;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function formatSet(s: any, units: ReturnType<typeof useUnits>): string {
  const weight = s.weight_kg != null ? units.fmt(s.weight_kg, "mass", { decimals: 1 }) : "BW";
  if (s.reps != null) return `${weight} × ${s.reps}`;
  if (s.duration_seconds != null) return `${weight} × ${s.duration_seconds}s`;
  if (s.distance_meters != null) {
    return `${weight} × ${units.fmt(s.distance_meters, "elevation")}`;
  }
  return weight;
}

function isRide(sportType: string | null | undefined): boolean {
  return sportGroup(sportType) === "ride";
}

const CHIP_TONES: Record<LabelTone, string> = {
  green: "bg-green-900 text-green-300",
  yellow: "bg-yellow-900 text-yellow-300",
  red: "bg-red-900 text-red-300",
  default: "bg-gray-800 text-gray-400",
};

/** Small qualitative chip shown under a table value. */
function LabelChip({ label }: { label: FieldLabel | null }) {
  if (!label) return null;
  return (
    <div className="mt-0.5">
      <span className={`px-1.5 py-0.5 rounded text-[10px] whitespace-nowrap ${CHIP_TONES[label.tone]}`} title={label.detail}>
        {label.text}
      </span>
    </div>
  );
}

function SortIcon({ active, dir }: { active: boolean; dir: SortDir }) {
  return (
    <span className={`ml-1 inline-block transition-opacity ${active ? "opacity-100" : "opacity-0 group-hover:opacity-40"}`}>
      {active && dir === "desc" ? "↓" : "↑"}
    </span>
  );
}

function DecouplingBadge({ val }: { val: number | null }) {
  if (val === null) return null;
  if (val < 5)
    return <span className="px-1.5 py-0.5 rounded text-xs bg-green-900 text-green-300" title="Cardiac decoupling">{val.toFixed(1)}% CD</span>;
  if (val < 10)
    return <span className="px-1.5 py-0.5 rounded text-xs bg-yellow-900 text-yellow-300" title="Cardiac decoupling">{val.toFixed(1)}% CD</span>;
  return <span className="px-1.5 py-0.5 rounded text-xs bg-red-900 text-red-300" title="Cardiac decoupling">{val.toFixed(1)}% CD</span>;
}

function EfficiencyBadge({ val }: { val: number | null }) {
  if (val === null) return null;
  if (val > 66)
    return <span className="px-1.5 py-0.5 rounded text-xs bg-green-900 text-green-300" title="Effort efficiency score">{Math.round(val)} EFF</span>;
  if (val >= 33)
    return <span className="px-1.5 py-0.5 rounded text-xs bg-yellow-900 text-yellow-300" title="Effort efficiency score">{Math.round(val)} EFF</span>;
  return <span className="px-1.5 py-0.5 rounded text-xs bg-red-900 text-red-300" title="Effort efficiency score">{Math.round(val)} EFF</span>;
}

/** Single metric tile for the panel grid. */
function MetricTile({
  label,
  value,
  sub,
  color = "default",
}: {
  label: string;
  value: string;
  sub?: string;
  color?: "green" | "yellow" | "red" | "default";
}) {
  const valueClass =
    color === "green"  ? "text-green-400"  :
    color === "yellow" ? "text-yellow-400" :
    color === "red"    ? "text-red-400"    :
    "text-gray-100";
  return (
    <div className="bg-gray-800 rounded-lg px-3 py-2.5">
      <p className="text-xs text-gray-500 mb-0.5">{label}</p>
      <p className={`text-sm font-semibold ${valueClass}`}>{value}</p>
      {sub && <p className="text-xs text-gray-600 mt-0.5">{sub}</p>}
    </div>
  );
}

/** HR zone stacked bar with legend. */
function HrZonesBar({ a }: { a: Activity }) {
  const z1 = a.hr_zone_1_pct ?? 0;
  const z2 = a.hr_zone_2_pct ?? 0;
  const z3 = a.hr_zone_3_pct ?? 0;
  const z4 = a.hr_zone_4_pct ?? 0;
  const z5 = a.hr_zone_5_pct ?? 0;
  if (!a.hr_zone_1_pct && !a.hr_zone_2_pct) return null;

  return (
    <div>
      <p className="text-xs text-gray-500 mb-1.5">HR Zone Distribution</p>
      <div className="flex h-5 rounded overflow-hidden gap-px">
        {z1 > 0 && <div style={{ width: `${z1}%` }} className="bg-gray-500" title={`Z1 ${z1.toFixed(0)}%`} />}
        {z2 > 0 && <div style={{ width: `${z2}%` }} className="bg-blue-600" title={`Z2 ${z2.toFixed(0)}%`} />}
        {z3 > 0 && <div style={{ width: `${z3}%` }} className="bg-yellow-500" title={`Z3 ${z3.toFixed(0)}%`} />}
        {z4 > 0 && <div style={{ width: `${z4}%` }} className="bg-orange-500" title={`Z4 ${z4.toFixed(0)}%`} />}
        {z5 > 0 && <div style={{ width: `${z5}%` }} className="bg-red-500"    title={`Z5 ${z5.toFixed(0)}%`} />}
      </div>
      <div className="flex gap-3 mt-1.5 flex-wrap">
        {[["Z1", z1, "bg-gray-500"], ["Z2", z2, "bg-blue-600"], ["Z3", z3, "bg-yellow-500"], ["Z4", z4, "bg-orange-500"], ["Z5", z5, "bg-red-500"]].map(([label, pct, cls]) =>
          (pct as number) > 0 ? (
            <span key={label as string} className="flex items-center gap-1 text-xs text-gray-400">
              <span className={`inline-block w-2 h-2 rounded-sm ${cls}`} />
              {label} {(pct as number).toFixed(0)}%
            </span>
          ) : null
        )}
      </div>
    </div>
  );
}

/** Exercise breakdown panel section for lifting workouts. */
function ExerciseBreakdown({ exercises_json }: { exercises_json: string }) {
  const units = useUnits();
  const [showAll, setShowAll] = useState(false);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let exercises: any[] = [];
  try {
    exercises = JSON.parse(exercises_json);
  } catch {
    return null;
  }
  if (exercises.length === 0) return null;

  const visible = showAll ? exercises : exercises.slice(0, 3);
  const hasMore = exercises.length > 3;

  return (
    <section className="space-y-3">
      <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Exercises</h4>
      <div className="space-y-4">
        {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
        {visible.map((ex: any, i: number) => {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const warmupSets = (ex.sets ?? []).filter((s: any) => s.type === "warmup");
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const workingSets = (ex.sets ?? []).filter((s: any) => s.type !== "warmup");
          const muscleGroup = ex.muscle_group ?? ex.primary_muscle_group ?? "";
          return (
            <div key={i} className="border-l-2 border-gray-700 pl-3">
              <div className="flex items-baseline justify-between gap-2 mb-1.5">
                <span className="text-sm font-medium text-gray-200">{ex.title ?? ex.name ?? "Exercise"}</span>
                {muscleGroup && (
                  <span className="text-xs text-gray-500 shrink-0">{muscleGroup}</span>
                )}
              </div>
              <div className="flex flex-wrap gap-x-3 gap-y-1">
                {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
                {warmupSets.map((s: any, j: number) => (
                  <span key={`w${j}`} className="text-xs text-gray-600 italic">{formatSet(s, units)}</span>
                ))}
                {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
                {workingSets.map((s: any, j: number) => (
                  <span key={j} className="text-xs text-gray-400">{formatSet(s, units)}</span>
                ))}
              </div>
            </div>
          );
        })}
      </div>
      {hasMore && !showAll && (
        <button
          onClick={() => setShowAll(true)}
          className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
        >
          Show all {exercises.length} exercises
        </button>
      )}
    </section>
  );
}

export default function Activities({ mode, theme, lastSyncAt, onSynced }: Props) {
  const units = useUnits();
  const [activities, setActivities] = useState<Activity[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState("");

  const isLifting = mode === "lifting";
  const [modeOnly, setModeOnly] = useState(false);
  const showAllView = !modeOnly;
  const isLiftingView = isLifting && modeOnly;

  // Sorting
  const [sortKey, setSortKey] = useState<SortKey>("date");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  // Filtering
  const [search, setSearch] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [minDist, setMinDist] = useState("");

  // Slide-out panel state
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [deepDiveReport, setDeepDiveReport] = useState<string>("");
  const [deepDiveModel, setDeepDiveModel] = useState<string>("");
  const [deepDiveLoading, setDeepDiveLoading] = useState(false);
  const [deepDiveError, setDeepDiveError] = useState("");
  const [notes, setNotes] = useState<string>("");
  const [notesSaving, setNotesSaving] = useState(false);
  const [notesSaved, setNotesSaved] = useState(false);

  const selectedActivity = activities.find((a) => a.id === selectedId) ?? null;
  const isLiftingActivity = selectedActivity?.sport_type === "WeightTraining";

  useEffect(() => {
    setLoading(true);
    fetch(modeOnly ? `/api/activities?mode=${mode}` : "/api/activities")
      .then((r) => r.json())
      .then(setActivities)
      .finally(() => setLoading(false));
    // units.system: analysis summaries are rendered server-side in the current units.
  }, [mode, modeOnly, units.system]);

  // Reset sort key and modeOnly when switching modes
  useEffect(() => {
    setSortKey("date");
    setSortDir("desc");
    setModeOnly(false);
  }, [mode]);

  function openPanel(id: number) {
    const act = activities.find((a) => a.id === id);
    setSelectedId(id);
    setDeepDiveReport(act?.deep_dive_report ?? "");
    setDeepDiveModel(act?.deep_dive_model ?? "");
    setDeepDiveError("");
    setDeepDiveLoading(false);
    setNotes(act?.user_notes ?? "");
    setNotesSaved(false);
  }

  function closePanel() {
    setSelectedId(null);
    setDeepDiveReport("");
    setDeepDiveModel("");
    setDeepDiveError("");
    setDeepDiveLoading(false);
    setNotes("");
    setNotesSaved(false);
  }

  async function handleSync() {
    setSyncing(true);
    setSyncMsg("");
    try {
      const data = await fetch("/api/sync", { method: "POST" }).then((r) => r.json());
      const count = data.total ?? 0;
      setSyncMsg(count > 0 ? `${count} new item${count === 1 ? "" : "s"} synced.` : "Already up to date.");
      const rows = await fetch(modeOnly ? `/api/activities?mode=${mode}` : "/api/activities").then((r) => r.json());
      setActivities(rows);
      onSynced();
    } catch {
      setSyncMsg("Sync failed.");
    } finally {
      setSyncing(false);
    }
  }

  function discussInChat(activityId: number) {
    sessionStorage.setItem(PENDING_CHAT_ACTIVITY_KEY, String(activityId));
    location.hash = "chat";
  }

  async function runDeepDive(force = false) {
    if (selectedId === null) return;
    setDeepDiveError("");
    setDeepDiveLoading(true);
    if (!force && selectedActivity?.deep_dive_report) {
      setDeepDiveReport(selectedActivity.deep_dive_report);
      setDeepDiveLoading(false);
      return;
    }
    try {
      const url = `/api/activities/${selectedId}/deep-dive${force ? "?force=true" : ""}`;
      const res = await fetch(url, { method: "POST" });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Request failed" }));
        setDeepDiveError(err.detail || "Deep dive failed.");
        return;
      }
      const data = await res.json();
      setDeepDiveReport(data.report);
      setDeepDiveModel(data.model ?? "");
      setActivities((prev) =>
        prev.map((a) =>
          a.id === selectedId
            ? { ...a, deep_dive_report: data.report, deep_dive_model: data.model ?? null }
            : a
        )
      );
    } catch {
      setDeepDiveError("Network error — could not complete deep dive.");
    } finally {
      setDeepDiveLoading(false);
    }
  }

  async function saveNotes() {
    if (selectedId === null) return;
    setNotesSaving(true);
    setNotesSaved(false);
    try {
      await fetch(`/api/activities/${selectedId}/notes`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ notes }),
      });
      setActivities((prev) =>
        prev.map((a) => (a.id === selectedId ? { ...a, user_notes: notes } : a))
      );
      setNotesSaved(true);
    } finally {
      setNotesSaving(false);
    }
  }

  function handleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(key === "date" ? "desc" : "asc");
    }
  }

  const filtered = useMemo(() => {
    let rows = activities;
    if (search.trim()) {
      const q = search.toLowerCase();
      rows = rows.filter((a) => (a.name ?? "").toLowerCase().includes(q));
    }
    if (dateFrom) rows = rows.filter((a) => a.date >= dateFrom);
    if (dateTo)   rows = rows.filter((a) => a.date <= dateTo);
    const minDistM = minDist ? units.toSI(parseFloat(minDist), "distance") : null;
    if (modeOnly && !isLifting && minDistM != null) rows = rows.filter((a) => (a.distance_m ?? 0) >= minDistM);

    return [...rows].sort((a, b) => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const av = (a as any)[sortKey] ?? (sortKey === "name" ? "" : -Infinity);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const bv = (b as any)[sortKey] ?? (sortKey === "name" ? "" : -Infinity);
      if (av < bv) return sortDir === "asc" ? -1 : 1;
      if (av > bv) return sortDir === "asc" ? 1 : -1;
      return 0;
    });
  }, [activities, search, dateFrom, dateTo, minDist, sortKey, sortDir, isLifting, modeOnly, units]);

  const baselines = useMemo(() => buildBaselines(activities), [activities]);
  const labelsOf = (a: Activity): ActivityLabels => labelsFor(a, baselines);
  const selectedLabels = selectedActivity ? labelsOf(selectedActivity) : null;

  const paceLabel = mode === "cycling" ? "Speed" : mode === "hybrid" ? "Pace/Speed" : "Pace";
  const focusClass = "focus:outline-none focus:border-gray-500";

  function Th({ label, col, right = false }: { label: string; col: SortKey; right?: boolean }) {
    return (
      <th
        onClick={() => handleSort(col)}
        className={`group px-4 py-2 font-medium cursor-pointer select-none whitespace-nowrap hover:text-gray-200 transition-colors ${right ? "text-right" : ""}`}
      >
        {label}
        <SortIcon active={sortKey === col} dir={sortDir} />
      </th>
    );
  }

  const filtersActive = search || dateFrom || dateTo || (modeOnly && !isLifting && minDist);

  // ── Panel helpers ────────────────────────────────────────────────────────

  function cdColor(v: number | null): "green" | "yellow" | "red" | "default" {
    if (v === null) return "default";
    if (v < 5) return "green";
    if (v < 10) return "yellow";
    return "red";
  }

  function effColor(v: number | null): "green" | "yellow" | "red" | "default" {
    if (v === null) return "default";
    if (v > 66) return "green";
    if (v >= 33) return "yellow";
    return "red";
  }

  function paceOrSpeed(a: Activity, forceSpeed = false): string {
    if (forceSpeed || isRide(a.sport_type)) return units.fmtSpeed(a.avg_pace_s_per_km);
    return a.avg_pace_s_per_km ? units.fmt(a.avg_pace_s_per_km, "pace") : "—";
  }

  const hasMetrics = selectedActivity && (
    selectedActivity.cardiac_decoupling_pct !== null ||
    selectedActivity.effort_efficiency_score !== null ||
    selectedActivity.pace_fade_s_per_km !== null ||
    selectedActivity.avg_cadence !== null ||
    selectedActivity.climb_m_per_km !== null ||
    selectedActivity.hr_zone_1_pct !== null
  );

  // Count distinct exercises from exercises_json
  function exerciseCount(a: Activity): number {
    if (!a.exercises_json) return 0;
    try { return JSON.parse(a.exercises_json).length; } catch { return 0; }
  }

  return (
    <div className="flex flex-col h-full p-6 gap-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-100">
          {isLifting ? "Sessions" : "Activities"}{" "}
          <span className="text-sm font-normal text-gray-400">
            ({filtered.length}{filtersActive ? ` of ${activities.length}` : ""})
          </span>
        </h2>
        <div className="flex items-center gap-3">
          {syncMsg ? (
            <span className={`text-sm ${theme.accentClass}`}>{syncMsg}</span>
          ) : (
            <span className="text-sm text-gray-500">{formatSyncFreshness(lastSyncAt)}</span>
          )}
          <button
            onClick={handleSync}
            disabled={syncing}
            className={`px-3 py-1.5 rounded-md ${theme.accentButton} text-white text-sm disabled:opacity-50 transition-colors`}
          >
            {syncing ? "Syncing…" : "Sync Activities"}
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-2 items-center">
        <input
          type="text"
          placeholder="Search by name…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className={`rounded-md bg-gray-900 border border-gray-700 px-3 py-1.5 text-sm text-gray-100 placeholder-gray-500 ${focusClass} w-48`}
        />
        <input
          type="date"
          value={dateFrom}
          onChange={(e) => setDateFrom(e.target.value)}
          title="From date"
          className={`rounded-md bg-gray-900 border border-gray-700 px-3 py-1.5 text-sm text-gray-100 ${focusClass}`}
        />
        <span className="text-gray-600 text-sm">–</span>
        <input
          type="date"
          value={dateTo}
          onChange={(e) => setDateTo(e.target.value)}
          title="To date"
          className={`rounded-md bg-gray-900 border border-gray-700 px-3 py-1.5 text-sm text-gray-100 ${focusClass}`}
        />
        {modeOnly && !isLifting && (
          <input
            type="number"
            placeholder={`Min ${units.label("distance")}`}
            value={minDist}
            onChange={(e) => setMinDist(e.target.value)}
            min="0"
            step="1"
            className={`rounded-md bg-gray-900 border border-gray-700 px-3 py-1.5 text-sm text-gray-100 placeholder-gray-500 ${focusClass} w-24`}
          />
        )}
        {mode !== "hybrid" && (
          <button
            onClick={() => setModeOnly((v) => !v)}
            className={`px-3 py-1.5 rounded-md text-sm border transition-colors ${
              modeOnly
                ? `${theme.accentButton} text-white border-transparent`
                : "bg-gray-900 border-gray-700 text-gray-400 hover:text-gray-200"
            }`}
          >
            Mode Only
          </button>
        )}
        {filtersActive && (
          <button
            onClick={() => { setSearch(""); setDateFrom(""); setDateTo(""); setMinDist(""); }}
            className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
          >
            Clear
          </button>
        )}
      </div>

      {/* Table */}
      {loading ? (
        <p className="text-gray-500 text-sm">Loading…</p>
      ) : (
        <div className="overflow-auto flex-1 rounded-lg border border-gray-800">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-900 text-gray-400 text-left sticky top-0">
                {showAllView ? (
                  <>
                    <Th label="Date"       col="date" />
                    <th className="px-4 py-2 font-medium whitespace-nowrap text-gray-400">Type</th>
                    <Th label="Name"       col="name" />
                    <Th label={`Dist (${units.label("distance")})`} col="distance_m" right />
                    <Th label="Time"       col="moving_time_s"     right />
                    <Th label="Pace/Speed" col="avg_pace_s_per_km" right />
                    <Th label="Avg HR"     col="avg_hr"            right />
                    <Th label={`Elev (${units.label("elevation")})`} col="elevation_gain_m" right />
                    <Th label={`Climb (${units.label("climb_rate")})`} col="climb_m_per_km" right />
                    <th className="px-4 py-2 font-medium whitespace-nowrap text-right"></th>
                  </>
                ) : isLiftingView ? (
                  <>
                    <Th label="Date"        col="date" />
                    <Th label="Name"        col="name" />
                    <Th label={`Volume (${units.label("mass")})`} col="total_volume_kg" right />
                    <Th label="Time"        col="moving_time_s"    right />
                    <Th label="Sets"        col="total_sets"       right />
                    <th className="px-4 py-2 font-medium whitespace-nowrap text-right text-gray-400">Exercises</th>
                    <th className="px-4 py-2 font-medium whitespace-nowrap text-right"></th>
                  </>
                ) : (
                  <>
                    <Th label="Date"      col="date" />
                    <Th label="Name"      col="name" />
                    <Th label={`Dist (${units.label("distance")})`} col="distance_m" right />
                    <Th label="Time"      col="moving_time_s"     right />
                    <Th label={paceLabel} col="avg_pace_s_per_km" right />
                    <Th label="Avg HR"    col="avg_hr"            right />
                    <Th label={`Elev (${units.label("elevation")})`} col="elevation_gain_m" right />
                    <Th label={`Climb (${units.label("climb_rate")})`} col="climb_m_per_km" right />
                    <th className="px-4 py-2 font-medium whitespace-nowrap text-right"></th>
                  </>
                )}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={showAllView ? 10 : isLiftingView ? 7 : 9} className="px-4 py-8 text-center text-gray-500">
                    No {isLifting ? "sessions" : "activities"} match your filters.
                  </td>
                </tr>
              ) : (
                filtered.map((a) => {
                  const lbl = labelsOf(a);
                  return (
                  <tr
                    key={a.id}
                    className={`hover:bg-gray-800/50 transition-colors cursor-pointer ${selectedId === a.id ? "bg-gray-800/60" : ""}`}
                    onClick={() => openPanel(a.id)}
                  >
                    <td className="px-4 py-2 text-gray-400 whitespace-nowrap">{a.date}</td>
                    {showAllView && (
                      <td className="px-4 py-2 text-gray-500 whitespace-nowrap text-xs">{a.sport_type ?? "—"}</td>
                    )}
                    <td className="px-4 py-2">
                      <span className="text-gray-100">{a.name || "—"}</span>
                      {a.analysis_summary && (
                        <p className="text-xs text-gray-500 mt-0.5 max-w-xs truncate">{a.analysis_summary}</p>
                      )}
                      {!isLiftingView && (a.cardiac_decoupling_pct !== null || a.effort_efficiency_score !== null) && (
                        <div className="flex gap-1 mt-1 flex-wrap">
                          <DecouplingBadge val={a.cardiac_decoupling_pct} />
                          <EfficiencyBadge val={a.effort_efficiency_score} />
                        </div>
                      )}
                    </td>
                    {isLiftingView ? (
                      <>
                        <td className="px-4 py-2 text-right text-gray-100">
                          {units.fmt(a.total_volume_kg, "mass", { withLabel: false })}
                        </td>
                        <td className="px-4 py-2 text-right text-gray-400">
                          {formatDuration(a.moving_time_s)}
                        </td>
                        <td className="px-4 py-2 text-right text-gray-400">
                          {a.total_sets ?? "—"}
                        </td>
                        <td className="px-4 py-2 text-right text-gray-400">
                          {exerciseCount(a) || "—"}
                        </td>
                      </>
                    ) : (
                      <>
                        <td className="px-4 py-2 text-right text-gray-100">
                          {units.fmt(a.distance_m || 0, "distance", { withLabel: false })}
                          <LabelChip label={lbl.distance} />
                        </td>
                        <td className="px-4 py-2 text-right text-gray-400">
                          {formatDuration(a.moving_time_s)}
                          <LabelChip label={lbl.time} />
                        </td>
                        <td className="px-4 py-2 text-right text-gray-400">
                          {paceOrSpeed(a)}
                          <LabelChip label={lbl.pace} />
                        </td>
                        <td className="px-4 py-2 text-right text-gray-400">
                          {a.avg_hr ?? "—"}
                          <LabelChip label={lbl.hr} />
                        </td>
                        <td className="px-4 py-2 text-right text-gray-400">
                          {units.fmt(a.elevation_gain_m, "elevation", { withLabel: false })}
                          <LabelChip label={lbl.elevation} />
                        </td>
                        <td className="px-4 py-2 text-right text-gray-400">
                          {units.fmt(a.climb_m_per_km, "climb_rate", { withLabel: false })}
                          <LabelChip label={lbl.climb} />
                        </td>
                      </>
                    )}
                    <td className="px-4 py-2 text-right" onClick={(e) => e.stopPropagation()}>
                      <button
                        onClick={() => openPanel(a.id)}
                        className="px-2 py-1 rounded text-xs bg-gray-700 hover:bg-gray-600 text-gray-300 transition-colors whitespace-nowrap"
                      >
                        {a.analysis_status === "done" ? "Details ›" : "Details"}
                      </button>
                    </td>
                  </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* ── Slide-out panel ──────────────────────────────────────────────── */}
      {selectedActivity && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 z-40 bg-black/50"
            onClick={closePanel}
          />

          {/* Panel */}
          <div className="fixed right-0 top-0 h-full w-full max-w-2xl z-50 bg-gray-950 border-l border-gray-800 flex flex-col shadow-2xl">

            {/* Panel header */}
            <div className="px-5 py-4 border-b border-gray-800 flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <h3 className="text-gray-100 font-semibold truncate">{selectedActivity.name || "Activity"}</h3>
                  {!isLiftingActivity && (
                    <a
                      href={`https://www.strava.com/activities/${selectedActivity.id}`}
                      target="_blank"
                      rel="noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      className="text-xs text-orange-500 hover:text-orange-400 transition-colors shrink-0"
                    >
                      Strava ↗
                    </a>
                  )}
                </div>
                <p className="text-xs text-gray-500 mt-0.5">
                  {selectedActivity.date}
                  {selectedActivity.sport_type ? ` · ${selectedActivity.sport_type}` : ""}
                </p>
              </div>
              <button
                onClick={closePanel}
                className="text-gray-500 hover:text-gray-300 transition-colors text-xl leading-none shrink-0 mt-0.5"
              >
                ×
              </button>
            </div>

            {/* Panel body — scrollable */}
            <div className="overflow-y-auto flex-1 p-5 space-y-6">

              {/* Basic stats row */}
              {isLiftingActivity ? (
                <div className="grid grid-cols-4 gap-2">
                  <MetricTile
                    label={`Volume (${units.label("mass")})`}
                    value={units.fmt(selectedActivity.total_volume_kg, "mass", { withLabel: false })}
                  />
                  <MetricTile
                    label="Time"
                    value={formatDuration(selectedActivity.moving_time_s)}
                  />
                  <MetricTile
                    label="Sets"
                    value={selectedActivity.total_sets != null ? String(selectedActivity.total_sets) : "—"}
                  />
                  <MetricTile
                    label="Exercises"
                    value={String(exerciseCount(selectedActivity) || "—")}
                  />
                </div>
              ) : (
                <div className="grid grid-cols-4 gap-2">
                  <MetricTile
                    label="Distance"
                    value={units.fmt(selectedActivity.distance_m || 0, "distance")}
                    sub={selectedLabels?.distance ? `${selectedLabels.distance.text} · ${selectedLabels.distance.detail.split(" (")[0]}` : undefined}
                    color={selectedLabels?.distance?.tone}
                  />
                  <MetricTile
                    label="Time"
                    value={formatDuration(selectedActivity.moving_time_s)}
                    sub={selectedLabels?.time ? `${selectedLabels.time.text} · ${selectedLabels.time.detail.split(" (")[0]}` : undefined}
                    color={selectedLabels?.time?.tone}
                  />
                  <MetricTile
                    label={mode === "cycling" || isRide(selectedActivity.sport_type) ? "Speed" : "Pace"}
                    value={paceOrSpeed(selectedActivity, mode === "cycling")}
                    sub={selectedLabels?.pace ? `${selectedLabels.pace.text} · ${selectedLabels.pace.detail}` : undefined}
                    color={selectedLabels?.pace?.tone}
                  />
                  <MetricTile
                    label="Avg HR"
                    value={selectedActivity.avg_hr ? `${Math.round(selectedActivity.avg_hr)} bpm` : "—"}
                    sub={selectedLabels?.hr ? `${selectedLabels.hr.text} · ${selectedLabels.hr.detail}` : undefined}
                    color={selectedLabels?.hr?.tone}
                  />
                </div>
              )}

              {/* Exercise breakdown — lifting only */}
              {isLiftingActivity && selectedActivity.exercises_json && (
                <ExerciseBreakdown exercises_json={selectedActivity.exercises_json} />
              )}

              {/* Analysis summary */}
              {selectedActivity.analysis_summary && (
                <div className="bg-gray-800/60 rounded-lg px-4 py-3 border border-gray-700">
                  <p className="text-xs text-gray-500 mb-1">Analysis Summary</p>
                  <p className="text-sm text-gray-200 leading-relaxed">{selectedActivity.analysis_summary}</p>
                </div>
              )}

              {/* Cardio metrics grid — running/cycling only */}
              {!isLiftingActivity && hasMetrics && (
                <section className="space-y-3">
                  <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Computed Metrics</h4>

                  <div className="grid grid-cols-2 gap-2">
                    {selectedActivity.cardiac_decoupling_pct !== null && (
                      <MetricTile
                        label="Cardiac Decoupling"
                        value={`${selectedActivity.cardiac_decoupling_pct.toFixed(1)}%`}
                        sub={selectedActivity.cardiac_decoupling_pct < 5 ? "Excellent" : selectedActivity.cardiac_decoupling_pct < 10 ? "Moderate stress" : "High drift"}
                        color={cdColor(selectedActivity.cardiac_decoupling_pct)}
                      />
                    )}
                    {selectedActivity.effort_efficiency_score !== null && (
                      <MetricTile
                        label="Effort Efficiency"
                        value={`${Math.round(selectedActivity.effort_efficiency_score)} / 100`}
                        sub="Normalized vs history"
                        color={effColor(selectedActivity.effort_efficiency_score)}
                      />
                    )}
                    {selectedActivity.pace_fade_s_per_km !== null && (
                      <MetricTile
                        label="Pace Fade"
                        value={units.fmt(selectedActivity.pace_fade_s_per_km, "pace_delta")}
                        sub={selectedActivity.pace_fade_s_per_km > PACE_FADE_NOTABLE_S_PER_KM ? "Slowed in final third" : selectedActivity.pace_fade_s_per_km < -PACE_FADE_NOTABLE_S_PER_KM ? "Negative split" : "Even pacing"}
                        color={selectedActivity.pace_fade_s_per_km > PACE_FADE_NOTABLE_S_PER_KM ? "yellow" : selectedActivity.pace_fade_s_per_km < -PACE_FADE_NOTABLE_S_PER_KM ? "green" : "default"}
                      />
                    )}
                    {selectedActivity.avg_cadence !== null && (
                      <MetricTile
                        label={isRide(selectedActivity.sport_type) ? "Cadence (rpm)" : "Cadence (spm)"}
                        value={`${Math.round(selectedActivity.avg_cadence)}`}
                        sub={selectedActivity.cadence_std_dev !== null ? `±${selectedActivity.cadence_std_dev.toFixed(1)} std dev` : undefined}
                      />
                    )}
                    {selectedActivity.climb_m_per_km !== null && (
                      <MetricTile
                        label="Climbing Ratio"
                        value={units.fmt(selectedActivity.climb_m_per_km, "climb_rate")}
                        sub={selectedLabels?.climb ? `${selectedLabels.climb.text} · ${selectedLabels.climb.detail}` : undefined}
                        color={selectedLabels?.climb?.tone}
                      />
                    )}
                    {selectedActivity.suffer_score_mismatch_flag === 1 && (
                      <MetricTile
                        label="HR Reliability"
                        value="⚠ Mismatch"
                        sub="Suffer score vs HR zones inconsistent"
                        color="yellow"
                      />
                    )}
                  </div>

                  <HrZonesBar a={selectedActivity} />
                </section>
              )}

              {/* No analysis yet — running/cycling only */}
              {!isLiftingActivity && !hasMetrics && selectedActivity.analysis_status !== "done" && (
                <p className="text-sm text-gray-600">
                  {selectedActivity.analysis_status === "skipped"
                    ? "No stream data available for this activity."
                    : selectedActivity.analysis_status === "error"
                    ? "Analysis failed for this activity."
                    : "Analysis pending — will run on next sync."}
                </p>
              )}

              {/* ── User Notes ───────────────────────────────────────── */}
              <section className="space-y-2">
                <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Your Notes</h4>
                <textarea
                  value={notes}
                  onChange={(e) => { setNotes(e.target.value); setNotesSaved(false); }}
                  placeholder="Add context for the Deep Dive — how you felt, goals, weather, etc."
                  rows={3}
                  className="w-full rounded-lg bg-gray-800 border border-gray-700 px-3 py-2 text-sm text-gray-200 placeholder-gray-600 resize-y focus:outline-none focus:border-gray-500"
                />
                <div className="flex items-center gap-3">
                  <button
                    onClick={saveNotes}
                    disabled={notesSaving}
                    className="px-3 py-1.5 rounded-md bg-gray-700 hover:bg-gray-600 text-sm text-gray-200 disabled:opacity-50 transition-colors"
                  >
                    {notesSaving ? "Saving…" : "Save Notes"}
                  </button>
                  {notesSaved && <span className="text-xs text-green-400">Saved</span>}
                </div>
              </section>

              {/* ── Deep Dive ─────────────────────────────────────────── */}
              <section className="space-y-3">
                <div className="flex items-center justify-between">
                  <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Deep Dive Analysis</h4>
                  <div className="flex items-center gap-3">
                    <button
                      onClick={() => discussInChat(selectedActivity.id)}
                      className={`text-xs ${theme.accentClass} hover:underline transition-colors`}
                    >
                      Discuss in chat →
                    </button>
                    {(deepDiveReport || selectedActivity.deep_dive_report) && !deepDiveLoading && (
                      <button
                        onClick={() => runDeepDive(true)}
                        className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
                      >
                        Regenerate
                      </button>
                    )}
                  </div>
                </div>

                {deepDiveLoading && (
                  <div className="flex items-center gap-3 text-gray-400">
                    <svg className="animate-spin h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                    </svg>
                    <span className="text-sm text-gray-400">Analyzing… this may take 10–20 seconds.</span>
                  </div>
                )}

                {deepDiveError && (
                  <p className="text-sm text-red-400">{deepDiveError}</p>
                )}

                {!deepDiveLoading && !deepDiveReport && !selectedActivity.deep_dive_report && !deepDiveError && (
                  <button
                    onClick={() => runDeepDive()}
                    className={`px-4 py-2 rounded-lg text-sm font-medium ${theme.accentButton} text-white transition-colors`}
                  >
                    Run Deep Dive
                  </button>
                )}

                {!deepDiveLoading && (deepDiveReport || selectedActivity.deep_dive_report) && (
                  <>
                    <div className="flex items-center gap-3 flex-wrap">
                      {selectedActivity.deep_dive_completed_at && !deepDiveReport && (
                        <p className="text-xs text-gray-600">
                          Generated {new Date(selectedActivity.deep_dive_completed_at).toLocaleString()}
                        </p>
                      )}
                      {(deepDiveModel || selectedActivity.deep_dive_model) && (
                        <span className="text-[10px] text-gray-700 font-mono">
                          {deepDiveModel || selectedActivity.deep_dive_model}
                        </span>
                      )}
                    </div>
                    <div className="prose prose-invert prose-sm max-w-none text-gray-300 [&_h1]:text-base [&_h2]:text-sm [&_h3]:text-sm [&_ul]:pl-4 [&_ol]:pl-4 [&_li]:my-0.5 [&_p]:my-1.5 [&_strong]:text-gray-100 [&_hr]:border-gray-700">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {deepDiveReport || selectedActivity.deep_dive_report || ""}
                      </ReactMarkdown>
                    </div>
                  </>
                )}
              </section>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
