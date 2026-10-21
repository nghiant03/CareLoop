import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import * as api from '../api';
import type { Envelope, Patient } from '../types';
import App from '../App';

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof api>();
  return {
    ...actual,
    getApprovalMode: vi.fn(),
    setApprovalMode: vi.fn(),
    listPatients: vi.fn(),
    getLatestEnvelope: vi.fn(),
    listObservations: vi.fn(),
    listPlans: vi.fn(),
    createPlan: vi.fn(),
    approveEnvelope: vi.fn(),
    rejectEnvelope: vi.fn(),
    sendChat: vi.fn(),
  };
});

const patients: Patient[] = [
  { id: 'P0005', name: 'Mr Tan', age: 62, sex: 'M', diagnoses: ['T2D', 'HTN', 'CKD_stage_4'] },
];

const proposedEnvelope: Envelope = {
  id: 'ENV-P0005-001',
  patient_id: 'P0005',
  status: 'PROPOSED',
  version: 1,
  lifecycle_revision: 3,
  scope_eligible: true,
  constraints: [{ nutrient: 'sodium_mg', kind: 'max', value: 2000, unit: 'mg' }],
  trace: [],
};

beforeEach(() => {
  window.localStorage.clear();
  vi.mocked(api.getApprovalMode).mockResolvedValue('auto');
  vi.mocked(api.setApprovalMode).mockImplementation(async (mode) => mode);
  vi.mocked(api.listPatients).mockResolvedValue(patients);
  vi.mocked(api.getLatestEnvelope).mockResolvedValue(proposedEnvelope);
  vi.mocked(api.listObservations).mockResolvedValue({ patient_id: 'P0005', count: 0, observations: [] });
  vi.mocked(api.listPlans).mockResolvedValue({ count: 0, plans: [] });
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

test('selecting a patient loads their latest envelope without generating a new proposal, and carries across to Patient view', async () => {
  render(<MemoryRouter initialEntries={['/']}><App /></MemoryRouter>);
  const user = userEvent.setup();

  await user.click(await screen.findByRole('heading', { name: 'Mr Tan' }));
  expect(api.getLatestEnvelope).toHaveBeenCalledWith('P0005');
  expect(await screen.findByText('ENV-P0005-001')).toBeTruthy();

  const viewGroup = screen.getByRole('group', { name: 'Demo view' });
  await user.click(within(viewGroup).getByRole('button', { name: 'Patient' }));

  expect(await screen.findByRole('heading', { name: 'Your meal plan' })).toBeTruthy();
  expect(screen.getByText(/Viewing meals for/)).toBeTruthy();
  expect(screen.getByLabelText<HTMLSelectElement>('Acting as').value).toBe('P0005');
  expect(screen.queryByRole('link', { name: 'Review' })).toBeNull();
  expect(screen.queryByRole('link', { name: 'Queue' })).toBeNull();
  expect(screen.queryByRole('link', { name: 'What-if' })).toBeNull();
  expect(screen.getByRole('status', { name: 'Approval policy' })).toBeTruthy();
});

test('approval mode toggle updates the runtime policy and hides/shows the demo notice', async () => {
  render(<MemoryRouter initialEntries={['/']}><App /></MemoryRouter>);
  const user = userEvent.setup();

  expect(await screen.findByText(/Demo mode — new targets are auto-approved/)).toBeTruthy();
  const modeGroup = screen.getByRole('group', { name: 'Approval mode' });
  await user.click(within(modeGroup).getByRole('button', { name: 'Manual review' }));

  expect(api.setApprovalMode).toHaveBeenCalledWith('clinician');
  await waitFor(() => expect(screen.queryByRole('status', { name: 'Approval policy' })).toBeNull());
});

test('reviewer name and rejection confirmation submit custom attestation values', async () => {
  vi.mocked(api.approveEnvelope).mockResolvedValue({ ...proposedEnvelope, status: 'APPROVED', approved_by: 'Dr Lim' });
  vi.mocked(api.rejectEnvelope).mockResolvedValue({ ...proposedEnvelope, status: 'REJECTED' });
  render(<MemoryRouter initialEntries={['/']}><App /></MemoryRouter>);
  const user = userEvent.setup();

  const reviewerInput = screen.getByLabelText('Reviewer name');
  await user.clear(reviewerInput);
  await user.type(reviewerInput, 'Dr Lim');

  await user.click(await screen.findByRole('heading', { name: 'Mr Tan' }));
  await screen.findByText('ENV-P0005-001');

  await user.click(screen.getByRole('button', { name: 'Reject' }));
  await user.type(screen.getByLabelText('Reason for rejection'), 'Pending repeat potassium lab');
  await user.click(screen.getByRole('button', { name: 'Confirm reject' }));

  expect(api.rejectEnvelope).toHaveBeenCalledWith('ENV-P0005-001', {
    reason: 'Pending repeat potassium lab',
    rejected_by: 'Dr Lim',
    expected_revision: 3,
  });
});
