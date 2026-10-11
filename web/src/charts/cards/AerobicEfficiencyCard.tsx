import ScatterTrendCard, { type ScatterPoint as RechartsScatterPoint } from "../ScatterTrendCard";
import { filterDatasetByRange } from "../dateFilter";
import { fmtPace } from "../tokens";
import { sportTitle } from "./metricCopy";
import type { ScatterTrendDataset } from "../api";

interface Props {
  dataset: ScatterTrendDataset;
  since: string | null;
  until: string | null;
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
  if (!p || p.date == null || p.value == null) return null;
  return (
    <div className="bg-gray-800 border border-gray-700 rounded-md p-2.5 text-xs shadow-lg leading-5">
      <p className="text-gray-400">{String(p.date)}</p>
      {p.name && <p className="text-gray-100 font-medium">{String(p.name)}</p>}
      <p className="text-gray-300">
        Efficiency: <span className="text-white">{Number(p.value).toFixed(2)}</span>
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

export default function AerobicEfficiencyCard({ dataset, since, until }: Props) {
  const sportLabel = dataset.sport === "ride" ? "ride" : "run";
  const sportLabelPlural = `${sportLabel}s`;

  if (!dataset.available) {
    return (
      <section className="bg-gray-900 rounded-lg border border-gray-800 p-5">
        <h3 className="text-gray-100 font-semibold mb-3">{sportTitle(dataset)}</h3>
        <div className="flex gap-4 items-start py-6 px-4">
          <span className="text-3xl">🫀</span>
          <div>
            <p className="text-gray-300 text-sm font-medium mb-1">
              {10 - (dataset.qualifying_count ?? 0)} more qualifying{" "}
              {10 - (dataset.qualifying_count ?? 0) === 1 ? sportLabel : sportLabelPlural} needed
            </p>
            <p className="text-gray-500 text-xs leading-relaxed max-w-lg">
              Aerobic efficiency tracks your speed relative to heart rate — higher means
              you&apos;re covering more ground per heartbeat, a reliable signal of improving
              fitness. It will appear once you have 10 {sportLabelPlural} logged with average HR
              between 120–155 bpm (easy to moderate effort, excluding warm-ups, races, and sensor
              dropouts).
            </p>
            {(dataset.qualifying_count ?? 0) > 0 && (
              <p className="text-green-500/80 text-xs mt-2">
                {dataset.qualifying_count} qualifying{" "}
                {dataset.qualifying_count === 1 ? sportLabel : sportLabelPlural} recorded so far.
              </p>
            )}
          </div>
        </div>
      </section>
    );
  }

  const filtered = filterDatasetByRange(dataset, since, until) as ScatterTrendDataset;
  if (filtered.scatter.length === 0) {
    return (
      <section className="bg-gray-900 rounded-lg border border-gray-800 p-5">
        <h3 className="text-gray-100 font-semibold mb-1">{sportTitle(dataset)}</h3>
        <p className="text-gray-500 text-sm text-center py-10">
          No qualifying {sportLabelPlural} (120–155 bpm) in this date range.
        </p>
      </section>
    );
  }

  return (
    <ScatterTrendCard
      title={sportTitle(dataset)}
      subtitle="Speed / HR for moderate efforts (120–155 bpm) · 4-week rolling average · higher = fitter"
      badge={
        !since && !until && filtered.improving && (
          <span className="text-green-400 text-xs bg-green-500/10 border border-green-500/20 rounded-full px-2 py-0.5">
            ↑ Improving
          </span>
        )
      }
      scatter={filtered.scatter as unknown as RechartsScatterPoint[]}
      rollingAvg={filtered.rolling_avg}
      scatterLabel={`Easy ${sportLabelPlural} (120–155 bpm)`}
      customTooltip={<AerobicEffTooltip />}
      showImproving={!since && !until && filtered.improving}
      yLabel="Efficiency"
    />
  );
}
