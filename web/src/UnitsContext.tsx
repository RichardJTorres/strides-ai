import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import {
  convert,
  formatSpeedFromPace,
  formatValue,
  toSI,
  unitLabel,
  type FormatOptions,
  type Quantity,
  type UnitSystem,
} from "./units";

// App-wide unit system. App.tsx seeds it from GET /api/settings; switching it on the Settings page
// persists through PUT /api/settings and re-renders every consumer, so the swap cascades without
// a reload. The coach picks the new system up on its next turn (the system prompt is rebuilt).

interface UnitsContextValue {
  system: UnitSystem;
  setSystem: (system: UnitSystem) => Promise<void>;
  /** Canonical value -> display string in the current system. */
  fmt: (value: number | null | undefined, qty: Quantity, opts?: FormatOptions) => string;
  fmtSpeed: (sPerKm: number | null | undefined, empty?: string) => string;
  label: (qty: Quantity) => string;
  /** Canonical value -> display number (for charts, inputs, sorting thresholds). */
  convert: (value: number | null | undefined, qty: Quantity) => number | null;
  /** Number typed by the user in the current system -> canonical value. */
  toSI: (value: number | null | undefined, qty: Quantity) => number | null;
}

const UnitsContext = createContext<UnitsContextValue | null>(null);

export function UnitsProvider({ initial, children }: { initial: UnitSystem; children: ReactNode }) {
  const [system, setLocal] = useState<UnitSystem>(initial);

  const setSystem = useCallback(async (next: UnitSystem) => {
    const previous = system;
    setLocal(next);
    try {
      const res = await fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ unit_system: next }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
    } catch (err) {
      setLocal(previous);
      throw err;
    }
  }, [system]);

  const value = useMemo<UnitsContextValue>(
    () => ({
      system,
      setSystem,
      fmt: (value, qty, opts) => formatValue(value, qty, system, opts),
      fmtSpeed: (sPerKm, empty) => formatSpeedFromPace(sPerKm, system, empty),
      label: (qty) => unitLabel(qty, system),
      convert: (value, qty) => convert(value, qty, system),
      toSI: (value, qty) => toSI(value, qty, system),
    }),
    [system, setSystem],
  );

  return <UnitsContext.Provider value={value}>{children}</UnitsContext.Provider>;
}

export function useUnits(): UnitsContextValue {
  const ctx = useContext(UnitsContext);
  if (!ctx) throw new Error("useUnits must be used inside <UnitsProvider>");
  return ctx;
}
