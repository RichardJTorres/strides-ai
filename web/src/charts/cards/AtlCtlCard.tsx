import TimeSeriesLineCard from "../TimeSeriesLineCard";
import ChartCard from "../ChartCard";
import { filterDatasetByRange } from "../dateFilter";
import type { AtlCtlDataset } from "../api";
import { LifetimeUnavailable, EmptyInRange } from "./EmptyState";

interface Props {
  dataset: AtlCtlDataset;
  since: string | null;
  until: string | null;
  isAllTime: boolean;
  unit: "miles" | "km";
}

function ratioZone(ratio: number): { label: string; color: string } {
  if (ratio > 1.3) return { label: "⚠ Injury risk", color: "#ef4444" };
  if (ratio < 0.8) return { label: "↓ Detraining", color: "#9ca3af" };
  return { label: "✓ Optimal", color: "#22c55e" };
}

function ATLTooltip({
  active,
  payload,
  label,
  unit,
}: {
  active?: boolean;
  payload?: { dataKey: string; value: number }[];
  label?: string;
  unit: "miles" | "km";
}) {
  if (!active || !payload?.length) return null;
  const get = (key: string) => payload.find((p) => p.dataKey === key)?.value;
  const atl = get("atl");
  const ctl = get("ctl");
  const ratio = get("ratio");
  const ul = unit === "miles" ? "mi" : "km";

  const zone = ratio != null ? ratioZone(ratio).label : "";

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

export default function AtlCtlCard({ dataset, since, until, isAllTime, unit }: Props) {
  if (!dataset.available) {
    return (
      <ChartCard title={dataset.title}>
        <LifetimeUnavailable dataset={dataset} />
      </ChartCard>
    );
  }

  const filtered = filterDatasetByRange(dataset, since, until) as AtlCtlDataset;
  const data = isAllTime ? filtered.data.slice(-365) : filtered.data;
  if (data.length === 0) {
    return (
      <ChartCard title={dataset.title}>
        <EmptyInRange />
      </ChartCard>
    );
  }

  const ul = unit === "miles" ? "mi" : "km";
  const ratioMax = Math.max(2.5, ...data.map((d) => d.ratio ?? 0));
  const ratioMaxRounded = Math.ceil(ratioMax * 10) / 10;

  // Most recent point in the currently-displayed (filtered) series — shown as a persistent
  // stats row so the current load is visible without hovering the chart.
  const latest = data[data.length - 1];
  const latestZone = latest.ratio != null ? ratioZone(latest.ratio) : null;

  const statsRow = (
    <div className="flex flex-wrap gap-5">
      <div>
        <div className="text-[10px] text-gray-500 uppercase tracking-wider">ATL (7d)</div>
        <div className="text-lg font-semibold" style={{ color: "#ef4444" }}>
          {latest.atl.toFixed(1)} <span className="text-xs text-gray-500">{ul}/d</span>
        </div>
      </div>
      <div>
        <div className="text-[10px] text-gray-500 uppercase tracking-wider">CTL (42d)</div>
        <div className="text-lg font-semibold" style={{ color: "#60a5fa" }}>
          {latest.ctl.toFixed(1)} <span className="text-xs text-gray-500">{ul}/d</span>
        </div>
      </div>
      {latestZone && (
        <div>
          <div className="text-[10px] text-gray-500 uppercase tracking-wider">ATL/CTL Ratio</div>
          <div className="text-lg font-semibold" style={{ color: "#a78bfa" }}>
            {latest.ratio!.toFixed(2)}
          </div>
          <div className="text-xs" style={{ color: latestZone.color }}>
            {latestZone.label}
          </div>
        </div>
      )}
    </div>
  );

  return (
    <TimeSeriesLineCard
      title={dataset.title}
      statsRow={statsRow}
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
      data={data as unknown as Record<string, unknown>[]}
      xKey="date"
      series={[
        { key: "atl", label: "ATL (7d)", color: "#ef4444", yAxisId: "load" },
        { key: "ctl", label: "CTL (42d)", color: "#60a5fa", yAxisId: "load" },
        { key: "ratio", label: "ATL/CTL", color: "#a78bfa", yAxisId: "ratio", dashed: true },
      ]}
      yAxes={[
        { id: "load", tickFormatter: (v) => v.toFixed(1), label: `${ul}/d` },
        { id: "ratio", orientation: "right", domain: [0, ratioMaxRounded], width: 36, label: "ratio" },
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
  );
}
