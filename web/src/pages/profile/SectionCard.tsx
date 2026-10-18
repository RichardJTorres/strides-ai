import { useState } from "react";
import type { ThemeConfig } from "../../App";
import type { Doc, SectionName } from "./types";

interface Props {
  id: string;
  title: string;
  /** Which coaching modes use this section, shown as a badge. */
  usedIn: string;
  section: SectionName;
  /** The keys of ``section`` this card owns; only these are saved by this card. */
  keys: string[];
  fields: Doc;
  saved: Doc;
  updated?: string | null;
  theme: ThemeConfig;
  onSaved: (section: SectionName, keys: string[], values: Doc) => void;
  children: React.ReactNode;
  /** Optional extra dirty/save hook for data that lives outside the profile (e.g. races). */
  hint?: string;
}

const pick = (doc: Doc, keys: string[]): Doc => Object.fromEntries(keys.map((k) => [k, doc[k]]));

function formatUpdated(ts?: string | null) {
  if (!ts) return "not saved yet";
  const d = new Date(ts.replace(" ", "T") + "Z");
  return Number.isNaN(d.getTime()) ? ts : `updated ${d.toLocaleDateString()}`;
}

/** A profile card with its own dirty state and Save, so editing one card never rewrites another. */
export default function SectionCard({
  id, title, usedIn, section, keys, fields, saved, updated, theme, onSaved, children, hint,
}: Props) {
  const [saving, setSaving] = useState(false);
  const [justSaved, setJustSaved] = useState(false);
  const [error, setError] = useState("");

  const current = pick(fields, keys);
  const dirty = JSON.stringify(current) !== JSON.stringify(pick(saved, keys));

  async function save() {
    setSaving(true);
    setError("");
    try {
      const res = await fetch(`/api/profile/${section}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fields: current }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(typeof body.detail === "string" ? body.detail.split("\n")[0] : "Save failed");
      }
      onSaved(section, keys, current);
      setJustSaved(true);
      setTimeout(() => setJustSaved(false), 2000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section id={id} className="rounded-lg border border-gray-800 bg-gray-900/40 p-5 scroll-mt-4">
      <div className="flex items-start justify-between gap-3 mb-4">
        <div>
          <h3 className="text-sm font-semibold text-gray-300">{title}</h3>
          <p className="text-[11px] text-gray-500 mt-0.5">
            Used in: {usedIn} · {formatUpdated(updated)}
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {justSaved && <span className={`text-xs ${theme.accentClass}`}>Saved!</span>}
          {dirty && !saving && <span className="text-xs text-amber-400">Unsaved</span>}
          <button
            onClick={save}
            disabled={saving || !dirty}
            className={`px-3 py-1 rounded-md ${theme.accentButton} text-white text-xs font-medium disabled:opacity-40 disabled:cursor-not-allowed transition-colors`}
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
      {error && <p className="text-xs text-red-400 mb-3">{error}</p>}
      {hint && <p className="text-xs text-gray-500 mb-3">{hint}</p>}
      {children}
    </section>
  );
}
