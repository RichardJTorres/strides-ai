import { useState } from "react";
import type { ThemeConfig } from "../../App";
import type { Doc, SectionName } from "./types";

export interface ProfileProposal {
  section: SectionName;
  label: string;
  op: "set" | "append";
  current: unknown;
  proposed: unknown;
  /** Exact body for PUT /api/profile/{section}. */
  fields: Doc;
}

const show = (v: unknown) =>
  v == null || v === "" ? "—" : Array.isArray(v) ? v.join(", ") : String(v);

/** Accept/Dismiss cards for profile changes the coach proposed via update_profile. */
export default function ProposalCards({
  proposals, theme,
}: { proposals: ProfileProposal[]; theme: ThemeConfig }) {
  // index -> "accepted" | "dismissed" | error message
  const [status, setStatus] = useState<Record<number, string>>({});

  async function accept(i: number, p: ProfileProposal) {
    try {
      const res = await fetch(`/api/profile/${p.section}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fields: p.fields }),
      });
      setStatus((s) => ({ ...s, [i]: res.ok ? "accepted" : "error" }));
    } catch {
      setStatus((s) => ({ ...s, [i]: "error" }));
    }
  }

  return (
    <div className="mt-3 space-y-2">
      {proposals.map((p, i) => {
        const st = status[i];
        return (
          <div key={i} className="rounded-lg border border-gray-700 bg-gray-900/60 px-4 py-3 text-sm">
            <p className="text-xs text-gray-500 mb-1">Profile change suggested by your coach</p>
            <p className="text-gray-200">
              <span className="font-medium">{p.label}</span>
              {p.op === "append" ? " (add)" : ""}: <span className={theme.accentClass}>{show(p.proposed)}</span>
            </p>
            {p.current != null && <p className="text-xs text-gray-500">Currently: {show(p.current)}</p>}
            <div className="mt-2 flex items-center gap-2">
              {st === "accepted" && <span className={`text-xs ${theme.accentClass}`}>Saved to your profile</span>}
              {st === "dismissed" && <span className="text-xs text-gray-500">Dismissed</span>}
              {st === "error" && <span className="text-xs text-red-400">Couldn't save — edit it on the Profile page</span>}
              {(!st || st === "error") && (
                <>
                  <button onClick={() => accept(i, p)} className={`px-3 py-1 rounded-md ${theme.accentButton} text-white text-xs font-medium`}>
                    Accept
                  </button>
                  <button onClick={() => setStatus((s) => ({ ...s, [i]: "dismissed" }))} className="px-3 py-1 rounded-md border border-gray-700 text-gray-400 text-xs hover:bg-gray-800">
                    Dismiss
                  </button>
                </>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
