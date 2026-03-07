import { useEffect, useState } from "react";
import type { Mode, ThemeConfig } from "../App";

interface Props {
  mode: Mode;
  theme: ThemeConfig;
}

// ── Field components ──────────────────────────────────────────────────────────

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

// ── Common lower sections ─────────────────────────────────────────────────────

function CommonSections({
  fields,
  setFields,
  focusClass,
}: {
  fields: Record<string, string>;
  setFields: (key: string, val: string) => void;
  focusClass: string;
}) {
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
          placeholder="e.g. Left IT band niggle when mileage exceeds 60 km/week…"
          rows={3}
          focusClass={focusClass}
        />
      </Section>
      <Section title="Gear">
        <TextArea
          label="Shoes, watch, other kit"
          value={fields.gear ?? ""}
          onChange={(v) => setFields("gear", v)}
          placeholder="e.g. Nike Vaporfly (~400 km), Garmin Forerunner 955…"
          rows={3}
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
  function setNested(section: string, key: string, val: string) {
    setFields((f) => ({ ...f, [section]: { ...f[section], [key]: val } }));
  }

  function setTop(key: string, val: string) {
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
              <Field label="Height" value={fields.personal?.height ?? ""} onChange={(v) => setNested("personal", "height", v)} placeholder="e.g. 175 cm" focusClass={focusClass} />
              <Field label="Weight" value={fields.personal?.weight ?? ""} onChange={(v) => setNested("personal", "weight", v)} placeholder="e.g. 70 kg" focusClass={focusClass} />
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
                    placeholder="e.g. 50 km/week"
                    focusClass={focusClass}
                  />
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
                    placeholder="e.g. 150 km/week"
                    focusClass={focusClass}
                  />
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

          {/* Common lower sections */}
          <CommonSections fields={fields} setFields={setTop} focusClass={focusClass} />
        </div>
      )}
    </div>
  );
}
