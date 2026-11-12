import { useUnits } from "../../UnitsContext";

/** Unit helpers the calendar shares. Planned distances are stored in km; activities in meters. */
export function useDistance() {
  const units = useUnits();
  const fmtKm = (km: number | null | undefined, decimals = 1, withLabel = true) =>
    units.fmt(km == null ? null : km * 1000, "distance", { decimals, withLabel });
  return { units, fmtKm, distLabel: units.label("distance") };
}
