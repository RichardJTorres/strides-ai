import type { ThemeConfig } from "../App";
import { PENDING_CHAT_DRAFT_KEY } from "../pages/chatActivityHandoff";
import type { DigestMetric, InsightStatus, InsightsDigest } from "./api";
import { useInsights } from "./useInsights";
import { useUnits } from "../UnitsContext";

const STATUS_STYLE: Record<InsightStatus, { label: string; cls: string }> = {
  building: { label: "Building", cls: "bg-green-500/20 text-green-400" },
  maintaining: { label: "Maintaining", cls: "bg-blue-500/20 text-blue-400" },
  peaking: { label: "Peaking", cls: "bg-purple-500/20 text-purple-400" },
  overreaching: { label: "Overreaching", cls: "bg-red-500/20 text-red-400" },
  recovering: { label: "Recovering", cls: "bg-amber-500/20 text-amber-400" },
  detraining: { label: "Detraining", cls: "bg-amber-500/20 text-amber-400" },
  insufficient_data: { label: "Not enough data", cls: "bg-gray-700 text-gray-400" },
};

const TONE_DOT = {
  positive: "bg-green-400",
  neutral: "bg-gray-500",
  warning: "bg-amber-400",
} as const;

// Which digest metrics headline the stat strip, in order. Missing ones are skipped.
const TILE_IDS = ["volume.distance", "volume.ramp", "volume.freq", "load.ctl", "load.acwr"];

const ARROW = { up: "▲", down: "▼", flat: "▬" } as const;

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="bg-gray-800/60 rounded-md px-3 py-2 min-w-0">
      <div className="text-[11px] text-gray-500 leading-tight">{label}</div>
      <div className="text-gray-100 font-semibold tabular-nums">{value}</div>
      {sub && <div className="text-[11px] text-gray-500 tabular-nums leading-tight">{sub}</div>}
    </div>
  );
}

function metricSub(m: DigestMetric): string | undefined {
  if (!m.direction || m.baseline_formatted == null) return undefined;
  const change = m.delta_pct != null
    ? `${m.delta_pct > 0 ? "+" : ""}${m.delta_pct.toFixed(0)}%`
    : `${(m.delta ?? 0) > 0 ? "+" : ""}${(m.delta ?? 0).toFixed(1)} pts`;
  return `${ARROW[m.direction]} ${change} vs ${m.baseline_formatted}`;
}

function StatStrip({ digest }: { digest: InsightsDigest }) {
  const byId = new Map(digest.metrics.map((m) => [m.id, m]));
  const tiles = TILE_IDS.map((id) => byId.get(id)).filter((m): m is DigestMetric => !!m);
  const race = digest.context.next_race;
  const comp = digest.context.compliance;
  if (tiles.length === 0 && !race && !comp) return null;
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
      {tiles.map((m) => (
        <Tile key={m.id} label={m.label} value={m.formatted} sub={metricSub(m)} />
      ))}
      {race && (
        <Tile label={race.name} value={`${race.days_out} d`} sub={`race on ${race.date}`} />
      )}
      {!race && comp && comp.consistency_pct != null && (
        <Tile
          label={`Plan adherence (${comp.window_days} d)`}
          value={`${comp.consistency_pct.toFixed(0)}%`}
          sub={`${comp.completed + comp.modified}/${comp.scored} done`}
        />
      )}
    </div>
  );
}

interface Props {
  mode: string;
  theme: ThemeConfig;
}

export default function InsightsCard({ mode, theme }: Props) {
  const { system } = useUnits();
  const { data, loading, generating, error, generate } = useInsights(mode, system);

  const digest = data?.digest;
  const report = data?.report;
  const labels = new Map((digest?.metrics ?? []).map((m) => [m.id, m.label]));
  const status = report ? STATUS_STYLE[report.status] : null;
  const generatedAt = data?.generated_at
    ? new Date(data.generated_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })
    : null;

  return (
    <section className="bg-gray-900 rounded-lg border border-gray-800 p-5 space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-gray-100 font-semibold">Training Insights</h3>
        {status && (
          <span className={`text-[11px] font-medium px-2 py-0.5 rounded-full ${status.cls}`}>
            {status.label}
          </span>
        )}
        {data?.stale && (
          <span className="text-[11px] px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-300">
            New data since this was generated
          </span>
        )}
        {report && (
          <button
            onClick={() => generate(true)}
            disabled={generating}
            className="ml-auto text-xs text-gray-500 hover:text-gray-300 disabled:opacity-50"
          >
            {generating ? "Refreshing…" : "Refresh"}
          </button>
        )}
      </div>

      <>
          <p className="text-gray-500 text-xs -mt-2">
            Last 4 weeks vs prior 8
            {generatedAt && ` · generated ${generatedAt}`}
            {data?.model && ` · ${data.model}`}
          </p>

          {loading && <p className="text-gray-500 text-sm animate-pulse">Loading insights…</p>}

          {digest && <StatStrip digest={digest} />}

          {digest && !digest.sufficient && (
            <p className="text-gray-400 text-sm">
              Not enough recent training data yet — insights need at least 6 activities across 3
              completed weeks.
            </p>
          )}

          {report && (
            <div className="space-y-4">
              {report.headline && <p className="text-gray-200 text-sm">{report.headline}</p>}

              {report.findings.length > 0 && (
                <div>
                  <h4 className="text-xs uppercase tracking-wide text-gray-500 mb-2">Findings</h4>
                  <ul className="space-y-2.5">
                    {report.findings.map((f, i) => (
                      <li key={i} className="flex gap-2.5">
                        <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${TONE_DOT[f.tone]}`} />
                        <div className="min-w-0">
                          <div className="text-sm text-gray-100 font-medium">{f.title}</div>
                          <div className="text-sm text-gray-400">{f.detail}</div>
                          {f.metric_ids.length > 0 && (
                            <div className="mt-1 flex flex-wrap gap-1">
                              {f.metric_ids.map((id) => (
                                <span key={id} className="text-[10px] text-gray-500 bg-gray-800 rounded px-1.5 py-0.5">
                                  {labels.get(id) ?? id}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {report.recommendations.length > 0 && (
                <div>
                  <h4 className="text-xs uppercase tracking-wide text-gray-500 mb-2">Do next</h4>
                  <ol className="space-y-2">
                    {report.recommendations.map((r, i) => (
                      <li key={i} className="flex gap-2.5 text-sm">
                        <span className={`${theme.accentClass} font-semibold tabular-nums`}>{i + 1}.</span>
                        <div>
                          <span className="text-gray-100">{r.action}</span>
                          {r.why && <span className="text-gray-500"> — {r.why}</span>}
                          <div className="mt-1 flex gap-3 text-xs">
                            <button
                              className="text-gray-400 hover:text-gray-200 underline"
                              onClick={() => {
                                try {
                                  sessionStorage.setItem(
                                    PENDING_CHAT_DRAFT_KEY,
                                    `Update my training calendar to follow this recommendation` +
                                      `${r.date ? ` (${r.date})` : ""}: ${r.action}. ` +
                                      "Work around my planned workouts, races and blocked-out days.",
                                  );
                                } catch { /* best-effort handoff */ }
                                location.hash = "chat";
                              }}
                            >
                              Plan this with coach
                            </button>
                            {r.date && (
                              <a href="#calendar" className="text-gray-500 hover:text-gray-300">
                                {r.date} on calendar →
                              </a>
                            )}
                          </div>
                        </div>
                      </li>
                    ))}
                  </ol>
                </div>
              )}
            </div>
          )}

          {digest?.sufficient && !report && !loading && (
            <div className="flex items-center gap-3">
              <button
                onClick={() => generate(false)}
                disabled={generating}
                className={`${theme.accentButton} text-white text-sm px-3 py-1.5 rounded-md disabled:opacity-60`}
              >
                {generating ? "Analyzing…" : "Generate insights"}
              </button>
              {generating && (
                <span className="text-xs text-gray-500">This may take 10–20 seconds.</span>
              )}
            </div>
          )}

          {report && generating && (
            <p className="text-xs text-gray-500 animate-pulse">Analyzing… this may take 10–20 seconds.</p>
          )}

          {error && <p className="text-sm text-red-400">Insights failed: {error}</p>}
      </>
    </section>
  );
}
