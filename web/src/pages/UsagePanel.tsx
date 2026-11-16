import { useState } from "react";
import { useApi } from "../ui/api";
import { EmptyState, ErrorState, LoadingState, Notice } from "../ui/states";
import { formatCost, formatDate, formatTokens } from "../ui/format";

interface Group {
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  cost_usd: number;
  unpriced_calls: number;
}
type Named<K extends string> = Group & Record<K, string>;
interface UsagePayload {
  days: number;
  totals: Group;
  by_day: Named<"day">[];
  by_model: Named<"model">[];
  by_source: Named<"source">[];
}

const RANGES = [7, 30, 90];

const SOURCE_LABELS: Record<string, string> = {
  chat: "Chat",
  deep_dive: "Activity deep dive",
  insights: "Training insights",
  memory_review: "Memory review",
  plan_generation: "Plan generation",
  route_analysis: "Route analysis",
};

/** An estimate: a dash when nothing could be priced, and a trailing "+" when only some could. */
function Cost({ group }: { group: Group }) {
  const { calls, unpriced_calls: unpriced } = group;
  const partial = unpriced > 0;
  return (
    <span title={partial ? `${unpriced} call(s) could not be priced` : undefined}>
      {calls > 0 && unpriced === calls ? "—" : formatCost(group.cost_usd)}
      {partial && unpriced < calls ? "+" : ""}
    </span>
  );
}

function Table<T extends Group>({
  title,
  rows,
  label,
}: {
  title: string;
  rows: T[];
  label: (row: T) => string;
}) {
  return (
    <div>
      <h4 className="text-xs font-semibold text-gray-400 mb-1">{title}</h4>
      <table className="w-full table-fixed text-xs text-gray-300">
        <thead>
          <tr className="text-left text-gray-500">
            <th className="py-1 font-normal w-2/5">
              <span className="sr-only">{title}</span>
            </th>
            <th className="py-1 font-normal text-right">Calls</th>
            <th className="py-1 font-normal text-right">Input</th>
            <th className="py-1 font-normal text-right">Output</th>
            <th className="py-1 font-normal text-right">Est. cost</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={label(r)} className="border-t border-gray-800">
              <td className="py-1">{label(r)}</td>
              <td className="py-1 text-right">{r.calls}</td>
              <td className="py-1 text-right">{formatTokens(r.input_tokens)}</td>
              <td className="py-1 text-right">{formatTokens(r.output_tokens)}</td>
              <td className="py-1 text-right">
                <Cost group={r} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Tokens and estimated cost of every LLM call the app made (chat and one-shot analyses). */
export default function UsagePanel() {
  const [days, setDays] = useState(30);
  const { data, loading, error, reload } = useApi<UsagePayload>(`/api/usage?days=${days}`);

  return (
    <section>
      <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-1">
        Model usage
      </h3>
      <p className="text-xs text-gray-600 mb-3">
        Tokens the provider reported for each call. Costs are estimates from a built-in price
        table; models without a known price show “—”.
      </p>
      <div className="flex gap-2 mb-3" role="group" aria-label="Usage period">
        {RANGES.map((d) => (
          <button
            key={d}
            type="button"
            onClick={() => setDays(d)}
            aria-pressed={days === d}
            className={`text-xs px-2 py-1 rounded border ${
              days === d
                ? "border-gray-500 text-gray-100"
                : "border-gray-800 text-gray-500 hover:text-gray-300"
            }`}
          >
            {d} days
          </button>
        ))}
      </div>
      {loading && !data ? (
        <LoadingState />
      ) : error ? (
        <ErrorState message={error} onRetry={reload} />
      ) : !data || data.totals.calls === 0 ? (
        <EmptyState>No model calls recorded in the last {days} days.</EmptyState>
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
            <Tile label="Calls">{data.totals.calls}</Tile>
            <Tile label="Input">{formatTokens(data.totals.input_tokens)}</Tile>
            <Tile label="Output">{formatTokens(data.totals.output_tokens)}</Tile>
            <Tile label="Est. cost">
              <Cost group={data.totals} />
            </Tile>
          </div>
          {data.totals.unpriced_calls > 0 && (
            <Notice tone="info">
              {data.totals.unpriced_calls} call(s) could not be priced (unknown model, or the
              provider reported no token counts), so the cost is a lower bound.
            </Notice>
          )}
          <Table title="By model" rows={data.by_model} label={(r) => r.model} />
          <Table
            title="By feature"
            rows={data.by_source}
            label={(r) => SOURCE_LABELS[r.source] ?? r.source}
          />
          <Table
            title="By day"
            rows={[...data.by_day].reverse()}
            label={(r) => formatDate(r.day, "short")}
          />
        </div>
      )}
    </section>
  );
}

function Tile({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-gray-800 px-3 py-2">
      <div className="text-xs text-gray-500">{label}</div>
      <div className="text-gray-100">{children}</div>
    </div>
  );
}
