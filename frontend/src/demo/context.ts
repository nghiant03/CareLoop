import { createContext, useContext } from 'react';

export type DemoView = 'clinician' | 'patient';
export type ApprovalModeState = 'auto' | 'clinician' | 'loading' | 'unknown';

export const DEFAULT_REVIEWER = 'clinician-1';
export const VIEW_HOME: Record<DemoView, string> = { clinician: '/', patient: '/plan' };
export const PATIENT_ROUTES = new Set(['/plan', '/adherence', '/chat']);

export interface DemoState {
  /** False when no provider is mounted (isolated screen tests); shared state is then inert. */
  managed: boolean;
  view: DemoView;
  setView: (view: DemoView) => void;
  patientId: string | null;
  setPatientId: (patientId: string | null) => void;
  /** Free-text actor label sent with review actions; an attestation, not an identity. */
  reviewerName: string;
  setReviewerName: (name: string) => void;
  approvalMode: ApprovalModeState;
  approvalModeSwitching: boolean;
  approvalModeError: string | null;
  changeApprovalMode: (mode: 'auto' | 'clinician') => Promise<void>;
}

const noop = () => {};

const UNMANAGED: DemoState = {
  managed: false,
  view: 'clinician',
  setView: noop,
  patientId: null,
  setPatientId: noop,
  reviewerName: DEFAULT_REVIEWER,
  setReviewerName: noop,
  approvalMode: 'unknown',
  approvalModeSwitching: false,
  approvalModeError: null,
  changeApprovalMode: async () => {},
};

export const DemoContext = createContext<DemoState>(UNMANAGED);

export function useDemo(): DemoState {
  return useContext(DemoContext);
}
