import { hrefFor, navigate } from "../../nav";
import Button from "../../ui/Button";
import { formatDate } from "../../ui/format";
import { PENDING_CHAT_DRAFT_KEY } from "../chatActivityHandoff";
import Modal from "../../ui/Modal";
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
  const weekLabel = `${formatDate(selectedWeek.cells[0].dateStr, "short")} – ${formatDate(selectedWeek.cells[6].dateStr, "short")}`;

  // Opens the chat with a drafted (never auto-sent) request to review this week.
  const askCoach = () => {
    const done = selectedWeek.completed + selectedWeek.modified;
    const total = done + selectedWeek.missed + selectedWeek.upcoming;
    try {
      sessionStorage.setItem(
        PENDING_CHAT_DRAFT_KEY,
        `Review my training week of ${weekLabel}` +
          (total > 0 ? ` (${done} of ${total} planned workouts done so far)` : "") +
          ". What went well, what should I adjust, and does next week's plan still make sense?",
      );
    } catch { /* best-effort handoff */ }
    navigate("chat");
  };

  return (
    <Modal
      title={`Week of ${weekLabel}`}
      onClose={onClose}
    >
          <div className="p-5 space-y-4">
            <Button variant="ghost" size="sm" onClick={askCoach}>Ask coach about this week</Button>
            <div className="grid grid-cols-2 gap-3">
              <div className="bg-gray-800/40 rounded p-3">
                <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Distance</div>
                <div className="text-sm text-gray-200">
                  {fmtKm(selectedWeek.plannedKm)} planned · {fmtKm(selectedWeek.actualKm)} actual
                </div>
              </div>
              <div className="bg-gray-800/40 rounded p-3">
                <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Workouts</div>
                {(() => {
                  const w = selectedWeek;
                  const total = w.completed + w.modified + w.missed + w.upcoming;
                  if (total === 0) {
                    return <div className="text-sm text-gray-500">No planned workouts this week</div>;
                  }
                  const breakdown = weekBreakdown(w);
                  return (
                    <>
                      <div className="text-sm text-gray-200">
                        {w.completed + w.modified} of {total} planned workouts done
                      </div>
                      {(breakdown || w.upcoming > 0) && (
                        <div className="text-xs text-gray-500 mt-0.5">
                          {[breakdown, w.upcoming > 0 && `${w.upcoming} to go`].filter(Boolean).join(" · ")}
                        </div>
                      )}
                    </>
                  );
                })()}
              </div>
            </div>

            <div>
              <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-2">Day by day</div>
              <div className="space-y-2">
                {selectedWeek.cells.map(cell => {
                  const dateStr = cell.dateStr;
                  const workout = plan[dateStr];
                  const { matched: matchedActivity, others: dayActivities } = splitActivities(dateStr);
                  const complianceDay = compliance[dateStr];
                  return (
                    <div
                      key={dateStr}
                      className="flex gap-3 items-start border border-gray-800 rounded px-3 py-2"
                    >
                      <a href={hrefFor("calendar", dateStr)} onClick={onClose} className="w-16 flex-shrink-0 text-xs text-gray-500 hover:underline">
                        {formatDate(dateStr, "weekday")}
                      </a>
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
                          <div className="text-xs text-gray-600 italic">No planned workout</div>
                        )}
                        {matchedActivity && (
                          <a href={hrefFor("activities", matchedActivity.id)} className="block text-xs text-gray-400 hover:underline">
                            {matchedActivity.name} →
                          </a>
                        )}
                        {dayActivities.map(a => (
                          <a key={a.id} href={hrefFor("activities", a.id)} className="block text-xs text-gray-400 hover:underline">
                            ✓ {units.fmt(a.distance_m ?? 0, "distance", { decimals: 1 })} {a.sport_type} →
                          </a>
                        ))}
                        {complianceDay && (
                          <div className="flex items-center gap-1.5 text-xs">
                            {COMPLIANCE_DOT_COLORS[complianceDay.status] && (
                              <span
                                className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${COMPLIANCE_DOT_COLORS[complianceDay.status]}`}
                              />
                            )}
                            <span className="text-gray-300 font-medium">
                              {COMPLIANCE_STATUS_LABELS[complianceDay.status]}
                            </span>
                            <span className="text-gray-500 truncate">— {complianceDay.note}</span>
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
    </Modal>
  );
}
