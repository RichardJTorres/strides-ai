import { useCallback, useEffect, useState } from "react";
import { useUnits } from "../../UnitsContext";
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

  // Load, projected ramp and plan conflicts depend on the plan and blocked days/races, so they
  // are refetched whenever either changes (the backend is the single source of these numbers).
  useEffect(() => {
    fetch("/api/calendar/training-state")
      .then(r => (r.ok ? r.json() : null))
      .then(setTrainingState)
      .catch(() => {});
  }, [plan, prefs, units.system]);

  useEffect(() => {
    fetch("/api/calendar/prefs")
      .then(r => r.json())
      .then(setPrefs)
      .catch(() => {});
    fetch("/api/calendar/plan")
      .then(r => r.json())
      .then((rows: Workout[]) => {
        const byDate: Record<string, Workout> = {};
        for (const w of rows) byDate[w.date] = w;
        setPlan(byDate);
      })
      .catch(() => {});
    fetch("/api/activities")
      .then(r => r.json())
      .then((rows: Activity[]) => {
        const byDate: Record<string, Activity[]> = {};
        for (const a of rows) {
          if (!byDate[a.date]) byDate[a.date] = [];
          byDate[a.date].push(a);
        }
        setActivities(byDate);
      })
      .catch(() => {});
  }, []);

  // Compliance (plan-vs-actual) is fetched per-visible-grid-range rather than once for all
  // time, matching how the grid itself is paginated by month.
  useEffect(() => {
    const cells = buildGrid(currentMonth);
    const start = cells[0].dateStr;
    const end = cells[cells.length - 1].dateStr;

    fetch(`/api/calendar/compliance?start_date=${start}&end_date=${end}`)
      .then(r => r.json())
      .then((res: { days: ComplianceDay[] }) => {
        const byDate: Record<string, ComplianceDay> = {};
        for (const d of res.days) byDate[d.date] = d;
        setCompliance(byDate);
      })
      .catch(() => {});
    // units.system: compliance notes are rendered server-side in the current units.
  }, [currentMonth, units.system]);

  const savePrefs = useCallback((updated: Prefs) => {
    fetch("/api/calendar/prefs", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updated),
    }).catch(() => {});
  }, []);

  const toggleBlocked = (date: string) => {
    const updated = {
      ...prefs,
      blocked_days: prefs.blocked_days.includes(date)
        ? prefs.blocked_days.filter(d => d !== date)
        : [...prefs.blocked_days, date],
    };
    setPrefs(updated);
    savePrefs(updated);
  };

  const addRace = (race: Race) => {
    const updated = {
      ...prefs,
      races: [...prefs.races, race].sort((a, b) => a.date.localeCompare(b.date)),
    };
    setPrefs(updated);
    savePrefs(updated);
  };

  const removeRace = (date: string) => {
    const updated = { ...prefs, races: prefs.races.filter(r => r.date !== date) };
    setPrefs(updated);
    savePrefs(updated);
  };

  return {
    prefs, plan, setPlan, activities, compliance, trainingState, toggleBlocked, addRace, removeRace,
  };
}
