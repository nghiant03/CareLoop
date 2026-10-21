import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { getApprovalMode, setApprovalMode } from '../api';
import { DEFAULT_REVIEWER, DemoContext, type ApprovalModeState, type DemoState, type DemoView } from './context';

const STORAGE_KEY = 'careloop.demo';
const POLL_MS = 10000;

interface Stored {
  view: DemoView;
  patientId: string | null;
  reviewerName: string;
}

function readInitial(): Stored {
  let stored: Partial<Stored> = {};
  try {
    stored = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || '{}') as Partial<Stored>;
  } catch {
    stored = {};
  }
  const params = new URLSearchParams(window.location.search);
  const urlView = params.get('view');
  const view: DemoView = urlView === 'patient' || urlView === 'clinician'
    ? urlView
    : stored.view === 'patient' ? 'patient' : 'clinician';
  return {
    view,
    patientId: params.get('patient') || stored.patientId || null,
    reviewerName: stored.reviewerName?.trim() || DEFAULT_REVIEWER,
  };
}

/** Demo-only presentation state. Switching views is not authentication. */
export default function DemoProvider({ children }: { children: ReactNode }) {
  const [initial] = useState(readInitial);
  const [view, setView] = useState<DemoView>(initial.view);
  const [patientId, setPatientId] = useState<string | null>(initial.patientId);
  const [reviewerName, setReviewerName] = useState(initial.reviewerName);
  const [approvalMode, setMode] = useState<ApprovalModeState>('loading');
  const [approvalModeSwitching, setSwitching] = useState(false);
  const [approvalModeError, setModeError] = useState<string | null>(null);

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ view, patientId, reviewerName }));
    } catch {
      // Storage may be unavailable (private mode); the session still works.
    }
  }, [view, patientId, reviewerName]);

  useEffect(() => {
    let mounted = true;
    const check = async () => {
      try {
        const selected = await getApprovalMode();
        if (mounted) setMode(selected);
      } catch {
        if (mounted) setMode('unknown');
      }
    };
    void check();
    const interval = setInterval(check, POLL_MS);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  const changeApprovalMode = useCallback(async (mode: 'auto' | 'clinician') => {
    setSwitching(true);
    setModeError(null);
    try {
      setMode(await setApprovalMode(mode));
    } catch (err: unknown) {
      setModeError(err instanceof Error ? err.message : 'Failed to switch approval mode');
    } finally {
      setSwitching(false);
    }
  }, []);

  const value = useMemo<DemoState>(() => ({
    managed: true,
    view,
    setView,
    patientId,
    setPatientId,
    reviewerName,
    setReviewerName,
    approvalMode,
    approvalModeSwitching,
    approvalModeError,
    changeApprovalMode,
  }), [view, patientId, reviewerName, approvalMode, approvalModeSwitching, approvalModeError, changeApprovalMode]);

  return <DemoContext.Provider value={value}>{children}</DemoContext.Provider>;
}
