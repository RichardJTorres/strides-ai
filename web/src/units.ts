// Mirror of strides_ai/units.py — the single place the UI converts and labels measurements.
// Every API value is SI-based (meters, s/km, kg, ml); components never do their own math.
// tests/fixtures/unit_cases.json is asserted against both implementations (web/units.test.mjs).

export type UnitSystem = "metric" | "imperial";
export const DEFAULT_UNIT_SYSTEM: UnitSystem = "metric";

export type Quantity =
  | "distance" // meters
  | "elevation" // meters
  | "pace" // seconds per km
  | "speed" // meters per second
  | "pace_delta" // seconds per km
  | "climb_rate" // meters per km
  | "mass" // kilograms
  | "volume" // milliliters
  | "height"; // centimeters (body height; imperial is shown as feet + inches)

const METERS_PER_MILE = 1609.344;
const FEET_PER_METER = 3.28084;
const POUNDS_PER_KG = 2.20462;
const FL_OZ_PER_ML = 0.033814;
const KM_PER_MILE = METERS_PER_MILE / 1000;
export const CM_PER_INCH = 2.54;

interface UnitSpec {
  label: string;
  factor: number; // display = canonical * factor
  decimals: number;
}

const SPECS: Record<Quantity, Record<UnitSystem, UnitSpec>> = {
  distance: {
    metric: { label: "km", factor: 0.001, decimals: 2 },
    imperial: { label: "mi", factor: 1 / METERS_PER_MILE, decimals: 2 },
  },
  elevation: {
    metric: { label: "m", factor: 1, decimals: 0 },
    imperial: { label: "ft", factor: FEET_PER_METER, decimals: 0 },
  },
  pace: {
    metric: { label: "/km", factor: 1, decimals: 0 },
    imperial: { label: "/mi", factor: KM_PER_MILE, decimals: 0 },
  },
  speed: {
    metric: { label: "km/h", factor: 3.6, decimals: 1 },
    imperial: { label: "mph", factor: 3600 / METERS_PER_MILE, decimals: 1 },
  },
  pace_delta: {
    metric: { label: "s/km", factor: 1, decimals: 0 },
    imperial: { label: "s/mi", factor: KM_PER_MILE, decimals: 0 },
  },
  climb_rate: {
    metric: { label: "m/km", factor: 1, decimals: 0 },
    imperial: { label: "ft/mi", factor: FEET_PER_METER * KM_PER_MILE, decimals: 0 },
  },
  mass: {
    metric: { label: "kg", factor: 1, decimals: 0 },
    imperial: { label: "lb", factor: POUNDS_PER_KG, decimals: 0 },
  },
  volume: {
    metric: { label: "ml", factor: 1, decimals: 0 },
    imperial: { label: "fl oz", factor: FL_OZ_PER_ML, decimals: 0 },
  },
  height: {
    metric: { label: "cm", factor: 1, decimals: 0 },
    imperial: { label: "in", factor: 1 / CM_PER_INCH, decimals: 0 },
  },
};

export function parseUnitSystem(value: unknown): UnitSystem {
  return value === "imperial" || value === "metric" ? value : DEFAULT_UNIT_SYSTEM;
}

export function unitLabel(qty: Quantity, system: UnitSystem): string {
  return SPECS[qty][system].label;
}

/** Canonical (SI) value -> display value. */
export function convert(value: number, qty: Quantity, system: UnitSystem): number;
export function convert(value: number | null | undefined, qty: Quantity, system: UnitSystem): number | null;
export function convert(value: number | null | undefined, qty: Quantity, system: UnitSystem): number | null {
  if (value == null) return null;
  return value * SPECS[qty][system].factor;
}

/** Display value typed by the user -> canonical (SI) value. */
export function toSI(value: number | null | undefined, qty: Quantity, system: UnitSystem): number | null {
  if (value == null || Number.isNaN(value)) return null;
  return value / SPECS[qty][system].factor;
}

/** Stored pace (s/km) -> canonical speed (m/s); cycling activities store pace too. */
export function speedFromPace(sPerKm: number | null | undefined): number | null {
  if (sPerKm == null || sPerKm <= 0) return null;
  return 1000 / sPerKm;
}

export interface FormatOptions {
  decimals?: number;
  empty?: string;
  withLabel?: boolean;
}

function clock(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${String(secs).padStart(2, "0")}`;
}

/** Canonical value -> display string, e.g. "6.21 mi", "8:02/mi", "+12 s/km". */
export function formatValue(
  value: number | null | undefined,
  qty: Quantity,
  system: UnitSystem,
  { decimals, empty = "—", withLabel = true }: FormatOptions = {},
): string {
  const spec = SPECS[qty][system];
  const shown = convert(value, qty, system);
  if (shown == null) return empty;
  if (qty === "height" && system === "imperial") {
    const [feet, inches] = feetInches(value as number);
    return withLabel ? `${feet}' ${inches}"` : `${feet}'${inches}`;
  }
  if (qty === "pace") return clock(shown) + (withLabel ? spec.label : "");
  const d = decimals ?? spec.decimals;
  let number = shown.toFixed(d);
  if (number.startsWith("-") && Number(number) === 0) number = number.slice(1);
  if (qty === "pace_delta" && !number.startsWith("-")) number = `+${number}`;
  return withLabel ? `${number} ${spec.label}` : number;
}

/** Body height in cm -> whole [feet, inches], rounded to the nearest inch. */
export function feetInches(cm: number): [number, number] {
  const total = Math.round(cm / CM_PER_INCH);
  return [Math.floor(total / 12), total % 12];
}

export function formatSpeedFromPace(sPerKm: number | null | undefined, system: UnitSystem, empty = "—"): string {
  return formatValue(speedFromPace(sPerKm), "speed", system, { empty });
}

/** Charts API vocabulary ("miles" | "km") for a unit system. */
export function chartUnitParam(system: UnitSystem): "miles" | "km" {
  return system === "imperial" ? "miles" : "km";
}
