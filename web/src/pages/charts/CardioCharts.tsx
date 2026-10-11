import { useMemo, useState } from "react";
import type { Mode, ThemeConfig } from "../../App";
import FilterBar from "../../charts/FilterBar";
import { getPresetRange, type DateRange, type FilterPreset } from "../../charts/dateFilter";
import { useChartData } from "../../charts/useChartData";
import { renderChartDataset } from "../../charts/cards/registry";
import { groupIntoSections } from "../../charts/sections";

type Unit = "miles" | "km";

interface Props {
  mode: Mode;
  theme: ThemeConfig;
}

export default function CardioCharts({ mode, theme }: Props) {
  const [unit, setUnit] = useState<Unit>(() => {
    return (localStorage.getItem("strides_unit") as Unit) || "miles";
  });
  const { data, loading, error } = useChartData(mode, unit);

  const [preset, setPreset] = useState<FilterPreset>("last-3m");
  const [customSince, setCustomSince] = useState("");
  const [customUntil, setCustomUntil] = useState("");
  const [showUnavailable, setShowUnavailable] = useState(false);
  const [activeSectionId, setActiveSectionId] = useState<string>("load");

  function selectUnit(u: Unit) {
    setUnit(u);
    localStorage.setItem("strides_unit", u);
  }

  const range = useMemo((): DateRange => {
    if (preset === "custom") return { since: customSince || null, until: customUntil || null };
    return getPresetRange(preset);
  }, [preset, customSince, customUntil]);

  const isAllTime = preset === "all-time";

  // Page-level empty short-circuit: if the primary, always-present weekly_distance chart has
  // no activities at all (lifetime), show one page-level message instead of N redundant
  // per-card empty boxes.
  const weeklyDistance = data?.charts.find((c) => c.metric_key === "weekly_distance");
  const noActivitiesAtAll =
    weeklyDistance?.available === false && weeklyDistance.unavailable_reason === "no_activities";

  // Sections are derived purely from each chart's own metric_key/sport — same data, just
  // grouped into tabs so Hybrid's 12 charts aren't all dumped on screen at once. Falls back to
  // the first section when the active id doesn't exist for the current mode (e.g. switching
  // from Hybrid's "Ride Performance" tab to Running, which has no ride section).
  const sections = useMemo(
    () => (data ? groupIntoSections(data.charts, mode) : []),
    [data, mode],
  );
  const currentSection = sections.find((s) => s.id === activeSectionId) ?? sections[0];
  const unavailableCount = currentSection?.charts.filter((ds) => !ds.available).length ?? 0;
  const visibleCharts = currentSection?.charts.filter((ds) => showUnavailable || ds.available) ?? [];
  const invalidRange = !!(range.since && range.until && range.since > range.until);
  const sectionDescription = currentSection?.id === "load"
    ? "See how your weekly volume is changing. The current week is still in progress."
    : "Compare similar workouts over time. Terrain, effort, and conditions can change these measurements.";

  return (
    <div className="h-full overflow-y-auto">
      <div className="p-6 space-y-5 max-w-5xl mx-auto">
        <div className="flex flex-wrap gap-3 items-center justify-between">
          <h2 className="text-xl font-bold text-gray-100">Training Charts</h2>
          <div className="flex rounded-md overflow-hidden border border-gray-700 text-sm">
            {(["miles", "km"] as Unit[]).map((u) => (
              <button
                key={u}
                onClick={() => selectUnit(u)}
                className={`px-4 py-1.5 transition-colors ${
                  unit === u
                    ? `${theme.accentBg} ${theme.accentClass} font-medium`
                    : "text-gray-400 hover:bg-gray-800"
                }`}
              >
                {u === "miles" ? "Miles" : "km"}
              </button>
            ))}
          </div>
        </div>

        <FilterBar
          preset={preset}
          customSince={customSince}
          customUntil={customUntil}
          onPreset={setPreset}
          onCustomSince={setCustomSince}
          onCustomUntil={setCustomUntil}
          theme={theme}
        />

        {loading && (
          <div className="flex items-center justify-center py-24 text-gray-500">
            <span className="animate-pulse">Loading chart data…</span>
          </div>
        )}

        {error && (
          <div className="bg-red-950 border border-red-800 text-red-300 rounded-lg p-4 text-sm">
            Failed to load charts: {error}
          </div>
        )}

        {!loading && !error && noActivitiesAtAll && (
          <div className="text-center py-16 text-gray-500">No activities yet.</div>
        )}

        {!loading && !error && data && !noActivitiesAtAll && sections.length > 0 && (
          <>
            {sections.length > 1 && (
              <div className="flex gap-1 overflow-x-auto border-b border-gray-800">
                {sections.map((s) => (
                  <button
                    key={s.id}
                    onClick={() => setActiveSectionId(s.id)}
                    aria-pressed={currentSection?.id === s.id}
                    className={`whitespace-nowrap px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px ${
                      currentSection?.id === s.id
                        ? `${theme.accentClass} border-current`
                        : "text-gray-400 border-transparent hover:text-gray-300"
                    }`}
                  >
                    {s.label}
                  </button>
                ))}
              </div>
            )}

            <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
              <p className="text-gray-400">{sectionDescription}</p>
              {unavailableCount > 0 && (
                <label className="flex items-center gap-2 text-gray-400 cursor-pointer">
                  <input type="checkbox" checked={showUnavailable}
                    onChange={(e) => setShowUnavailable(e.target.checked)} />
                  Show {unavailableCount} charts needing more data
                </label>
              )}
            </div>
            {invalidRange ? (
              <p role="alert" className="text-amber-300 p-4 border border-amber-800 rounded-lg">
                Choose an end date on or after the start date.
              </p>
            ) : visibleCharts.length === 0 ? (
              <p className="text-gray-400 py-10 text-center">
                These charts need more recorded data. Select “Show charts needing more data” to see what is missing.
              </p>
            ) : visibleCharts.map((ds) => (
              <div key={ds.id}>
                {renderChartDataset({
                  dataset: ds,
                  since: range.since,
                  until: range.until,
                  isAllTime,
                  unit,
                })}
              </div>
            ))}
          </>
        )}
      </div>
    </div>
  );
}
