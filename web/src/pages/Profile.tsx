import { useEffect, useRef, useState } from "react";
import type { Mode, ThemeConfig } from "../App";
import { useUnits } from "../UnitsContext";
import { CM_PER_INCH, feetInches, type Quantity, type UnitSystem } from "../units";

interface Props {
  mode: Mode;
  theme: ThemeConfig;
}

// ── Field components ──────────────────────────────────────────────────────────

// Profile fields are free text the athlete writes, so they are never converted; only the
// example placeholders follow the unit setting.
const PLACEHOLDERS: Record<UnitSystem, Record<string, string>> = {
  metric: {
    injuries: "e.g. Left IT band niggle when mileage exceeds 60 km/week…",
    gear: "e.g. Nike Vaporfly (~400 km), Garmin Forerunner 955…",
    runVolume: "e.g. 50 km/week",
    rideVolume: "e.g. 150 km/week",
  },
  imperial: {
    injuries: "e.g. Left IT band niggle when mileage exceeds 40 mi/week…",
    gear: "e.g. Nike Vaporfly (~250 mi), Garmin Forerunner 955…",
    runVolume: "e.g. 30 mi/week",
    rideVolume: "e.g. 90 mi/week",
  },
};

const inputClass =
  "rounded-md bg-gray-900 border border-gray-700 px-3 py-2 text-sm text-gray-100 placeholder-gray-600 focus:outline-none";

/**
 * Number input for a value stored in SI (personal.weight_kg, ...), shown in the athlete's units.
 * The text the athlete types is kept as a draft and only written back when edited, so an
 * untouched field never drifts through a round-trip conversion (77 kg -> 169.8 lb -> 77.02 kg).
 */
function MeasuredInput({
  label,
  value,
  qty,
  decimals,
  placeholder,
  onChange,
  focusClass,
}: {
  label: string;
  value: number | null | undefined;
  qty: Quantity;
  decimals: number;
  placeholder?: string;
  onChange: (si: number | null) => void;
  focusClass: string;
}) {
  const units = useUnits();
  const display = (si: number | null | undefined) =>
    si == null ? "" : String(Number(units.convert(si, qty)!.toFixed(decimals)));
  const [draft, setDraft] = useState(() => display(value));
  const lastSI = useRef(value ?? null);

  // Re-sync the draft when the value is replaced from outside (load, reset) or units change.
  useEffect(() => {
    if ((value ?? null) !== lastSI.current) {
      lastSI.current = value ?? null;
      setDraft(display(value));
    }
  }, [value]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => setDraft(display(lastSI.current)), [units.system]); // eslint-disable-line react-hooks/exhaustive-deps

  function handle(text: string) {
    setDraft(text);
    const n = parseFloat(text);
    const si = text.trim() === "" || Number.isNaN(n) ? null : units.toSI(n, qty);
    lastSI.current = si;
    onChange(si);
  }

  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-medium text-gray-400">
        {label} ({units.label(qty)})
      </label>
      <input
        type="number"
        min="0"
        step="any"
        value={draft}
        onChange={(e) => handle(e.target.value)}
        placeholder={placeholder}
        className={`${inputClass} ${focusClass}`}
      />
    </div>
  );
}

/** Body height: one cm field in metric, feet + inches in imperial. Stored as personal.height_cm. */
function HeightInput({
  value,
  onChange,
  focusClass,
}: {
  value: number | null | undefined;
  onChange: (cm: number | null) => void;
  focusClass: string;
}) {
  const { system } = useUnits();
  const split = (cm: number | null | undefined) => {
    if (cm == null) return { ft: "", inch: "" };
    const [ft, inch] = feetInches(cm);
    return { ft: String(ft), inch: String(inch) };
  };
  const [draft, setDraft] = useState(() => split(value));
  const lastCm = useRef(value ?? null);

  useEffect(() => {
    if ((value ?? null) !== lastCm.current) {
      lastCm.current = value ?? null;
      setDraft(split(value));
    }
  }, [value]);

  if (system === "metric") {
    return (
      <MeasuredInput
        label="Height"
        value={value}
        qty="height"
        decimals={0}
        placeholder="e.g. 175"
        onChange={(cm) => {
          lastCm.current = cm;
          setDraft(split(cm));
          onChange(cm);
        }}
        focusClass={focusClass}
      />
    );
  }

  function handle(next: { ft: string; inch: string }) {
    setDraft(next);
    const ft = parseFloat(next.ft);
    const inch = parseFloat(next.inch);
    const cm =
      Number.isNaN(ft) && Number.isNaN(inch)
        ? null
        : ((Number.isNaN(ft) ? 0 : ft) * 12 + (Number.isNaN(inch) ? 0 : inch)) * CM_PER_INCH;
    lastCm.current = cm;
    onChange(cm);
  }

  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-medium text-gray-400">Height (ft / in)</label>
      <div className="flex gap-2">
        <input
          type="number" min="0" step="1" placeholder="5" aria-label="Height, feet"
          value={draft.ft}
          onChange={(e) => handle({ ...draft, ft: e.target.value })}
          className={`${inputClass} ${focusClass} w-1/2`}
        />
        <input
          type="number" min="0" max="11" step="1" placeholder="9" aria-label="Height, inches"
          value={draft.inch}
          onChange={(e) => handle({ ...draft, inch: e.target.value })}
          className={`${inputClass} ${focusClass} w-1/2`}
        />
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  placeholder,
  focusClass,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  focusClass: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-medium text-gray-400">{label}</label>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className={`rounded-md bg-gray-900 border border-gray-700 px-3 py-2 text-sm text-gray-100 placeholder-gray-600 focus:outline-none ${focusClass}`}
      />
    </div>
  );
}

function TextArea({
  label,
  value,
  onChange,
  placeholder,
  rows = 4,
  focusClass,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  rows?: number;
  focusClass: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-medium text-gray-400">{label}</label>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        rows={rows}
        className={`rounded-md bg-gray-900 border border-gray-700 px-3 py-2 text-sm text-gray-100 placeholder-gray-600 focus:outline-none ${focusClass} resize-y`}
      />
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900/40 p-5">
      <h3 className="text-sm font-semibold text-gray-300 mb-4">{title}</h3>
      {children}
    </div>
  );
}

// ── Snacks list ───────────────────────────────────────────────────────────────

function SnacksList({
  snacks,
  onChange,
  focusClass,
}: {
  snacks: string[];
  onChange: (v: string[]) => void;
  focusClass: string;
}) {
  const [input, setInput] = useState("");

  function add() {
    const val = input.trim();
    if (!val || snacks.includes(val)) return;
    onChange([...snacks, val]);
    setInput("");
  }

  function remove(i: number) {
    onChange(snacks.filter((_, idx) => idx !== i));
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter") {
      e.preventDefault();
      add();
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <label className="text-xs font-medium text-gray-400">
        Preferred snacks &amp; fuel — the coach will pick from this list when suggesting nutrition loadouts
      </label>
      {snacks.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {snacks.map((s, i) => (
            <span
              key={i}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-gray-800 border border-gray-700 text-sm text-gray-200"
            >
              {s}
              <button
                type="button"
                onClick={() => remove(i)}
                className="text-gray-500 hover:text-red-400 transition-colors leading-none"
                aria-label={`Remove ${s}`}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="e.g. Maurten Gel 100, Clif Bar, Medjool dates…"
          className={`flex-1 rounded-md bg-gray-900 border border-gray-700 px-3 py-2 text-sm text-gray-100 placeholder-gray-600 focus:outline-none ${focusClass}`}
        />
        <button
          type="button"
          onClick={add}
          disabled={!input.trim()}
          className="px-3 py-2 rounded-md bg-gray-700 hover:bg-gray-600 text-gray-200 text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          Add
        </button>
      </div>
    </div>
  );
}

// ── Common lower sections ─────────────────────────────────────────────────────

function CommonSections({
  fields,
  setFields,
  setFieldsRaw,
  focusClass,
}: {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  fields: Record<string, any>;
  setFields: (key: string, val: string) => void;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  setFieldsRaw: (key: string, val: any) => void;
  focusClass: string;
}) {
  const { system } = useUnits();
  return (
    <>
      <Section title="Goals">
        <TextArea
          label="Upcoming races, time targets, other goals"
          value={fields.goals ?? ""}
          onChange={(v) => setFields("goals", v)}
          placeholder="e.g. Sub-4 marathon at Berlin in September…"
          rows={3}
          focusClass={focusClass}
        />
      </Section>
      <Section title="Injuries & Health">
        <TextArea
          label="Current or recurring injuries, medical conditions"
          value={fields.injuries_and_health ?? ""}
          onChange={(v) => setFields("injuries_and_health", v)}
          placeholder={PLACEHOLDERS[system].injuries}
          rows={3}
          focusClass={focusClass}
        />
      </Section>
      <Section title="Gear">
        <TextArea
          label="Shoes, watch, other kit"
          value={fields.gear ?? ""}
          onChange={(v) => setFields("gear", v)}
          placeholder={PLACEHOLDERS[system].gear}
          rows={3}
          focusClass={focusClass}
        />
      </Section>
      <Section title="Nutrition & Snacks">
        <SnacksList
          snacks={Array.isArray(fields.nutrition_snacks) ? fields.nutrition_snacks : []}
          onChange={(v) => setFieldsRaw("nutrition_snacks", v)}
          focusClass={focusClass}
        />
      </Section>
      <Section title="Other Notes">
        <TextArea
          label="Training preferences, coaching style, anything else"
          value={fields.other_notes ?? ""}
          onChange={(v) => setFields("other_notes", v)}
          placeholder="e.g. Prefer easy effort on weekdays, long run Saturday mornings…"
          rows={3}
          focusClass={focusClass}
        />
      </Section>
    </>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export default function Profile({ mode, theme }: Props) {
  const { system } = useUnits();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [fields, setFields] = useState<Record<string, any>>({});
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [original, setOriginal] = useState<Record<string, any>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);

  useEffect(() => {
    setLoading(true);
    setSaved(false);
    fetch(`/api/profile?mode=${mode}`)
      .then((r) => r.json())
      .then(({ fields: f }) => {
        setFields(f ?? {});
        setOriginal(f ?? {});
      })
      .finally(() => setLoading(false));
  }, [mode]);

  async function handleSave() {
    setSaving(true);
    setSaved(false);
    try {
      await fetch(`/api/profile?mode=${mode}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fields }),
      });
      setOriginal(fields);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } finally {
      setSaving(false);
    }
  }

  async function handleReset() {
    setResetting(true);
    try {
      const data = await fetch(`/api/profile/reset?mode=${mode}`, { method: "POST" }).then((r) => r.json());
      setFields(data.fields ?? {});
      setOriginal(data.fields ?? {});
      setConfirmReset(false);
    } finally {
      setResetting(false);
    }
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  function setNested(section: string, key: string, val: string | number | null) {
    setFields((f) => ({ ...f, [section]: { ...f[section], [key]: val } }));
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  function setTop(key: string, val: any) {
    setFields((f) => ({ ...f, [key]: val }));
  }

  const focusClass = theme.accentFocus;
  const dirty = JSON.stringify(fields) !== JSON.stringify(original);

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-semibold text-gray-100">Athlete Profile</h2>
            <span className={`text-xs px-2 py-0.5 rounded-full ${theme.accentBg} ${theme.accentClass}`}>
              {theme.label}
            </span>
          </div>
          <p className="text-xs text-gray-500 mt-0.5">
            Loaded fresh every session — tell your coach who you are.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {saved && <span className={`text-sm ${theme.accentClass}`}>Saved!</span>}
          <button
            onClick={() => setConfirmReset(true)}
            className="px-3 py-1.5 rounded-md border border-gray-700 text-gray-400 text-sm hover:bg-gray-800 transition-colors"
          >
            Reset
          </button>
          <button
            onClick={handleSave}
            disabled={saving || !dirty}
            className={`px-4 py-1.5 rounded-md ${theme.accentButton} text-white text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed transition-colors`}
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>

      {/* Reset confirm dialog */}
      {confirmReset && (
        <div className="mx-6 mt-4 rounded-lg border border-red-800/60 bg-red-950/30 p-4 flex items-center justify-between gap-4">
          <p className="text-sm text-red-300">
            Reset to default empty template? <span className="text-red-400 font-medium">This will erase your current profile.</span>
          </p>
          <div className="flex gap-2 shrink-0">
            <button
              onClick={() => setConfirmReset(false)}
              className="px-3 py-1.5 rounded-md border border-gray-700 text-gray-300 text-sm hover:bg-gray-800 transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleReset}
              disabled={resetting}
              className="px-3 py-1.5 rounded-md bg-red-700 hover:bg-red-600 text-white text-sm font-medium disabled:opacity-50 transition-colors"
            >
              {resetting ? "Resetting…" : "Yes, reset"}
            </button>
          </div>
        </div>
      )}

      {/* Form */}
      {loading ? (
        <div className="flex-1 flex items-center justify-center text-gray-500 text-sm">
          Loading…
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {/* Personal — all modes */}
          <Section title="Personal">
            <div className="grid grid-cols-2 gap-4">
              <Field label="Name" value={fields.personal?.name ?? ""} onChange={(v) => setNested("personal", "name", v)} focusClass={focusClass} />
              <Field label="Gender" value={fields.personal?.gender ?? ""} onChange={(v) => setNested("personal", "gender", v)} focusClass={focusClass} />
              <Field label="Date of birth" value={fields.personal?.date_of_birth ?? ""} onChange={(v) => setNested("personal", "date_of_birth", v)} placeholder="e.g. 1990-05-15" focusClass={focusClass} />
              <HeightInput value={fields.personal?.height_cm} onChange={(cm) => setNested("personal", "height_cm", cm)} focusClass={focusClass} />
              <MeasuredInput label="Weight" value={fields.personal?.weight_kg} qty="mass" decimals={1} placeholder={system === "imperial" ? "e.g. 155" : "e.g. 70"} onChange={(kg) => setNested("personal", "weight_kg", kg)} focusClass={focusClass} />
              <Field label="Max heart rate" value={fields.personal?.max_hr ?? ""} onChange={(v) => setNested("personal", "max_hr", v)} placeholder="e.g. 185" focusClass={focusClass} />
              {fields.personal?.body_notes && (
                <div className="col-span-2">
                  <Field label="Body notes (couldn't be read as a height or weight — move the numbers above if you like)" value={fields.personal.body_notes} onChange={(v) => setNested("personal", "body_notes", v)} focusClass={focusClass} />
                </div>
              )}
            </div>
          </Section>

          {/* Running Background — running + hybrid */}
          {(mode === "running" || mode === "hybrid") && (
            <Section title="Running Background">
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <Field
                    label="Running since"
                    value={fields.running_background?.running_since ?? ""}
                    onChange={(v) => setNested("running_background", "running_since", v)}
                    placeholder="e.g. 2018"
                    focusClass={focusClass}
                  />
                  <Field
                    label="Typical weekly volume"
                    value={fields.running_background?.weekly_volume ?? fields.running_background?.weekly_run_volume ?? ""}
                    onChange={(v) => setNested("running_background", mode === "hybrid" ? "weekly_run_volume" : "weekly_volume", v)}
                    placeholder={PLACEHOLDERS[system].runVolume}
                    focusClass={focusClass}
                  />
                  {mode === "running" && (
                    <div className="col-span-2 flex flex-col gap-1">
                      <label className="text-xs font-medium text-gray-400">Running Focus</label>
                      <select
                        value={fields.running_background?.running_focus ?? ""}
                        onChange={(e) => setNested("running_background", "running_focus", e.target.value)}
                        className={`rounded-md bg-gray-900 border border-gray-700 px-3 py-2 text-sm text-gray-100 focus:outline-none ${focusClass}`}
                      >
                        <option value="">Select…</option>
                        <option value="fitness">Fitness &amp; General Health</option>
                        <option value="road_racing">Road Racing (5K – Marathon)</option>
                        <option value="marathon">Marathon Training</option>
                        <option value="trail">Trail Running</option>
                        <option value="ultra">Ultra Running</option>
                        <option value="track">Track &amp; Speed</option>
                        <option value="beginner">Beginner / Return to Running</option>
                        <option value="multi_sport">Multi-Sport / Triathlon</option>
                      </select>
                    </div>
                  )}
                </div>
                <TextArea
                  label="Background"
                  value={fields.running_background?.background ?? ""}
                  onChange={(v) => setNested("running_background", "background", v)}
                  placeholder="Athletic history, how you got into running, previous race experience…"
                  rows={3}
                  focusClass={focusClass}
                />
              </div>
            </Section>
          )}

          {/* Running Personal Bests — running + hybrid */}
          {(mode === "running" || mode === "hybrid") && (
            <Section title="Running Personal Bests">
              <div className="grid grid-cols-4 gap-4">
                {(["5k", "10k", "half_marathon", "marathon"] as const).map((k) => {
                  const section = mode === "running" ? "personal_bests" : "running_bests";
                  const labels: Record<string, string> = { "5k": "5K", "10k": "10K", half_marathon: "Half marathon", marathon: "Marathon" };
                  const placeholders: Record<string, string> = { "5k": "e.g. 22:30", "10k": "e.g. 47:00", half_marathon: "e.g. 1:45:00", marathon: "e.g. 3:45:00" };
                  return (
                    <Field
                      key={k}
                      label={labels[k]}
                      value={fields[section]?.[k] ?? ""}
                      onChange={(v) => setNested(section, k, v)}
                      placeholder={placeholders[k]}
                      focusClass={focusClass}
                    />
                  );
                })}
              </div>
            </Section>
          )}

          {/* Cycling Background — cycling + hybrid */}
          {(mode === "cycling" || mode === "hybrid") && (
            <Section title="Cycling Background">
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <Field
                    label="Cycling since"
                    value={fields.cycling_background?.cycling_since ?? ""}
                    onChange={(v) => setNested("cycling_background", "cycling_since", v)}
                    placeholder="e.g. 2020"
                    focusClass={focusClass}
                  />
                  <Field
                    label="Typical weekly distance"
                    value={fields.cycling_background?.weekly_distance ?? fields.cycling_background?.weekly_ride_distance ?? ""}
                    onChange={(v) => setNested("cycling_background", mode === "hybrid" ? "weekly_ride_distance" : "weekly_distance", v)}
                    placeholder={PLACEHOLDERS[system].rideVolume}
                    focusClass={focusClass}
                  />
                  {mode === "cycling" && (
                    <div className="col-span-2 flex flex-col gap-1">
                      <label className="text-xs font-medium text-gray-400">Cycling Focus</label>
                      <select
                        value={fields.cycling_background?.cycling_focus ?? ""}
                        onChange={(e) => setNested("cycling_background", "cycling_focus", e.target.value)}
                        className={`rounded-md bg-gray-900 border border-gray-700 px-3 py-2 text-sm text-gray-100 focus:outline-none ${focusClass}`}
                      >
                        <option value="">Select…</option>
                        <option value="fitness">Fitness &amp; General Health</option>
                        <option value="road_racing">Road Racing / Criteriums</option>
                        <option value="gran_fondo">Gran Fondo / Sportive</option>
                        <option value="time_trial">Time Trial</option>
                        <option value="mountain_biking">Mountain Biking</option>
                        <option value="gravel">Gravel &amp; Adventure</option>
                        <option value="triathlon">Triathlon / Multi-Sport</option>
                        <option value="beginner">Beginner / Return to Cycling</option>
                      </select>
                    </div>
                  )}
                </div>
                <TextArea
                  label="Background"
                  value={fields.cycling_background?.background ?? ""}
                  onChange={(v) => setNested("cycling_background", "background", v)}
                  placeholder="How you got into cycling, race experience, riding style…"
                  rows={3}
                  focusClass={focusClass}
                />
              </div>
            </Section>
          )}

          {/* Cycling Bests — cycling + hybrid */}
          {(mode === "cycling" || mode === "hybrid") && (
            <Section title="Cycling Bests">
              <div className="grid grid-cols-2 gap-4">
                <Field label="FTP (watts)" value={fields.cycling_bests?.ftp ?? ""} onChange={(v) => setNested("cycling_bests", "ftp", v)} placeholder="e.g. 250 W" focusClass={focusClass} />
                <Field label="Fastest century" value={fields.cycling_bests?.fastest_century ?? ""} onChange={(v) => setNested("cycling_bests", "fastest_century", v)} placeholder="e.g. 3:45:00" focusClass={focusClass} />
                <Field label="Fastest gran fondo" value={fields.cycling_bests?.fastest_gran_fondo ?? ""} onChange={(v) => setNested("cycling_bests", "fastest_gran_fondo", v)} placeholder="e.g. 5:30:00" focusClass={focusClass} />
                <Field label="Other" value={fields.cycling_bests?.other ?? ""} onChange={(v) => setNested("cycling_bests", "other", v)} placeholder="e.g. KOM on local climb" focusClass={focusClass} />
              </div>
            </Section>
          )}

          {/* Lifting Background — lifting only */}
          {mode === "lifting" && (
            <Section title="Lifting Background">
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <Field
                    label="Lifting since"
                    value={fields.lifting_background?.lifting_since ?? ""}
                    onChange={(v) => setNested("lifting_background", "lifting_since", v)}
                    placeholder="e.g. 2019"
                    focusClass={focusClass}
                  />
                  <Field
                    label="Sessions per week"
                    value={fields.lifting_background?.sessions_per_week ?? ""}
                    onChange={(v) => setNested("lifting_background", "sessions_per_week", v)}
                    placeholder="e.g. 4"
                    focusClass={focusClass}
                  />
                  <div className="col-span-2 flex flex-col gap-1">
                    <label className="text-xs font-medium text-gray-400">Training Style</label>
                    <select
                      value={fields.lifting_background?.training_style ?? ""}
                      onChange={(e) => setNested("lifting_background", "training_style", e.target.value)}
                      className={`rounded-md bg-gray-900 border border-gray-700 px-3 py-2 text-sm text-gray-100 focus:outline-none ${focusClass}`}
                    >
                      <option value="">Select…</option>
                      <option value="general_strength">General Strength</option>
                      <option value="powerlifting">Powerlifting</option>
                      <option value="bodybuilding">Bodybuilding / Hypertrophy</option>
                      <option value="olympic">Olympic Weightlifting</option>
                      <option value="crossfit">CrossFit / Functional Fitness</option>
                      <option value="calisthenics">Calisthenics / Bodyweight</option>
                      <option value="athletic">Athletic Performance</option>
                      <option value="beginner">Beginner / Getting Started</option>
                    </select>
                  </div>
                </div>
                <TextArea
                  label="Background"
                  value={fields.lifting_background?.background ?? ""}
                  onChange={(v) => setNested("lifting_background", "background", v)}
                  placeholder="How you got into lifting, programs you've run, gym setup…"
                  rows={3}
                  focusClass={focusClass}
                />
              </div>
            </Section>
          )}

          {/* Common lower sections */}
          <CommonSections fields={fields} setFields={setTop} setFieldsRaw={setTop} focusClass={focusClass} />
        </div>
      )}
    </div>
  );
}
