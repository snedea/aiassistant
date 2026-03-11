import { useState, useEffect, useRef, useCallback } from "react";

export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs: number,
): { data: T | null; error: string | null; loading: boolean; refresh: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const isMountedRef = useRef(true);

  const load = useCallback(async () => {
    try {
      const result = await fetcher();
      if (isMountedRef.current) {
        setData(result);
        setError(null);
        setLoading(false);
      }
    } catch (e) {
      if (isMountedRef.current) {
        setError((e as Error).message);
        setLoading(false);
      }
    }
  }, [fetcher]);

  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    isMountedRef.current = true;
    queueMicrotask(() => void load());
    intervalRef.current = setInterval(() => void load(), intervalMs);

    const onAuthRequired = () => {
      if (intervalRef.current !== null) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
    window.addEventListener("auth-required", onAuthRequired);

    return () => {
      if (intervalRef.current !== null) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      window.removeEventListener("auth-required", onAuthRequired);
      isMountedRef.current = false;
    };
  }, [load, intervalMs]);

  return { data, error, loading, refresh: load };
}
