import { useCallback, useEffect, useState } from "react";
import type { Mode, ThemeConfig } from "../../App";
import Completeness from "./Completeness";
import DisciplineCard from "./DisciplineCard";
import SharedSections from "./SharedSections";
import {
  DISCIPLINE_SPECS,
  type Discipline,
  type Doc,
  type ProfileResponse,
  type SectionName,
} from "./types";

interface Props {
  mode: Mode;
  theme: ThemeConfig;
}

const NAV: { id: string; label: string }[] = [
  { id: "profile-you", label: "You" },
  { id: "profile-goals", label: "Goals & schedule" },
];

export default function ProfilePage({ mode, theme }: Props) {
  const [data, setData] = useState<ProfileResponse | null>(null);
  const [fields, setFields] = useState<Doc>({});
  const [saved, setSaved] = useState<Doc>({});
  const [error, setError] = useState("");

  const load = useCallback(() => {
    return fetch(`/api/profile?mode=${mode}`)
      .then((r) => {
        if (!r.ok) throw new Error("Could not load profile");
        return r.json() as Promise<ProfileResponse>;
      })
      .then((d) => {
        setData(d);
        setFields(d.fields);
        setSaved(d.fields);
        setError("");
      })
      .catch((e) => setError(e.message));
  }, [mode]);

  useEffect(() => {
    setData(null);
    load();
  }, [load]);

  // Path is [key] for shared fields or [discipline, key] for a discipline field.
  const setPath = useCallback((path: string[], value: unknown) => {
    setFields((f) =>
      path.length === 1 ? { ...f, [path[0]]: value } : { ...f, [path[0]]: { ...f[path[0]], [path[1]]: value } },
    );
  }, []);

  // After a card saves, adopt its values as the new baseline and refresh server-derived data
  // (completeness, "updated" timestamps) without touching other cards' unsaved edits.
  const onSaved = useCallback((section: SectionName, keys: string[], values: Doc) => {
    setSaved((s) =>
      section === "shared" ? { ...s, ...values } : { ...s, [section]: { ...s[section], ...values } },
    );
    fetch(`/api/profile?mode=${mode}`)
      .then((r) => r.json())
      .then((d: ProfileResponse) => setData((prev) => (prev ? { ...prev, completeness: d.completeness, updated: d.updated } : d)));
  }, [mode]);

  if (error) {
    return <div className="flex-1 flex items-center justify-center text-red-400 text-sm">{error}</div>;
  }
  if (!data) {
    return <div className="flex-1 flex items-center justify-center text-gray-500 text-sm">Loading…</div>;
  }

  const focusClass = theme.accentFocus;
  const { active, other } = data.mode_sections;
  const ctx = { fields, setPath, theme, focusClass };
  const nav = [
    ...NAV,
    ...active.map((d) => ({ id: `profile-${d}`, label: DISCIPLINE_SPECS[d].title })),
    { id: "profile-health", label: "Injuries & health" },
    { id: "profile-nutrition", label: "Nutrition" },
    { id: "profile-notes", label: "Notes" },
    ...(other.length > 0 ? [{ id: "profile-other-training", label: "Other training" }] : []),
  ];
  const jump = (id: string) => {
    const el = document.getElementById(id);
    if (el instanceof HTMLDetailsElement) el.open = true; // expand collapsed sections on jump
    el?.scrollIntoView({ behavior: "smooth" });
  };

  return (
    <div className="flex flex-col h-full">
      <div className="px-6 py-4 border-b border-gray-800">
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-semibold text-gray-100">Athlete Profile</h2>
          <span className={`text-xs px-2 py-0.5 rounded-full ${theme.accentBg} ${theme.accentClass}`}>{theme.label}</span>
        </div>
        <p className="text-xs text-gray-500 mt-0.5">
          One profile for every coaching mode. Your {theme.label.toLowerCase()} sees everything here, with
          your {active.join(" + ")} details in full and your other training summarised.
        </p>
      </div>

      <div className="flex-1 overflow-y-auto">
        <div className="max-w-5xl mx-auto p-6 flex gap-6">
          <nav className="hidden lg:block w-40 shrink-0 sticky top-0 self-start">
            <ul className="space-y-1 text-sm">
              {nav.map((n) => (
                <li key={n.id}>
                  <button onClick={() => jump(n.id)} className="text-gray-400 hover:text-gray-100 text-left w-full py-1">
                    {n.label}
                  </button>
                </li>
              ))}
            </ul>
          </nav>

          <div className="flex-1 min-w-0 space-y-4">
            <Completeness data={data.completeness} theme={theme} />
            <SharedSections
              {...ctx} saved={saved} updated={data.updated.shared} onSaved={onSaved}
              afterGoals={active.map((d) => (
                <DisciplineCard key={d} discipline={d} {...ctx} saved={saved} updated={data.updated[d]} onSaved={onSaved} />
              ))}
            />
            {other.length > 0 && (
              <details id="profile-other-training" className="rounded-lg border border-gray-800 scroll-mt-4">
                <summary className="px-5 py-3 cursor-pointer text-sm font-semibold text-gray-300">
                  Other training ({other.map((d) => DISCIPLINE_SPECS[d].title).join(", ")})
                </summary>
                <p className="px-5 text-xs text-gray-500">
                  Your {theme.label.toLowerCase()} sees a one-line summary of these under "Also trains".
                </p>
                <div className="p-4 space-y-4">
                  {other.map((d: Discipline) => (
                    <DisciplineCard key={d} discipline={d} {...ctx} saved={saved} updated={data.updated[d]} onSaved={onSaved} />
                  ))}
                </div>
              </details>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
