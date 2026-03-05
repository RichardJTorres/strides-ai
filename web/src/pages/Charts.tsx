import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  ReferenceArea,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

// ── Types ─────────────────────────────────────────────────────────────────────

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

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtPace(s: number) {
  return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
}

function fmtWeekDate(str: string) {
  return new Date(str + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function fmtTs(ts: number) {
  return new Date(ts).toLocaleDateString("en-US", { month: "short", year: "2-digit" });
}

// Dark-theme recharts style props (reused across charts)
const GRID_COLOR = "#374151";
const TICK_STYLE = { fill: "#9ca3af", fontSize: 11 };
const AXIS_LINE = { stroke: "#4b5563" };
const TOOLTIP_STYLE = {
  backgroundColor: "#1f2937",
  border: "1px solid #374151",
  borderRadius: "6px",
  color: "#f3f4f6",
  fontSize: 12,
};
const LEGEND_STYLE = { color: "#9ca3af", fontSize: 12 };

// ── Date filter ───────────────────────────────────────────────────────────────

type FilterPreset = "this-month" | "last-month" | "ytd" | "last-3m" | "last-6m" | "last-year" | "all-time" | "custom";

interface DateRange {
  since: string | null; // YYYY-MM-DD
  until: string | null;
}

const PRESETS: { id: FilterPreset; label: string }[] = [
  { id: "this-month", label: "This Month" },
  { id: "last-month", label: "Last Month" },
  { id: "ytd", label: "Year to Date" },
  { id: "last-3m", label: "Last 3M" },
  { id: "last-6m", label: "Last 6M" },
  { id: "last-year", label: "Last Year" },
  { id: "all-time", label: "All Time" },
  { id: "custom", label: "Custom" },
];

function getPresetRange(preset: FilterPreset): DateRange {
  if (preset === "all-time" || preset === "custom") return { since: null, until: null };
  const today = new Date();
  const y = today.getFullYear();
  const m = today.getMonth();
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  switch (preset) {
    case "this-month":  return { since: iso(new Date(y, m, 1)), until: null };
    case "last-month":  return { since: iso(new Date(y, m - 1, 1)), until: iso(new Date(y, m, 0)) };
    case "ytd":         return { since: `${y}-01-01`, until: null };
    case "last-3m": { const d = new Date(today); d.setMonth(m - 3); return { since: iso(d), until: null }; }
    case "last-6m": { const d = new Date(today); d.setMonth(m - 6); return { since: iso(d), until: null }; }
    case "last-year": { const d = new Date(today); d.setFullYear(y - 1); return { since: iso(d), until: null }; }
  }
}

function filterByDate<T>(items: T[], key: keyof T, since: string | null, until: string | null): T[] {
  if (!since && !until) return items;
  return items.filter((item) => {
    const d = String(item[key] ?? "");
    if (since && d < since) return false;
    if (until && d > until) return false;
    return true;
  });
}

// ── Weekly Mileage ────────────────────────────────────────────────────────────

function WeeklyMileageChart({ data, unit }: { data: WeeklyPoint[]; unit: Unit }) {
  const ul = unit === "miles" ? "mi" : "km";

  return (
    <section className="bg-gray-900 rounded-lg border border-gray-800 p-5">
      <h3 className="text-gray-100 font-semibold mb-0.5">Weekly Mileage</h3>
      <p className="text-gray-500 text-xs mb-4">
        Per-week totals · 4-week rolling average ·{" "}
        <span className="text-green-400">■</span> current week
      </p>
      <ResponsiveContainer width="100%" height={260}>
        <ComposedChart data={data} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID_COLOR} vertical={false} />
          <XAxis
            dataKey="week"
            tickFormatter={fmtWeekDate}
            tick={TICK_STYLE}
            axisLine={AXIS_LINE}
            tickLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            tick={TICK_STYLE}
            axisLine={AXIS_LINE}
            tickLine={false}
            width={36}
            tickFormatter={(v) => `${v}${ul}`}
          />
          <Tooltip
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            formatter={((val: any, name: any) => [`${Number(val).toFixed(1)} ${ul}`, name]) as any}
            labelFormatter={(label: unknown) => fmtWeekDate(String(label))}
            contentStyle={TOOLTIP_STYLE}
            cursor={{ fill: "#374151", opacity: 0.4 }}
          />
          <Legend wrapperStyle={LEGEND_STYLE} />
          <Bar dataKey="distance" name="Distance" maxBarSize={18} radius={[2, 2, 0, 0]}>
            {data.map((entry, i) => (
              <Cell key={i} fill={entry.is_current ? "#4ade80" : "#22d3ee"} opacity={0.85} />
            ))}
          </Bar>
          <Line
            dataKey="rolling_avg"
            name="4-week avg"
            stroke="#fb923c"
            strokeWidth={2}
            dot={false}
            strokeDasharray="5 3"
          />
        </ComposedChart>
      </ResponsiveContainer>
    </section>
  );
}

// ── ATL / CTL ─────────────────────────────────────────────────────────────────

function ATLTooltip({ active, payload, label, unit }: {
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
      {atl != null && <p style={{ color: "#ef4444" }}>ATL: {atl.toFixed(2)} {ul}/day</p>}
      {ctl != null && <p style={{ color: "#60a5fa" }}>CTL: {ctl.toFixed(2)} {ul}/day</p>}
      {ratio != null && (
        <p style={{ color: "#a78bfa" }}>
          Ratio: {ratio.toFixed(2)} — {zone}
        </p>
      )}
    </div>
  );
}

function ATLCTLChart({ data, unit }: { data: ATLCTLPoint[]; unit: Unit }) {
  const ul = unit === "miles" ? "mi" : "km";
  const ratioMax = Math.max(2.5, ...data.map((d) => d.ratio ?? 0));

  return (
    <section className="bg-gray-900 rounded-lg border border-gray-800 p-5">
      <h3 className="text-gray-100 font-semibold mb-0.5">Training Load — ATL / CTL</h3>
      <p className="text-gray-500 text-xs mb-4">
        ATL = 7-day EWA · CTL = 42-day EWA · Ratio zones:{" "}
        <span className="text-green-400">optimal 0.8–1.3</span>
        {" · "}
        <span className="text-red-400">injury risk &gt;1.3</span>
        {" · "}
        <span className="text-gray-400">detraining &lt;0.8</span>
      </p>
      <ResponsiveContainer width="100%" height={300}>
        <ComposedChart data={data} margin={{ top: 4, right: 52, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID_COLOR} vertical={false} />
          <XAxis
            dataKey="date"
            tickFormatter={fmtWeekDate}
            tick={TICK_STYLE}
            axisLine={AXIS_LINE}
            tickLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            yAxisId="load"
            tick={TICK_STYLE}
            axisLine={AXIS_LINE}
            tickLine={false}
            width={40}
            tickFormatter={(v) => `${v.toFixed(1)}`}
            label={{ value: `${ul}/d`, angle: -90, position: "insideLeft", fill: "#6b7280", fontSize: 10, dx: 10 }}
          />
          <YAxis
            yAxisId="ratio"
            orientation="right"
            domain={[0, Math.ceil(ratioMax * 10) / 10]}
            tick={TICK_STYLE}
            axisLine={AXIS_LINE}
            tickLine={false}
            width={36}
            label={{ value: "ratio", angle: 90, position: "insideRight", fill: "#6b7280", fontSize: 10, dx: -4 }}
          />

          {/* Zone shading on ratio axis */}
          <ReferenceArea yAxisId="ratio" y1={0.8} y2={1.3} fill="#22c55e" fillOpacity={0.07} />
          <ReferenceArea yAxisId="ratio" y1={1.3} y2={Math.ceil(ratioMax * 10) / 10} fill="#ef4444" fillOpacity={0.07} />
          <ReferenceArea yAxisId="ratio" y1={0} y2={0.8} fill="#6b7280" fillOpacity={0.07} />

          <Tooltip content={<ATLTooltip unit={unit} />} />
          <Legend wrapperStyle={LEGEND_STYLE} />

          <Line yAxisId="load" dataKey="atl" name="ATL (7d)" stroke="#ef4444" strokeWidth={1.5} dot={false} />
          <Line yAxisId="load" dataKey="ctl" name="CTL (42d)" stroke="#60a5fa" strokeWidth={1.5} dot={false} />
          <Line
            yAxisId="ratio"
            dataKey="ratio"
            name="ATL/CTL"
            stroke="#a78bfa"
            strokeWidth={1.5}
            dot={false}
            strokeDasharray="5 3"
            connectNulls={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </section>
  );
}

// ── Aerobic Efficiency ────────────────────────────────────────────────────────

function AerobicEffTooltip({ active, payload }: { active?: boolean; payload?: { payload: unknown }[] }) {
  if (!active || !payload?.length) return null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const p = payload[0]?.payload as any;
  // Rolling-avg points have no run-level fields — skip them
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
        Pace: <span className="text-white">{fmtPace(Number(p.pace_s))}/{String(p.ul)}</span>
      </p>
    </div>
  );
}

// Custom shape that renders the "↑ improving" annotation at the last rolling-avg point
function ImprovingLabel(props: Record<string, unknown>) {
  const cx = Number(props.cx ?? 0);
  const cy = Number(props.cy ?? 0);
  return (
    <text x={cx + 8} y={cy - 5} fill="#4ade80" fontSize={10} fontStyle="italic" fontFamily="inherit">
      ↑ improving
    </text>
  );
}

function AerobicEfficiencyChart({ data, unit }: { data: AerobicEffData; unit: Unit }) {
  const ul = unit === "miles" ? "mi" : "km";
  const { has_enough_data, qualifying_count, scatter, rolling_avg, improving } = data;

  // Convert to {x: timestamp, y: value, ...} for ScatterChart
  const scatterXY = useMemo(
    () => scatter.map((p) => ({ x: new Date(p.date + "T00:00:00").getTime(), y: p.efficiency, ul, ...p })),
    [scatter, ul],
  );
  const rollingXY = useMemo(
    () => rolling_avg.map((r) => ({ x: new Date(r.date + "T00:00:00").getTime(), y: r.avg })),
    [rolling_avg],
  );
  const lastRollingPoint = useMemo(
    () => (rollingXY.length > 0 ? [rollingXY[rollingXY.length - 1]] : []),
    [rollingXY],
  );

  const allY = scatterXY.map((p) => p.y);
  const minY = allY.length ? Math.min(...allY) : 0;
  const maxY = allY.length ? Math.max(...allY) : 1;
  const pad = (maxY - minY) * 0.12 || 0.2;

  // Not enough qualifying runs overall
  if (!has_enough_data) {
    const needed = 10 - qualifying_count;
    return (
      <section className="bg-gray-900 rounded-lg border border-gray-800 p-5">
        <h3 className="text-gray-100 font-semibold mb-3">Aerobic Efficiency</h3>
        <div className="flex gap-4 items-start py-6 px-4">
          <span className="text-3xl">🫀</span>
          <div>
            <p className="text-gray-300 text-sm font-medium mb-1">
              {needed} more qualifying {needed === 1 ? "run" : "runs"} needed
            </p>
            <p className="text-gray-500 text-xs leading-relaxed max-w-lg">
              Aerobic efficiency tracks your running speed relative to heart rate — higher means
              you&apos;re covering more ground per heartbeat, a reliable signal of improving fitness.
              It will appear once you have 10 runs logged with average HR between 120–155 bpm
              (easy to moderate effort, excluding warm-ups, races, and sensor dropouts).
            </p>
            {qualifying_count > 0 && (
              <p className="text-green-500/80 text-xs mt-2">
                {qualifying_count} qualifying {qualifying_count === 1 ? "run" : "runs"} recorded so far.
              </p>
            )}
          </div>
        </div>
      </section>
    );
  }

  // Enough data overall but nothing visible in the current filter window
  if (scatterXY.length < 3) {
    return (
      <section className="bg-gray-900 rounded-lg border border-gray-800 p-5">
        <h3 className="text-gray-100 font-semibold mb-1">Aerobic Efficiency</h3>
        <p className="text-gray-500 text-sm text-center py-10">
          No qualifying runs (120–155 bpm) in this date range.
        </p>
      </section>
    );
  }

  return (
    <section className="bg-gray-900 rounded-lg border border-gray-800 p-5">
      <div className="flex items-center gap-2 mb-0.5">
        <h3 className="text-gray-100 font-semibold">Aerobic Efficiency</h3>
        {improving && (
          <span className="text-green-400 text-xs bg-green-500/10 border border-green-500/20 rounded-full px-2 py-0.5">
            ↑ Improving
          </span>
        )}
      </div>
      <p className="text-gray-500 text-xs mb-4">
        Speed / HR for easy efforts (120–155 bpm) · 4-week rolling average · higher = fitter
      </p>
      <ResponsiveContainer width="100%" height={280}>
        <ScatterChart margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID_COLOR} />
          <XAxis
            type="number"
            dataKey="x"
            scale="time"
            domain={["dataMin", "dataMax"]}
            tickFormatter={fmtTs}
            tick={TICK_STYLE}
            axisLine={AXIS_LINE}
            tickLine={false}
            name="Date"
          />
          <YAxis
            type="number"
            dataKey="y"
            domain={[minY - pad, maxY + pad]}
            tickFormatter={(v: number) => v.toFixed(2)}
            tick={TICK_STYLE}
            axisLine={AXIS_LINE}
            tickLine={false}
            width={44}
            name="Efficiency"
            label={{ value: "Efficiency", angle: -90, position: "insideLeft", fill: "#6b7280", fontSize: 10, dx: 14 }}
          />
          <Tooltip
            content={<AerobicEffTooltip />}
            cursor={{ strokeDasharray: "3 3", stroke: "#4b5563" }}
          />
          <Legend wrapperStyle={LEGEND_STYLE} />

          {/* Individual run dots */}
          <Scatter name={`Easy runs (120–155 bpm)`} data={scatterXY} fill="#22d3ee" opacity={0.65} />

          {/* 4-week rolling average line */}
          <Scatter
            data={rollingXY}
            line={{ stroke: "#4ade80", strokeWidth: 2.5 }}
            shape={() => null}
            legendType="none"
            name="rolling-avg"
          />

          {/* "↑ improving" label anchored to the last rolling-avg point */}
          {improving && lastRollingPoint.length > 0 && (
            <Scatter
              data={lastRollingPoint}
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              shape={(props: any) => <ImprovingLabel {...props} />}
              legendType="none"
              name="improving-label"
            />
          )}
        </ScatterChart>
      </ResponsiveContainer>
    </section>
  );
}

// ── Filter bar ────────────────────────────────────────────────────────────────

function FilterBar({
  preset,
  customSince,
  customUntil,
  onPreset,
  onCustomSince,
  onCustomUntil,
}: {
  preset: FilterPreset;
  customSince: string;
  customUntil: string;
  onPreset: (p: FilterPreset) => void;
  onCustomSince: (v: string) => void;
  onCustomUntil: (v: string) => void;
}) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-3 flex flex-wrap items-center gap-1.5">
      {PRESETS.map(({ id, label }) => (
        <button
          key={id}
          onClick={() => onPreset(id)}
          className={`px-3 py-1 text-xs rounded-md border transition-colors ${
            preset === id
              ? "bg-green-500/20 text-green-400 border-green-500/30 font-medium"
              : "text-gray-400 border-gray-700 hover:bg-gray-800 hover:text-gray-200"
          }`}
        >
          {label}
        </button>
      ))}
      {preset === "custom" && (
        <div className="flex items-center gap-2 ml-1">
          <input
            type="date"
            value={customSince}
            onChange={(e) => onCustomSince(e.target.value)}
            className="bg-gray-800 text-gray-200 border border-gray-600 rounded px-2 py-0.5 text-xs focus:outline-none focus:border-green-500"
            style={{ colorScheme: "dark" }}
          />
          <span className="text-gray-500 text-xs">→</span>
          <input
            type="date"
            value={customUntil}
            onChange={(e) => onCustomUntil(e.target.value)}
            className="bg-gray-800 text-gray-200 border border-gray-600 rounded px-2 py-0.5 text-xs focus:outline-none focus:border-green-500"
            style={{ colorScheme: "dark" }}
          />
        </div>
      )}
    </div>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────

export default function Charts() {
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
    fetch(`/api/charts?unit=${unit}`)
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
  }, [unit]);

  // Resolve the active date range
  const range = useMemo((): DateRange => {
    if (preset === "custom") return { since: customSince || null, until: customUntil || null };
    return getPresetRange(preset);
  }, [preset, customSince, customUntil]);

  // Apply filter and recompute trends
  const filtered = useMemo(() => {
    if (!data) return null;
    const { since, until } = range;
    const isAllTime = preset === "all-time";

    const weekly = filterByDate(data.weekly_mileage, "week", since, until);
    const atlCtl = filterByDate(data.atl_ctl, "date", since, until);
    const ae = data.aerobic_efficiency;
    const aeFiltered: AerobicEffData = {
      ...ae,
      scatter:     filterByDate(ae.scatter,     "date", since, until),
      rolling_avg: filterByDate(ae.rolling_avg, "date", since, until),
      // improving always reflects the real last-4-weeks vs previous-4-weeks
    };

    return {
      ...data,
      weekly_mileage:     isAllTime ? weekly.slice(-52)  : weekly,
      atl_ctl:            isAllTime ? atlCtl.slice(-365) : atlCtl,
      aerobic_efficiency: aeFiltered,
    };
  }, [data, range, preset]);

  const empty = filtered && filtered.weekly_mileage.length === 0 && filtered.atl_ctl.length === 0 && filtered.aerobic_efficiency.scatter.length === 0;

  return (
    <div className="h-full overflow-y-auto">
      <div className="p-6 space-y-5 max-w-5xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-bold text-gray-100">Training Charts</h2>
          <div className="flex rounded-md overflow-hidden border border-gray-700 text-sm">
            {(["miles", "km"] as Unit[]).map((u) => (
              <button
                key={u}
                onClick={() => setUnit(u)}
                className={`px-4 py-1.5 transition-colors ${
                  unit === u
                    ? "bg-green-500/20 text-green-400 font-medium"
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
            No activities in this date range.
          </div>
        )}

        {filtered && !loading && !empty && (
          <>
            <WeeklyMileageChart data={filtered.weekly_mileage} unit={unit} />
            <ATLCTLChart data={filtered.atl_ctl} unit={unit} />
            <AerobicEfficiencyChart data={filtered.aerobic_efficiency} unit={unit} />
          </>
        )}
      </div>
    </div>
  );
}
