import { useEffect, useState } from "react";
import { fetchCardioCharts, type CardioChartsResponse } from "./api";

interface State {
  data: CardioChartsResponse | null;
  loading: boolean;
  error: string | null;
}

/**
 * Fetches cardio chart data for the given mode/unit, with request cancellation so rapid
 * switching can never paint a stale response. The previous dataset is cleared SYNCHRONOUSLY
 * when mode/unit changes (before the new request even starts) — so there is never a frame
 * showing one mode's charts under another mode's heading while the new request is in flight.
 */
export function useChartData(mode: string, unit: string): State {
  const requestKey = `${mode}:${unit}`;
  const [state, setState] = useState<State & { requestKey: string }>({
    requestKey, data: null, loading: true, error: null,
  });

  useEffect(() => {
    const controller = new AbortController();
    setState({ requestKey, data: null, loading: true, error: null });

    fetchCardioCharts(mode, unit, controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return;
        setState({ requestKey, data, loading: false, error: null });
      })
      .catch((e: unknown) => {
        if (controller.signal.aborted) return;
        const message = e instanceof Error ? e.message : String(e);
        setState({ requestKey, data: null, loading: false, error: message });
      });

    return () => controller.abort();
  }, [mode, unit, requestKey]);

  // Effects run after render. Mask state from the previous request during that first render,
  // rather than relying on the effect's reset to hide it in a later frame.
  return state.requestKey === requestKey
    ? state
    : { data: null, loading: true, error: null };
}
