import { useEffect, useMemo, useState } from "react";
import type { Mode, ThemeConfig } from "../App";

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
  analysis_summary: string | null;
  cardiac_decoupling_pct: number | null;
  effort_efficiency_score: number | null;
  analysis_status: string | null;
  deep_dive_report: string | null;
}

interface Props {
  mode: Mode;
  theme: ThemeConfig;
}

type SortKey = "date" | "name" | "distance_m" | "moving_time_s" | "avg_pace_s_per_km" | "avg_hr" | "elevation_gain_m";
type SortDir = "asc" | "desc";

function formatPace(s: number | null): string {
  if (!s) return "—";
  const mins = Math.floor(s / 60);
  const secs = Math.floor(s % 60);
  return `${mins}:${String(secs).padStart(2, "0")}/km`;
}

function formatSpeed(s: number | null): string {
  if (!s || s <= 0) return "—";
  return `${(3600 / s).toFixed(1)} km/h`;
}

function formatDuration(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h) return `${h}h${String(m).padStart(2, "0")}m`;
  return `${m}m${String(sec).padStart(2, "0")}s`;
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

export default function Activities({ mode, theme }: Props) {
  const [activities, setActivities] = useState<Activity[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState("");

  // Sorting
  const [sortKey, setSortKey] = useState<SortKey>("date");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  // Filtering
  const [search, setSearch] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [minDist, setMinDist] = useState("");

  // Deep dive modal state
  const [deepDiveId, setDeepDiveId] = useState<number | null>(null);
  const [deepDiveReport, setDeepDiveReport] = useState<string>("");
  const [deepDiveLoading, setDeepDiveLoading] = useState(false);
  const [deepDiveError, setDeepDiveError] = useState("");

  useEffect(() => {
    setLoading(true);
    fetch(`/api/activities?mode=${mode}`)
      .then((r) => r.json())
      .then(setActivities)
      .finally(() => setLoading(false));
  }, [mode]);

  async function handleSync() {
    setSyncing(true);
    setSyncMsg("");
    try {
      const res = await fetch("/api/sync", { method: "POST" });
      const data = await res.json();
      setSyncMsg(
        data.new_activities > 0
          ? `${data.new_activities} new activit${data.new_activities === 1 ? "y" : "ies"} synced.`
          : "Already up to date."
      );
      const rows = await fetch(`/api/activities?mode=${mode}`).then((r) => r.json());
      setActivities(rows);
    } catch {
      setSyncMsg("Sync failed.");
    } finally {
      setSyncing(false);
    }
  }

  async function handleDeepDive(activityId: number, force = false) {
    setDeepDiveId(activityId);
    setDeepDiveReport("");
    setDeepDiveError("");
    setDeepDiveLoading(true);

    // Check if there's already a cached report
    const cached = activities.find((a) => a.id === activityId);
    if (cached?.deep_dive_report && !force) {
      setDeepDiveReport(cached.deep_dive_report);
      setDeepDiveLoading(false);
      return;
    }

    try {
      const url = `/api/activities/${activityId}/deep-dive${force ? "?force=true" : ""}`;
      const res = await fetch(url, { method: "POST" });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Request failed" }));
        setDeepDiveError(err.detail || "Deep dive failed.");
        return;
      }
      const data = await res.json();
      setDeepDiveReport(data.report);
      // Update the cached report in local state
      setActivities((prev) =>
        prev.map((a) => (a.id === activityId ? { ...a, deep_dive_report: data.report } : a))
      );
    } catch {
      setDeepDiveError("Network error — could not complete deep dive.");
    } finally {
      setDeepDiveLoading(false);
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
    if (minDist)  rows = rows.filter((a) => (a.distance_m ?? 0) / 1000 >= parseFloat(minDist));

    return [...rows].sort((a, b) => {
      const av = a[sortKey] ?? (sortKey === "name" ? "" : -Infinity);
      const bv = b[sortKey] ?? (sortKey === "name" ? "" : -Infinity);
      if (av < bv) return sortDir === "asc" ? -1 : 1;
      if (av > bv) return sortDir === "asc" ? 1 : -1;
      return 0;
    });
  }, [activities, search, dateFrom, dateTo, minDist, sortKey, sortDir]);

  const paceLabel = mode === "cycling" ? "Speed" : mode === "hybrid" ? "Pace/Speed" : "Pace";
  const focusClass = "focus:outline-none focus:border-gray-500";

  function Th({
    label,
    col,
    right = false,
  }: {
    label: string;
    col: SortKey;
    right?: boolean;
  }) {
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

  const filtersActive = search || dateFrom || dateTo || minDist;

  const deepDiveActivity = activities.find((a) => a.id === deepDiveId);

  return (
    <div className="flex flex-col h-full p-6 gap-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-100">
          Activities{" "}
          <span className="text-sm font-normal text-gray-400">
            ({filtered.length}{filtersActive ? ` of ${activities.length}` : ""})
          </span>
        </h2>
        <div className="flex items-center gap-3">
          {syncMsg && <span className={`text-sm ${theme.accentClass}`}>{syncMsg}</span>}
          <button
            onClick={handleSync}
            disabled={syncing}
            className={`px-3 py-1.5 rounded-md ${theme.accentButton} text-white text-sm disabled:opacity-50 transition-colors`}
          >
            {syncing ? "Syncing…" : "Sync Strava"}
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
        <input
          type="number"
          placeholder="Min km"
          value={minDist}
          onChange={(e) => setMinDist(e.target.value)}
          min="0"
          step="1"
          className={`rounded-md bg-gray-900 border border-gray-700 px-3 py-1.5 text-sm text-gray-100 placeholder-gray-500 ${focusClass} w-24`}
        />
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
                <Th label="Date"      col="date" />
                <Th label="Name"      col="name" />
                <Th label="Dist (km)" col="distance_m"       right />
                <Th label="Time"      col="moving_time_s"     right />
                <Th label={paceLabel} col="avg_pace_s_per_km" right />
                <Th label="Avg HR"    col="avg_hr"            right />
                <Th label="Elev (m)"  col="elevation_gain_m"  right />
                <th className="px-4 py-2 font-medium whitespace-nowrap text-right">Deep Dive</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py-8 text-center text-gray-500">
                    No activities match your filters.
                  </td>
                </tr>
              ) : (
                filtered.map((a) => (
                  <tr key={a.id} className="hover:bg-gray-800/50 transition-colors">
                    <td className="px-4 py-2 text-gray-400 whitespace-nowrap">{a.date}</td>
                    <td className="px-4 py-2">
                      <a
                        href={`https://www.strava.com/activities/${a.id}`}
                        target="_blank"
                        rel="noreferrer"
                        className="text-gray-100 hover:text-orange-400 transition-colors"
                      >
                        {a.name || "—"}
                      </a>
                      {a.analysis_summary && (
                        <p className="text-xs text-gray-500 mt-0.5 max-w-xs truncate">{a.analysis_summary}</p>
                      )}
                      {(a.cardiac_decoupling_pct !== null || a.effort_efficiency_score !== null) && (
                        <div className="flex gap-1 mt-1 flex-wrap">
                          <DecouplingBadge val={a.cardiac_decoupling_pct} />
                          <EfficiencyBadge val={a.effort_efficiency_score} />
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-2 text-right text-gray-100">
                      {((a.distance_m || 0) / 1000).toFixed(2)}
                    </td>
                    <td className="px-4 py-2 text-right text-gray-400">
                      {formatDuration(a.moving_time_s)}
                    </td>
                    <td className="px-4 py-2 text-right text-gray-400">
                      {mode === "cycling"
                        ? formatSpeed(a.avg_pace_s_per_km)
                        : mode === "hybrid"
                        ? (a.sport_type === "Ride" || a.sport_type === "VirtualRide" || a.sport_type === "GravelRide"
                            ? formatSpeed(a.avg_pace_s_per_km)
                            : formatPace(a.avg_pace_s_per_km))
                        : formatPace(a.avg_pace_s_per_km)}
                    </td>
                    <td className="px-4 py-2 text-right text-gray-400">
                      {a.avg_hr ?? "—"}
                    </td>
                    <td className="px-4 py-2 text-right text-gray-400">
                      {a.elevation_gain_m != null ? Math.round(a.elevation_gain_m) : "—"}
                    </td>
                    <td className="px-4 py-2 text-right">
                      <button
                        onClick={() => handleDeepDive(a.id)}
                        className="px-2 py-1 rounded text-xs bg-gray-700 hover:bg-gray-600 text-gray-300 transition-colors whitespace-nowrap"
                      >
                        {a.deep_dive_report ? "View Dive" : "Deep Dive"}
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Deep Dive Modal */}
      {deepDiveId !== null && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70"
          onClick={(e) => { if (e.target === e.currentTarget) setDeepDiveId(null); }}
        >
          <div className="bg-gray-900 border border-gray-700 rounded-xl shadow-2xl w-full max-w-3xl max-h-[85vh] flex flex-col mx-4">
            {/* Modal header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800">
              <div>
                <h3 className="text-gray-100 font-semibold">Deep Dive Analysis</h3>
                {deepDiveActivity && (
                  <p className="text-xs text-gray-500 mt-0.5">{deepDiveActivity.name} · {deepDiveActivity.date}</p>
                )}
              </div>
              <div className="flex items-center gap-2">
                {!deepDiveLoading && deepDiveReport && (
                  <button
                    onClick={() => handleDeepDive(deepDiveId, true)}
                    className="px-2 py-1 rounded text-xs bg-gray-700 hover:bg-gray-600 text-gray-400 transition-colors"
                  >
                    Regenerate
                  </button>
                )}
                <button
                  onClick={() => setDeepDiveId(null)}
                  className="text-gray-500 hover:text-gray-300 transition-colors text-lg leading-none"
                >
                  ×
                </button>
              </div>
            </div>

            {/* Modal body */}
            <div className="overflow-y-auto flex-1 px-6 py-4">
              {deepDiveLoading && (
                <div className="flex items-center gap-3 text-gray-400">
                  <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                  </svg>
                  <span className="text-sm">Analyzing your run… this may take 10–20 seconds.</span>
                </div>
              )}
              {deepDiveError && (
                <p className="text-red-400 text-sm">{deepDiveError}</p>
              )}
              {deepDiveReport && !deepDiveLoading && (
                <pre className="text-gray-300 text-sm whitespace-pre-wrap font-sans leading-relaxed">
                  {deepDiveReport}
                </pre>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
