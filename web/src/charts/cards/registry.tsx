import type { ChartDataset } from "../api";
import AerobicEfficiencyCard from "./AerobicEfficiencyCard";
import AtlCtlCard from "./AtlCtlCard";
import StackedBarMetricCard from "./StackedBarMetricCard";
import TimeSeriesMetricCard from "./TimeSeriesMetricCard";
import WeeklyBarMetricCard from "./WeeklyBarMetricCard";

interface RenderProps {
  dataset: ChartDataset;
  since: string | null;
  until: string | null;
  isAllTime: boolean;
  unit: "miles" | "km";
}

const HR_ZONE_COLORS: Record<string, string> = {
  Z1: "#60a5fa",
  Z2: "#4ade80",
  Z3: "#facc15",
  Z4: "#f97316",
  Z5: "#ef4444",
};

const ALLOCATION_COLORS: Record<string, string> = {
  Run: "#4ade80",
  Ride: "#22d3ee",
};

/** metric_key -> renderer. The two metrics with bespoke visuals (custom tooltips, multi-tier
 * empty states) get dedicated components; everything else reuses one of the three generic
 * per-chart_type cards with metric-specific copy/colors. */
export function renderChartDataset({ dataset, since, until, isAllTime, unit }: RenderProps) {
  switch (dataset.metric_key) {
    case "weekly_distance":
      if (dataset.chart_type !== "weekly_bar") return null;
      return (
        <WeeklyBarMetricCard
          dataset={dataset}
          since={since}
          until={until}
          isAllTime={isAllTime}
          valueLabel="Distance"
        />
      );
    case "weekly_elevation":
      if (dataset.chart_type !== "weekly_bar") return null;
      return (
        <WeeklyBarMetricCard
          dataset={dataset}
          since={since}
          until={until}
          isAllTime={isAllTime}
          valueLabel="Elevation"
          barColor="#a78bfa"
        />
      );
    case "atl_ctl":
      if (dataset.chart_type !== "atl_ctl") return null;
      return <AtlCtlCard dataset={dataset} since={since} until={until} isAllTime={isAllTime} unit={unit} />;
    case "aerobic_efficiency":
      if (dataset.chart_type !== "scatter") return null;
      return <AerobicEfficiencyCard dataset={dataset} since={since} until={until} />;
    case "hr_zone_trend":
      if (dataset.chart_type !== "stacked_bar") return null;
      return (
        <StackedBarMetricCard
          dataset={dataset}
          since={since}
          until={until}
          categoryColors={HR_ZONE_COLORS}
        />
      );
    case "training_time_allocation":
      if (dataset.chart_type !== "stacked_bar") return null;
      return (
        <StackedBarMetricCard
          dataset={dataset}
          since={since}
          until={until}
          categoryColors={ALLOCATION_COLORS}
        />
      );
    case "cadence_trend":
    case "pace_fade_trend":
    case "cardiac_decoupling_trend":
      if (dataset.chart_type !== "time_series") return null;
      return <TimeSeriesMetricCard dataset={dataset} since={since} until={until} />;
    default:
      return null;
  }
}
