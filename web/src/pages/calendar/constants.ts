import type { WeekStart } from "./types";

// Column order of the grid, by the week-start setting. DAY_NAMES is indexed by Date.getDay().
export const DAYS_OF_WEEK: Record<WeekStart, string[]> = {
  monday: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
  sunday: ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
};
export const DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

// The taxonomy is defined once, in strides_ai/kinds.py. These mirror it, and
// tests/fixtures/taxonomy.json (asserted by pytest and by web/taxonomy.test.mjs) keeps them
// from drifting. Races and rest are kinds, not workout types.
export const WORKOUT_TYPE_GROUPS: { label: string; types: string[] }[] = [
  { label: "Running", types: ["Easy Run", "Long Run", "Tempo Run"] },
  { label: "Cycling", types: ["Easy Ride", "Long Ride", "Tempo Ride", "Indoor Ride"] },
  { label: "Other", types: ["Intervals", "Cross-Training", "Yoga"] },
];
// Route (Strava or RideWithGPS) only makes sense for running/cycling workouts and races.
export const ROUTE_CAPABLE_WORKOUT_TYPES = new Set([
  ...WORKOUT_TYPE_GROUPS[0].types,
  ...WORKOUT_TYPE_GROUPS[1].types,
]);
// Distance/elevation don't apply to these (never scored either).
export const NO_DISTANCE_WORKOUT_TYPES = new Set(["Yoga"]);
// Structured workouts are cycling-only; the server enforces it.
export const keepsStructure = (workoutType: string) => WORKOUT_TYPE_GROUPS[1].types.includes(workoutType);

export const ENTRY_KINDS: { kind: "workout" | "race" | "rest" | "travel" | "other"; label: string }[] = [
  { kind: "workout", label: "Workout" },
  { kind: "race", label: "Race" },
  { kind: "rest", label: "Rest day" },
  { kind: "travel", label: "Travel" },
  { kind: "other", label: "Other" },
];
export const RACE_SPORTS = ["run", "ride", "other"];
export const RACE_PRIORITIES = ["A", "B", "C"];

export const COMPLIANCE_DOT_COLORS: Record<string, string> = {
  completed: "bg-green-400",
  modified: "bg-amber-400",
  missed: "bg-red-400",
  // upcoming/unscored intentionally render nothing — never imply pass/fail on a day that
  // can't be judged yet (upcoming) or at all (rest/yoga).
};

export const COMPLIANCE_STATUS_LABELS: Record<string, string> = {
  completed: "Completed",
  modified: "Shortened",
  missed: "Missed",
  upcoming: "Upcoming",
  unscored: "Not scored",
};

export const INTENSITIES = ["easy", "moderate", "hard"];

export const WORKOUT_COLORS: Record<string, string> = {
  "Easy Run":       "bg-green-500/20 text-green-300 border-green-500/30",
  "Long Run":       "bg-purple-500/20 text-purple-300 border-purple-500/30",
  "Tempo Run":      "bg-orange-500/20 text-orange-300 border-orange-500/30",
  "Easy Ride":      "bg-teal-500/20 text-teal-300 border-teal-500/30",
  "Long Ride":      "bg-cyan-500/20 text-cyan-300 border-cyan-500/30",
  "Tempo Ride":     "bg-yellow-500/20 text-yellow-300 border-yellow-500/30",
  "Indoor Ride":    "bg-indigo-500/20 text-indigo-300 border-indigo-500/30",
  "Running Race":   "bg-amber-500/20 text-amber-300 border-amber-500/30",
  "Cycling Race":   "bg-amber-500/20 text-amber-300 border-amber-500/30",
  "Intervals":      "bg-red-500/20 text-red-300 border-red-500/30",
  "Race":           "bg-amber-500/20 text-amber-300 border-amber-500/30",
  "Cross-Training": "bg-blue-500/20 text-blue-300 border-blue-500/30",
  "Yoga":           "bg-pink-500/20 text-pink-300 border-pink-500/30",
  "Rest":           "bg-gray-700/50 text-gray-400 border-gray-600/30",
  "Travel":         "bg-sky-500/20 text-sky-300 border-sky-500/30",
  "Other":          "bg-gray-700/50 text-gray-400 border-gray-600/30",
};


// Shown for a workout type that has no colour of its own.
export const FALLBACK_WORKOUT_COLOR = "bg-gray-700/50 text-gray-400 border-gray-600/30";

// distance/elevation hold what the athlete sees and types, in their unit system; they are
// converted back to the stored km / m on save (see kmFromInput / mFromInput).
export const EMPTY_FORM = {
  workout_type: "Easy Run",
  title: "",
  sport: "run",
  goal_time: "",
  priority: "",
  result_activity_id: "",
  description: "",
  distance: "",
  elevation: "",
  duration_min: "",
  intensity: "easy",
  route_url: "",
  clear_structure: false,
};

export const VERDICT_STYLES: Record<string, { cls: string; label: string }> = {
  good_match: { cls: "bg-green-500/20 text-green-300 border-green-500/30", label: "✓ Good match" },
  too_hard: { cls: "bg-red-500/20 text-red-300 border-red-500/30", label: "⚠ Too hard" },
  too_easy: { cls: "bg-blue-500/20 text-blue-300 border-blue-500/30", label: "⚠ Too easy" },
  wrong_terrain: { cls: "bg-orange-500/20 text-orange-300 border-orange-500/30", label: "⚠ Wrong terrain" },
  needs_info: { cls: "bg-gray-700/50 text-gray-400 border-gray-600/30", label: "? Needs info" },
};

export const RUN_TYPES = new Set(["Run", "TrailRun", "VirtualRun"]);
