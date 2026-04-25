import type { ReactNode } from "react";
import {
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import ChartCard from "./ChartCard";
import {
  AXIS_LINE,
  GRID_COLOR,
  LEGEND_STYLE,
  TICK_STYLE,
  TOOLTIP_STYLE,
  fmtWeekDate,
} from "./tokens";

export interface WeeklyBarPoint {
  week: string;
  value: number;
  rolling_avg: number;
  is_current: boolean;
}

interface Props {
  title: string;
  subtitle?: ReactNode;
  data: WeeklyBarPoint[];
  unitLabel: string; // e.g. "mi", "km", "kg", or "" for unitless counts
  valueLabel: string; // e.g. "Distance", "Volume", "Sessions"
  formatValue?: (n: number) => string;
  barColor?: string; // default cyan; current week always green
  height?: number;
}

const DEFAULT_BAR = "#22d3ee";
const CURRENT_BAR = "#4ade80";
const ROLLING_LINE = "#fb923c";

export default function WeeklyBarCard({
  title,
  subtitle,
  data,
  unitLabel,
  valueLabel,
  formatValue,
  barColor = DEFAULT_BAR,
  height = 260,
}: Props) {
  const fmt = formatValue ?? ((n: number) => `${Number(n).toFixed(1)}${unitLabel ? ` ${unitLabel}` : ""}`);
  return (
    <ChartCard
      title={title}
      subtitle={
        subtitle ?? (
          <>
            Per-week totals · 4-week rolling average ·{" "}
            <span className="text-green-400">■</span> current week
          </>
        )
      }
    >
      <ResponsiveContainer width="100%" height={height}>
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
            width={40}
            tickFormatter={(v) => `${v}${unitLabel}`}
          />
          <Tooltip
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            formatter={((val: any, name: any) => [fmt(Number(val)), name]) as any}
            labelFormatter={(label: unknown) => fmtWeekDate(String(label))}
            contentStyle={TOOLTIP_STYLE}
            cursor={{ fill: "#374151", opacity: 0.4 }}
          />
          <Legend wrapperStyle={LEGEND_STYLE} />
          <Bar dataKey="value" name={valueLabel} maxBarSize={18} radius={[2, 2, 0, 0]}>
            {data.map((entry, i) => (
              <Cell key={i} fill={entry.is_current ? CURRENT_BAR : barColor} opacity={0.85} />
            ))}
          </Bar>
          <Line
            dataKey="rolling_avg"
            name="4-week avg"
            stroke={ROLLING_LINE}
            strokeWidth={2}
            dot={false}
            strokeDasharray="5 3"
          />
        </ComposedChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}
