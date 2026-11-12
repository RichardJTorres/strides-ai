import { useCallback, useEffect, useState } from "react";
import { useUnits } from "../../UnitsContext";
import { fetchJson, jsonBody } from "../../ui/api";
import { buildGrid } from "./grid";
import type { Activity, ComplianceDay, Plan, Prefs, TrainingState, WeekStart, Workout } from "./types";

/** Everything the calendar loads, plus the blocked-day mutation. */
export function useCalendarData(currentMonth: Date) {
  const units = useUnits();
  const [prefs, setPrefs] = useState<Prefs>({ blocked_days: [], races: [] });
  const [plan, setPlan] = useState<Plan>({});
  const [activities, setActivities] = useState<Record<string, Activity[]>>({});
  const [compliance, setCompliance] = useState<Record<string, ComplianceDay>>({});
  const [trainingState, setTrainingState] = useState<TrainingState | null>(null);
  // The Settings page owns this preference; the Calendar remounts on every visit, so it picks up
  // a change on the next open. Fails soft to Monday. `weekStartLoaded` holds the compliance
  // fetch back so its first request already covers the right grid range.
  const [weekStart, setWeekStart] = useState<WeekStart>("monday");
  const [weekStartLoaded, setWeekStartLoaded] = useState(false);
  const [loading, setLoading] = useState(true);
  // A failed initial load: without the plan the grid would look like an empty calendar.
  const [loadError, setLoadError] = useState<string | null>(null);
  // A failed blocked-day / race save (the change is rolled back).
  const [prefsError, setPrefsError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  // Bumped once a write has been confirmed. The plan-derived figures below are also refetched
  // on every plan change, but an optimistic change (a drag) is shown before the server has it,
  // so that fetch can return the old numbers; this one cannot.
  const [confirmed, setConfirmed] = useState(0);
  const refreshDerived = useCallback(() => setConfirmed(n => n + 1), []);

  useEffect(() => {
    fetchJson<{ week_start?: string }>("/api/settings")
      .then(s => { if (s.week_start === "sunday") setWeekStart("sunday"); })
      .catch(() => {})
      .finally(() => setWeekStartLoaded(true));
  }, []);

  // Load, projected ramp and plan conflicts depend on the plan and blocked days/races, so they
  // are refetched whenever either changes (the backend is the single source of these numbers).
  // Secondary: the grid is complete without it, so a failure only hides the load strip.
  useEffect(() => {
    let cancelled = false;
    fetchJson<TrainingState>("/api/calendar/training-state")
      .then(state => { if (!cancelled) setTrainingState(state); })
      .catch(() => { if (!cancelled) setTrainingState(null); });
    return () => { cancelled = true; };
  }, [plan, prefs, units.system, confirmed]);

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
    if (!weekStartLoaded) return;
    let cancelled = false;
    const cells = buildGrid(currentMonth, weekStart);
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
  }, [currentMonth, units.system, plan, confirmed, weekStart, weekStartLoaded]);

  // Optimistic: show the change at once. If the save fails, show what the server actually has
  // (several quick changes can overlap, so "the previous value" is not reliably the saved one).
  const savePrefs = useCallback((updated: Prefs) => {
    setPrefs(updated);
    setPrefsError(null);
    fetchJson("/api/calendar/prefs", jsonBody("PUT", updated))
      .then(refreshDerived)
      .catch(() => {
        setPrefsError("Couldn't save your last change to blocked days. Try again.");
        fetchJson<Prefs>("/api/calendar/prefs").then(setPrefs).catch(() => {});
      });
  }, [refreshDerived]);

  const toggleBlocked = (date: string) => {
    savePrefs({
      ...prefs,
      blocked_days: prefs.blocked_days.includes(date)
        ? prefs.blocked_days.filter(d => d !== date)
        : [...prefs.blocked_days, date],
    });
  };

  return {
    prefs, plan, setPlan, activities, compliance, trainingState, toggleBlocked, weekStart,
    loading, loadError, prefsError, reload: () => setAttempt(n => n + 1), confirmed, refreshDerived,
  };
}
