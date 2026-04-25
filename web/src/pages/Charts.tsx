import type { Mode, ThemeConfig } from "../App";
import CardioCharts from "./charts/CardioCharts";
import LiftingCharts from "./charts/LiftingCharts";

interface Props {
  mode: Mode;
  theme: ThemeConfig;
}

export default function Charts({ mode, theme }: Props) {
  if (mode === "lifting") return <LiftingCharts theme={theme} />;
  return <CardioCharts mode={mode} theme={theme} />;
}
