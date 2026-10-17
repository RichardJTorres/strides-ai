import { useMemo, useState } from "react";
import type { Mode, ThemeConfig } from "../../App";
import FilterBar from "../../charts/FilterBar";
import { getPresetRange, type DateRange, type FilterPreset } from "../../charts/dateFilter";
import { useChartData } from "../../charts/useChartData";
import { renderChartDataset } from "../../charts/cards/registry";
import SportToggleCard from "../../charts/cards/SportToggleCard";
import InsightsCard from "../../charts/InsightsCard";
import type { ChartDataset } from "../../charts/api";
import { groupIntoSections } from "../../charts/sections";
import { useUnits } from "../../UnitsContext";
import { chartUnitParam } from "../../units";

// Metrics that exist per sport in Hybrid and are shown as one card with a Run/Ride toggle.
const SPORT_TOGGLE_METRICS = new Set(["weekly_elevation", "climbing_ratio"]);

// Insights is a tab of its own: it uses a fixed 4-vs-8-week window, so the date filter and chart
// cards don't apply to it.
const INSIGHTS_SECTION = { id: "insights", label: "Insights" };

type Item = { key: string; datasets: ChartDataset[] };

function toItems(charts: ChartDataset[]): Item[] {
  const items: Item[] = [];
  const toggles = new Map<string, Item>();
  for (const ds of charts) {
    if (SPORT_TOGGLE_METRICS.has(ds.metric_key) && ds.sport) {
      const existing = toggles.get(ds.metric_key);
      if (existing) existing.datasets.push(ds);
      else {
        const item = { key: ds.metric_key, datasets: [ds] };
        toggles.set(ds.metric_key, item);
        items.push(item);
      }
    } else {
      items.push({ key: ds.id, datasets: [ds] });
    }
  }
  return items;
}

interface Props {
  mode: Mode;
  theme: ThemeConfig;
}

export default function CardioCharts({ mode, theme }: Props) {
  // Units follow the app-wide setting (Settings → Units); the charts API still speaks "miles"/"km".
  const unit = chartUnitParam(useUnits().system);
  const { data, loading, error } = useChartData(mode, unit);

  const [preset, setPreset] = useState<FilterPreset>("last-3m");
  const [customSince, setCustomSince] = useState("");
  const [customUntil, setCustomUntil] = useState("");
  const [showUnavailable, setShowUnavailable] = useState(false);
  const [activeSectionId, setActiveSectionId] = useState<string>(INSIGHTS_SECTION.id);

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
  const tabs = [INSIGHTS_SECTION, ...sections];
  const isInsights = activeSectionId === INSIGHTS_SECTION.id;
  const currentSection = isInsights
    ? undefined
    : sections.find((s) => s.id === activeSectionId) ?? sections[0];
  const currentTabId = isInsights ? INSIGHTS_SECTION.id : currentSection?.id;
  const items = toItems(currentSection?.charts ?? []);
  const itemAvailable = (it: Item) => it.datasets.some((d) => d.available);
  const unavailableCount = items.filter((it) => !itemAvailable(it)).length;
  const visibleCharts = items.filter((it) => showUnavailable || itemAvailable(it));
  const invalidRange = !!(range.since && range.until && range.since > range.until);
  const sectionDescription = currentSection?.id === "load"
    ? "See how your weekly volume is changing. The current week is still in progress."
    : "Compare similar workouts over time. Terrain, effort, and conditions can change these measurements.";

  return (
    <div className="h-full overflow-y-auto">
      <div className="p-6 space-y-5 max-w-5xl mx-auto">
        <div className="flex flex-wrap gap-3 items-center justify-between">
          <h2 className="text-xl font-bold text-gray-100">Training Analytics</h2>
        </div>

        {!isInsights && <FilterBar
          preset={preset}
          customSince={customSince}
          customUntil={customUntil}
          onPreset={setPreset}
          onCustomSince={setCustomSince}
          onCustomUntil={setCustomUntil}
          theme={theme}
        />}

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
            <div className="flex gap-1 overflow-x-auto border-b border-gray-800">
              {tabs.map((s) => (
                  <button
                    key={s.id}
                    onClick={() => setActiveSectionId(s.id)}
                    aria-pressed={currentTabId === s.id}
                    className={`whitespace-nowrap px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px ${
                      currentTabId === s.id
                        ? `${theme.accentClass} border-current`
                        : "text-gray-400 border-transparent hover:text-gray-300"
                    }`}
                  >
                    {s.label}
                  </button>
              ))}
            </div>

            {isInsights ? (
              <InsightsCard mode={mode} theme={theme} />
            ) : (<>
            <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
              {sectionDescription && <p className="text-gray-400">{sectionDescription}</p>}
              {unavailableCount > 0 && (
                <label className="flex items-center gap-2 text-gray-400 cursor-pointer ml-auto">
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
            ) : visibleCharts.map((it) => (
              <div key={it.key}>
                {it.datasets.length > 1 ? (
                  <SportToggleCard
                    datasets={it.datasets}
                    since={range.since}
                    until={range.until}
                    isAllTime={isAllTime}
                    unit={unit}
                  />
                ) : (
                  renderChartDataset({
                    dataset: it.datasets[0],
                    since: range.since,
                    until: range.until,
                    isAllTime,
                    unit,
                    loadContext: data?.load_context,
                  })
                )}
              </div>
            ))}
            </>)}
          </>
        )}
      </div>
    </div>
  );
}
