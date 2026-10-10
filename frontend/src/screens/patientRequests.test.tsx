import { act, cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import * as api from '../api';
import type { ChatMessageResponse, Envelope, Patient } from '../types';
import ClinicianReviewScreen from './ClinicianReviewScreen';
import ChatScreen from './ChatScreen';
import PatientMealPlanScreen from './PatientMealPlanScreen';
import SimulationScreen from './SimulationScreen';
import AdherenceScreen from './AdherenceScreen';
import ReviewQueueScreen from './ReviewQueueScreen';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../api');

const patients: Patient[] = [
  { id: 'A', name: 'Patient A', age: 60, sex: 'F', diagnoses: [] },
  { id: 'B', name: 'Patient B', age: 60, sex: 'M', diagnoses: [] },
];

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function envelope(patientId: string): Envelope {
  return {
    id: `ENV-${patientId}`, patient_id: patientId, status: 'PROPOSED', version: 1,
    lifecycle_revision: 7, scope_eligible: true, trace: [],
    constraints: [{ nutrient: 'sodium_mg', kind: 'max', value: 2000, unit: 'mg' }],
  };
}

beforeEach(() => {
  vi.mocked(api.listPatients).mockResolvedValue(patients);
  vi.mocked(api.listObservations).mockResolvedValue({ patient_id: 'A', count: 0, observations: [] });
  vi.mocked(api.listPlans).mockResolvedValue({ count: 0, plans: [] });
  vi.mocked(api.listSimulations).mockResolvedValue({ count: 0, simulations: [] });
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(() => { cleanup(); vi.resetAllMocks(); });

test('a late proposal cannot appear or be approved for the newly selected patient', async () => {
  const proposal = deferred<api.RulesRunResult>();
  vi.mocked(api.runRules).mockReturnValueOnce(proposal.promise);
  render(<MemoryRouter><ClinicianReviewScreen /></MemoryRouter>);
  const user = userEvent.setup();
  await user.click(await screen.findByRole('heading', { name: 'Patient A' }));
  await user.click(screen.getByRole('button', { name: 'Generate proposed envelope' }));
  await user.click(screen.getByRole('heading', { name: 'Patient B' }));
  await act(async () => proposal.resolve({ envelope: envelope('A'), trace: [] }));
  expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull();
  expect(screen.queryByRole('heading', { name: 'Proposed envelope' })).toBeNull();
  expect(api.approveEnvelope).not.toHaveBeenCalled();
});

test('approval submits the revision the clinician actually reviewed', async () => {
  vi.mocked(api.runRules).mockResolvedValue({ envelope: envelope('A'), trace: [] });
  vi.mocked(api.approveEnvelope).mockResolvedValue({ ...envelope('A'), status: 'APPROVED' });
  render(<MemoryRouter><ClinicianReviewScreen /></MemoryRouter>);
  const user = userEvent.setup();
  await user.click(await screen.findByRole('heading', { name: 'Patient A' }));
  await user.click(screen.getByRole('button', { name: 'Generate proposed envelope' }));
  await user.click(await screen.findByRole('button', { name: 'Approve' }));
  expect(api.approveEnvelope).toHaveBeenCalledWith('ENV-A', {
    clinician_id: 'clinician-1', expected_revision: 7,
  });
});

test('a conflict can reload the latest envelope without approving it automatically', async () => {
  vi.mocked(api.runRules).mockResolvedValue({ envelope: envelope('A'), trace: [] });
  vi.mocked(api.approveEnvelope).mockRejectedValue(new Error('Envelope changed; reload before retrying.'));
  vi.mocked(api.getEnvelope).mockResolvedValue({ ...envelope('A'), lifecycle_revision: 8, status: 'EDITED' });
  render(<MemoryRouter><ClinicianReviewScreen /></MemoryRouter>);
  const user = userEvent.setup();
  await user.click(await screen.findByRole('heading', { name: 'Patient A' }));
  await user.click(screen.getByRole('button', { name: 'Generate proposed envelope' }));
  await user.click(await screen.findByRole('button', { name: 'Approve' }));
  await user.click(await screen.findByRole('button', { name: 'Reload envelope' }));
  expect(api.getEnvelope).toHaveBeenCalledWith('ENV-A');
  expect(api.approveEnvelope).toHaveBeenCalledTimes(1);
  expect(await screen.findByText('EDITED')).toBeTruthy();
  await user.click(screen.getByRole('button', { name: 'Approve' }));
  expect(api.approveEnvelope).toHaveBeenLastCalledWith('ENV-A', {
    clinician_id: 'clinician-1', expected_revision: 8,
  });
});

test('chat responses remain scoped across A → B → A selection changes', async () => {
  const oldReply = deferred<ChatMessageResponse>();
  vi.mocked(api.sendChat).mockReturnValueOnce(oldReply.promise);
  render(<ChatScreen />);
  const user = userEvent.setup();
  const select = await screen.findByLabelText('Patient');
  await screen.findByRole('option', { name: /Patient A/ });
  await user.selectOptions(select, 'A');
  await user.type(screen.getByPlaceholderText('Type your question…'), 'How much sodium?');
  await user.click(screen.getByRole('button', { name: 'Send' }));
  await user.selectOptions(select, 'B');
  await user.selectOptions(select, 'A');
  await act(async () => oldReply.resolve({ answer: 'Old personal target', citations: [], escalated: false }));
  expect(screen.queryByText('Old personal target')).toBeNull();
  expect(screen.queryByText('How much sodium?')).toBeNull();
});

test('a late plan failure does not overwrite the newly selected patient state', async () => {
  const oldPlan = deferred<Awaited<ReturnType<typeof api.createPlan>>>();
  vi.mocked(api.createPlan).mockReturnValueOnce(oldPlan.promise);
  render(<PatientMealPlanScreen />);
  const user = userEvent.setup();
  const select = await screen.findByLabelText('Patient');
  await screen.findByRole('option', { name: /Patient A/ });
  await user.selectOptions(select, 'A');
  await user.click(screen.getByRole('button', { name: 'Generate 7-day plan' }));
  await user.selectOptions(select, 'B');
  await act(async () => oldPlan.reject(new Error('Patient A plan failure')));
  expect(screen.queryByText('Patient A plan failure')).toBeNull();
  expect(screen.getByRole<HTMLButtonElement>('button', { name: 'Generate 7-day plan' }).disabled).toBe(false);
});

test('out-of-order simulation prefill preserves the selected patient targets', async () => {
  const oldEnvelope = deferred<Envelope>();
  vi.mocked(api.getLatestEnvelope)
    .mockReturnValueOnce(oldEnvelope.promise)
    .mockResolvedValueOnce({ ...envelope('B'), constraints: [
      { nutrient: 'protein_g', kind: 'max', value: 55, unit: 'g' },
    ] });
  render(<SimulationScreen />);
  const user = userEvent.setup();
  const select = await screen.findByLabelText('Patient');
  await screen.findByRole('option', { name: /Patient A/ });
  await user.selectOptions(select, 'A');
  await user.selectOptions(select, 'B');
  await screen.findByDisplayValue('protein_g');
  await act(async () => oldEnvelope.resolve(envelope('A')));
  expect(screen.queryByDisplayValue('sodium_mg')).toBeNull();
  expect(screen.getByDisplayValue('protein_g')).toBeTruthy();
  expect(api.listSimulations).toHaveBeenCalledWith('B');
  expect(api.listSimulations).not.toHaveBeenCalledWith('A');
});

test('a stale adherence error cannot replace the selected patient error', async () => {
  const oldSummary = deferred<Awaited<ReturnType<typeof api.getAdherenceSummary>>>();
  vi.mocked(api.getAdherenceSummary).mockReturnValueOnce(oldSummary.promise)
    .mockRejectedValueOnce(new Error('Patient B summary unavailable'));
  vi.mocked(api.getAdherenceDeviation).mockRejectedValue(new Error('No trends'));
  render(<AdherenceScreen />);
  const user = userEvent.setup();
  const select = await screen.findByLabelText('Patient');
  await screen.findByRole('option', { name: /Patient A/ });
  await user.selectOptions(select, 'A');
  await user.selectOptions(select, 'B');
  await screen.findByText('Patient B summary unavailable');
  await act(async () => oldSummary.reject(new Error('Patient A summary unavailable')));
  expect(screen.queryByText('Patient A summary unavailable')).toBeNull();
  expect(screen.getByText('Patient B summary unavailable')).toBeTruthy();
});

test('a stale review queue cannot repopulate a new patient filter', async () => {
  const oldQueue = deferred<Awaited<ReturnType<typeof api.getReviewQueue>>>();
  vi.mocked(api.getReviewQueue).mockReturnValueOnce(oldQueue.promise)
    .mockResolvedValue({ count: 0, items: [] });
  vi.mocked(api.getReviewItems).mockResolvedValue({ count: 0, items: [] });
  render(<MemoryRouter><ReviewQueueScreen /></MemoryRouter>);
  const user = userEvent.setup();
  const select = await screen.findByLabelText('Patient');
  await screen.findByRole('option', { name: /Patient B/ });
  await user.selectOptions(select, 'B');
  await act(async () => oldQueue.resolve({ count: 1, items: [{
    review_id: 'REV-A', patient_id: 'A', source: 'lab_trend', severity: 'alert',
    reason: 'Patient A old alert', status: 'OPEN', created_at: '2026-01-01', payload: {},
  }] }));
  expect(screen.queryByText('Patient A old alert')).toBeNull();
  expect(api.getReviewQueue).toHaveBeenLastCalledWith('B', 'open');
});
