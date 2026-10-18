import { useEffect, useRef, useState } from "react";
import { useUnits } from "../../UnitsContext";
import { CM_PER_INCH, feetInches, type Quantity, type UnitSystem } from "../../units";

// example placeholders follow the unit setting.
export const PLACEHOLDERS: Record<UnitSystem, Record<string, string>> = {
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

export const inputClass =
  "rounded-md bg-gray-900 border border-gray-700 px-3 py-2 text-sm text-gray-100 placeholder-gray-600 focus:outline-none";

/**
 * Number input for a value stored in SI (personal.weight_kg, ...), shown in the athlete's units.
 * The text the athlete types is kept as a draft and only written back when edited, so an
 * untouched field never drifts through a round-trip conversion (77 kg -> 169.8 lb -> 77.02 kg).
 */
export function MeasuredInput({
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
export function HeightInput({
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

export function Field({
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

export function TextArea({
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

// ── Snacks list ───────────────────────────────────────────────────────────────

export function SnacksList({
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
