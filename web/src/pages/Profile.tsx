import { useEffect, useState } from "react";

interface ProfileFields {
  personal: {
    name: string;
    gender: string;
    date_of_birth: string;
    height: string;
    weight: string;
  };
  running_background: {
    running_since: string;
    weekly_volume: string;
    background: string;
  };
  personal_bests: {
    "5k": string;
    "10k": string;
    half_marathon: string;
    marathon: string;
  };
  goals: string;
  injuries_and_health: string;
  other_notes: string;
}

const EMPTY: ProfileFields = {
  personal: { name: "", gender: "", date_of_birth: "", height: "", weight: "" },
  running_background: { running_since: "", weekly_volume: "", background: "" },
  personal_bests: { "5k": "", "10k": "", half_marathon: "", marathon: "" },
  goals: "",
  injuries_and_health: "",
  other_notes: "",
};

// ── Field components ──────────────────────────────────────────────────────────

function Field({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-medium text-gray-400">{label}</label>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="rounded-md bg-gray-900 border border-gray-700 px-3 py-2 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-green-500"
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
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  rows?: number;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-medium text-gray-400">{label}</label>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        rows={rows}
        className="rounded-md bg-gray-900 border border-gray-700 px-3 py-2 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-green-500 resize-y"
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

// ── Main component ────────────────────────────────────────────────────────────

export default function Profile() {
  const [fields, setFields] = useState<ProfileFields>(EMPTY);
  const [original, setOriginal] = useState<ProfileFields>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    fetch("/api/profile")
      .then((r) => r.json())
      .then((data) => {
        const merged = deepMerge(EMPTY, data.fields ?? {});
        setFields(merged);
        setOriginal(merged);
      })
      .finally(() => setLoading(false));
  }, []);

  async function handleSave() {
    setSaving(true);
    setSaved(false);
    try {
      await fetch("/api/profile", {
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

  function setPersonal(key: keyof ProfileFields["personal"], val: string) {
    setFields((f) => ({ ...f, personal: { ...f.personal, [key]: val } }));
  }

  function setBg(key: keyof ProfileFields["running_background"], val: string) {
    setFields((f) => ({
      ...f,
      running_background: { ...f.running_background, [key]: val },
    }));
  }

  function setPB(key: keyof ProfileFields["personal_bests"], val: string) {
    setFields((f) => ({
      ...f,
      personal_bests: { ...f.personal_bests, [key]: val },
    }));
  }

  const dirty = JSON.stringify(fields) !== JSON.stringify(original);

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800">
        <div>
          <h2 className="text-lg font-semibold text-gray-100">Athlete Profile</h2>
          <p className="text-xs text-gray-500 mt-0.5">
            Loaded fresh every session — tell your coach who you are.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {saved && <span className="text-sm text-green-400">Saved!</span>}
          <button
            onClick={handleSave}
            disabled={saving || !dirty}
            className="px-4 py-1.5 rounded-md bg-green-600 hover:bg-green-500 text-white text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>

      {/* Form */}
      {loading ? (
        <div className="flex-1 flex items-center justify-center text-gray-500 text-sm">
          Loading…
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {/* Personal */}
          <Section title="Personal">
            <div className="grid grid-cols-2 gap-4">
              <Field
                label="Name"
                value={fields.personal.name}
                onChange={(v) => setPersonal("name", v)}
              />
              <Field
                label="Gender"
                value={fields.personal.gender}
                onChange={(v) => setPersonal("gender", v)}
              />
              <Field
                label="Date of birth"
                value={fields.personal.date_of_birth}
                onChange={(v) => setPersonal("date_of_birth", v)}
                placeholder="e.g. 1990-05-15"
              />
              <Field
                label="Height"
                value={fields.personal.height}
                onChange={(v) => setPersonal("height", v)}
                placeholder="e.g. 175 cm"
              />
              <Field
                label="Weight"
                value={fields.personal.weight}
                onChange={(v) => setPersonal("weight", v)}
                placeholder="e.g. 70 kg"
              />
            </div>
          </Section>

          {/* Running Background */}
          <Section title="Running Background">
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <Field
                  label="Running since"
                  value={fields.running_background.running_since}
                  onChange={(v) => setBg("running_since", v)}
                  placeholder="e.g. 2018"
                />
                <Field
                  label="Typical weekly volume"
                  value={fields.running_background.weekly_volume}
                  onChange={(v) => setBg("weekly_volume", v)}
                  placeholder="e.g. 50 km/week"
                />
              </div>
              <TextArea
                label="Background"
                value={fields.running_background.background}
                onChange={(v) => setBg("background", v)}
                placeholder="Athletic history, how you got into running, previous race experience…"
                rows={3}
              />
            </div>
          </Section>

          {/* Personal Bests */}
          <Section title="Personal Bests">
            <div className="grid grid-cols-4 gap-4">
              <Field
                label="5K"
                value={fields.personal_bests["5k"]}
                onChange={(v) => setPB("5k", v)}
                placeholder="e.g. 22:30"
              />
              <Field
                label="10K"
                value={fields.personal_bests["10k"]}
                onChange={(v) => setPB("10k", v)}
                placeholder="e.g. 47:00"
              />
              <Field
                label="Half marathon"
                value={fields.personal_bests.half_marathon}
                onChange={(v) => setPB("half_marathon", v)}
                placeholder="e.g. 1:45:00"
              />
              <Field
                label="Marathon"
                value={fields.personal_bests.marathon}
                onChange={(v) => setPB("marathon", v)}
                placeholder="e.g. 3:45:00"
              />
            </div>
          </Section>

          {/* Goals */}
          <Section title="Goals">
            <TextArea
              label="Upcoming races, time targets, other goals"
              value={fields.goals}
              onChange={(v) => setFields((f) => ({ ...f, goals: v }))}
              placeholder="e.g. Sub-4 marathon at Berlin in September, lose 5 kg before race season…"
              rows={3}
            />
          </Section>

          {/* Injuries & Health */}
          <Section title="Injuries & Health">
            <TextArea
              label="Current or recurring injuries, medical conditions"
              value={fields.injuries_and_health}
              onChange={(v) =>
                setFields((f) => ({ ...f, injuries_and_health: v }))
              }
              placeholder="e.g. Left IT band niggle when mileage exceeds 60 km/week…"
              rows={3}
            />
          </Section>

          {/* Other Notes */}
          <Section title="Other Notes">
            <TextArea
              label="Training preferences, coaching style, anything else"
              value={fields.other_notes}
              onChange={(v) => setFields((f) => ({ ...f, other_notes: v }))}
              placeholder="e.g. Prefer easy effort on weekdays, long run Saturday mornings…"
              rows={3}
            />
          </Section>
        </div>
      )}
    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function deepMerge<T extends object>(base: T, override: Partial<T>): T {
  const result = { ...base };
  for (const key in override) {
    const b = base[key];
    const o = override[key];
    if (b !== null && typeof b === "object" && !Array.isArray(b) && typeof o === "object" && o !== null) {
      (result as Record<string, unknown>)[key] = deepMerge(b as object, o as object);
    } else if (o !== undefined) {
      (result as Record<string, unknown>)[key] = o;
    }
  }
  return result;
}
