import { createContext, useContext, useEffect, useRef, useState } from 'react';
import { api, type Actor } from './api';

export const Session = createContext<{
  actor: Actor;
  patientId: string;
  refreshPatients: () => void;
}>({
  actor: { name: '', role: 'clinician' },
  patientId: '',
  refreshPatients: () => {},
});
export const useSession = () => useContext(Session);
export const decision = (actor: Actor, reason: string) => ({ actor, reason });

export function useResource<T>(path: string | null, version = 0, paginated = false) {
  const [state, setState] = useState<{
    path: string | null;
    version: number;
    data?: T;
    error?: string;
  }>({ path: null, version: -1 });
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    const load = async (): Promise<T> => {
      if (!paginated) return api<T>(path, undefined, controller.signal);
      const rows: unknown[] = [];
      for (let offset = 0; ; offset += 100) {
        const page = await api<unknown[]>(`${path}${path.includes('?') ? '&' : '?'}limit=100&offset=${offset}`, undefined, controller.signal);
        rows.push(...page);
        if (page.length < 100) return rows as T;
      }
    };
    load()
      .then((data) => {
        if (!controller.signal.aborted) setState({ path, version, data });
      })
      .catch((error) => {
        if (!controller.signal.aborted)
          setState({ path, version, error: error.message });
      });
    return () => controller.abort();
  }, [path, version, paginated]);
  const current = state.path === path && state.version === version;
  return {
    data: current ? state.data : undefined,
    error: current ? state.error : undefined,
    loading: !!path && (!current || (!state.data && !state.error)),
  };
}

export function useTask() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const running = useRef(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const run = async (work: () => Promise<void>, success = 'Saved.') => {
    if (running.current) return;
    running.current = true;
    setBusy(true);
    setError('');
    setMessage('');
    try {
      await work();
      if (alive.current) setMessage(success);
    } catch (err) {
      if (alive.current)
        setError(
          err instanceof Error ? err.message : 'Request failed. Please retry.',
        );
    } finally {
      running.current = false;
      if (alive.current) setBusy(false);
    }
  };
  return { busy, error, message, run };
}
