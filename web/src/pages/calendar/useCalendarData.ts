import { useCallback, useEffect, useState } from "react";
import { useUnits } from "../../UnitsContext";
import { fetchJson, jsonBody } from "../../ui/api";
import { buildGrid } from "./grid";
import type { Activity, ComplianceDay, Plan, Prefs, Race, TrainingState, Workout } from "./types";

/** Everything the calendar loads, plus the preference mutations (blocked days, races). */
export function useCalendarData(currentMonth: Date) {
  const units = useUnits();
  const [prefs, setPrefs] = useState<Prefs>({ blocked_days: [], races: [] });
  const [plan, setPlan] = useState<Plan>({});
  const [activities, setActivities] = useState<Record<string, Activity[]>>({});
  const [compliance, setCompliance] = useState<Record<string, ComplianceDay>>({});
  const [trainingState, setTrainingState] = useState<TrainingState | null>(null);
  const [loading, setLoading] = useState(true);
  // A failed initial load: without the plan the grid would look like an empty calendar.
  const [loadError, setLoadError] = useState<string | null>(null);
  // A failed blocked-day / race save (the change is rolled back).
  const [prefsError, setPrefsError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  // Load, projected ramp and plan conflicts depend on the plan and blocked days/races, so they
  // are refetched whenever either changes (the backend is the single source of these numbers).
  // Secondary: the grid is complete without it, so a failure only hides the load strip.
  useEffect(() => {
    fetchJson<TrainingState>("/api/calendar/training-state")
      .then(setTrainingState)
      .catch(() => setTrainingState(null));
  }, [plan, prefs, units.system]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    Promise.all([
      fetchJson<Prefs>("/api/calendar/prefs"),
      fetchJson<Workout[]>("/api/calendar/plan"),
      fetchJson<Activity[]>("/api/activities"),
    ])
      .then(([loadedPrefs, planRows, activityRows]) => {
        if (cancelled) return;
        setPrefs(loadedPrefs);
        const planByDate: Plan = {};
        for (const w of planRows) planByDate[w.date] = w;
        setPlan(planByDate);
        const byDate: Record<string, Activity[]> = {};
        for (const a of activityRows) (byDate[a.date] ??= []).push(a);
        setActivities(byDate);
      })
      .catch((e: Error) => {
        if (!cancelled) setLoadError(`Couldn't load the calendar: ${e.message}`);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [attempt]);

  // Compliance (plan-vs-actual) is fetched per-visible-grid-range rather than once for all
  // time, matching how the grid itself is paginated by month. Refetched when the plan changes,
  // since an edit changes what each day is scored against.
  useEffect(() => {
    let cancelled = false;
    const cells = buildGrid(currentMonth);
    const start = cells[0].dateStr;
    const end = cells[cells.length - 1].dateStr;
    fetchJson<{ days: ComplianceDay[] }>(
      `/api/calendar/compliance?start_date=${start}&end_date=${end}`,
    )
      .then(res => {
        if (cancelled) return;
        const byDate: Record<string, ComplianceDay> = {};
        for (const d of res.days) byDate[d.date] = d;
        setCompliance(byDate);
      })
      .catch(() => {
        // Secondary: the plan still renders; only the status dots are missing.
        if (!cancelled) setCompliance({});
      });
    return () => { cancelled = true; };
    // units.system: compliance notes are rendered server-side in the current units.
  }, [currentMonth, units.system, plan]);

  // Optimistic: show the change at once, put the previous value back if the save fails.
  const savePrefs = useCallback((updated: Prefs, previous: Prefs) => {
    setPrefs(updated);
    setPrefsError(null);
    fetchJson("/api/calendar/prefs", jsonBody("PUT", updated)).catch(() => {
      setPrefs(current => (current === updated ? previous : current));
      setPrefsError("Couldn't save that change, so it was undone. Try again.");
    });
  }, []);

  const toggleBlocked = (date: string) => {
    savePrefs(
      {
        ...prefs,
        blocked_days: prefs.blocked_days.includes(date)
          ? prefs.blocked_days.filter(d => d !== date)
          : [...prefs.blocked_days, date],
      },
      prefs,
    );
  };

  const addRace = (race: Race) => {
    savePrefs(
      { ...prefs, races: [...prefs.races, race].sort((a, b) => a.date.localeCompare(b.date)) },
      prefs,
    );
  };

  const removeRace = (date: string) => {
    savePrefs({ ...prefs, races: prefs.races.filter(r => r.date !== date) }, prefs);
  };

  return {
    prefs, plan, setPlan, activities, compliance, trainingState, toggleBlocked, addRace, removeRace,
    loading, loadError, prefsError, reload: () => setAttempt(n => n + 1),
  };
}
