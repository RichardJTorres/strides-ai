import { useEffect, useMemo, useState } from "react";
import type { ThemeConfig } from "../../App";
import FilterBar from "../../charts/FilterBar";
import StackedBarCard, { type StackedCategory } from "../../charts/StackedBarCard";
import TimeSeriesLineCard, { type SeriesSpec } from "../../charts/TimeSeriesLineCard";
import WeeklyBarCard, { type WeeklyBarPoint } from "../../charts/WeeklyBarCard";
import {
  filterByDate,
  getPresetRange,
  type DateRange,
  type FilterPreset,
} from "../../charts/dateFilter";
import { SERIES_PALETTE } from "../../charts/tokens";

interface OneRMPoint {
  date: string;
  one_rm_kg: number;
}

interface OneRMData {
  series: Record<string, OneRMPoint[]>;
  exercises: string[];
}

interface MuscleWeek {
  week: string;
  is_current: boolean;
  [muscle: string]: number | string | boolean;
}

interface MuscleGroupData {
  weeks: MuscleWeek[];
  categories: string[];
}

interface RPEPoint {
  date: string;
  rpe: number;
  rolling_avg: number;
}

interface LiftingChartData {
  weekly_volume: WeeklyBarPoint[];
  weekly_sessions: WeeklyBarPoint[];
  one_rm_progression: OneRMData;
  muscle_group_sets: MuscleGroupData;
  rpe_trend: RPEPoint[];
}

interface Props {
  theme: ThemeConfig;
}

// Build a single time-series row per date by merging all exercises' 1RM points.
// Recharts wants `[{date, "Bench": 100, "Squat": 150, ...}, ...]`, sparse keys ok.
function pivotOneRm(series: Record<string, OneRMPoint[]>): Record<string, unknown>[] {
  const byDate = new Map<string, Record<string, unknown>>();
  for (const [exercise, points] of Object.entries(series)) {
    for (const p of points) {
      const row = byDate.get(p.date) ?? { date: p.date };
      row[exercise] = p.one_rm_kg;
      byDate.set(p.date, row);
    }
  }
  return Array.from(byDate.values()).sort((a, b) =>
    String(a.date).localeCompare(String(b.date)),
  );
}

export default function LiftingCharts({ theme }: Props) {
  const [data, setData] = useState<LiftingChartData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [preset, setPreset] = useState<FilterPreset>("all-time");
  const [customSince, setCustomSince] = useState("");
  const [customUntil, setCustomUntil] = useState("");

  useEffect(() => {
    setLoading(true);
    setError(null);
    fetch("/api/charts?mode=lifting")
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((d: LiftingChartData) => {
        setData(d);
        setLoading(false);
      })
      .catch((e) => {
        setError(e.message);
        setLoading(false);
      });
  }, []);

  const range = useMemo((): DateRange => {
    if (preset === "custom") return { since: customSince || null, until: customUntil || null };
    return getPresetRange(preset);
  }, [preset, customSince, customUntil]);

  const filtered = useMemo(() => {
    if (!data) return null;
    const { since, until } = range;
    const isAllTime = preset === "all-time";

    const weeklyVol = filterByDate(data.weekly_volume, "week", since, until);
    const weeklySess = filterByDate(data.weekly_sessions, "week", since, until);
    const muscleWeeks = filterByDate(data.muscle_group_sets.weeks, "week", since, until);
    const rpeTrend = filterByDate(data.rpe_trend, "date", since, until);

    // Filter each 1RM exercise's series, then drop exercises with no points.
    const oneRmFiltered: Record<string, OneRMPoint[]> = {};
    for (const [ex, pts] of Object.entries(data.one_rm_progression.series)) {
      const f = filterByDate(pts, "date", since, until);
      if (f.length > 0) oneRmFiltered[ex] = f;
    }

    return {
      weekly_volume: isAllTime ? weeklyVol.slice(-52) : weeklyVol,
      weekly_sessions: isAllTime ? weeklySess.slice(-52) : weeklySess,
      muscle_group_sets: {
        weeks: isAllTime ? muscleWeeks.slice(-52) : muscleWeeks,
        categories: data.muscle_group_sets.categories,
      },
      one_rm_progression: {
        series: oneRmFiltered,
        exercises: Object.keys(oneRmFiltered),
      },
      rpe_trend: rpeTrend,
    };
  }, [data, range, preset]);

  const empty =
    filtered &&
    filtered.weekly_volume.length === 0 &&
    filtered.weekly_sessions.length === 0 &&
    filtered.rpe_trend.length === 0 &&
    filtered.one_rm_progression.exercises.length === 0;

  const oneRmRows = useMemo(
    () => (filtered ? pivotOneRm(filtered.one_rm_progression.series) : []),
    [filtered],
  );
  const oneRmSeries: SeriesSpec[] = (filtered?.one_rm_progression.exercises ?? []).map(
    (ex, i) => ({
      key: ex,
      label: ex,
      color: SERIES_PALETTE[i % SERIES_PALETTE.length],
      strokeWidth: 1.75,
      connectNulls: true,
    }),
  );

  const muscleCategories: StackedCategory[] = (filtered?.muscle_group_sets.categories ?? []).map(
    (m, i) => ({
      key: m,
      label: m,
      color: SERIES_PALETTE[i % SERIES_PALETTE.length],
    }),
  );

  return (
    <div className="h-full overflow-y-auto">
      <div className="p-6 space-y-5 max-w-5xl mx-auto">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-bold text-gray-100">Training Charts</h2>
        </div>

        <FilterBar
          preset={preset}
          customSince={customSince}
          customUntil={customUntil}
          onPreset={setPreset}
          onCustomSince={setCustomSince}
          onCustomUntil={setCustomUntil}
          theme={theme}
        />

        {loading && (
          <div className="flex items-center justify-center py-24 text-gray-500">
            <span className="animate-pulse">Loading chart data…</span>
          </div>
        )}

        {error && (
          <div className="bg-red-950 border border-red-800 text-red-300 rounded-lg p-4 text-sm">
            Failed to load charts: {error}
          </div>
        )}

        {empty && (
          <div className="text-center py-16 text-gray-500">
            No lifting sessions in this date range. Sync HEVY from the Settings tab.
          </div>
        )}

        {filtered && !loading && !empty && (
          <>
            <WeeklyBarCard
              title="Weekly Training Volume"
              data={filtered.weekly_volume}
              unitLabel="kg"
              valueLabel="Volume"
              formatValue={(n) => `${n.toLocaleString(undefined, { maximumFractionDigits: 0 })} kg`}
            />

            {filtered.one_rm_progression.exercises.length > 0 ? (
              <TimeSeriesLineCard
                title="Estimated 1RM Progression"
                subtitle={`Daily best Epley estimate per lift · top ${filtered.one_rm_progression.exercises.length} most-trained exercises`}
                data={oneRmRows}
                xKey="date"
                series={oneRmSeries}
                yAxes={[
                  {
                    id: "y",
                    tickFormatter: (v) => `${v}kg`,
                    label: "kg",
                  },
                ]}
              />
            ) : (
              <section className="bg-gray-900 rounded-lg border border-gray-800 p-5">
                <h3 className="text-gray-100 font-semibold mb-1">Estimated 1RM Progression</h3>
                <p className="text-gray-500 text-sm text-center py-10">
                  No qualifying sets (≤12 reps) in this date range.
                </p>
              </section>
            )}

            {filtered.muscle_group_sets.categories.length > 0 ? (
              <StackedBarCard
                title="Working Sets by Muscle Group"
                subtitle="Per-week working-set count, stacked by primary muscle group · warm-ups excluded"
                data={filtered.muscle_group_sets.weeks as unknown as Record<string, unknown>[]}
                xKey="week"
                categories={muscleCategories}
                yLabel="sets"
              />
            ) : null}

            <WeeklyBarCard
              title="Weekly Sessions"
              subtitle="Sessions per week · 4-week rolling average · ■ current week"
              data={filtered.weekly_sessions}
              unitLabel=""
              valueLabel="Sessions"
              formatValue={(n) => `${n}`}
              barColor="#a78bfa"
            />

            {filtered.rpe_trend.length > 0 ? (
              <TimeSeriesLineCard
                title="Session Intensity (RPE)"
                subtitle="Per-session average RPE · 4-session rolling average · watch for sustained drift toward 9+"
                data={filtered.rpe_trend as unknown as Record<string, unknown>[]}
                xKey="date"
                series={[
                  { key: "rpe", label: "Session RPE", color: "#22d3ee" },
                  {
                    key: "rolling_avg",
                    label: "4-session avg",
                    color: "#fb923c",
                    dashed: true,
                  },
                ]}
                yAxes={[{ id: "y", domain: [5, 10] as [number, number], tickFormatter: (v) => v.toFixed(1) }]}
              />
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}
