import type { ChartDataset } from "../api";
import type { MetricCopy } from "./metricCopy";

/**
 * Two genuinely distinct "nothing to show" states:
 *  - lifetime unavailable (dataset.available === false) — reason-specific copy.
 *  - available lifetime, but zero points survive the user's selected date-range filter — a
 *    different message, since reporting "not enough data" here would be actively wrong (the
 *    athlete DOES have enough data, just not in this window).
 */

function countNoun(dataset: ChartDataset): string {
  return dataset.count_unit === "weeks" ? "weeks" : "activities";
}

export function LifetimeUnavailable({
  dataset,
  copy,
}: {
  dataset: ChartDataset;
  copy?: MetricCopy;
}) {
  const noun = countNoun(dataset);
  const qualifying = dataset.qualifying_count ?? 0;

  let heading: string;
  if (dataset.unavailable_reason === "no_activities") {
    heading = "No activities yet.";
  } else if (dataset.unavailable_reason === "missing_required_field") {
    heading = `None of your activities have recorded this yet.`;
  } else {
    heading = `More ${noun} needed (${qualifying} so far).`;
  }

  return (
    <div className="flex gap-4 items-start py-6 px-4">
      {copy && <span className="text-3xl">{copy.icon}</span>}
      <div>
        <p className="text-gray-300 text-sm font-medium mb-1">{heading}</p>
        {copy && <p className="text-gray-500 text-xs leading-relaxed max-w-lg">{copy.description}</p>}
      </div>
    </div>
  );
}

export function EmptyInRange() {
  return (
    <p className="text-gray-500 text-sm text-center py-10">
      No data in this date range — you have historical data, try widening the range.
    </p>
  );
}
