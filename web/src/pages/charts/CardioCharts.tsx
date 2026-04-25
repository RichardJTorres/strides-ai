import { useEffect, useMemo, useState } from "react";
import type { Mode, ThemeConfig } from "../../App";
import FilterBar from "../../charts/FilterBar";
import ScatterTrendCard from "../../charts/ScatterTrendCard";
import TimeSeriesLineCard from "../../charts/TimeSeriesLineCard";
import WeeklyBarCard from "../../charts/WeeklyBarCard";
import {
  filterByDate,
  getPresetRange,
  type DateRange,
  type FilterPreset,
} from "../../charts/dateFilter";
import { fmtPace } from "../../charts/tokens";

type Unit = "miles" | "km";

interface WeeklyPoint {
  week: string;
  distance: number;
  rolling_avg: number;
  is_current: boolean;
}

interface ATLCTLPoint {
  date: string;
  atl: number;
  ctl: number;
  ratio: number | null;
}

interface AerobicEffPoint {
  date: string;
  efficiency: number;
  name: string;
  hr: number;
  pace_s: number;
}

interface AerobicEffData {
  has_enough_data: boolean;
  qualifying_count: number;
  scatter: AerobicEffPoint[];
  rolling_avg: { date: string; avg: number }[];
  improving: boolean;
}

interface ChartData {
  unit: string;
  weekly_mileage: WeeklyPoint[];
  atl_ctl: ATLCTLPoint[];
  aerobic_efficiency: AerobicEffData;
}

interface Props {
  mode: Mode;
  theme: ThemeConfig;
}

// ── Custom tooltips kept here (cardio-specific) ──────────────────────────────

function ATLTooltip({
  active,
  payload,
  label,
  unit,
}: {
  active?: boolean;
  payload?: { dataKey: string; value: number }[];
  label?: string;
  unit: Unit;
}) {
  if (!active || !payload?.length) return null;
  const get = (key: string) => payload.find((p) => p.dataKey === key)?.value;
  const atl = get("atl");
  const ctl = get("ctl");
  const ratio = get("ratio");
  const ul = unit === "miles" ? "mi" : "km";

  let zone = "";
  if (ratio != null) {
    zone = ratio > 1.3 ? "⚠ Injury risk" : ratio < 0.8 ? "↓ Detraining" : "✓ Optimal";
  }

  return (
    <div className="bg-gray-800 border border-gray-700 rounded-md p-2.5 text-xs shadow-lg leading-5">
      <p className="text-gray-300 font-medium mb-1">{label}</p>
      {atl != null && (
        <p style={{ color: "#ef4444" }}>
          ATL: {atl.toFixed(2)} {ul}/day
        </p>
      )}
      {ctl != null && (
        <p style={{ color: "#60a5fa" }}>
          CTL: {ctl.toFixed(2)} {ul}/day
        </p>
      )}
      {ratio != null && (
        <p style={{ color: "#a78bfa" }}>
          Ratio: {ratio.toFixed(2)} — {zone}
        </p>
      )}
    </div>
  );
}

function AerobicEffTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: { payload: unknown }[];
}) {
  if (!active || !payload?.length) return null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const p = payload[0]?.payload as any;
  if (!p || p.date == null || p.efficiency == null) return null;
  return (
    <div className="bg-gray-800 border border-gray-700 rounded-md p-2.5 text-xs shadow-lg leading-5">
      <p className="text-gray-400">{String(p.date)}</p>
      {p.name && <p className="text-gray-100 font-medium">{String(p.name)}</p>}
      <p className="text-gray-300">
        Efficiency: <span className="text-white">{Number(p.efficiency).toFixed(2)}</span>
      </p>
      <p className="text-gray-300">
        HR: <span className="text-white">{p.hr} bpm</span>
      </p>
      <p className="text-gray-300">
        Pace:{" "}
        <span className="text-white">
          {fmtPace(Number(p.pace_s))}/{String(p.ul)}
        </span>
      </p>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function CardioCharts({ mode, theme }: Props) {
  const [unit, setUnit] = useState<Unit>(() => {
    return (localStorage.getItem("strides_unit") as Unit) || "miles";
  });
  const [data, setData] = useState<ChartData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [preset, setPreset] = useState<FilterPreset>("all-time");
  const [customSince, setCustomSince] = useState("");
  const [customUntil, setCustomUntil] = useState("");

  useEffect(() => {
    localStorage.setItem("strides_unit", unit);
    setLoading(true);
    setError(null);
    fetch(`/api/charts?unit=${unit}&mode=${mode}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((d) => {
        setData(d);
        setLoading(false);
      })
      .catch((e) => {
        setError(e.message);
        setLoading(false);
      });
  }, [unit, mode]);

  const range = useMemo((): DateRange => {
    if (preset === "custom") return { since: customSince || null, until: customUntil || null };
    return getPresetRange(preset);
  }, [preset, customSince, customUntil]);

  const filtered = useMemo(() => {
    if (!data) return null;
    const { since, until } = range;
    const isAllTime = preset === "all-time";

    const weekly = filterByDate(data.weekly_mileage, "week", since, until);
    const atlCtl = filterByDate(data.atl_ctl, "date", since, until);
    const ae = data.aerobic_efficiency;
    const aeFiltered: AerobicEffData = {
      ...ae,
      scatter: filterByDate(ae.scatter, "date", since, until),
      rolling_avg: filterByDate(ae.rolling_avg, "date", since, until),
    };

    return {
      ...data,
      weekly_mileage: isAllTime ? weekly.slice(-52) : weekly,
      atl_ctl: isAllTime ? atlCtl.slice(-365) : atlCtl,
      aerobic_efficiency: aeFiltered,
    };
  }, [data, range, preset]);

  const empty =
    filtered &&
    filtered.weekly_mileage.length === 0 &&
    filtered.atl_ctl.length === 0 &&
    filtered.aerobic_efficiency.scatter.length === 0;

  const ul = unit === "miles" ? "mi" : "km";
  const weeklyTitle =
    mode === "cycling"
      ? "Weekly Distance"
      : mode === "hybrid"
        ? "Weekly Distance (All)"
        : "Weekly Mileage";
  const activityLabel = mode === "cycling" ? "ride" : "run";
  const activityLabelPlural = mode === "cycling" ? "rides" : "runs";
  const ratioMax = filtered ? Math.max(2.5, ...filtered.atl_ctl.map((d) => d.ratio ?? 0)) : 2.5;
  const ratioMaxRounded = Math.ceil(ratioMax * 10) / 10;

  // WeeklyBarCard expects {value} not {distance}; map at render time.
  const weeklyBarData =
    filtered?.weekly_mileage.map((p) => ({
      week: p.week,
      value: p.distance,
      rolling_avg: p.rolling_avg,
      is_current: p.is_current,
    })) ?? [];

  return (
    <div className="h-full overflow-y-auto">
      <div className="p-6 space-y-5 max-w-5xl mx-auto">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-bold text-gray-100">Training Charts</h2>
          <div className="flex rounded-md overflow-hidden border border-gray-700 text-sm">
            {(["miles", "km"] as Unit[]).map((u) => (
              <button
                key={u}
                onClick={() => setUnit(u)}
                className={`px-4 py-1.5 transition-colors ${
                  unit === u
                    ? `${theme.accentBg} ${theme.accentClass} font-medium`
                    : "text-gray-400 hover:bg-gray-800"
                }`}
              >
                {u === "miles" ? "Miles" : "km"}
              </button>
            ))}
          </div>
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
          <div className="text-center py-16 text-gray-500">No activities in this date range.</div>
        )}

        {filtered && !loading && !empty && (
          <>
            <WeeklyBarCard
              title={weeklyTitle}
              data={weeklyBarData}
              unitLabel={ul}
              valueLabel="Distance"
            />
            <TimeSeriesLineCard
              title="Training Load — ATL / CTL"
              subtitle={
                <>
                  ATL = 7-day EWA · CTL = 42-day EWA · Ratio zones:{" "}
                  <span className="text-green-400">optimal 0.8–1.3</span>
                  {" · "}
                  <span className="text-red-400">injury risk &gt;1.3</span>
                  {" · "}
                  <span className="text-gray-400">detraining &lt;0.8</span>
                </>
              }
              data={filtered.atl_ctl as unknown as Record<string, unknown>[]}
              xKey="date"
              series={[
                { key: "atl", label: "ATL (7d)", color: "#ef4444", yAxisId: "load" },
                { key: "ctl", label: "CTL (42d)", color: "#60a5fa", yAxisId: "load" },
                {
                  key: "ratio",
                  label: "ATL/CTL",
                  color: "#a78bfa",
                  yAxisId: "ratio",
                  dashed: true,
                },
              ]}
              yAxes={[
                {
                  id: "load",
                  tickFormatter: (v) => v.toFixed(1),
                  label: `${ul}/d`,
                },
                {
                  id: "ratio",
                  orientation: "right",
                  domain: [0, ratioMaxRounded],
                  width: 36,
                  label: "ratio",
                },
              ]}
              referenceAreas={[
                { yAxisId: "ratio", y1: 0.8, y2: 1.3, fill: "#22c55e" },
                { yAxisId: "ratio", y1: 1.3, y2: ratioMaxRounded, fill: "#ef4444" },
                { yAxisId: "ratio", y1: 0, y2: 0.8, fill: "#6b7280" },
              ]}
              customTooltip={<ATLTooltip unit={unit} />}
              height={300}
              rightMargin={52}
            />

            {/* Aerobic efficiency: show empty / not-enough-data states */}
            {!filtered.aerobic_efficiency.has_enough_data ? (
              <section className="bg-gray-900 rounded-lg border border-gray-800 p-5">
                <h3 className="text-gray-100 font-semibold mb-3">Aerobic Efficiency</h3>
                <div className="flex gap-4 items-start py-6 px-4">
                  <span className="text-3xl">🫀</span>
                  <div>
                    <p className="text-gray-300 text-sm font-medium mb-1">
                      {10 - filtered.aerobic_efficiency.qualifying_count} more qualifying{" "}
                      {10 - filtered.aerobic_efficiency.qualifying_count === 1
                        ? activityLabel
                        : activityLabelPlural}{" "}
                      needed
                    </p>
                    <p className="text-gray-500 text-xs leading-relaxed max-w-lg">
                      Aerobic efficiency tracks your speed relative to heart rate — higher means
                      you&apos;re covering more ground per heartbeat, a reliable signal of improving
                      fitness. It will appear once you have 10 {activityLabelPlural} logged with
                      average HR between 120–155 bpm (easy to moderate effort, excluding warm-ups,
                      races, and sensor dropouts).
                    </p>
                    {filtered.aerobic_efficiency.qualifying_count > 0 && (
                      <p className="text-green-500/80 text-xs mt-2">
                        {filtered.aerobic_efficiency.qualifying_count} qualifying{" "}
                        {filtered.aerobic_efficiency.qualifying_count === 1
                          ? activityLabel
                          : activityLabelPlural}{" "}
                        recorded so far.
                      </p>
                    )}
                  </div>
                </div>
              </section>
            ) : filtered.aerobic_efficiency.scatter.length < 3 ? (
              <section className="bg-gray-900 rounded-lg border border-gray-800 p-5">
                <h3 className="text-gray-100 font-semibold mb-1">Aerobic Efficiency</h3>
                <p className="text-gray-500 text-sm text-center py-10">
                  No qualifying {activityLabelPlural} (120–155 bpm) in this date range.
                </p>
              </section>
            ) : (
              <ScatterTrendCard
                title="Aerobic Efficiency"
                subtitle="Speed / HR for moderate efforts (120–155 bpm) · 4-week rolling average · higher = fitter"
                badge={
                  filtered.aerobic_efficiency.improving && (
                    <span className="text-green-400 text-xs bg-green-500/10 border border-green-500/20 rounded-full px-2 py-0.5">
                      ↑ Improving
                    </span>
                  )
                }
                scatter={filtered.aerobic_efficiency.scatter.map((p) => ({
                  date: p.date,
                  value: p.efficiency,
                  efficiency: p.efficiency,
                  name: p.name,
                  hr: p.hr,
                  pace_s: p.pace_s,
                  ul,
                }))}
                rollingAvg={filtered.aerobic_efficiency.rolling_avg}
                scatterLabel={`Easy ${activityLabelPlural} (120–155 bpm)`}
                customTooltip={<AerobicEffTooltip />}
                showImproving={filtered.aerobic_efficiency.improving}
                yLabel="Efficiency"
              />
            )}
          </>
        )}
      </div>
    </div>
  );
}
