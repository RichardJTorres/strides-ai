import type { Mode, ThemeConfig } from "../App";
import CardioCharts from "./charts/CardioCharts";
import LiftingCharts from "./charts/LiftingCharts";

interface Props {
  mode: Mode;
  theme: ThemeConfig;
  /** The open tab from the URL (`#analytics/progress`), or null for the default. */
  routeParam?: string | null;
}

export default function Charts({ mode, theme, routeParam }: Props) {
  if (mode === "lifting") return <LiftingCharts theme={theme} />;
  return <CardioCharts mode={mode} theme={theme} routeParam={routeParam} />;
}
