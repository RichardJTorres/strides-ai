import type { ChartDataset } from "./api";
import type { Mode } from "../App";

const LOAD_METRIC_KEYS = new Set([
  "weekly_distance",
  "atl_ctl",
  "weekly_elevation",
  "training_time_allocation",
]);

export interface ChartSection {
  id: string;
  label: string;
  charts: ChartDataset[];
}

/**
 * Groups the backend's already-ordered chart list into tabbed sections, purely from each
 * dataset's own metric_key/sport fields — no backend change needed. Hybrid splits the
 * "performance" group further by sport, since mixing run and ride efficiency charts in one
 * tab would be as confusing as mixing them in one chart (the reason they're separate series
 * in the first place).
 */
export function groupIntoSections(charts: ChartDataset[], mode: Mode): ChartSection[] {
  const load = charts.filter((c) => LOAD_METRIC_KEYS.has(c.metric_key));
  const performance = charts.filter((c) => !LOAD_METRIC_KEYS.has(c.metric_key));

  const sections: ChartSection[] = [{ id: "load", label: "Training Load", charts: load }];

  if (mode === "hybrid") {
    sections.push({
      id: "run_performance",
      label: "Run Performance",
      charts: performance.filter((c) => c.sport === "run"),
    });
    sections.push({
      id: "ride_performance",
      label: "Ride Performance",
      charts: performance.filter((c) => c.sport === "ride"),
    });
  } else {
    sections.push({ id: "performance", label: "Performance", charts: performance });
  }

  return sections.filter((s) => s.charts.length > 0);
}
