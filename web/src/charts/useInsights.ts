import { useCallback, useEffect, useRef, useState } from "react";
import { fetchInsights, generateInsights, type InsightsPayload } from "./api";

interface State {
  data: InsightsPayload | null;
  loading: boolean;
  generating: boolean;
  error: string | null;
}

/**
 * Loads the cached insights + live digest for a mode (never calls the LLM), and exposes
 * `generate` to (re)build the readout. State is keyed by mode/units so a switch can never paint
 * another mode's report; in-flight requests are aborted on change/unmount.
 */
export function useInsights(mode: string, unitSystem: string) {
  const requestKey = `${mode}:${unitSystem}`;
  const [state, setState] = useState<State & { requestKey: string }>({
    requestKey, data: null, loading: true, generating: false, error: null,
  });
  const genController = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    genController.current?.abort();
    setState({ requestKey, data: null, loading: true, generating: false, error: null });
    fetchInsights(mode, controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return;
        setState({ requestKey, data, loading: false, generating: false, error: null });
      })
      .catch((e: unknown) => {
        if (controller.signal.aborted) return;
        setState({
          requestKey, data: null, loading: false, generating: false,
          error: e instanceof Error ? e.message : String(e),
        });
      });
    return () => controller.abort();
  }, [mode, requestKey]);

  const generate = useCallback((force: boolean) => {
    genController.current?.abort();
    const controller = new AbortController();
    genController.current = controller;
    setState((s) => ({ ...s, generating: true, error: null }));
    generateInsights(mode, force, controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return;
        setState({ requestKey, data, loading: false, generating: false, error: null });
      })
      .catch((e: unknown) => {
        if (controller.signal.aborted) return;
        setState((s) => ({
          ...s, generating: false, error: e instanceof Error ? e.message : String(e),
        }));
      });
  }, [mode, requestKey]);

  useEffect(() => () => genController.current?.abort(), []);

  return state.requestKey === requestKey
    ? { ...state, generate }
    : { data: null, loading: true, generating: false, error: null, generate };
}
