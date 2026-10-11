// Typed response/dataset contract mirroring strides_ai/analytics/models.py exactly.
// This IS the API contract — no separate conversion layer between what the backend
// computes and what the frontend consumes.

export type UnavailableReason =
  | "no_activities"
  | "missing_required_field"
  | "insufficient_qualifying_count";

interface ChartDatasetBase {
  id: string;
  metric_key: string;
  sport: "run" | "ride" | null;
  title: string;
  unit: string | null;
  available: boolean;
  unavailable_reason: UnavailableReason | null;
  qualifying_count: number | null;
  total_count: number | null;
  count_unit: "activities" | "weeks";
}

export interface WeeklyBarPoint {
  week: string;
  value: number;
  rolling_avg: number;
  is_current: boolean;
}

export interface WeeklyBarDataset extends ChartDatasetBase {
  chart_type: "weekly_bar";
  data: WeeklyBarPoint[];
}

export interface AtlCtlPoint {
  date: string;
  atl: number;
  ctl: number;
  ratio: number | null;
}

export interface AtlCtlDataset extends ChartDatasetBase {
  chart_type: "atl_ctl";
  data: AtlCtlPoint[];
}

export interface ScatterPoint {
  date: string;
  value: number;
  name: string;
  hr: number;
  pace_s: number;
  ul: string;
}

export interface RollingAvgPoint {
  date: string;
  avg: number;
}

export interface ScatterTrendDataset extends ChartDatasetBase {
  chart_type: "scatter";
  scatter: ScatterPoint[];
  rolling_avg: RollingAvgPoint[];
  improving: boolean;
}

export interface TimeSeriesPoint {
  date: string;
  value: number;
  rolling_avg: number;
}

export interface TimeSeriesDataset extends ChartDatasetBase {
  chart_type: "time_series";
  data: TimeSeriesPoint[];
}

export interface StackedBarPoint {
  week: string;
  is_current: boolean;
  values: Record<string, number>;
}

export interface StackedBarDataset extends ChartDatasetBase {
  chart_type: "stacked_bar";
  data: StackedBarPoint[];
  categories: string[];
}

export type ChartDataset =
  | WeeklyBarDataset
  | AtlCtlDataset
  | ScatterTrendDataset
  | TimeSeriesDataset
  | StackedBarDataset;

export interface CardioChartsResponse {
  mode: string;
  unit: string;
  charts: ChartDataset[];
}

export async function fetchCardioCharts(
  mode: string,
  unit: string,
  signal: AbortSignal,
): Promise<CardioChartsResponse> {
  const res = await fetch(`/api/charts?unit=${unit}&mode=${mode}`, { signal });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}
