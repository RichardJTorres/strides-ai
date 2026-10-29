// At-a-glance labels for activity fields. Pure functions (no React / no imports) so
// they can be unit-tested directly. All inputs are SI (meters, seconds, m/km) — the
// labels themselves are unit-agnostic, so a metric/imperial switch never changes them.

export type SportGroup = "run" | "ride" | "other";
export type LabelTone = "green" | "yellow" | "red" | "default";

export interface FieldLabel {
  text: string;
  tone: LabelTone;
  /** Tooltip / sub-caption explaining the label. */
  detail: string;
}

export interface LabelableActivity {
  date: string;
  sport_type: string | null;
  distance_m: number | null;
  moving_time_s: number | null;
  elevation_gain_m: number | null;
  climb_m_per_km: number | null;
  avg_pace_s_per_km: number | null;
  avg_hr: number | null;
}

// Mirrors RUN_TYPES / CYCLE_TYPES in strides_ai/activity_types.py.
const RUN_TYPES = new Set(["Run", "TrailRun", "VirtualRun"]);
const RIDE_TYPES = new Set(["Ride", "VirtualRide", "GravelRide"]);

export function sportGroup(sportType: string | null | undefined): SportGroup {
  if (sportType && RUN_TYPES.has(sportType)) return "run";
  if (sportType && RIDE_TYPES.has(sportType)) return "ride";
  return "other";
}

// ── Terrain (climbing ratio, m of gain per km) ───────────────────────────────
// Mirrors HIGH_CLIMB_M_PER_KM in strides_ai/analysis.py: 100 ft/mi ≈ 18.94 m/km.
export const HIGH_CLIMB_M_PER_KM = 100 / (3.280839895 * 1.609344);

// Lower bound (m/km) of Rolling, Hilly, Mountainous. Rides climb gentler per km, so
// their tiers sit lower. Run "Hilly" starts at the existing high-elevation flag.
export const CLIMB_TIERS: Record<"run" | "ride", [number, number, number]> = {
  run: [8, HIGH_CLIMB_M_PER_KM, 40],
  ride: [5, 12, 25],
};

const TERRAIN: { text: string; tone: LabelTone; blurb: string }[] = [
  { text: "Flat", tone: "default", blurb: "little climbing" },
  { text: "Rolling", tone: "default", blurb: "gentle, steady rises" },
  { text: "Hilly", tone: "yellow", blurb: "sustained climbing" },
  { text: "Mountainous", tone: "red", blurb: "very steep or big-climb terrain" },
];

/** Climb rate for an activity: stored value, else derived from gain / distance. */
export function climbRate(a: LabelableActivity): number | null {
  if (a.climb_m_per_km != null) return a.climb_m_per_km;
  if (a.elevation_gain_m != null && a.distance_m && a.distance_m > 0) {
    return a.elevation_gain_m / (a.distance_m / 1000);
  }
  return null;
}

/** Climb rate (m/km) for a planned workout, or null without both a distance and a gain. */
export function plannedClimbRate(
  distanceKm: number | null | undefined,
  elevationM: number | null | undefined,
): number | null {
  if (!distanceKm || distanceKm <= 0 || !elevationM || elevationM <= 0) return null;
  return elevationM / distanceKm;
}

export function climbLabel(rate: number | null | undefined, group: SportGroup): FieldLabel | null {
  if (rate == null || !Number.isFinite(rate) || group === "other") return null;
  const tiers = CLIMB_TIERS[group];
  const idx = rate >= tiers[2] ? 3 : rate >= tiers[1] ? 2 : rate >= tiers[0] ? 1 : 0;
  const t = TERRAIN[idx];
  return { text: t.text, tone: t.tone, detail: `${t.blurb} for a ${group}` };
}

// ── Size relative to the athlete's normal ────────────────────────────────────
export type Metric = "distance_m" | "moving_time_s" | "elevation_gain_m" | "avg_pace_s_per_km" | "avg_hr";

export interface Baseline {
  n: number;
  p25: number;
  median: number;
  p75: number;
}

export type Baselines = Partial<Record<SportGroup, Partial<Record<Metric, Baseline>>>>;

export const MIN_BASELINE = 6; // same floor as insights.MIN_ACTIVITIES
export const BASELINE_WINDOW_DAYS = 90;
const VERY_SHORT_RATIO = 0.5;
const VERY_LONG_RATIO = 1.5;
const METRICS: Metric[] = ["distance_m", "moving_time_s", "elevation_gain_m", "avg_pace_s_per_km", "avg_hr"];
// Pace / HR spread: "very" needs to clear the Tukey fence (1.5× IQR past the quartile) AND
// sit at least 10% from the median, so a tight cluster of similar days does not over-label.
const FENCE_IQR = 1.5;
const VERY_MIN_DEVIATION = 0.1;

/** Linear-interpolated percentile of an ascending-sorted array (q in 0..1). */
function percentile(sorted: number[], q: number): number {
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

function dayMs(date: string): number {
  return Date.parse(date.slice(0, 10));
}

function summarize(values: number[]): Baseline {
  const s = [...values].sort((a, b) => a - b);
  return { n: s.length, p25: percentile(s, 0.25), median: percentile(s, 0.5), p75: percentile(s, 0.75) };
}

/**
 * Per sport group and metric: median / quartiles over the last BASELINE_WINDOW_DAYS
 * (measured back from the most recent activity, so it is deterministic). If the window
 * holds fewer than MIN_BASELINE values, all history is used; if that is still too few,
 * the metric has no baseline and gets no label. Zero / missing values are ignored.
 */
export function buildBaselines(activities: LabelableActivity[]): Baselines {
  const out: Baselines = {};
  for (const group of ["run", "ride"] as const) {
    const rows = activities.filter((a) => sportGroup(a.sport_type) === group && !Number.isNaN(dayMs(a.date)));
    if (!rows.length) continue;
    const latest = Math.max(...rows.map((a) => dayMs(a.date)));
    const cutoff = latest - BASELINE_WINDOW_DAYS * 86_400_000;
    for (const metric of METRICS) {
      const pick = (subset: LabelableActivity[]) =>
        subset.map((a) => a[metric]).filter((v): v is number => v != null && v > 0);
      let values = pick(rows.filter((a) => dayMs(a.date) >= cutoff));
      if (values.length < MIN_BASELINE) values = pick(rows);
      if (values.length < MIN_BASELINE) continue;
      (out[group] ??= {})[metric] = summarize(values);
    }
  }
  return out;
}

/**
 * Short / Typical / Long vs the athlete's normal for that sport group.
 * Typical = inside the P25–P75 band. Very short / very long also require being
 * past 0.5× / 1.5× the median, so a wide band doesn't over-label.
 */
export function relativeLabel(
  value: number | null | undefined,
  baseline: Baseline | undefined,
  group: SportGroup,
): FieldLabel | null {
  if (value == null || !(value > 0) || !baseline || baseline.median <= 0 || group === "other") return null;
  const ratio = value / baseline.median;
  let text: string;
  let tone: LabelTone = "default";
  if (value <= Math.min(baseline.p25, VERY_SHORT_RATIO * baseline.median)) text = "Very short";
  else if (value < baseline.p25) text = "Short";
  else if (value >= Math.max(baseline.p75, VERY_LONG_RATIO * baseline.median)) {
    text = "Very long";
    tone = "red";
  } else if (value > baseline.p75) {
    text = "Long";
    tone = "yellow";
  } else text = "Typical";
  return { text, tone, detail: `${ratio.toFixed(1)}× your typical ${group} (${baseline.n} recent activities)` };
}

/** Label words for a metric where lower and higher values are both meaningful. */
export interface SpreadWords {
  veryLow: string;
  low: string;
  high: string;
  veryHigh: string;
  /** Tint the high side yellow/red; false for neutral metrics like pace. */
  tintHigh: boolean;
  /** Tooltip, given percent above (+) or below (-) the median. */
  detail: (pctFromMedian: number, group: SportGroup) => string;
}

// Pace is s/km, so a LOWER value is FASTER.
export const PACE_WORDS: SpreadWords = {
  veryLow: "Very fast",
  low: "Fast",
  high: "Slow",
  veryHigh: "Very slow",
  tintHigh: false,
  detail: (p, g) => `${Math.abs(p)}% ${p < 0 ? "faster" : "slower"} than your typical ${g}`,
};

export const HR_WORDS: SpreadWords = {
  veryLow: "Very low",
  low: "Low",
  high: "High",
  veryHigh: "Very high",
  tintHigh: true,
  detail: (p, g) => `${Math.abs(p)}% ${p < 0 ? "below" : "above"} your typical ${g} heart rate`,
};

/**
 * Typical = inside the P25–P75 band; outside it is Low/High (Fast/Slow), and "Very"
 * additionally clears the Tukey fence and VERY_MIN_DEVIATION from the median.
 * Only the high side can be tinted (yellow/red), and only when words.tintHigh is set.
 */
export function spreadLabel(
  value: number | null | undefined,
  baseline: Baseline | undefined,
  group: SportGroup,
  words: SpreadWords,
): FieldLabel | null {
  if (value == null || !(value > 0) || !baseline || baseline.median <= 0 || group === "other") return null;
  const iqr = baseline.p75 - baseline.p25;
  const dev = (value - baseline.median) / baseline.median;
  const pct = Math.round(dev * 100);
  let text = "Typical";
  let tone: LabelTone = "default";
  if (value < baseline.p25) {
    const very = value < baseline.p25 - FENCE_IQR * iqr && dev <= -VERY_MIN_DEVIATION;
    text = very ? words.veryLow : words.low;
  } else if (value > baseline.p75) {
    const very = value > baseline.p75 + FENCE_IQR * iqr && dev >= VERY_MIN_DEVIATION;
    text = very ? words.veryHigh : words.high;
    if (words.tintHigh) tone = very ? "red" : "yellow";
  }
  const detail = text === "Typical" ? `within your normal ${group} range` : words.detail(pct, group);
  return { text, tone, detail };
}

export interface ActivityLabels {
  pace: FieldLabel | null;
  hr: FieldLabel | null;
  distance: FieldLabel | null;
  time: FieldLabel | null;
  elevation: FieldLabel | null;
  climb: FieldLabel | null;
}

export function labelsFor(a: LabelableActivity, baselines: Baselines): ActivityLabels {
  const group = sportGroup(a.sport_type);
  const b = baselines[group as "run" | "ride"];
  return {
    pace: spreadLabel(a.avg_pace_s_per_km, b?.avg_pace_s_per_km, group, PACE_WORDS),
    hr: spreadLabel(a.avg_hr, b?.avg_hr, group, HR_WORDS),
    distance: relativeLabel(a.distance_m, b?.distance_m, group),
    time: relativeLabel(a.moving_time_s, b?.moving_time_s, group),
    elevation: relativeLabel(a.elevation_gain_m, b?.elevation_gain_m, group),
    climb: climbLabel(climbRate(a), group),
  };
}
