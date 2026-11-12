import type { TrainingState } from "./types";

export default function LoadStrip({ state }: { state: TrainingState }) {
  const { ctl, atl, ratio } = state.load;
  if (ctl === null || atl === null) return null;
  const t = state.thresholds;
  const zone =
    ratio === null ? null
    : ratio > t.acwr_high ? { label: "High fatigue", color: "text-red-400" }
    : ratio < t.acwr_low ? { label: "Fresh / detraining", color: "text-zinc-400" }
    : { label: "Optimal", color: "text-green-400" };
  const ul = state.unit === "miles" ? "mi" : "km";
  const hard = state.conflicts.filter(c => c.hard).length;
  const soft = state.conflicts.filter(c => !c.hard);
  return (
    <div className="px-4 py-2 border-b border-zinc-800 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-zinc-400">
      <span>CTL <b className="text-blue-400">{ctl.toFixed(1)}</b> {ul}/d</span>
      <span>ATL <b className="text-red-400">{atl.toFixed(1)}</b> {ul}/d</span>
      {zone && ratio !== null && (
        <span>Ratio <b className={zone.color}>{ratio.toFixed(2)}</b> · {zone.label}</span>
      )}
      {hard > 0 && <span className="text-amber-400">⚠ {hard} workout(s) on blocked/race days</span>}
      {soft.slice(0, 2).map((c, i) => (
        <span key={i} className="text-amber-400" title={c.detail}>⚠ {c.detail}</span>
      ))}
      <a href="#analytics" className="ml-auto text-zinc-500 hover:text-zinc-300">Analytics →</a>
    </div>
  );
}
