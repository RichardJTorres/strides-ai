import ChartCard from "../ChartCard";
import WeeklyBarCard from "../WeeklyBarCard";
import { filterDatasetByRange } from "../dateFilter";
import type { WeeklyBarDataset } from "../api";
import { LifetimeUnavailable, EmptyInRange } from "./EmptyState";
import { METRIC_COPY, sportTitle } from "./metricCopy";

interface Props {
  dataset: WeeklyBarDataset;
  since: string | null;
  until: string | null;
  isAllTime: boolean;
  valueLabel: string;
  barColor?: string;
}


export default function WeeklyBarMetricCard({
  dataset,
  since,
  until,
  isAllTime,
  valueLabel,
  barColor,
}: Props) {
  const copy = METRIC_COPY[dataset.metric_key];
  const title = sportTitle(dataset);

  if (!dataset.available) {
    return (
      <ChartCard title={title}>
        <LifetimeUnavailable dataset={dataset} copy={copy} />
      </ChartCard>
    );
  }

  const filtered = filterDatasetByRange(dataset, since, until) as WeeklyBarDataset;
  const data = isAllTime ? filtered.data.slice(-52) : filtered.data;
  if (data.length === 0) {
    return (
      <ChartCard title={title}>
        <EmptyInRange />
      </ChartCard>
    );
  }

  return (
    <WeeklyBarCard
      title={title}
      subtitle={`${copy?.description ?? "Weekly distance with a 4-week rolling average."} Whole weeks shown; the green bar is the current, incomplete week.`}
      data={data}
      unitLabel={dataset.unit ?? ""}
      valueLabel={valueLabel}
      barColor={barColor}
    />
  );
}
