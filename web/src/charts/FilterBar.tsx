import type { ThemeConfig } from "../App";
import { PRESETS, type FilterPreset } from "./dateFilter";

interface Props {
  preset: FilterPreset;
  customSince: string;
  customUntil: string;
  onPreset: (p: FilterPreset) => void;
  onCustomSince: (v: string) => void;
  onCustomUntil: (v: string) => void;
  theme: ThemeConfig;
}

export default function FilterBar({
  preset,
  customSince,
  customUntil,
  onPreset,
  onCustomSince,
  onCustomUntil,
  theme,
}: Props) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-3 flex flex-wrap items-center gap-1.5">
      {PRESETS.map(({ id, label }) => (
        <button
          key={id}
          onClick={() => onPreset(id)}
          className={`px-3 py-1 text-xs rounded-md border transition-colors ${
            preset === id
              ? `${theme.accentBg} ${theme.accentClass} ${theme.accentBorder} font-medium`
              : "text-gray-400 border-gray-700 hover:bg-gray-800 hover:text-gray-200"
          }`}
        >
          {label}
        </button>
      ))}
      {preset === "custom" && (
        <div className="flex items-center gap-2 ml-1">
          <input
            type="date"
            value={customSince}
            onChange={(e) => onCustomSince(e.target.value)}
            className="bg-gray-800 text-gray-200 border border-gray-600 rounded px-2 py-0.5 text-xs focus:outline-none focus:border-gray-500"
            style={{ colorScheme: "dark" }}
          />
          <span className="text-gray-500 text-xs">→</span>
          <input
            type="date"
            value={customUntil}
            onChange={(e) => onCustomUntil(e.target.value)}
            className="bg-gray-800 text-gray-200 border border-gray-600 rounded px-2 py-0.5 text-xs focus:outline-none focus:border-gray-500"
            style={{ colorScheme: "dark" }}
          />
        </div>
      )}
    </div>
  );
}
