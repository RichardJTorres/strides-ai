import type { ReactNode } from "react";
import {
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceArea,
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

export interface SeriesSpec {
  key: string;
  label: string;
  color: string;
  dashed?: boolean;
  yAxisId?: string;
  strokeWidth?: number;
  connectNulls?: boolean;
}

export interface YAxisSpec {
  id: string;
  orientation?: "left" | "right";
  domain?: [number, number] | ["auto", "auto"];
  tickFormatter?: (v: number) => string;
  label?: string;
  width?: number;
}

export interface ReferenceAreaSpec {
  yAxisId: string;
  y1: number;
  y2: number;
  fill: string;
  opacity?: number;
}

interface Props {
  title: string;
  subtitle?: ReactNode;
  badge?: ReactNode;
  data: Record<string, unknown>[];
  xKey: string;
  series: SeriesSpec[];
  yAxes?: YAxisSpec[];
  referenceAreas?: ReferenceAreaSpec[];
  customTooltip?: ReactNode;
  height?: number;
  rightMargin?: number;
}

export default function TimeSeriesLineCard({
  title,
  subtitle,
  badge,
  data,
  xKey,
  series,
  yAxes,
  referenceAreas,
  customTooltip,
  height = 280,
  rightMargin = 16,
}: Props) {
  // Default single y-axis on the left if none specified.
  const axes: YAxisSpec[] = yAxes && yAxes.length > 0 ? yAxes : [{ id: "y" }];
  const seriesNormalized = series.map((s) => ({ ...s, yAxisId: s.yAxisId ?? axes[0].id }));

  return (
    <ChartCard title={title} subtitle={subtitle} badge={badge}>
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={data} margin={{ top: 4, right: rightMargin, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID_COLOR} vertical={false} />
          <XAxis
            dataKey={xKey}
            tickFormatter={fmtWeekDate}
            tick={TICK_STYLE}
            axisLine={AXIS_LINE}
            tickLine={false}
            interval="preserveStartEnd"
          />
          {axes.map((ax) => (
            <YAxis
              key={ax.id}
              yAxisId={ax.id}
              orientation={ax.orientation ?? "left"}
              domain={ax.domain}
              tick={TICK_STYLE}
              axisLine={AXIS_LINE}
              tickLine={false}
              width={ax.width ?? 40}
              tickFormatter={ax.tickFormatter}
              label={
                ax.label
                  ? {
                      value: ax.label,
                      angle: ax.orientation === "right" ? 90 : -90,
                      position: ax.orientation === "right" ? "insideRight" : "insideLeft",
                      fill: "#6b7280",
                      fontSize: 10,
                      dx: ax.orientation === "right" ? -4 : 14,
                    }
                  : undefined
              }
            />
          ))}
          {referenceAreas?.map((r, i) => (
            <ReferenceArea
              key={i}
              yAxisId={r.yAxisId}
              y1={r.y1}
              y2={r.y2}
              fill={r.fill}
              fillOpacity={r.opacity ?? 0.07}
            />
          ))}
          {customTooltip ? (
            <Tooltip content={customTooltip as never} />
          ) : (
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              labelFormatter={(label: unknown) => fmtWeekDate(String(label))}
            />
          )}
          <Legend wrapperStyle={LEGEND_STYLE} />
          {seriesNormalized.map((s) => (
            <Line
              key={s.key}
              yAxisId={s.yAxisId}
              dataKey={s.key}
              name={s.label}
              stroke={s.color}
              strokeWidth={s.strokeWidth ?? 1.5}
              strokeDasharray={s.dashed ? "5 3" : undefined}
              dot={false}
              connectNulls={s.connectNulls ?? false}
            />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}
