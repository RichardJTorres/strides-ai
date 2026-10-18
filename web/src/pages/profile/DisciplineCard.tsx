import { useUnits } from "../../UnitsContext";
import { Field, TextArea, inputClass } from "./fields";
import SectionCard from "./SectionCard";
import {
  DISCIPLINE_MODES,
  DISCIPLINE_SPECS,
  type CardContext,
  type Discipline,
  type Doc,
} from "./types";
import type { ThemeConfig } from "../../App";

const KEYS = ["since", "volume", "focus", "background", "bests", "gear"];

interface Props extends CardContext {
  discipline: Discipline;
  saved: Doc;
  updated?: string | null;
  theme: ThemeConfig;
  onSaved: (section: Discipline, keys: string[], values: Doc) => void;
}

/** One card for a discipline (running / cycling / lifting), driven by DISCIPLINE_SPECS. */
export default function DisciplineCard({
  discipline, fields, saved, updated, theme, focusClass, setPath, onSaved,
}: Props) {
  const { system } = useUnits();
  const spec = DISCIPLINE_SPECS[discipline];
  const d: Doc = fields[discipline] ?? {};
  const set = (key: string, v: unknown) => setPath([discipline, key], v);

  return (
    <SectionCard
      id={`profile-${discipline}`}
      title={spec.title}
      usedIn={DISCIPLINE_MODES[discipline]}
      section={discipline}
      keys={KEYS}
      fields={d}
      saved={saved[discipline] ?? {}}
      updated={updated}
      theme={theme}
      onSaved={(s, keys, values) => onSaved(discipline, keys, values)}
    >
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <Field label={spec.sinceLabel} value={d.since ?? ""} onChange={(v) => set("since", v)} placeholder={spec.sincePlaceholder} focusClass={focusClass} />
          <Field label={spec.volumeLabel} value={d.volume ?? ""} onChange={(v) => set("volume", v)} placeholder={spec.volumePlaceholder(system)} focusClass={focusClass} />
          <div className="col-span-2 flex flex-col gap-1">
            <label className="text-xs font-medium text-gray-400">{spec.focusLabel}</label>
            <select
              value={d.focus ?? ""}
              onChange={(e) => set("focus", e.target.value)}
              className={`${inputClass} ${focusClass}`}
            >
              <option value="">Select…</option>
              {spec.focusOptions.map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </div>
        </div>
        <TextArea label="Background" value={d.background ?? ""} onChange={(v) => set("background", v)} placeholder={spec.backgroundPlaceholder} rows={3} focusClass={focusClass} />
        <div>
          <p className="text-xs font-medium text-gray-400 mb-2">Personal bests</p>
          <div className="grid grid-cols-2 gap-4">
            {spec.bests.map((b) => (
              <Field
                key={b.key}
                label={b.label}
                value={d.bests?.[b.key] ?? ""}
                onChange={(v) => setPath([discipline, "bests"], { ...d.bests, [b.key]: v })}
                placeholder={b.placeholder}
                focusClass={focusClass}
              />
            ))}
          </div>
        </div>
        <TextArea label={spec.gearLabel} value={d.gear ?? ""} onChange={(v) => set("gear", v)} placeholder={spec.gearPlaceholder(system)} rows={2} focusClass={focusClass} />
      </div>
    </SectionCard>
  );
}
