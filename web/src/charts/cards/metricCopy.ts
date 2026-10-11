import type { ChartDataset } from "../api";

// Per-metric explanatory copy for the lifetime-unavailable empty state. Each card component
// supplies this (and its own units/axis labels) — not a generic config-driven chart engine,
// just the small bits of text that differ per metric.

export interface MetricCopy {
  icon: string;
  description: string;
}

export const METRIC_COPY: Record<string, MetricCopy> = {
  cadence_trend: {
    icon: "👟",
    description:
      "Tracks your average running cadence (steps per minute) over time, with a 4-week rolling average. Compare runs at similar speeds; a higher cadence alone does not establish better running economy.",
  },
  pace_fade_trend: {
    icon: "📉",
    description:
      "How much your pace slows (positive) or speeds up (negative, a negative split) in the final third of a run vs. the first third. Zero means even pacing. Compare similar routes and workouts; hills and intervals also affect the result.",
  },
  hr_zone_trend: {
    icon: "❤️",
    description:
      "Weekly time-in-zone distribution (Z1 recovery through Z5 max effort), weighted by activity duration. A base-building block should show mostly Z1/Z2; a polarized plan mixes a lot of Z1/Z2 with occasional Z4/Z5.",
  },
  cardiac_decoupling_trend: {
    icon: "🫀",
    description:
      "How much your heart rate drifts relative to pace within a single activity, trended over time. Compare steady, longer efforts on similar terrain; intervals, hills, and weather can affect drift.",
  },
  weekly_elevation: {
    icon: "⛰️",
    description:
      "Total climbing per week, with a 4-week rolling average — useful for tracking whether you're building the climbing volume your goals call for.",
  },
  training_time_allocation: {
    icon: "⚖️",
    description:
      "Weekly training time split between running and cycling, in hours — not distance, since a ride covers far more ground per hour than a run. Shows whether you're actually balancing both disciplines.",
  },
};

/** Shared title formatting keeps sport-specific chart instances consistent. */
export function sportTitle(dataset: ChartDataset): string {
  if (!dataset.sport) return dataset.title;
  return `${dataset.title} (${dataset.sport === "run" ? "Run" : "Ride"})`;
}
