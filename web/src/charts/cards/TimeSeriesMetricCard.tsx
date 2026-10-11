import ChartCard from "../ChartCard";
import TimeSeriesLineCard from "../TimeSeriesLineCard";
import { filterDatasetByRange, visiblePointCount } from "../dateFilter";
import type { TimeSeriesDataset } from "../api";
import { LifetimeUnavailable, EmptyInRange } from "./EmptyState";
import { METRIC_COPY, sportTitle } from "./metricCopy";

interface Props {
  dataset: TimeSeriesDataset;
  since: string | null;
  until: string | null;
  color?: string;
}

const DEFAULT_COLOR = "#22d3ee";
const ROLLING_COLOR = "#fb923c";


export default function TimeSeriesMetricCard({ dataset, since, until, color = DEFAULT_COLOR }: Props) {
  const copy = METRIC_COPY[dataset.metric_key];
  const title = sportTitle(dataset);

  if (!dataset.available) {
    return (
      <ChartCard title={title}>
        <LifetimeUnavailable dataset={dataset} copy={copy} />
      </ChartCard>
    );
  }

  const filtered = filterDatasetByRange(dataset, since, until) as TimeSeriesDataset;
  if (visiblePointCount(filtered) === 0) {
    return (
      <ChartCard title={title}>
        <EmptyInRange />
      </ChartCard>
    );
  }

  return (
    <TimeSeriesLineCard
      title={title}
      subtitle={`${copy?.description ?? ""} · Units: ${dataset.unit ?? "value"}`}
      data={filtered.data as unknown as Record<string, unknown>[]}
      xKey="date"
      yAxes={[{ id: "y", label: dataset.unit ?? undefined }]}
      series={[
        { key: "value", label: "Per activity", color },
        { key: "rolling_avg", label: "4-wk avg", color: ROLLING_COLOR, dashed: true },
      ]}
    />
  );
}
