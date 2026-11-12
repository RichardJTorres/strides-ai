// Pure helpers for changing entries; the components own the fetching.
import type { Entry, Plan } from "./types";

export const findEntry = (plan: Plan, id: number): Entry | undefined => {
  for (const entries of Object.values(plan)) {
    const hit = entries.find(e => e.id === id);
    if (hit) return hit;
  }
  return undefined;
};

/** The plan with one entry shown on another day (optimistic; the server confirms or the plan is
 *  reloaded). Entries coexist, so nothing on the target day is displaced. */
export function applyMove(plan: Plan, id: number, to: string): Plan {
  const moving = findEntry(plan, id);
  if (!moving || moving.date === to) return plan;
  const next: Plan = {};
  for (const [date, entries] of Object.entries(plan)) {
    const kept = entries.filter(e => e.id !== id);
    if (kept.length) next[date] = kept;
  }
  next[to] = [...(next[to] ?? []), { ...moving, date: to }].sort((a, b) => a.id - b.id);
  return next;
}

/** Dragging an entry is a date-only PATCH: nothing else about it changes. */
export const datePatch = (to: string) => ({ date: to });

/** The message for a failed write: the server's reason when it gave one. */
export async function failureMessage(res: Response | undefined, fallback: string): Promise<string> {
  const detail = res ? (await res.json().catch(() => null))?.detail : null;
  return typeof detail === "string" && detail ? detail : fallback;
}

export type AcceptMode = "replace" | "append";

/** The change set for accepting a generated block, shared by the preview and the commit so they
 *  cannot disagree. Replace removes the existing *workout* entries in the range (never races,
 *  rest days or travel) and adds the new ones in the same atomic request; append only adds. */
export function generationOps(
  generated: { date: string }[],
  plan: Plan,
  range: { start: string; end: string },
  mode: AcceptMode,
) {
  const replaced: Entry[] = mode === "replace"
    ? Object.entries(plan)
        .filter(([date]) => date >= range.start && date <= range.end)
        .flatMap(([, entries]) => entries.filter(e => e.kind === "workout"))
    : [];
  return {
    replaced,
    ops: [
      ...replaced.map(e => ({ op: "delete", id: e.id })),
      ...generated.map(g => ({ op: "create", ...g })),
    ],
  };
}

/** A fresh idempotency key for one accept attempt; resent unchanged when the attempt is retried. */
export const newRequestId = () =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `req-${Date.now()}-${Math.random().toString(36).slice(2)}`;

/** Strict `H:MM:SS` / `MM:SS` -> seconds, else null (mirrors strides_ai.kinds.parse_goal_time). */
export function parseGoalTime(text: string): number | null {
  const m = /^(?:(\d{1,2}):)?(\d{1,2}):(\d{2})$/.exec(text.trim());
  if (!m) return null;
  const h = Number(m[1] ?? 0), min = Number(m[2]), sec = Number(m[3]);
  if (sec > 59 || (m[1] !== undefined && min > 59)) return null;
  return h * 3600 + min * 60 + sec;
}

export const formatGoalTime = (seconds: number | null | undefined): string => {
  if (seconds == null) return "";
  const h = Math.floor(seconds / 3600), m = Math.floor((seconds % 3600) / 60), s = seconds % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
};

export interface EntryForm {
  workout_type: string; title: string; sport: string; goal_time: string; priority: string;
  result_activity_id: string; description: string; distance: string; elevation: string;
  duration_min: string; intensity: string; route_url: string; clear_structure: boolean;
}

export interface BodyContext {
  /** Set when editing an existing entry; its structure is kept unless the athlete clears it. */
  existing: Entry | null;
  kmFromInput: (value: string) => number | null;
  mFromInput: (value: string) => number | null;
  routeCapable: (workoutType: string) => boolean;
  noDistance: (workoutType: string) => boolean;
  keepsStructure: (workoutType: string) => boolean;
}

/** The request body for saving the form. Create sends `kind` and `date`; edit is a PATCH, so a
 *  field that is not sent is left alone (structure, unless the athlete removes it). */
export function buildEntryBody(
  kind: Entry["kind"], date: string, form: EntryForm, ctx: BodyContext,
): Record<string, unknown> {
  const body: Record<string, unknown> = ctx.existing ? {} : { kind, date };
  const notes = form.description.trim() || null;
  if (kind === "workout") {
    const noDistance = ctx.noDistance(form.workout_type);
    const hasStructure = !!ctx.existing?.structure && ctx.keepsStructure(form.workout_type) && !form.clear_structure;
    Object.assign(body, {
      workout_type: form.workout_type,
      objective: notes,
      distance_km: noDistance ? null : ctx.kmFromInput(form.distance),
      elevation_m: noDistance ? null : ctx.mFromInput(form.elevation),
      intensity: form.intensity,
      route_url: ctx.routeCapable(form.workout_type) && form.route_url ? form.route_url : null,
    });
    // A structure decides the duration, so it is not sent while one is kept.
    if (!hasStructure) body.duration_min = form.duration_min ? parseInt(form.duration_min) : null;
    if (form.clear_structure || !ctx.keepsStructure(form.workout_type)) body.structure = null;
  } else if (kind === "race") {
    const goal = form.goal_time.trim();
    const seconds = goal ? parseGoalTime(goal) : null;
    Object.assign(body, {
      title: form.title.trim() || "Race",
      sport: form.sport,
      distance_km: ctx.kmFromInput(form.distance),
      elevation_m: ctx.mFromInput(form.elevation),
      goal_time_s: seconds,
      goal_text: goal && seconds === null ? goal : null,
      priority: form.priority || null,
      route_url: form.sport !== "other" && form.route_url ? form.route_url : null,
      notes,
    });
    if (ctx.existing) body.result_activity_id = form.result_activity_id ? Number(form.result_activity_id) : null;
  } else if (kind === "travel" || kind === "other") {
    Object.assign(body, { title: form.title.trim() || null, notes });
  } else {
    Object.assign(body, { notes });
  }
  return body;
}
