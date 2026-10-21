import { useEffect, useRef } from 'react';
import type { Patient } from '../types';
import { useDemo } from './context';

/**
 * Follow the demo-wide patient selection with a screen's own selection handler.
 *
 * The screen keeps ownership of its reset/load logic; this hook only invokes it
 * when the shared patient differs from the screen's current patient. Without a
 * provider (isolated tests) it does nothing.
 */
export function useSharedPatient(
  patients: Patient[],
  currentPatientId: string | null | undefined,
  select: (patient: Patient) => void,
  paused = false,
) {
  const { managed, patientId } = useDemo();
  const selectRef = useRef(select);
  useEffect(() => {
    selectRef.current = select;
  });
  useEffect(() => {
    if (!managed || paused || !patientId || currentPatientId === patientId) return;
    const patient = patients.find((p) => p.id === patientId);
    if (patient) selectRef.current(patient);
  }, [managed, paused, patients, patientId, currentPatientId]);
}
