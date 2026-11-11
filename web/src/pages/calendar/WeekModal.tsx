import {
  COMPLIANCE_DOT_COLORS, COMPLIANCE_STATUS_LABELS, FALLBACK_WORKOUT_COLOR, WORKOUT_COLORS,
} from "./constants";
import { splitActivities as splitDay, summarizeWeek, weekBreakdown, weekFrom } from "./grid";
import type { Activity, ComplianceDay, Plan } from "./types";
import { useDistance } from "./useDistance";

interface Props {
  /** First day of the week to show ("YYYY-MM-DD"). */
  weekStart: string;
  plan: Plan;
  activities: Record<string, Activity[]>;
  compliance: Record<string, ComplianceDay>;
  onClose: () => void;
}

/** A week's totals and day-by-day breakdown. Derived from live data on every render, so an
 *  edit made while it is open shows up. */
export default function WeekModal({ weekStart, plan, activities, compliance, onClose }: Props) {
  const { units, fmtKm } = useDistance();
  const selectedWeek = summarizeWeek(weekFrom(weekStart), plan, activities, compliance);
  const splitActivities = (date: string) => splitDay(plan, activities, compliance, date);

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-black/60"
        onClick={() => onClose()}
      />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 pointer-events-none">
        <div className="pointer-events-auto bg-zinc-900 border border-zinc-700 rounded-lg w-full max-w-lg max-h-[85vh] overflow-y-auto shadow-2xl">
          <div className="px-5 py-4 border-b border-zinc-800 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-zinc-200">
              Week of{" "}
              {new Date(selectedWeek.cells[0].dateStr + "T12:00:00").toLocaleDateString("default", {
                month: "short",
                day: "numeric",
              })}
              {" – "}
              {new Date(selectedWeek.cells[6].dateStr + "T12:00:00").toLocaleDateString("default", {
                month: "short",
                day: "numeric",
              })}
            </h3>
            <button
              onClick={() => onClose()}
              className="text-zinc-500 hover:text-zinc-300 text-xl leading-none"
            >×</button>
          </div>

          <div className="p-5 space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div className="bg-zinc-800/40 rounded p-3">
                <div className="text-[10px] text-zinc-500 uppercase tracking-wider mb-1">Distance</div>
                <div className="text-sm text-zinc-200">
                  {fmtKm(selectedWeek.plannedKm)} planned · {fmtKm(selectedWeek.actualKm)} actual
                </div>
              </div>
              <div className="bg-zinc-800/40 rounded p-3">
                <div className="text-[10px] text-zinc-500 uppercase tracking-wider mb-1">Workouts</div>
                {(() => {
                  const w = selectedWeek;
                  const total = w.completed + w.modified + w.missed + w.upcoming;
                  if (total === 0) {
                    return <div className="text-sm text-zinc-500">No planned workouts this week</div>;
                  }
                  const breakdown = weekBreakdown(w);
                  return (
                    <>
                      <div className="text-sm text-zinc-200">
                        {w.completed + w.modified} of {total} planned workouts done
                      </div>
                      {(breakdown || w.upcoming > 0) && (
                        <div className="text-xs text-zinc-500 mt-0.5">
                          {[breakdown, w.upcoming > 0 && `${w.upcoming} to go`].filter(Boolean).join(" · ")}
                        </div>
                      )}
                    </>
                  );
                })()}
              </div>
            </div>

            <div>
              <div className="text-[10px] text-zinc-500 uppercase tracking-wider mb-2">Day by day</div>
              <div className="space-y-2">
                {selectedWeek.cells.map(cell => {
                  const dateStr = cell.dateStr;
                  const workout = plan[dateStr];
                  const { matched: matchedActivity, others: dayActivities } = splitActivities(dateStr);
                  const complianceDay = compliance[dateStr];
                  return (
                    <div
                      key={dateStr}
                      className="flex gap-3 items-start border border-zinc-800 rounded px-3 py-2"
                    >
                      <div className="w-16 flex-shrink-0 text-xs text-zinc-500">
                        {new Date(dateStr + "T12:00:00").toLocaleDateString("default", {
                          weekday: "short",
                          month: "short",
                          day: "numeric",
                        })}
                      </div>
                      <div className="flex-1 min-w-0 space-y-1">
                        {workout ? (
                          <div
                            className={`inline-block text-xs px-1.5 py-0.5 rounded border ${WORKOUT_COLORS[workout.workout_type] ?? FALLBACK_WORKOUT_COLOR}`}
                          >
                            {workout.workout_type}
                            {matchedActivity
                              ? ` · ✓ ${units.fmt(matchedActivity.distance_m ?? 0, "distance", { decimals: 1 })}${workout.distance_km ? ` / ${fmtKm(workout.distance_km)}` : ""}`
                              : workout.distance_km ? ` · ${fmtKm(workout.distance_km)}` : ""}
                          </div>
                        ) : (
                          <div className="text-xs text-zinc-600 italic">No planned workout</div>
                        )}
                        {dayActivities.map(a => (
                          <div key={a.id} className="text-xs text-zinc-400">
                            ✓ {units.fmt(a.distance_m ?? 0, "distance", { decimals: 1 })} {a.sport_type}
                          </div>
                        ))}
                        {complianceDay && (
                          <div className="flex items-center gap-1.5 text-xs">
                            {COMPLIANCE_DOT_COLORS[complianceDay.status] && (
                              <span
                                className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${COMPLIANCE_DOT_COLORS[complianceDay.status]}`}
                              />
                            )}
                            <span className="text-zinc-300 font-medium">
                              {COMPLIANCE_STATUS_LABELS[complianceDay.status]}
                            </span>
                            <span className="text-zinc-500 truncate">— {complianceDay.note}</span>
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
