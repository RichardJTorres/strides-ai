import { useEffect, useState } from "react";
import { plannedClimbRate } from "../activityLabels";
import { FALLBACK_WORKOUT_COLOR, WORKOUT_COLORS } from "./constants";
import type { GeneratePlanResult, Plan, SetPlan } from "./types";
import { useDistance } from "./useDistance";

const GEN_STAGES: { after: number; text: string }[] = [
  { after: 0, text: "Reviewing your profile, recent training and calendar…" },
  { after: 6, text: "Drafting the training block…" },
  { after: 20, text: "Balancing load, rest days and race constraints…" },
  { after: 40, text: "Finalizing workouts…" },
  { after: 70, text: "Still working — longer blocks can take a minute or two…" },
];

// Generation is one non-streaming request, so this shows liveness (spinner + elapsed time) and
// time-based stage hints rather than real server progress.
function GeneratingProgress() {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const t0 = Date.now();
    const id = window.setInterval(() => setElapsed(Math.floor((Date.now() - t0) / 1000)), 1000);
    return () => window.clearInterval(id);
  }, []);
  const stage = [...GEN_STAGES].reverse().find(s => elapsed >= s.after) ?? GEN_STAGES[0];
  return (
    <div role="status" aria-live="polite" className="flex items-center gap-3 rounded border border-zinc-700 bg-zinc-800/60 px-3 py-3">
      <span className="h-4 w-4 shrink-0 rounded-full border-2 border-zinc-600 border-t-green-400 animate-spin" />
      <div className="min-w-0 flex-1">
        <div className="text-sm text-zinc-200">{stage.text}</div>
        <div className="text-xs text-zinc-500">
          {elapsed}s elapsed · usually 15–45 seconds · keep this window open
        </div>
      </div>
    </div>
  );
}

interface Props {
  /** The range the modal opens with; mounting it afresh resets everything else. */
  initialStart: string;
  initialEnd: string;
  plan: Plan;
  setPlan: SetPlan;
  onClose: () => void;
}

/** Ask the coach for a training block over a date range, review it, then accept or discard. */
export default function GenerateModal({ initialStart, initialEnd, plan, setPlan, onClose }: Props) {
  const { units, fmtKm } = useDistance();
  const [genStart, setGenStart] = useState(initialStart);
  const [genEnd, setGenEnd] = useState(initialEnd);
  const [genFreeform, setGenFreeform] = useState("");
  const [genLoading, setGenLoading] = useState(false);
  const [genAccepting, setGenAccepting] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);
  const [genResult, setGenResult] = useState<GeneratePlanResult | null>(null);

  const generatePlan = async () => {
    if (!genStart || !genEnd) return;
    setGenLoading(true);
    setGenError(null);
    setGenResult(null);
    try {
      const res = await fetch("/api/calendar/generate-plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          start_date: genStart,
          end_date: genEnd,
          freeform_text: genFreeform,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        setGenError(err.detail || "Failed to generate training block.");
        return;
      }
      setGenResult(await res.json());
    } catch {
      setGenError("Failed to generate training block. Check your connection and try again.");
    } finally {
      setGenLoading(false);
    }
  };

  const acceptGeneratedPlan = async () => {
    if (!genResult || genResult.workouts.length === 0) return;
    setGenAccepting(true);
    setGenError(null);
    try {
      const res = await fetch("/api/calendar/plan/bulk", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ set: genResult.workouts }),
      });
      if (!res.ok) {
        setGenError("Failed to save the training block.");
        return;
      }
      setPlan(prev => {
        const next = { ...prev };
        for (const w of genResult.workouts) next[w.date] = w;
        return next;
      });
      onClose();
    } finally {
      setGenAccepting(false);
    }
  };

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-black/60"
        onClick={() => !genLoading && !genAccepting && onClose()}
      />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 pointer-events-none">
        <div className="pointer-events-auto bg-zinc-900 border border-zinc-700 rounded-lg w-full max-w-lg max-h-[85vh] overflow-y-auto shadow-2xl">
          <div className="px-5 py-4 border-b border-zinc-800 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-zinc-200">Generate Training Block</h3>
            <button
              onClick={() => onClose()}
              className="text-zinc-500 hover:text-zinc-300 text-xl leading-none"
            >×</button>
          </div>

          <div className="p-5 space-y-4">
            {!genResult ? (
              <>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs text-zinc-500 mb-1 block">Start date</label>
                    <input
                      type="date" value={genStart}
                      onChange={e => setGenStart(e.target.value)}
                      className="w-full text-sm bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-zinc-200"
                    />
                  </div>
                  <div>
                    <label className="text-xs text-zinc-500 mb-1 block">End date</label>
                    <input
                      type="date" value={genEnd}
                      onChange={e => setGenEnd(e.target.value)}
                      className="w-full text-sm bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-zinc-200"
                    />
                  </div>
                </div>
                {genStart && genEnd && genStart > genEnd && (
                  <p className="text-xs text-red-400">Start date must be on or before end date.</p>
                )}
                <div>
                  <label className="text-xs text-zinc-500 mb-1 block">Notes (optional)</label>
                  <textarea
                    rows={3}
                    placeholder={'e.g. "I have a century ride Nov 15, focus on climbing" or "I\'m traveling Oct 10-12, keep it light"'}
                    value={genFreeform}
                    onChange={e => setGenFreeform(e.target.value)}
                    className="w-full text-sm bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-zinc-200 resize-none"
                  />
                </div>
                {genLoading && <GeneratingProgress />}
                {genError && <p className="text-xs text-red-400">{genError}</p>}
                <button
                  onClick={generatePlan}
                  disabled={genLoading || !genStart || !genEnd || genStart > genEnd}
                  className="w-full text-sm bg-green-700 hover:bg-green-600 disabled:opacity-50 text-white rounded px-3 py-2 font-medium"
                >
                  {genLoading ? "Generating…" : "Generate"}
                </button>
              </>
            ) : (
              <>
                {genResult.summary && (
                  <p className="text-sm text-zinc-300 leading-relaxed">{genResult.summary}</p>
                )}
                {(genResult.warnings ?? []).map((w, i) => (
                  <p key={i} className="text-xs text-amber-400">⚠ {w}</p>
                ))}
                {genResult.workouts.length === 0 ? (
                  <p className="text-sm text-zinc-500 italic">No workouts suggested for this range.</p>
                ) : (
                  <div className="space-y-1.5 max-h-72 overflow-y-auto">
                    {genResult.workouts.map(w => (
                      <div
                        key={w.date}
                        className={`px-3 py-2 rounded border text-sm ${WORKOUT_COLORS[w.workout_type] ?? FALLBACK_WORKOUT_COLOR}`}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-medium">{w.date} — {w.workout_type}</span>
                          <span className="text-xs opacity-70 text-right">
                            {[
                              w.distance_km ? fmtKm(w.distance_km) : null,
                              w.duration_min ? `${w.duration_min}min` : null,
                              w.intensity,
                            ].filter(Boolean).join(" · ")}
                          </span>
                        </div>
                        {(w.elevation_m || w.structure_text) && (
                          <div className="text-xs opacity-80 mt-0.5">
                            {w.elevation_m ? `${units.fmt(w.elevation_m, "elevation")} gain` : null}
                            {(() => {
                              const rate = plannedClimbRate(w.distance_km, w.elevation_m);
                              return rate == null ? null : ` · ${units.fmt(rate, "climb_rate")}`;
                            })()}
                            {w.structure_text && <div className="font-mono opacity-90">{w.structure_text}</div>}
                          </div>
                        )}
                        {w.description && (
                          <div className="text-xs opacity-80 mt-0.5">{w.description}</div>
                        )}
                        {plan[w.date] && (
                          <div className="text-xs text-amber-400 mt-0.5">
                            ⚠ replaces existing "{plan[w.date].workout_type}"
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
                {genLoading && <GeneratingProgress />}
                {genError && <p className="text-xs text-red-400">{genError}</p>}
                <div className="flex gap-2 pt-1">
                  <button
                    onClick={acceptGeneratedPlan}
                    disabled={genAccepting || genResult.workouts.length === 0}
                    className="flex-1 text-sm bg-green-700 hover:bg-green-600 disabled:opacity-50 text-white rounded px-3 py-2 font-medium"
                  >
                    {genAccepting ? "Adding…" : "Accept & Add to Calendar"}
                  </button>
                  <button
                    onClick={generatePlan}
                    disabled={genLoading || genAccepting}
                    className="text-sm bg-zinc-700 hover:bg-zinc-600 disabled:opacity-50 text-zinc-300 rounded px-3 py-2"
                  >
                    {genLoading ? "Regenerating…" : "Regenerate"}
                  </button>
                  <button
                    onClick={() => onClose()}
                    className="text-sm bg-zinc-800 hover:bg-zinc-700 text-zinc-400 rounded px-3 py-2"
                  >
                    Discard
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
