import ChartCard from "../ChartCard";
import StackedBarCard from "../StackedBarCard";
import { filterDatasetByRange, visiblePointCount } from "../dateFilter";
import { SERIES_PALETTE } from "../tokens";
import type { StackedBarDataset } from "../api";
import { LifetimeUnavailable, EmptyInRange } from "./EmptyState";
import { METRIC_COPY, sportTitle } from "./metricCopy";

interface Props {
  dataset: StackedBarDataset;
  since: string | null;
  until: string | null;
  categoryColors?: Record<string, string>;
}


export default function StackedBarMetricCard({ dataset, since, until, categoryColors }: Props) {
  const copy = METRIC_COPY[dataset.metric_key];
  const title = sportTitle(dataset);

  if (!dataset.available) {
    return (
      <ChartCard title={title}>
        <LifetimeUnavailable dataset={dataset} copy={copy} />
      </ChartCard>
    );
  }

  const filtered = filterDatasetByRange(dataset, since, until) as StackedBarDataset;
  if (visiblePointCount(filtered) === 0) {
    return (
      <ChartCard title={title}>
        <EmptyInRange />
      </ChartCard>
    );
  }

  // StackedBarCard wants flat sibling keys per category; the API gives nested `values` for
  // cleaner typing — spread them right before handing off to the shared chart primitive.
  const rows = filtered.data.map((p) => ({ week: p.week, is_current: p.is_current, ...p.values }));
  const categories = dataset.categories.map((cat, i) => ({
    key: cat,
    label: cat,
    color: categoryColors?.[cat] ?? SERIES_PALETTE[i % SERIES_PALETTE.length],
  }));

  return (
    <StackedBarCard
      title={title}
      subtitle={copy?.description}
      data={rows}
      xKey="week"
      categories={categories}
      yLabel={dataset.unit ?? undefined}
    />
  );
}
