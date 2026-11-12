import type { Dispatch, MouseEvent, MutableRefObject, SetStateAction } from "react";

export interface Workout {
  date: string;
  workout_type: string;
  description?: string | null;
  distance_km?: number | null;
  elevation_m?: number | null;
  duration_min?: number | null;
  intensity?: string | null;
  nutrition_json?: string | null;
  route_url?: string | null;
  route_analysis_json?: string | null;
  route_analyzed_at?: string | null;
  // Structured (Zwift-style) workout, cycling types only; structure_text is the server's rendering.
  structure?: Record<string, unknown> | null;
  structure_text?: string | null;
}

export interface RouteAnalysis {
  verdict: string;
  explanation: string;
  suggestion?: string | null;
}

export interface ComplianceDay {
  date: string;
  workout_type: string;
  status: "completed" | "modified" | "missed" | "upcoming" | "unscored";
  planned_distance_km: number | null;
  actual_distance_km: number | null;
  matched_activity_id: number | null;
  note: string;
}

export interface Activity {
  id: number;
  name: string;
  date: string;
  distance_m: number;
  moving_time_s: number;
  elevation_gain_m: number | null;
  avg_pace_s_per_km: number | null;
  avg_hr: number | null;
  sport_type: string;
  deep_dive_report?: string | null;
}

export interface NutritionData {
  calories_pre: number;
  calories_during: number;
  calories_post: number;
  hydration_pre_ml: number;
  hydration_during_ml: number;
  hydration_post_ml: number;
  notes: string;
}

export interface RoutePreview {
  name?: string | null;
  distance_m?: number | null;
  elevation_gain_m?: number | null;
}

export interface Race {
  date: string;
  name: string;
  target_time?: string;
}

export interface Prefs {
  blocked_days: string[];
  races: Race[];
}

export interface GeneratedWorkout {
  date: string;
  workout_type: string;
  description?: string | null;
  distance_km?: number | null;
  elevation_m?: number | null;
  duration_min?: number | null;
  intensity?: string | null;
  structure?: Record<string, unknown> | null;
  structure_text?: string | null;
}

export interface GeneratePlanResult {
  workouts: GeneratedWorkout[];
  summary: string;
  warnings?: string[];
}

// strides_ai/training_state.py (GET /api/calendar/training-state). Volumes are in the athlete's
// display unit; ramp_pct is vs the prior 4-week average.
export interface TrainingState {
  load: { ctl: number | null; atl: number | null; ratio: number | null };
  thresholds: { acwr_low: number; acwr_high: number; ramp_elevated: number; ramp_high: number };
  unit: string;
  weeks: { week_start: string; volume: number; ramp_pct: number | null; flags: string[] }[];
  conflicts: { kind: string; date: string; detail: string; hard: boolean }[];
}

export interface GridCell {
  date: Date;
  dateStr: string;
  dayNum: number;
  inCurrentMonth: boolean;
}

export interface WeekSummary {
  cells: GridCell[];
  plannedKm: number;
  actualKm: number;
  completed: number;
  modified: number;
  missed: number;
  upcoming: number;
}

export type Plan = Record<string, Workout>;
export type SetPlan = Dispatch<SetStateAction<Plan>>;
export type DateRange = { start: string; end: string };

/** First day of each grid row (the "week_start" setting). Training weeks stay Monday-Sunday. */
export type WeekStart = "monday" | "sunday";

/** Everything a week row and its day cells read from the page. */
export interface GridProps {
  plan: Plan;
  activities: Record<string, Activity[]>;
  compliance: Record<string, ComplianceDay>;
  prefs: Prefs;
  trainingState: TrainingState | null;
  todayStr: string;
  selectedDate: string | null;
  range: DateRange | null;
  /** First hard conflict (blocked day / race day) per date, for the ⚠ badge. */
  conflictByDate: Record<string, string>;
  dragFrom: string | null;
  dragOver: string | null;
  setDragFrom: (date: string | null) => void;
  setDragOver: (date: string | null) => void;
  movePending: MutableRefObject<boolean>;
  handleDayClick: (e: MouseEvent, date: string) => void;
  /** Open a day, or with `extend` grow the selected range to it (what shift-click does). */
  activateDay: (date: string, extend: boolean) => void;
  moveWorkout: (from: string, to: string) => void;
  /** Opens the week breakdown for the week whose first grid cell is `weekStart`. */
  openWeek: (weekStart: string) => void;
}
