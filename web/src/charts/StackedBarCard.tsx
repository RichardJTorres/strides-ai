import type { ReactNode } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
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

export interface StackedCategory {
  key: string;
  label: string;
  color: string;
}

interface Props {
  title: string;
  subtitle?: ReactNode;
  data: Record<string, unknown>[];
  xKey: string;
  categories: StackedCategory[];
  yLabel?: string;
  height?: number;
}

export default function StackedBarCard({
  title,
  subtitle,
  data,
  xKey,
  categories,
  yLabel,
  height = 280,
}: Props) {
  return (
    <ChartCard title={title} subtitle={subtitle}>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID_COLOR} vertical={false} />
          <XAxis
            dataKey={xKey}
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
            label={
              yLabel
                ? {
                    value: yLabel,
                    angle: -90,
                    position: "insideLeft",
                    fill: "#6b7280",
                    fontSize: 10,
                    dx: 14,
                  }
                : undefined
            }
          />
          <Tooltip
            contentStyle={TOOLTIP_STYLE}
            labelFormatter={(label: unknown) => fmtWeekDate(String(label))}
            cursor={{ fill: "#374151", opacity: 0.4 }}
          />
          <Legend wrapperStyle={LEGEND_STYLE} />
          {categories.map((cat) => (
            <Bar
              key={cat.key}
              dataKey={cat.key}
              name={cat.label}
              stackId="stack"
              fill={cat.color}
              opacity={0.85}
              maxBarSize={20}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}
