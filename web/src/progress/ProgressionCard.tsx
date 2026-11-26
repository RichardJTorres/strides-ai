import { useRef, useState, type ReactNode } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AXIS_LINE, GRID_COLOR, TICK_STYLE, TOOLTIP_STYLE } from "../charts/tokens";
import { hrefFor, navigate } from "../nav";
import { PENDING_CHAT_DRAFT_KEY } from "../pages/chatActivityHandoff";
import { useUnits } from "../UnitsContext";
import { convert, unitLabel, type Quantity } from "../units";
import Button from "../ui/Button";
import { formatDate } from "../ui/format";
import { useApi } from "../ui/api";
import { ErrorState, LoadingState } from "../ui/states";
import { useTheme } from "../ui/theme";
import { chartRows, coachDraft, type PeakMetric, type Progression, type ProgressionChartRow } from "./progression";

const BAR = "#22d3ee"; // the app's default bar colour (WeeklyBarCard)
const CURRENT_BAR = "#4ade80"; // in-progress period, as on the weekly charts
const SPORT_LABEL = { run: "Running", ride: "Cycling" } as const;
const SPANS = [
  { months: 24, label: "2 years" },
  { months: 60, label: "5 years" },
];
const PEAKS: { id: PeakMetric; label: string; qty: Quantity }[] = [
  { id: "longest", label: "Longest", qty: "distance" },
  { id: "most_climb", label: "Most climbing", qty: "elevation" },
];

function Toggle<T extends string | number>({
  options,
  value,
  onChange,
  label,
}: {
  options: { id: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
  label: string;
}) {
  const theme = useTheme();
  return (
    <div role="group" aria-label={label} className="flex gap-1">
      {options.map((o) => (
        <button
          key={String(o.id)}
          type="button"
          aria-pressed={value === o.id}
          onClick={() => onChange(o.id)}
          className={`px-2.5 py-0.5 text-xs rounded-md border transition-colors ${
            value === o.id
              ? `${theme.accentBg} ${theme.accentClass} ${theme.accentBorder} font-medium`
              : "text-gray-400 border-gray-700 hover:bg-gray-800 hover:text-gray-200"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

interface TipProps {
  active?: boolean;
  payload?: { payload: ProgressionChartRow }[];
  render: (row: ProgressionChartRow) => ReactNode;
}

function Tip({ active, payload, render }: TipProps) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  return (
    <div style={TOOLTIP_STYLE} className="px-3 py-2">
      <div className="text-gray-400 mb-0.5">
        {row.label}
        {row.inProgress && " (in progress)"}
      </div>
      {render(row)}
    </div>
  );
}

function MonthBars({
  rows,
  dataKey,
  unit,
  height,
  onBarClick,
  tip,
}: {
  rows: ProgressionChartRow[];
  dataKey: "hours" | "peak";
  unit: string;
  height: number;
  onBarClick?: (row: ProgressionChartRow) => void;
  tip: (row: ProgressionChartRow) => ReactNode;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={rows} margin={{ top: 4, right: 8, left: 0, bottom: 0 }} barCategoryGap={2}>
        <CartesianGrid strokeDasharray="3 3" stroke={GRID_COLOR} vertical={false} />
        <XAxis
          dataKey="label"
          tick={TICK_STYLE}
          axisLine={AXIS_LINE}
          tickLine={false}
          interval="preserveStartEnd"
          minTickGap={24}
        />
        <YAxis
          tick={TICK_STYLE}
          axisLine={AXIS_LINE}
          tickLine={false}
          width={60}
          tickFormatter={(v) => `${v} ${unit}`}
        />
        <Tooltip content={<Tip render={tip} />} cursor={{ fill: "#374151", opacity: 0.4 }} />
        <Bar
          dataKey={dataKey}
          maxBarSize={18}
          radius={[4, 4, 0, 0]}
          onClick={onBarClick ? (d: { payload?: ProgressionChartRow }) => d.payload && onBarClick(d.payload) : undefined}
          cursor={onBarClick ? "pointer" : undefined}
        >
          {rows.map((r) => (
            <Cell key={r.month} fill={r.inProgress ? CURRENT_BAR : BAR} opacity={0.85} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

/**
 * Month by month volume and the month's biggest session, over two or five years. The same series
 * the coach's get_progression tool reads (GET /api/progress/months), so what the athlete points
 * at is what the coach sees. Two charts on one month axis instead of one chart with two scales.
 */
export default function ProgressionCard({ sports }: { sports: ("run" | "ride")[] }) {
  const { system } = useUnits();
  const [sport, setSport] = useState<"run" | "ride">(sports[0] ?? "ride");
  const [months, setMonths] = useState(24);
  const [metric, setMetric] = useState<PeakMetric>("longest");
  const { data: fresh, loading, error, reload } = useApi<Progression>(
    `/api/progress/months?sport=${sport}&months=${months}`,
  );
  // Keep the last charts on screen while another sport or span loads, so the card does not
  // collapse to a spinner and jump the page.
  const last = useRef<Progression | null>(null);
  if (fresh) last.current = fresh;
  const data = fresh ?? (loading ? last.current : null);

  const peak = PEAKS.find((p) => p.id === metric)!;
  const unit = unitLabel(peak.qty, system);
  const decimals = peak.qty === "distance" ? 1 : 0;
  const rows = data ? chartRows(data, metric, (si) => convert(si, peak.qty, system)) : [];
  const noun = sport === "run" ? "run" : "ride";

  // The draft describes what the request just loaded, never charts kept on screen meanwhile.
  const askCoach = () => {
    if (!fresh) return;
    try {
      sessionStorage.setItem(PENDING_CHAT_DRAFT_KEY, coachDraft(fresh.sport, rows));
    } catch { /* best-effort handoff */ }
    navigate("chat");
  };

  return (
    <section className="bg-gray-900 rounded-lg border border-gray-800 p-5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-gray-100 font-semibold">Long-term progression</h3>
          <p className="text-gray-500 text-xs mt-0.5">
            Month by month: hours of moving time, and the month's biggest single {noun}.{" "}
            <span className="text-green-400">■</span> this month, in progress. The coach reads the
            same numbers.
          </p>
        </div>
        <Button variant="ghost" size="sm" onClick={askCoach} disabled={!fresh || !rows.length}>
          Ask coach about this
        </Button>
      </div>

      <div className="mt-3 flex flex-wrap gap-3">
        {sports.length > 1 && (
          <Toggle
            label="Sport"
            options={sports.map((s) => ({ id: s, label: SPORT_LABEL[s] }))}
            value={sport}
            onChange={setSport}
          />
        )}
        <Toggle
          label="Time span"
          options={SPANS.map((s) => ({ id: s.months, label: s.label }))}
          value={months}
          onChange={setMonths}
        />
      </div>

      {error ? (
        <div className="mt-4">
          <ErrorState message={`Couldn't load your progression: ${error}`} onRetry={reload} />
        </div>
      ) : !data ? (
        loading ? <LoadingState /> : null
      ) : rows.length === 0 ? (
        <p className="text-sm text-gray-500 py-4">No {noun}s logged yet.</p>
      ) : (
        <div className={loading && !fresh ? "opacity-50 transition-opacity" : undefined} aria-busy={loading}>
          <h4 className="mt-4 mb-1 text-xs font-semibold uppercase tracking-wider text-gray-500">
            Hours per month
          </h4>
          <MonthBars
            rows={rows}
            dataKey="hours"
            unit="h"
            height={160}
            tip={(r) => <div className="text-gray-100">{r.hours.toFixed(1)} h</div>}
          />

          <div className="mt-4 mb-1 flex flex-wrap items-center justify-between gap-2">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-gray-500">
              {metric === "longest" ? `Longest ${noun}` : `Most climbing in one ${noun}`}, each month
            </h4>
            <Toggle label="Peak" options={PEAKS} value={metric} onChange={setMetric} />
          </div>
          <MonthBars
            rows={rows}
            dataKey="peak"
            unit={unit}
            height={160}
            onBarClick={(r) => r.peakId != null && navigate("activities", r.peakId)}
            tip={(r) =>
              r.peak == null ? (
                <div className="text-gray-500">No {noun}s</div>
              ) : (
                <>
                  <div className="text-gray-100">
                    {r.peak.toFixed(decimals)} {unit}
                  </div>
                  <div className="text-gray-400">
                    {r.peakName} · {formatDate(r.peakDate!)}
                  </div>
                  <div className="text-gray-500 text-[11px]">Click to open</div>
                </>
              )
            }
          />

          <details className="mt-3 text-sm">
            <summary className="cursor-pointer text-xs text-gray-500 hover:text-gray-300">
              Show as a table
            </summary>
            <table className="mt-2 w-full text-xs">
              <thead className="text-gray-500 text-left">
                <tr>
                  <th className="py-1 pr-3 font-normal">Month</th>
                  <th className="py-1 pr-3 font-normal text-right">Hours</th>
                  <th className="py-1 pr-3 font-normal text-right">{peak.label}</th>
                  <th className="py-1 font-normal">Activity</th>
                </tr>
              </thead>
              <tbody>
                {[...rows].reverse().map((r) => (
                  <tr key={r.month} className="border-t border-gray-800 text-gray-300">
                    <td className="py-1 pr-3 whitespace-nowrap">
                      {r.label}
                      {r.inProgress && <span className="text-gray-500"> (in progress)</span>}
                    </td>
                    <td className="py-1 pr-3 text-right tabular-nums">{r.hours.toFixed(1)}</td>
                    <td className="py-1 pr-3 text-right tabular-nums whitespace-nowrap">
                      {r.peak == null ? "—" : `${r.peak.toFixed(decimals)} ${unit}`}
                    </td>
                    <td className="py-1 text-gray-400">
                      {r.peakId != null ? (
                        <a href={hrefFor("activities", r.peakId)} className="underline hover:text-gray-200">
                          {r.peakName}
                        </a>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </div>
      )}
    </section>
  );
}
