import { hrefFor } from "../nav";
import { WEEK_STATUS_TEXT, type Progress, type WeekStatus } from "./api";

const STATUS_COLOR: Record<WeekStatus, string> = {
  hit: "text-green-400",
  on_track: "text-gray-300",
  at_risk: "text-amber-400",
  lost: "text-red-400",
  no_plan: "text-gray-500",
};

/** The plan streak and where this week stands, in one line under the month header. */
export default function ProgressStrip({ progress }: { progress: Progress }) {
  const { streak } = progress;
  const week = streak.this_week;
  if (streak.weeks === 0 && streak.best_weeks === 0 && week.status === "no_plan") return null;
  return (
    <div className="px-4 py-2 border-b border-gray-800 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs">
      <a
        href={hrefFor("analytics", "progress")}
        className="flex items-baseline gap-1.5 hover:underline"
        title={`A week counts when you miss at most ${streak.max_misses} planned workout. Best: ${streak.best_weeks} week${streak.best_weeks === 1 ? "" : "s"}.`}
      >
        <b className="text-sm text-gray-100">{streak.weeks}</b>
        <span className="text-gray-400">week streak</span>
      </a>
      <span className={STATUS_COLOR[week.status]}>
        {WEEK_STATUS_TEXT[week.status]}
        {week.status !== "no_plan" && (
          <span className="text-gray-500">
            {" "}· {week.done} done{week.missed > 0 ? `, ${week.missed} missed` : ""}
            {week.upcoming > 0 ? `, ${week.upcoming} to go` : ""}
          </span>
        )}
      </span>
    </div>
  );
}
