import { createContext, useContext, type ReactNode } from "react";

export type Mode = "running" | "cycling" | "hybrid" | "lifting";

export interface ThemeConfig {
  accentClass: string;
  accentBg: string;
  accentBorder: string;
  accentButton: string;
  accentFocus: string;
  accentActive: string;
  /** Solid accent fill, for dots and progress bars. */
  accentSolid: string;
  /** Opaque accent border, for the selected card in a set. */
  accentBorderSelected: string;
  /** Accent as a CSS colour, exposed as --accent for plain-CSS consumers (index.css). */
  accentHex: string;
  /** Short mode name ("Running"). */
  name: string;
  label: string;
}

// The one place a mode's colours are defined. All Tailwind class strings are written as complete
// literals so the JIT scanner picks them up.
export const THEMES: Record<Mode, ThemeConfig> = {
  running: {
    accentClass: "text-green-400",
    accentBg: "bg-green-500/20",
    accentBorder: "border-green-500/30",
    accentButton: "bg-green-600 hover:bg-green-500",
    accentFocus: "focus:border-green-500/40 focus:ring-green-500/10",
    accentActive: "bg-green-500/20 text-green-400",
    accentSolid: "bg-green-500",
    accentBorderSelected: "border-green-500",
    accentHex: "#4ade80",
    name: "Running",
    label: "Running Coach",
  },
  cycling: {
    accentClass: "text-blue-400",
    accentBg: "bg-blue-500/20",
    accentBorder: "border-blue-500/30",
    accentButton: "bg-blue-600 hover:bg-blue-500",
    accentFocus: "focus:border-blue-500/40 focus:ring-blue-500/10",
    accentActive: "bg-blue-500/20 text-blue-400",
    accentSolid: "bg-blue-500",
    accentBorderSelected: "border-blue-500",
    accentHex: "#60a5fa",
    name: "Cycling",
    label: "Cycling Coach",
  },
  hybrid: {
    accentClass: "text-purple-400",
    accentBg: "bg-purple-500/20",
    accentBorder: "border-purple-500/30",
    accentButton: "bg-purple-600 hover:bg-purple-500",
    accentFocus: "focus:border-purple-500/40 focus:ring-purple-500/10",
    accentActive: "bg-purple-500/20 text-purple-400",
    accentSolid: "bg-purple-500",
    accentBorderSelected: "border-purple-500",
    accentHex: "#c084fc",
    name: "Hybrid",
    label: "Hybrid Coach",
  },
  lifting: {
    accentClass: "text-orange-400",
    accentBg: "bg-orange-500/20",
    accentBorder: "border-orange-500/30",
    accentButton: "bg-orange-600 hover:bg-orange-500",
    accentFocus: "focus:border-orange-500/40 focus:ring-orange-500/10",
    accentActive: "bg-orange-500/20 text-orange-400",
    accentSolid: "bg-orange-500",
    accentBorderSelected: "border-orange-500",
    accentHex: "#fb923c",
    name: "Lifting",
    label: "Lifting Coach",
  },
};

export const MODES = Object.keys(THEMES) as Mode[];

const ThemeContext = createContext<ThemeConfig>(THEMES.running);

/** Supplies the active mode's theme to every component, so none needs a `theme` prop. */
export function ThemeProvider({ mode, children }: { mode: Mode; children: ReactNode }) {
  return <ThemeContext.Provider value={THEMES[mode]}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeConfig {
  return useContext(ThemeContext);
}
