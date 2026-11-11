
// Column order of the grid (weeks start on Monday). DAY_NAMES is indexed by Date.getDay().
export const DAYS_OF_WEEK = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
export const DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

// Mirrored in strides_ai/compliance.py (RUN_WORKOUT_TYPES/RIDE_WORKOUT_TYPES/
// UNSCORED_WORKOUT_TYPES) for plan-vs-actual compliance scoring — keep both in sync. If they
// drift, the backend falls back to treating an unrecognized type as sport-ambiguous rather
// than crashing or misclassifying, so drift degrades gracefully but should still be fixed.
export const WORKOUT_TYPE_GROUPS: { label: string; types: string[] }[] = [
  { label: "Running", types: ["Easy Run", "Long Run", "Tempo Run", "Running Race"] },
  { label: "Cycling", types: ["Easy Ride", "Long Ride", "Tempo Ride", "Indoor Ride", "Cycling Race"] },
  // Generic "Race" kept for existing entries predating the sport-specific race types above;
  // left out of Running/Cycling since it can't be sport-categorized automatically.
  { label: "Other", types: ["Intervals", "Race", "Cross-Training", "Yoga", "Rest"] },
];
// Route (Strava or RideWithGPS) only makes sense for Running/Cycling types — a generic
// "Race"/"Intervals" could be either sport, so it's left out rather than guessing.
export const ROUTE_CAPABLE_WORKOUT_TYPES = new Set([
  ...WORKOUT_TYPE_GROUPS[0].types,
  ...WORKOUT_TYPE_GROUPS[1].types,
]);
// Distance/elevation don't apply to these. Mirrored as UNSCORED_WORKOUT_TYPES in
// strides_ai/compliance.py — these are excluded from compliance scoring entirely.
export const NO_DISTANCE_WORKOUT_TYPES = new Set(["Yoga", "Rest"]);
// Structured workouts are cycling-only. Mirrored by RIDE_WORKOUT_TYPES in strides_ai/compliance.py,
// which the server enforces.
export const keepsStructure = (workoutType: string) => WORKOUT_TYPE_GROUPS[1].types.includes(workoutType);

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

export const INTENSITIES = ["easy", "moderate", "hard", "rest"];

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
};


// Shown for a workout type that has no colour of its own.
export const FALLBACK_WORKOUT_COLOR = "bg-gray-700/50 text-gray-400 border-gray-600/30";

// distance/elevation hold what the athlete sees and types, in their unit system; they are
// converted back to the stored km / m on save (see kmFromInput / mFromInput).
export const EMPTY_FORM = {
  workout_type: "Easy Run",
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
