// Shared dark-theme recharts style props + date formatters used across charts.

export const GRID_COLOR = "#374151";
export const TICK_STYLE = { fill: "#9ca3af", fontSize: 11 };
export const AXIS_LINE = { stroke: "#4b5563" };
export const TOOLTIP_STYLE = {
  backgroundColor: "#1f2937",
  border: "1px solid #374151",
  borderRadius: "6px",
  color: "#f3f4f6",
  fontSize: 12,
};
export const LEGEND_STYLE = { color: "#9ca3af", fontSize: 12 };

export function fmtPace(s: number) {
  return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
}

export function fmtWeekDate(str: string) {
  return new Date(str + "T00:00:00").toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

export function fmtTs(ts: number) {
  return new Date(ts).toLocaleDateString("en-US", { month: "short", year: "2-digit" });
}

// Palette used to assign distinct colours to dynamic series (e.g. one line per
// exercise for 1RM progression). Order tuned for dark backgrounds.
export const SERIES_PALETTE = [
  "#22d3ee", // cyan
  "#f97316", // orange
  "#a78bfa", // violet
  "#4ade80", // green
  "#facc15", // yellow
  "#f472b6", // pink
  "#60a5fa", // blue
  "#fb7185", // rose
];
