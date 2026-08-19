/**
 * Global API connection state context.
 * Tracks whether the last fetch succeeded, is in-flight, stale, or completely unavailable.
 */

import { createContext, useCallback, useContext, useRef, useState } from 'react';

export type ApiState = 'connected' | 'refreshing' | 'stale' | 'unavailable';

interface ApiStateCtx {
  state:        ApiState;
  lastOkAt:     Date | null;
  setRefreshing: () => void;
  setSuccess:    () => void;
  setFailed:     () => void;
}

const ApiStateContext = createContext<ApiStateCtx>({
  state:         'connected',
  lastOkAt:      null,
  setRefreshing: () => {},
  setSuccess:    () => {},
  setFailed:     () => {},
});

export function ApiStateProvider({ children }: { children: React.ReactNode }) {
  const [state, setState]       = useState<ApiState>('connected');
  const [lastOkAt, setLastOkAt] = useState<Date | null>(null);
  const hasHadSuccess           = useRef(false);

  const setRefreshing = useCallback(() => setState('refreshing'), []);

  const setSuccess = useCallback(() => {
    hasHadSuccess.current = true;
    setLastOkAt(new Date());
    setState('connected');
  }, []);

  const setFailed = useCallback(() => {
    setState(hasHadSuccess.current ? 'stale' : 'unavailable');
  }, []);

  return (
    <ApiStateContext.Provider value={{ state, lastOkAt, setRefreshing, setSuccess, setFailed }}>
      {children}
    </ApiStateContext.Provider>
  );
}

export function useApiState() {
  return useContext(ApiStateContext);
}
