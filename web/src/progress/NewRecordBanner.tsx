import { useState } from "react";
import { hrefFor } from "../nav";
import { SPORTS_BY_MODE, useProgress } from "./api";

const SEEN_KEY = "seen_records";

function readSeen(): string[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(SEEN_KEY) ?? "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

/**
 * One line announcing personal records set in the last two weeks that the athlete has not
 * dismissed yet. A record is identified by what it is and when it was set, so beating it again
 * announces it again. Dismissal is remembered in this browser.
 */
export default function NewRecordBanner({ mode }: { mode: string }) {
  const { data } = useProgress();
  const [seen, setSeen] = useState(readSeen);
  const sports = SPORTS_BY_MODE[mode] ?? [];
  const fresh = (data?.records ?? []).filter(
    (r) => r.is_new && sports.includes(r.sport) && !seen.includes(`${r.id}:${r.date}`),
  );
  if (fresh.length === 0) return null;

  const dismiss = () => {
    // Keep the list short: only the most recent dismissals can still be "new".
    const next = [...seen, ...fresh.map((r) => `${r.id}:${r.date}`)].slice(-50);
    setSeen(next);
    try {
      localStorage.setItem(SEEN_KEY, JSON.stringify(next));
    } catch { /* not remembered across reloads, but dismissed for now */ }
  };

  return (
    <div
      role="status"
      className="flex items-center gap-3 border-b border-yellow-500/30 bg-yellow-500/10 pl-4 pr-14 py-2 text-sm text-yellow-100"
    >
      <span className="min-w-0 flex-1">
        <span className="font-medium">New personal record{fresh.length === 1 ? "" : "s"}: </span>
        {fresh.map((r) => `${r.label} ${r.formatted}`).join(" · ")}
      </span>
      <a href={hrefFor("analytics", "progress")} className="shrink-0 underline hover:text-white">
        See records
      </a>
      <button onClick={dismiss} className="shrink-0 text-yellow-200/70 hover:text-white">
        Dismiss
      </button>
    </div>
  );
}
