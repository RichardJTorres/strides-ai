import { useEffect, useState } from "react";
import { useUnits } from "../../UnitsContext";
import type { ThemeConfig } from "../../App";
import { Field, HeightInput, MeasuredInput, PLACEHOLDERS, SnacksList, TextArea, inputClass } from "./fields";
import SectionCard from "./SectionCard";
import type { CardContext, Doc, Race, SectionName } from "./types";

interface Props extends CardContext {
  saved: Doc;
  updated?: string | null;
  onSaved: (section: SectionName, keys: string[], values: Doc) => void;
  /** Rendered between "Goals & schedule" and "Injuries & health" (the active discipline cards). */
  afterGoals?: React.ReactNode;
}

const WEEKDAYS: [string, string][] = [
  ["mon", "Mon"], ["tue", "Tue"], ["wed", "Wed"], ["thu", "Thu"], ["fri", "Fri"], ["sat", "Sat"], ["sun", "Sun"],
];
const ALL = "All modes";

/** Races live in the calendar prefs (shared with the Calendar page), not the profile row. */
function RaceList({ theme, focusClass }: { theme: ThemeConfig; focusClass: string }) {
  const [prefs, setPrefs] = useState<{ blocked_days: string[]; races: Race[] } | null>(null);
  const [form, setForm] = useState({ date: "", name: "", target_time: "" });

  useEffect(() => {
    fetch("/api/calendar/prefs").then((r) => r.json()).then(setPrefs).catch(() => setPrefs(null));
  }, []);

  async function persist(races: Race[]) {
    if (!prefs) return;
    const next = { ...prefs, races };
    setPrefs(next);
    await fetch("/api/calendar/prefs", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(next),
    });
  }

  function add() {
    if (!prefs || !form.date || !form.name) return;
    const race: Race = { date: form.date, name: form.name };
    if (form.target_time) race.target_time = form.target_time;
    persist([...prefs.races, race].sort((a, b) => a.date.localeCompare(b.date)));
    setForm({ date: "", name: "", target_time: "" });
  }

  if (!prefs) return null;
  return (
    <div className="flex flex-col gap-2">
      <label className="text-xs font-medium text-gray-400">
        Upcoming races — shared with the Calendar; saved as soon as you add or remove one
      </label>
      {prefs.races.map((r) => (
        <div key={`${r.date}-${r.name}`} className="flex items-center justify-between rounded-md border border-gray-800 px-3 py-1.5 text-sm text-gray-200">
          <span>
            <span className="text-gray-500 mr-2">{r.date}</span>
            {r.name}
            {r.target_time && <span className="text-gray-500"> · target {r.target_time}</span>}
          </span>
          <button
            onClick={() => persist(prefs.races.filter((x) => !(x.date === r.date && x.name === r.name)))}
            className="text-gray-500 hover:text-red-400"
            aria-label={`Remove ${r.name}`}
          >
            ×
          </button>
        </div>
      ))}
      <div className="flex gap-2 flex-wrap">
        <input type="date" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} className={`${inputClass} ${focusClass}`} aria-label="Race date" />
        <input type="text" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Race name" className={`${inputClass} ${focusClass} flex-1 min-w-32`} />
        <input type="text" value={form.target_time} onChange={(e) => setForm({ ...form, target_time: e.target.value })} placeholder="Target time" className={`${inputClass} ${focusClass} w-28`} />
        <button onClick={add} disabled={!form.date || !form.name} className={`px-3 py-2 rounded-md ${theme.accentButton} text-white text-sm disabled:opacity-40`}>
          Add race
        </button>
      </div>
    </div>
  );
}

export default function SharedSections({ fields, saved, updated, theme, focusClass, setPath, onSaved, afterGoals }: Props) {
  const { system } = useUnits();
  const personal: Doc = fields.personal ?? {};
  const avail: Doc = fields.availability ?? {};
  const common = { section: "shared" as const, fields, saved, updated, theme, onSaved };
  const setAvail = (key: string, v: unknown) => setPath(["availability"], { ...avail, [key]: v });
  const days: string[] = avail.preferred_days ?? [];

  return (
    <>
      <SectionCard {...common} id="profile-you" title="You" usedIn={ALL} keys={["personal"]}>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Name" value={personal.name ?? ""} onChange={(v) => setPath(["personal"], { ...personal, name: v })} focusClass={focusClass} />
          <Field label="Gender" value={personal.gender ?? ""} onChange={(v) => setPath(["personal"], { ...personal, gender: v })} focusClass={focusClass} />
          <Field label="Date of birth" value={personal.date_of_birth ?? ""} onChange={(v) => setPath(["personal"], { ...personal, date_of_birth: v })} placeholder="e.g. 1990-05-15" focusClass={focusClass} />
          <HeightInput value={personal.height_cm} onChange={(cm) => setPath(["personal"], { ...personal, height_cm: cm })} focusClass={focusClass} />
          <MeasuredInput label="Weight" value={personal.weight_kg} qty="mass" decimals={1} placeholder={system === "imperial" ? "e.g. 155" : "e.g. 70"} onChange={(kg) => setPath(["personal"], { ...personal, weight_kg: kg })} focusClass={focusClass} />
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-gray-400">Max heart rate (bpm)</label>
            <input
              type="number" min="60" max="250" step="1" placeholder="e.g. 185"
              value={personal.max_hr ?? ""}
              onChange={(e) => {
                const n = parseInt(e.target.value, 10);
                setPath(["personal"], { ...personal, max_hr: Number.isNaN(n) ? null : n });
              }}
              className={`${inputClass} ${focusClass}`}
            />
          </div>
          {personal.body_notes && (
            <div className="col-span-2">
              <Field label="Body notes (couldn't be read as a number — move the values above if you like)" value={personal.body_notes} onChange={(v) => setPath(["personal"], { ...personal, body_notes: v })} focusClass={focusClass} />
            </div>
          )}
        </div>
      </SectionCard>

      <SectionCard {...common} id="profile-goals" title="Goals & schedule" usedIn={ALL} keys={["goals", "availability"]}>
        <div className="space-y-4">
          <TextArea label="Long-term goals" value={fields.goals ?? ""} onChange={(v) => setPath(["goals"], v)} placeholder="e.g. Sub-4 marathon at Berlin in September, then a 200 km gravel event…" rows={3} focusClass={focusClass} />
          <RaceList theme={theme} focusClass={focusClass} />
          <div className="grid grid-cols-2 gap-4">
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-gray-400">Sessions per week (all sports)</label>
              <input
                type="number" min="0" max="21" step="1" placeholder="e.g. 5"
                value={avail.sessions_per_week ?? ""}
                onChange={(e) => {
                  const n = parseInt(e.target.value, 10);
                  setAvail("sessions_per_week", Number.isNaN(n) ? null : n);
                }}
                className={`${inputClass} ${focusClass}`}
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-gray-400">Long session day</label>
              <select value={avail.long_session_day ?? ""} onChange={(e) => setAvail("long_session_day", e.target.value)} className={`${inputClass} ${focusClass}`}>
                <option value="">No preference</option>
                {WEEKDAYS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </div>
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-xs font-medium text-gray-400">Days you can train</span>
            <div className="flex gap-2 flex-wrap">
              {WEEKDAYS.map(([v, l]) => {
                const on = days.includes(v);
                return (
                  <button
                    key={v} type="button" aria-pressed={on}
                    onClick={() => setAvail("preferred_days", on ? days.filter((d) => d !== v) : [...days, v])}
                    className={`px-3 py-1 rounded-full border text-sm transition-colors ${on ? `${theme.accentBg} ${theme.accentClass} ${theme.accentBorder}` : "border-gray-700 text-gray-400 hover:bg-gray-800"}`}
                  >
                    {l}
                  </button>
                );
              })}
            </div>
          </div>
          <Field label="Schedule notes" value={avail.notes ?? ""} onChange={(v) => setAvail("notes", v)} placeholder="e.g. Weekday sessions max 60 min; travel most of March" focusClass={focusClass} />
        </div>
      </SectionCard>

      {afterGoals}

      <SectionCard {...common} id="profile-health" title="Injuries & health" usedIn={ALL} keys={["injuries_and_health"]}>
        <TextArea label="Current or recurring injuries, medical conditions" value={fields.injuries_and_health ?? ""} onChange={(v) => setPath(["injuries_and_health"], v)} placeholder={PLACEHOLDERS[system].injuries} rows={3} focusClass={focusClass} />
      </SectionCard>

      <SectionCard {...common} id="profile-nutrition" title="Nutrition & snacks" usedIn={ALL} keys={["nutrition_snacks"]}>
        <SnacksList snacks={Array.isArray(fields.nutrition_snacks) ? fields.nutrition_snacks : []} onChange={(v) => setPath(["nutrition_snacks"], v)} focusClass={focusClass} />
      </SectionCard>

      <SectionCard {...common} id="profile-notes" title="Other notes" usedIn={ALL} keys={["other_notes"]}>
        <TextArea label="Training preferences, coaching style, anything else" value={fields.other_notes ?? ""} onChange={(v) => setPath(["other_notes"], v)} placeholder="e.g. Prefer easy effort on weekdays, long run Saturday mornings…" rows={3} focusClass={focusClass} />
      </SectionCard>
    </>
  );
}
