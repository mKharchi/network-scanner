/**
 * Generic data-fetching hook with real-time SSE event integration.
 * Manages loading, error, and stale-data caching; automatically refetches on live event triggers.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '../api/client';
import { useApiState } from './useApiState';

export type FetchState<T> =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'success'; data: T; fetchedAt: Date }
  | { status: 'error'; error: ApiError | Error; staleData?: T };

export function useFetch<T>(
  fetcher: (() => Promise<T>) | null,
  deps: unknown[] = [],
  liveEvents: string[] = [],
) {
  const [state, setLocalState] = useState<FetchState<T>>({ status: 'idle' });
  const { setRefreshing, setSuccess, setFailed } = useApiState();
  const abortRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);
  const fetcherRef = useRef(fetcher);

  // Keep fetcherRef updated with the latest function without triggering effects
  fetcherRef.current = fetcher;

  // Track mounted state
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const execute = useCallback(async (isBackground = false) => {
    if (!fetcherRef.current) return;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    // Transition to loading / refreshing
    setLocalState((prev) => {
      if (prev.status === 'success') {
        if (!isBackground) setRefreshing();
        return prev; // retain stale data while refreshing
      }
      setRefreshing();
      return { status: 'loading' };
    });

    try {
      const data = await fetcherRef.current();
      if (!mountedRef.current || controller.signal.aborted) return;
      setLocalState({ status: 'success', data, fetchedAt: new Date() });
      setSuccess();
    } catch (err) {
      if (!mountedRef.current || controller.signal.aborted) return;
      const error = err instanceof Error ? err : new Error(String(err));
      setLocalState((prev) => ({
        status: 'error',
        error,
        staleData: prev.status === 'success' ? prev.data : undefined,
      }));
      setFailed();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  // Initial fetch and dependency trigger
  useEffect(() => {
    execute();
    return () => {
      abortRef.current?.abort();
    };
  }, [execute]);

  // Subscribe to real-time events for instant background refresh
  useEffect(() => {
    if (liveEvents.length === 0) return;

    const handler = () => {
      execute(true); // background silent refresh
    };

    liveEvents.forEach((evt) => {
      window.addEventListener(evt, handler);
    });

    return () => {
      liveEvents.forEach((evt) => {
        window.removeEventListener(evt, handler);
      });
    };
  }, [execute, liveEvents]);

  return { state, refetch: () => execute(false) };
}
