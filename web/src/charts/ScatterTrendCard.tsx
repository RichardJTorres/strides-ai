import { useMemo, type ReactNode } from "react";
import {
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import ChartCard from "./ChartCard";
import { AXIS_LINE, GRID_COLOR, LEGEND_STYLE, TICK_STYLE, fmtTs } from "./tokens";

export interface ScatterPoint {
  date: string;
  value: number;
  // Arbitrary extra fields are passed to the tooltip via spread.
  [k: string]: unknown;
}

export interface RollingPoint {
  date: string;
  avg: number;
}

interface Props {
  title: string;
  subtitle?: ReactNode;
  badge?: ReactNode;
  scatter: ScatterPoint[];
  rollingAvg: RollingPoint[];
  scatterLabel: string;
  scatterColor?: string;
  rollingColor?: string;
  customTooltip?: ReactNode;
  showImproving?: boolean; // adds a "↑ improving" annotation at the last rolling-avg point
  yDomainPadFraction?: number;
  height?: number;
  yLabel?: string;
}

const DEFAULT_SCATTER = "#22d3ee";
const DEFAULT_TREND = "#4ade80";

function ImprovingLabel(props: Record<string, unknown>) {
  const cx = Number(props.cx ?? 0);
  const cy = Number(props.cy ?? 0);
  return (
    <text
      x={cx + 8}
      y={cy - 5}
      fill="#4ade80"
      fontSize={10}
      fontStyle="italic"
      fontFamily="inherit"
    >
      ↑ improving
    </text>
  );
}

export default function ScatterTrendCard({
  title,
  subtitle,
  badge,
  scatter,
  rollingAvg,
  scatterLabel,
  scatterColor = DEFAULT_SCATTER,
  rollingColor = DEFAULT_TREND,
  customTooltip,
  showImproving = false,
  yDomainPadFraction = 0.12,
  height = 280,
  yLabel,
}: Props) {
  const scatterXY = useMemo(
    () =>
      scatter.map((p) => ({
        x: new Date(p.date + "T00:00:00").getTime(),
        y: p.value,
        ...p,
      })),
    [scatter],
  );
  const rollingXY = useMemo(
    () =>
      rollingAvg.map((r) => ({
        x: new Date(r.date + "T00:00:00").getTime(),
        y: r.avg,
      })),
    [rollingAvg],
  );
  const lastRollingPoint = useMemo(
    () => (rollingXY.length > 0 ? [rollingXY[rollingXY.length - 1]] : []),
    [rollingXY],
  );

  const allY = scatterXY.map((p) => p.y);
  const minY = allY.length ? Math.min(...allY) : 0;
  const maxY = allY.length ? Math.max(...allY) : 1;
  const pad = (maxY - minY) * yDomainPadFraction || 0.2;

  return (
    <ChartCard title={title} subtitle={subtitle} badge={badge}>
      <ResponsiveContainer width="100%" height={height}>
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
            name="Value"
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
            content={customTooltip as never}
            cursor={{ strokeDasharray: "3 3", stroke: "#4b5563" }}
          />
          <Legend wrapperStyle={LEGEND_STYLE} />

          <Scatter name={scatterLabel} data={scatterXY} fill={scatterColor} opacity={0.65} />

          <Scatter
            data={rollingXY}
            line={{ stroke: rollingColor, strokeWidth: 2.5 }}
            shape={() => <></>}
            legendType="none"
            name="rolling-avg"
          />

          {showImproving && lastRollingPoint.length > 0 && (
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
    </ChartCard>
  );
}
