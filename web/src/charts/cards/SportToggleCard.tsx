import { useState } from "react";
import type { ChartDataset } from "../api";
import { renderChartDataset } from "./registry";

interface Props {
  datasets: ChartDataset[]; // same metric_key, one per sport
  since: string | null;
  until: string | null;
  isAllTime: boolean;
  unit: "miles" | "km";
}

const LABELS: Record<string, string> = { run: "Run", ride: "Ride" };

/** One card for a metric that exists per sport, with a Run/Ride toggle. The inner card is
 * rendered with `sport: null` so its title drops the "(Run)"/"(Ride)" suffix. */
export default function SportToggleCard({ datasets, since, until, isAllTime, unit }: Props) {
  const [sport, setSport] = useState<string>(
    (datasets.find((d) => d.available) ?? datasets[0]).sport ?? "run",
  );
  const active = datasets.find((d) => d.sport === sport) ?? datasets[0];

  return (
    <div className="space-y-2">
      <div className="flex justify-start gap-1" role="group" aria-label="Sport">
        {datasets.map((d) => (
          <button
            key={d.id}
            onClick={() => setSport(d.sport ?? "run")}
            aria-pressed={active.id === d.id}
            className={`px-3 py-1 text-xs rounded-md border transition-colors ${
              active.id === d.id
                ? "bg-gray-700 border-gray-500 text-gray-100"
                : "border-gray-700 text-gray-400 hover:text-gray-200"
            }`}
          >
            {LABELS[d.sport ?? "run"]}
          </button>
        ))}
      </div>
      {renderChartDataset({
        dataset: { ...active, sport: null } as ChartDataset,
        since,
        until,
        isAllTime,
        unit,
      })}
    </div>
  );
}
