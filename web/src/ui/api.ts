import { useCallback, useEffect, useState } from "react";

/**
 * fetch + JSON that throws on a non-2xx response, with the server's `detail` as the message when
 * it sent one. Use it instead of bare fetch so a failed request can never look like empty data.
 */
export async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail = body && typeof body.detail === "string" ? body.detail : null;
    throw new Error(detail ?? `Request failed (${res.status})`);
  }
  // A 204 (or any empty success) has no body to parse.
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export function jsonBody(method: string, body: unknown): RequestInit {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

export interface ApiState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

/**
 * GET `url` on mount and whenever `url` changes; `null` skips the request. `reload` refetches and
 * keeps showing the current data meanwhile; a different `url` never shows the previous one's data.
 */
export function useApi<T>(url: string | null): ApiState<T> {
  const [state, setState] = useState<{ url: string | null; data: T | null; error: string | null }>(
    { url: null, data: null, error: null },
  );
  const [loading, setLoading] = useState(url !== null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    setLoading(url !== null);
    if (url === null) return;
    const controller = new AbortController();
    fetchJson<T>(url, { signal: controller.signal })
      .then((data) => {
        if (controller.signal.aborted) return;
        setState({ url, data, error: null });
        setLoading(false);
      })
      .catch((e: unknown) => {
        if (controller.signal.aborted) return;
        setState({ url, data: null, error: e instanceof Error ? e.message : "Request failed" });
        setLoading(false);
      });
    return () => controller.abort();
  }, [url, attempt]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  const current = state.url === url;
  return {
    data: current ? state.data : null,
    loading,
    error: current ? state.error : null,
    reload,
  };
}
