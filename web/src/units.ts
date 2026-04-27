// Central unit conversion module — mirrors strides_ai/units.py.
// All storage in the app stays canonical SI; these helpers run at the display
// layer (and at form-submit time for the Calendar planner).

export type Units = "metric" | "imperial";

export const VALID_UNITS = new Set<Units>(["metric", "imperial"]);

// ── Constants ─────────────────────────────────────────────────────────────────

export const M_TO_MI = 0.000621371;
export const M_TO_KM = 0.001;
export const KG_TO_LB = 2.20462;
export const M_TO_FT = 3.28084;
export const S_PER_KM_TO_S_PER_MI = 1.60934;

// ── Labels ────────────────────────────────────────────────────────────────────

export function distUnitLabel(units: Units): string {
  return units === "imperial" ? "mi" : "km";
}

export function weightUnitLabel(units: Units): string {
  return units === "imperial" ? "lb" : "kg";
}

export function elevUnitLabel(units: Units): string {
  return units === "imperial" ? "ft" : "m";
}

export function speedUnitLabel(units: Units): string {
  return units === "imperial" ? "mph" : "km/h";
}

export function paceUnitLabel(units: Units): string {
  return units === "imperial" ? "min/mi" : "min/km";
}

// ── Numeric conversions ───────────────────────────────────────────────────────

export function mToDistance(m: number | null | undefined, units: Units): number | null {
  if (m == null) return null;
  return m * (units === "imperial" ? M_TO_MI : M_TO_KM);
}

export function kmToDistance(km: number | null | undefined, units: Units): number | null {
  if (km == null) return null;
  return km * 1000 * (units === "imperial" ? M_TO_MI : M_TO_KM);
}

export function kgToWeight(kg: number | null | undefined, units: Units): number | null {
  if (kg == null) return null;
  return units === "imperial" ? kg * KG_TO_LB : kg;
}

export function mToElevation(m: number | null | undefined, units: Units): number | null {
  if (m == null) return null;
  return units === "imperial" ? m * M_TO_FT : m;
}

export function sPerKmToPaceSeconds(
  sPerKm: number | null | undefined,
  units: Units,
): number | null {
  if (sPerKm == null) return null;
  return units === "imperial" ? sPerKm * S_PER_KM_TO_S_PER_MI : sPerKm;
}

export function sPerKmToSpeed(sPerKm: number | null | undefined, units: Units): number | null {
  if (sPerKm == null || sPerKm <= 0) return null;
  const kph = 3600 / sPerKm;
  return units === "imperial" ? kph * (M_TO_MI / M_TO_KM) : kph;
}

// ── Round-trip helpers (Calendar form) ────────────────────────────────────────

/** Convert a user-entered distance value to km for backend storage. */
export function imperialInputToKm(value: number | null | undefined, units: Units): number | null {
  if (value == null) return null;
  return units === "imperial" ? value / (M_TO_MI / M_TO_KM) : value;
}

/** Convert a user-entered elevation value to metres for backend storage. */
export function imperialInputToM(value: number | null | undefined, units: Units): number | null {
  if (value == null) return null;
  return units === "imperial" ? value / M_TO_FT : value;
}

/** Convert km from backend → user's preferred distance unit (for prefilling forms). */
export function kmToUserUnit(km: number | null | undefined, units: Units): number | null {
  if (km == null) return null;
  return units === "imperial" ? km * (M_TO_MI / M_TO_KM) : km;
}

/** Convert metres from backend → user's preferred elevation unit (for prefilling forms). */
export function mToUserElevation(m: number | null | undefined, units: Units): number | null {
  if (m == null) return null;
  return units === "imperial" ? m * M_TO_FT : m;
}

// ── Formatting helpers ────────────────────────────────────────────────────────

export function formatDistance(
  m: number | null | undefined,
  units: Units,
  precision = 2,
): string {
  const v = mToDistance(m, units);
  return v == null ? "—" : `${v.toFixed(precision)} ${distUnitLabel(units)}`;
}

export function formatPace(sPerKm: number | null | undefined, units: Units): string {
  const s = sPerKmToPaceSeconds(sPerKm, units);
  if (s == null) return "—";
  const mins = Math.floor(s / 60);
  const secs = Math.floor(s % 60);
  return `${mins}:${String(secs).padStart(2, "0")}/${distUnitLabel(units)}`;
}

export function formatSpeed(sPerKm: number | null | undefined, units: Units): string {
  const v = sPerKmToSpeed(sPerKm, units);
  return v == null ? "—" : `${v.toFixed(1)} ${speedUnitLabel(units)}`;
}

export function formatElevation(
  m: number | null | undefined,
  units: Units,
  precision = 0,
): string {
  const v = mToElevation(m, units);
  return v == null ? "—" : `${v.toFixed(precision)} ${elevUnitLabel(units)}`;
}

export function formatWeight(
  kg: number | null | undefined,
  units: Units,
  precision = 0,
): string {
  const v = kgToWeight(kg, units);
  return v == null ? "—" : `${v.toFixed(precision)} ${weightUnitLabel(units)}`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  const h = Math.floor(seconds / 3600);
  const rem = seconds % 3600;
  const m = Math.floor(rem / 60);
  const s = Math.floor(rem % 60);
  if (h > 0) return `${h}h${String(m).padStart(2, "0")}m${String(s).padStart(2, "0")}s`;
  return `${m}m${String(s).padStart(2, "0")}s`;
}
