import { useRef, useState } from "react";
import Badge from "../../ui/Badge";
import Button from "../../ui/Button";
import Spinner from "../../ui/Spinner";
import { Notice } from "../../ui/states";
import { chosenOps, failureMessage, newRequestId, opsKey } from "./entryOps";
import type {
  CalendarOp, WhatIfChange, WhatIfCoach, WhatIfDigest, WhatIfMetric, WhatIfResult,
} from "./types";

type Who = "mine" | "coach";

/** Why a change moves no load number, in the athlete's terms. */
const NOT_COUNTED: Record<string, string> = {
  past: "is in the past, so it cannot change the load numbers",
  beyond_horizon: "is more than four weeks out, past what the load projection covers",
  not_in_load: "does not count as load in this mode (rest, yoga, travel or another sport)",
  no_duration: "has no duration, so it adds no load; add one to see its effect",
};
const OP_VERB = { create: "Add", update: "Change", delete: "Remove" } as const;
const VERDICT = {
  fine: { tone: "success", label: "Looks fine" },
  caution: { tone: "warning", label: "Proceed with care" },
  bad: { tone: "danger", label: "Not a good idea" },
} as const;

interface Run {
  /** The operations this was computed for: the result is shown only while the form still builds them. */
  key: string;
  ops: CalendarOp[];
  digest: WhatIfDigest;
  coach: WhatIfCoach | null;
  coachError: string | null;
  coaching: boolean;
}

interface Props {
  /** The operations for the form as it stands now (the same ones Save would send). */
  ops: CalendarOp[];
  reloadPlan: () => Promise<void>;
  /** Called once a change was applied: `created` holds the ids of any new entries. */
  onApplied: (who: Who, created: number[]) => void;
}

const post = (url: string, body: unknown) =>
  fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

function ChangeLines({ changes }: { changes: WhatIfChange[] }) {
  return (
    <ul className="space-y-1">
      {changes.map(c => (
        <li key={c.ref} className="text-xs text-gray-300">
          {OP_VERB[c.op]} {c.day}: {c.label}
          {!c.scored && <span className="text-gray-500"> (not scored against your activities)</span>}
          {!c.counted && c.reason && (
            <span className="block text-amber-300/90">This {NOT_COUNTED[c.reason]}.</span>
          )}
        </li>
      ))}
    </ul>
  );
}

/** Values straight from the server's digest, never from the model's text. */
function MetricRows({ metrics }: { metrics: WhatIfMetric[] }) {
  return (
    <dl className="space-y-1">
      {metrics.map(m => (
        <div key={m.id} className="flex items-baseline justify-between gap-3 text-xs">
          <dt className="text-gray-400 min-w-0">{m.label}</dt>
          <dd className="text-gray-200 whitespace-nowrap tabular-nums">
            {m.formatted_before ?? "n/a"} → {m.formatted_after ?? "n/a"}
            {m.formatted_delta && <span className="text-gray-500"> ({m.formatted_delta})</span>}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function Numbers({ digest }: { digest: WhatIfDigest }) {
  const { new: added, resolved } = digest.violations;
  const nothingMoved = digest.metrics.length === 0 && digest.changes.every(c => c.counted);
  return (
    <div className="space-y-2">
      <ChangeLines changes={digest.changes} />
      {digest.metrics.length > 0 && <MetricRows metrics={digest.metrics} />}
      {nothingMoved && (
        <p className="text-xs text-gray-500">This change does not move any weekly total or load metric.</p>
      )}
      {!digest.sufficient && (
        <Notice tone="info">
          Fatigue/fitness load needs 28 days of history, so only weekly totals are shown.
        </Notice>
      )}
      {added.map(v => (
        <Notice key={`${v.kind}:${v.date}`} tone={v.hard ? "error" : "warning"}>
          {v.hard ? "Conflict: " : ""}{v.detail}
        </Notice>
      ))}
      {resolved.map(v => (
        <Notice key={`${v.kind}:${v.date}`} tone="success">Resolves: {v.detail}</Notice>
      ))}
    </div>
  );
}

function CoachCard({ coach }: { coach: WhatIfCoach }) {
  const v = VERDICT[coach.verdict];
  const { suggestion } = coach;
  return (
    <div className="space-y-2">
      <div className="flex items-start gap-2">
        <Badge tone={v.tone}>{v.label}</Badge>
        <p className="text-sm text-gray-200">{coach.headline}</p>
      </div>
      {coach.reasons.length > 0 && (
        <ul className="list-disc pl-4 space-y-1">
          {coach.reasons.map((r, i) => <li key={i} className="text-xs text-gray-400">{r.text}</li>)}
        </ul>
      )}
      {suggestion && (
        <div className="rounded-md border border-gray-700 p-2 space-y-2">
          <h5 className="text-xs font-semibold text-gray-300">Coach's alternative (replaces your change)</h5>
          <ChangeLines changes={suggestion.changes} />
          {suggestion.metrics.length > 0 && <MetricRows metrics={suggestion.metrics} />}
          {suggestion.warnings.map((w, i) => <Notice key={i} tone="warning">{w}</Notice>)}
        </div>
      )}
      {coach.suggestion_rejected && (
        <Notice tone="info">
          The coach suggested an alternative, but the calendar would not accept it, so it was
          dropped: {coach.suggestion_rejected}
        </Notice>
      )}
    </div>
  );
}

/**
 * "What if": evaluates the form's unsaved change against the saved plan and shows the numbers at
 * once, then what the coach makes of them. Nothing is saved until Apply, which sends the very
 * operations that were evaluated (or the coach's complete alternative) as one atomic request.
 */
export default function WhatIfPanel({ ops, reloadPlan, onApplied }: Props) {
  const [question, setQuestion] = useState("");
  const [run, setRun] = useState<Run | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [applying, setApplying] = useState<Who | null>(null);
  const [applyError, setApplyError] = useState<string | null>(null);
  // Responses of an earlier evaluation, or of one the athlete discarded, are ignored.
  const latest = useRef(0);
  // One idempotency key per attempt at one choice; a different choice sends different ops.
  const requestId = useRef<{ who: Who; id: string } | null>(null);

  const key = opsKey(ops);
  const stale = run !== null && run.key !== key;

  const evaluate = async () => {
    const mine = latest.current + 1;
    latest.current = mine;
    const evaluated = ops;
    setError(null);
    setApplyError(null);
    setRun(null);
    requestId.current = null;
    setLoading(true);
    let digest: WhatIfDigest;
    try {
      const res = await post("/api/calendar/what-if?llm=false", { ops: evaluated });
      if (mine !== latest.current) return;
      if (!res.ok) {
        setError(await failureMessage(res, "Couldn't evaluate this change."));
        return;
      }
      digest = ((await res.json()) as WhatIfResult).digest;
    } catch {
      if (mine === latest.current) setError("Couldn't reach the server. Check your connection and try again.");
      return;
    } finally {
      if (mine === latest.current) setLoading(false);
    }
    if (mine !== latest.current) return;
    const first: Run = { key: opsKey(evaluated), ops: evaluated, digest, coach: null, coachError: null, coaching: true };
    setRun(first);

    // The numbers are on screen; the coach follows and may fail without taking them away.
    const finish = (patch: Partial<Run>) => {
      if (mine === latest.current) setRun({ ...first, coaching: false, ...patch });
    };
    try {
      const res = await post("/api/calendar/what-if", { ops: evaluated, question });
      if (!res.ok) return finish({ coachError: await failureMessage(res, "The coach could not be reached.") });
      const full = (await res.json()) as WhatIfResult;
      finish({ coach: full.coach, coachError: full.coach_error });
    } catch {
      finish({ coachError: "The coach could not be reached." });
    }
  };

  const discard = () => {
    latest.current += 1; // answers still in flight are no longer wanted
    setRun(null);
    setError(null);
    setApplyError(null);
    setLoading(false);
    requestId.current = null;
  };

  const apply = async (who: Who) => {
    if (!run || stale) return;
    const chosen = chosenOps(run.ops, run.coach, who);
    if (chosen.length === 0) return;
    setApplying(who);
    setApplyError(null);
    try {
      if (requestId.current?.who !== who) requestId.current = { who, id: newRequestId() };
      const res = await post("/api/calendar/entries/bulk", { ops: chosen, request_id: requestId.current.id });
      if (!res.ok) {
        requestId.current = null; // a refused set was not applied, so a fresh attempt is fine
        setApplyError(await failureMessage(res, "Couldn't apply this."));
        return;
      }
      const out = (await res.json().catch(() => null)) as { created?: number[] } | null;
      await reloadPlan();
      onApplied(who, out?.created ?? []);
    } catch {
      // The key is kept: if the request did land, resending it applies nothing twice.
      setApplyError("Couldn't apply this. Check your connection and try again.");
    } finally {
      setApplying(null);
    }
  };

  const shown = run && !stale ? run : null;
  const suggestion = shown?.coach?.suggestion ?? null;

  return (
    <section aria-label="What if" className="border-t border-gray-800 pt-3 space-y-3">
      <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">What if</h4>
      <input
        type="text"
        maxLength={1000}
        value={question}
        onChange={e => setQuestion(e.target.value)}
        placeholder="Ask the coach (optional): is this too much after Thursday's tempo?"
        aria-label="Question for the coach"
        className="w-full text-sm bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-gray-200 placeholder:text-gray-600"
      />
      <Button variant="ghost" size="sm" loading={loading} onClick={evaluate}>
        What if I do this?
      </Button>

      <div aria-live="polite" className="space-y-3">
        {error && <Notice tone="error">{error}</Notice>}
        {run && stale && (
          <Notice tone="info">The form changed since this was evaluated. Run it again to see the effect.</Notice>
        )}
        {shown && (
          <>
            <Numbers digest={shown.digest} />
            {shown.coaching && (
              <div className="flex items-center gap-2 text-xs text-gray-400">
                <Spinner className="w-3 h-3" /> Asking the coach…
              </div>
            )}
            {shown.coachError && (
              <Notice tone="warning">
                {shown.coachError} The numbers above still hold.
              </Notice>
            )}
            {shown.coach && <CoachCard coach={shown.coach} />}
            {applyError && <Notice tone="error">{applyError}</Notice>}
            <div className="flex flex-wrap gap-2">
              <Button size="sm" loading={applying === "mine"} disabled={applying !== null} onClick={() => apply("mine")}>
                Apply mine
              </Button>
              {suggestion && (
                <Button
                  size="sm"
                  variant="secondary"
                  loading={applying === "coach"}
                  disabled={applying !== null}
                  onClick={() => apply("coach")}
                >
                  Apply with coach's adjustments
                </Button>
              )}
              <Button size="sm" variant="ghost" disabled={applying !== null} onClick={discard}>Discard</Button>
            </div>
          </>
        )}
      </div>
    </section>
  );
}
