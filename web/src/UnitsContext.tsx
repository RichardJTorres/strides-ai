import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { Units } from "./units";

interface UnitsContextValue {
  units: Units;
  setUnits: (next: Units) => Promise<void>;
  loaded: boolean;
}

const UnitsContext = createContext<UnitsContextValue | null>(null);

const LEGACY_LS_KEY = "strides_unit"; // used to be "miles" | "km" on Charts page

function migrateLegacyLocalStorage(): Units | null {
  const raw = localStorage.getItem(LEGACY_LS_KEY);
  if (raw === "miles") {
    localStorage.removeItem(LEGACY_LS_KEY);
    return "imperial";
  }
  if (raw === "km") {
    localStorage.removeItem(LEGACY_LS_KEY);
    return "metric";
  }
  return null;
}

export function UnitsProvider({ children }: { children: ReactNode }) {
  const [units, setUnitsState] = useState<Units>("metric");
  const [loaded, setLoaded] = useState(false);

  // Load from server; if server has no preference yet, migrate legacy localStorage
  useEffect(() => {
    let cancelled = false;
    fetch("/api/settings")
      .then((r) => r.json())
      .then(async (data: { units?: Units }) => {
        if (cancelled) return;
        const serverUnits: Units | undefined = data.units;
        const legacy = migrateLegacyLocalStorage();
        if (legacy && (!serverUnits || serverUnits === "metric")) {
          // First-run migration: legacy preference exists, server hasn't been told yet.
          await fetch("/api/settings", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ units: legacy }),
          }).catch(() => {});
          if (!cancelled) setUnitsState(legacy);
        } else if (serverUnits) {
          setUnitsState(serverUnits);
        }
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const setUnits = useCallback(async (next: Units) => {
    setUnitsState(next); // optimistic
    try {
      await fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ units: next }),
      });
    } catch {
      // best-effort; UI already updated
    }
  }, []);

  const value = useMemo(() => ({ units, setUnits, loaded }), [units, setUnits, loaded]);
  return <UnitsContext.Provider value={value}>{children}</UnitsContext.Provider>;
}

export function useUnits(): UnitsContextValue {
  const ctx = useContext(UnitsContext);
  if (!ctx) {
    throw new Error("useUnits must be used inside <UnitsProvider>");
  }
  return ctx;
}
