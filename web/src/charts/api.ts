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

/** Shared thresholds + planned-load projection from the calendar (strides_ai/training_state.py). */
export interface LoadContext {
  thresholds: {
    acwr_low: number; acwr_high: number; acwr_danger: number;
    ramp_elevated: number; ramp_high: number;
  };
  projection: { date: string; atl: number; ctl: number; ratio: number | null; planned: number }[];
  blocked_days: string[];
  race_dates: string[];
}

export interface CardioChartsResponse {
  mode: string;
  unit: string;
  charts: ChartDataset[];
  load_context?: LoadContext;
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

// ── Training insights (/api/charts/insights) ─────────────────────────────────────

export type InsightStatus =
  | "building" | "maintaining" | "peaking" | "overreaching"
  | "recovering" | "detraining" | "insufficient_data";

export interface DigestMetric {
  id: string;
  label: string;
  group: string;
  value: number;
  formatted: string;
  baseline: number | null;
  baseline_formatted: string | null;
  delta: number | null;
  delta_pct: number | null;
  direction: "up" | "down" | "flat" | null;
}

export interface DigestFlag {
  id: string;
  severity: "warning" | "info";
  text: string;
  metric_ids: string[];
}

export interface InsightsDigest {
  mode: string;
  as_of: string;
  windows: { recent: [string, string]; baseline: [string, string] };
  sufficient: boolean;
  activity_count: number;
  metrics: DigestMetric[];
  flags: DigestFlag[];
  missing: string[];
  context: {
    next_race: { name: string; date: string; days_out: number } | null;
    compliance: {
      window_days: number; scored: number; completed: number;
      modified: number; missed: number; consistency_pct: number | null;
    } | null;
    upcoming?: {
      sessions: { date: string; workout_type: string; distance: string | null; intensity: string | null }[];
      blocked_days: string[];
      race_dates: string[];
      conflicts: { kind: string; date: string; detail: string; hard: boolean }[];
    } | null;
  };
}

export interface InsightsReport {
  status: InsightStatus;
  headline: string;
  findings: { title: string; detail: string; tone: "positive" | "neutral" | "warning"; metric_ids: string[] }[];
  recommendations: { action: string; why: string; metric_ids: string[]; date?: string | null }[];
}

export interface InsightsPayload {
  mode: string;
  unit_system: string;
  digest: InsightsDigest;
  report: InsightsReport | null;
  generated_at: string | null;
  model: string | null;
  stale: boolean;
}

async function insightsError(res: Response): Promise<Error> {
  let detail = `HTTP ${res.status}`;
  try {
    const body = await res.json();
    if (body?.detail) detail = String(body.detail);
  } catch { /* keep status text */ }
  return new Error(detail);
}

export async function fetchInsights(mode: string, signal: AbortSignal): Promise<InsightsPayload> {
  const res = await fetch(`/api/charts/insights?mode=${mode}`, { signal });
  if (!res.ok) throw await insightsError(res);
  return res.json();
}

export async function generateInsights(
  mode: string, force: boolean, signal: AbortSignal,
): Promise<InsightsPayload> {
  const res = await fetch(`/api/charts/insights?mode=${mode}&force=${force}`, {
    method: "POST", signal,
  });
  if (!res.ok) throw await insightsError(res);
  return res.json();
}
