import { hrefFor } from "../nav";
import { formatDate } from "../ui/format";
import { WEEK_STATUS_TEXT, type Progress, type Quest, type WeekStatus } from "./api";

const STATUS_COLOR: Record<WeekStatus, string> = {
  hit: "text-green-400",
  on_track: "text-gray-300",
  at_risk: "text-amber-400",
  lost: "text-red-400",
  no_plan: "text-gray-500",
};

const QUEST_STYLE: Record<Quest["status"], { mark: string; cls: string; text: string }> = {
  done: { mark: "✓", cls: "border-green-500/30 bg-green-500/10 text-green-300", text: "done" },
  partial: { mark: "◐", cls: "border-amber-500/30 bg-amber-500/10 text-amber-300", text: "shortened" },
  pending: { mark: "○", cls: "border-gray-700 bg-gray-800/60 text-gray-300", text: "to do" },
  missed: { mark: "✕", cls: "border-red-500/30 bg-red-500/10 text-red-300", text: "missed" },
};

/** The plan streak and this week's quests, in one line under the month header. */
export default function ProgressStrip({ progress }: { progress: Progress }) {
  const { streak, quests } = progress;
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
      {quests.length > 0 && (
        <ul className="flex flex-wrap items-center gap-1.5 md:ml-auto" aria-label="This week's quests">
          {quests.map((q) => {
            const style = QUEST_STYLE[q.status];
            return (
              <li key={q.id}>
                <a
                  href={q.activity_id != null ? hrefFor("activities", q.activity_id) : hrefFor("calendar", q.date)}
                  className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 hover:brightness-125 ${style.cls}`}
                  title={`${q.label}, ${formatDate(q.date, "weekday")}: ${style.text}`}
                >
                  <span aria-hidden="true">{style.mark}</span>
                  {q.label}
                  <span className="opacity-60">{formatDate(q.date, "weekday").split(",")[0]}</span>
                </a>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
