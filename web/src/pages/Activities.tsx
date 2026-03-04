import { useEffect, useState } from "react";

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
}

function formatPace(s: number | null): string {
  if (!s) return "—";
  const mins = Math.floor(s / 60);
  const secs = Math.floor(s % 60);
  return `${mins}:${String(secs).padStart(2, "0")}/km`;
}

function formatDuration(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h) return `${h}h${String(m).padStart(2, "0")}m`;
  return `${m}m${String(sec).padStart(2, "0")}s`;
}

export default function Activities() {
  const [activities, setActivities] = useState<Activity[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState("");

  useEffect(() => {
    fetch("/api/activities")
      .then((r) => r.json())
      .then(setActivities)
      .finally(() => setLoading(false));
  }, []);

  async function handleSync() {
    setSyncing(true);
    setSyncMsg("");
    try {
      const res = await fetch("/api/sync", { method: "POST" });
      const data = await res.json();
      setSyncMsg(
        data.new_activities > 0
          ? `${data.new_activities} new run(s) synced.`
          : "Already up to date."
      );
      // Reload list
      const rows = await fetch("/api/activities").then((r) => r.json());
      setActivities(rows);
    } catch {
      setSyncMsg("Sync failed.");
    } finally {
      setSyncing(false);
    }
  }

  return (
    <div className="flex flex-col h-full p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-gray-100">
          Activities{" "}
          <span className="text-sm font-normal text-gray-400">
            ({activities.length})
          </span>
        </h2>
        <div className="flex items-center gap-3">
          {syncMsg && <span className="text-sm text-green-400">{syncMsg}</span>}
          <button
            onClick={handleSync}
            disabled={syncing}
            className="px-3 py-1.5 rounded-md bg-green-600 hover:bg-green-500 text-white text-sm disabled:opacity-50 transition-colors"
          >
            {syncing ? "Syncing…" : "Sync Strava"}
          </button>
        </div>
      </div>

      {loading ? (
        <p className="text-gray-500 text-sm">Loading…</p>
      ) : (
        <div className="overflow-auto flex-1 rounded-lg border border-gray-800">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-900 text-gray-400 text-left">
                <th className="px-4 py-2 font-medium">Date</th>
                <th className="px-4 py-2 font-medium">Name</th>
                <th className="px-4 py-2 font-medium text-right">Dist (km)</th>
                <th className="px-4 py-2 font-medium text-right">Time</th>
                <th className="px-4 py-2 font-medium text-right">Pace</th>
                <th className="px-4 py-2 font-medium text-right">Avg HR</th>
                <th className="px-4 py-2 font-medium text-right">Elev (m)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {activities.map((a) => (
                <tr
                  key={a.id}
                  className="hover:bg-gray-800/50 transition-colors"
                >
                  <td className="px-4 py-2 text-gray-400">{a.date}</td>
                  <td className="px-4 py-2 text-gray-100">{a.name || "—"}</td>
                  <td className="px-4 py-2 text-right text-gray-100">
                    {((a.distance_m || 0) / 1000).toFixed(2)}
                  </td>
                  <td className="px-4 py-2 text-right text-gray-400">
                    {formatDuration(a.moving_time_s)}
                  </td>
                  <td className="px-4 py-2 text-right text-gray-400">
                    {formatPace(a.avg_pace_s_per_km)}
                  </td>
                  <td className="px-4 py-2 text-right text-gray-400">
                    {a.avg_hr ?? "—"}
                  </td>
                  <td className="px-4 py-2 text-right text-gray-400">
                    {a.elevation_gain_m != null
                      ? Math.round(a.elevation_gain_m)
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
