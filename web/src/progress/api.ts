// GET /api/progress — mirrors the Pydantic models in strides_ai/progress.py. Keep in sync.
import { useEffect, useRef } from "react";
import { useUnits } from "../UnitsContext";
import { useApi, type ApiState } from "../ui/api";

export type Sport = "run" | "ride" | "lift";

export interface ProgressRecord {
  /** e.g. "run.longest", "lift.e1rm:Bench Press" */
  id: string;
  sport: Sport;
  label: string;
  /** SI: meters or kilograms. Display `formatted`, which is in the athlete's units. */
  value: number;
  formatted: string;
  /** The activity's date; the week's Monday for week records. */
  date: string;
  /** null for week records. */
  activity_id: number | null;
  is_new: boolean;
  /** The best before `date`; null when this is the first. */
  previous: { value: number; formatted: string; date: string } | null;
}

export interface Quest {
  id: string;
  kind: "long" | "quality" | "rest";
  label: string;
  date: string;
  status: "done" | "partial" | "pending" | "missed";
  activity_id: number | null;
}

export type WeekStatus = "hit" | "on_track" | "at_risk" | "lost" | "no_plan";

export interface Streak {
  weeks: number;
  best_weeks: number;
  max_misses: number;
  this_week: { done: number; missed: number; upcoming: number; status: WeekStatus };
}

export interface Progress {
  as_of: string;
  unit_system: string;
  /** Monday of the current week. */
  week_start: string;
  streak: Streak;
  quests: Quest[];
  records: ProgressRecord[];
}

/** What the in-progress week means for the streak, in the athlete's words. */
export const WEEK_STATUS_TEXT: Record<WeekStatus, string> = {
  hit: "This week counts",
  on_track: "On track this week",
  at_risk: "One more miss breaks it",
  lost: "This week won't count",
  no_plan: "Nothing planned this week",
};

/** Which sports' records a coaching mode shows. */
export const SPORTS_BY_MODE: Record<string, Sport[]> = {
  running: ["run"],
  cycling: ["ride"],
  hybrid: ["run", "ride"],
  lifting: ["lift"],
};

/**
 * The athlete's streak, quests and records. Refetches when the unit system changes (figures are
 * formatted server-side) and whenever `refreshKey` changes — pass something that changes when
 * the plan or the activities do.
 */
export function useProgress(refreshKey?: unknown): ApiState<Progress> {
  const units = useUnits();
  const state = useApi<Progress>("/api/progress");
  const { reload } = state;
  const mounted = useRef(false);
  useEffect(() => {
    // useApi already fetched on mount; only later changes need a refetch.
    if (mounted.current) reload();
    mounted.current = true;
  }, [reload, refreshKey, units.system]);
  return state;
}
