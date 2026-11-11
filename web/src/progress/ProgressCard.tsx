import { hrefFor } from "../nav";
import Badge from "../ui/Badge";
import { formatDate } from "../ui/format";
import { ErrorState, LoadingState } from "../ui/states";
import { SPORTS_BY_MODE, WEEK_STATUS_TEXT, useProgress, type ProgressRecord } from "./api";

const SPORT_LABEL = { run: "Running", ride: "Cycling", lift: "Lifting" } as const;

function RecordRow({ record: r }: { record: ProgressRecord }) {
  // A week record is dated by its Monday; an activity record links to the activity.
  const when = r.activity_id == null ? `week of ${formatDate(r.date)}` : formatDate(r.date);
  return (
    <tr className="border-t border-gray-800">
      <td className="py-2 pr-3 text-gray-300">
        {r.label} {r.is_new && <Badge tone="highlight">New</Badge>}
      </td>
      <td className="py-2 pr-3 text-right font-semibold tabular-nums text-gray-100 whitespace-nowrap">
        {r.formatted}
      </td>
      <td className="py-2 pr-3 text-gray-400 whitespace-nowrap">
        {r.activity_id != null ? (
          <a href={hrefFor("activities", r.activity_id)} className="underline hover:text-gray-200">
            {when}
          </a>
        ) : (
          when
        )}
      </td>
      <td className="py-2 text-gray-500 whitespace-nowrap hidden sm:table-cell">
        {r.previous ? `was ${r.previous.formatted} (${formatDate(r.previous.date)})` : "first on record"}
      </td>
    </tr>
  );
}

/**
 * The plan streak and personal records for the mode's sports. Lifting has no planned-workout
 * calendar, so it shows records only.
 */
export default function ProgressCard({ mode }: { mode: string }) {
  const { data, loading, error, reload } = useProgress();
  if (error) return <ErrorState message={`Couldn't load your progress: ${error}`} onRetry={reload} />;
  if (!data) return loading ? <LoadingState /> : null;

  const sports = SPORTS_BY_MODE[mode] ?? [];
  const { streak } = data;
  const week = streak.this_week;
  return (
    <div className="space-y-5">
      {mode !== "lifting" && (
        <section className="bg-gray-900 rounded-lg border border-gray-800 p-5">
          <h3 className="text-gray-100 font-semibold">Plan streak</h3>
          <p className="text-gray-500 text-xs mt-0.5">
            A week counts when you do at least one planned workout and miss at most{" "}
            {streak.max_misses}. Shortened workouts count; rest days are not scored.
          </p>
          <div className="mt-4 grid grid-cols-3 gap-2">
            <div className="bg-gray-800/60 rounded-md px-3 py-2">
              <div className="text-[11px] text-gray-500">Current</div>
              <div className="text-gray-100 font-semibold tabular-nums">
                {streak.weeks} week{streak.weeks === 1 ? "" : "s"}
              </div>
            </div>
            <div className="bg-gray-800/60 rounded-md px-3 py-2">
              <div className="text-[11px] text-gray-500">Best</div>
              <div className="text-gray-100 font-semibold tabular-nums">
                {streak.best_weeks} week{streak.best_weeks === 1 ? "" : "s"}
              </div>
            </div>
            <a href={hrefFor("calendar")} className="bg-gray-800/60 rounded-md px-3 py-2 hover:bg-gray-800">
              <div className="text-[11px] text-gray-500">This week</div>
              <div className="text-gray-100 font-semibold">{WEEK_STATUS_TEXT[week.status]}</div>
              {week.status !== "no_plan" && (
                <div className="text-[11px] text-gray-500 tabular-nums">
                  {week.done} done · {week.missed} missed · {week.upcoming} to go
                </div>
              )}
            </a>
          </div>
        </section>
      )}

      <section className="bg-gray-900 rounded-lg border border-gray-800 p-5">
        <h3 className="text-gray-100 font-semibold">Personal records</h3>
        <p className="text-gray-500 text-xs mt-0.5">
          Bests from whole activities and completed weeks. A sport gets records after 6 activities
          and 4 weeks of history.
        </p>
        {sports.map((sport) => {
          const records = data.records.filter((r) => r.sport === sport);
          return (
            <div key={sport} className="mt-4">
              {sports.length > 1 && (
                <h4 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-1">
                  {SPORT_LABEL[sport]}
                </h4>
              )}
              {records.length === 0 ? (
                <p className="text-sm text-gray-500 py-2">
                  No {SPORT_LABEL[sport].toLowerCase()} records yet.
                </p>
              ) : (
                <table className="w-full text-sm">
                  <tbody>
                    {records.map((r) => <RecordRow key={r.id} record={r} />)}
                  </tbody>
                </table>
              )}
            </div>
          );
        })}
      </section>
    </div>
  );
}
