import { act, cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import * as api from '../api';
import type { AdherenceDeviation, AdherenceSummary, Envelope, MealPlan, NutrientConstraint, Simulation, SubstituteDish } from '../types';
import ConstraintTable from '../components/ConstraintTable';
import ClinicianReviewScreen from './ClinicianReviewScreen';
import ReviewQueueScreen from './ReviewQueueScreen';
import PatientMealPlanScreen from './PatientMealPlanScreen';
import AdherenceScreen from './AdherenceScreen';
import ChatScreen from './ChatScreen';
import SimulationScreen from './SimulationScreen';

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof api>();
  return { ...actual, listPatients: vi.fn(), getPatient: vi.fn(), getEnvelope: vi.fn(), listObservations: vi.fn(),
    runRules: vi.fn(), approveEnvelope: vi.fn(), getReviewQueue: vi.fn(), getReviewItems: vi.fn(), createReviewProposal: vi.fn(),
    listPlans: vi.fn(), getPlan: vi.fn(), createPlan: vi.fn(), getSubstitutions: vi.fn(), applySwap: vi.fn(),
    getAdherenceSummary: vi.fn(), getAdherenceDeviation: vi.fn(), getCalendarMetadata: vi.fn(), searchDishes: vi.fn(), sendChat: vi.fn(),
    getLatestEnvelope: vi.fn(), listSimulations: vi.fn(), createSimulation: vi.fn() };
});

const patient = { id: 'P1', name: 'Patient One', age: 60, sex: 'F', diagnoses: [] };
const envelope: Envelope = { id: 'ENV-P1-003', patient_id: 'P1', status: 'PROPOSED', version: 2,
  lifecycle_revision: 19, scope_eligible: true, constraints: [{ nutrient: 'sodium_mg', kind: 'max', value: 1800, unit: 'mg' }] };

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function plan(id?: string, dish = 'D1'): MealPlan {
  return { plan_id: id, envelope_id: envelope.id, envelope_version: 2, patient_id: 'P1', feasible: true,
    violation_count: 0, infeasibility_reason: null, violations: [], relaxed_constraints: [], status: 'APPROVED',
    explanation: { headline: '', daily_targets: [], avoid: [], why: [] },
    days: [{ day: 1, totals: [], slots: [{ meal: 'breakfast', dish_id: dish, name: `Dish ${dish}`,
      nutrients: { energy_kcal: null, protein_g: 12, sodium_mg: 30, potassium_mg: 50 } }] }] };
}

const substitute = (id: string): SubstituteDish => ({ dish_id: id, name: id, distance: 0, nutrient_distance: 0,
  category_match: true, reason: 'Validated', day_deltas: {}, cost_delta: 0, passes_hard_checks: true });

beforeEach(() => {
  vi.mocked(api.listPatients).mockResolvedValue([patient]);
  vi.mocked(api.getPatient).mockResolvedValue(patient);
  vi.mocked(api.getEnvelope).mockResolvedValue(envelope);
  vi.mocked(api.listObservations).mockResolvedValue({ patient_id: 'P1', count: 0, observations: [] });
  vi.mocked(api.listPlans).mockResolvedValue({ count: 2, plans: ['A', 'B'].map((id) => ({ plan_id: id,
    patient_id: 'P1', envelope_id: envelope.id, feasible: true, violation_count: 0, created_at: '2026-01-01' })) });
  vi.mocked(api.getPlan).mockImplementation(async (id) => plan(id));
  vi.mocked(api.getSubstitutions).mockResolvedValue({ dish_id: 'D1', k: 3, patient_id: 'P1', plan_id: 'A',
    informational_only: false, notice: null, affected_days: [1], substitutions: [substitute('S1'), substitute('S2')] });
  Element.prototype.scrollIntoView = vi.fn();
});
afterEach(() => { cleanup(); vi.resetAllMocks(); vi.useRealTimers(); });

test('review proposal handoff loads the exact proposal and approves its displayed revision', async () => {
  const item = { review_id: 'R1', patient_id: 'P1', source: 'lab_trend' as const, severity: 'alert' as const,
    status: 'OPEN' as const, reason: 'Lab alert', created_at: '2026-01-01', payload: {} };
  vi.mocked(api.getReviewQueue).mockResolvedValue({ count: 1, items: [item] });
  vi.mocked(api.getReviewItems).mockResolvedValue({ count: 0, items: [] });
  vi.mocked(api.createReviewProposal).mockResolvedValue({ review_item: item, envelope_id: envelope.id });
  vi.mocked(api.approveEnvelope).mockResolvedValue({ ...envelope, status: 'APPROVED' });
  render(<MemoryRouter initialEntries={['/review-queue']}><Routes>
    <Route path="/review-queue" element={<ReviewQueueScreen />} /><Route path="/" element={<ClinicianReviewScreen />} />
  </Routes></MemoryRouter>);
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: 'Create proposal' }));
  await user.click(await screen.findByRole('button', { name: 'Approve' }));
  expect(api.getEnvelope).toHaveBeenCalledWith(envelope.id);
  expect(api.getPatient).toHaveBeenCalledWith('P1');
  expect(api.runRules).not.toHaveBeenCalled();
  expect(api.approveEnvelope).toHaveBeenCalledWith(envelope.id, { clinician_id: 'clinician-1', expected_revision: 19 });
});

test('canonical constraint provenance displays both guideline and clinician authors without inferred joins', () => {
  const constraints: NutrientConstraint[] = ['rules-engine', 'Dr Lin'].map((author, index) => ({
    nutrient: 'sodium_mg', kind: 'max', value: 1800 + index, unit: 'mg', provenance: {
      nutrient: 'sodium_mg', kind: 'max', value: 1800 + index, unit: 'mg', envelope_id: envelope.id, version: 2, author,
      citation: { rule_id: index ? 'CLINICIAN-EDIT' : 'KDIGO', guideline: index ? 'clinician override' : 'KDIGO 2024',
        section: 'Sodium', url: index ? null : 'https://example.org/kdigo' },
    },
  }));
  render(<ConstraintTable constraints={constraints} />);
  expect(screen.getByRole('link', { name: 'KDIGO 2024' }).getAttribute('href')).toBe('https://example.org/kdigo');
  expect(screen.getByText('Author: Dr Lin')).toBeTruthy();
  expect(screen.getByText('clinician override')).toBeTruthy();
});

async function loadPlanScreen() {
  render(<PatientMealPlanScreen />);
  const user = userEvent.setup();
  await user.selectOptions(await screen.findByLabelText('Patient'), 'P1');
  await user.click((await screen.findAllByRole('button', { name: 'Load plan' }))[0]);
  await screen.findByText('Dish D1');
  return user;
}

test('a late source-plan swap cannot replace a newly loaded plan for the same patient', async () => {
  const swap = deferred<MealPlan>();
  vi.mocked(api.applySwap).mockReturnValue(swap.promise);
  const user = await loadPlanScreen();
  await user.click(screen.getByRole('button', { name: 'Suggest swaps' }));
  await user.click((await screen.findAllByRole('button', { name: 'Apply swap' }))[0]);
  const controls = screen.getAllByRole<HTMLButtonElement>('button', { name: 'Apply swap' });
  expect(controls.every((button) => button.disabled)).toBe(true);
  await user.click(screen.getByRole('button', { name: 'Close' }));
  await user.click(screen.getAllByRole('button', { name: 'Load plan' })[1]);
  await screen.findByText('B', { selector: 'span' });
  await act(async () => swap.resolve(plan('A-derived', 'OLD')));
  expect(screen.queryByText('Dish OLD')).toBeNull();
  expect(api.applySwap).toHaveBeenCalledTimes(1);
  expect(api.applySwap).toHaveBeenCalledWith({ patient_id: 'P1', dish_id: 'D1', replacement_dish_id: 'S1', plan_id: 'A' });
});

test('late suggestions do not open for a new source plan and missing nutrient values retain their labels', async () => {
  const suggestions = deferred<Awaited<ReturnType<typeof api.getSubstitutions>>>();
  vi.mocked(api.getSubstitutions).mockReturnValue(suggestions.promise);
  const user = await loadPlanScreen();
  expect(screen.getByText('Protein 12.0 g · Sodium 30.0 mg · Potassium 50.0 mg')).toBeTruthy();
  await user.click(screen.getByRole('button', { name: 'Suggest swaps' }));
  await user.click(screen.getAllByRole('button', { name: 'Load plan' })[1]);
  await screen.findByText('B', { selector: 'span' });
  await act(async () => suggestions.resolve({ dish_id: 'D1', k: 1, patient_id: 'P1', plan_id: 'A',
    informational_only: false, notice: null, affected_days: [], substitutions: [substitute('STALE')] }));
  expect(screen.queryByText('STALE')).toBeNull();
});

test('an unidentified displayed plan disables swaps instead of falling back to another saved plan', async () => {
  vi.mocked(api.createPlan).mockResolvedValue(plan());
  render(<PatientMealPlanScreen />);
  const user = userEvent.setup();
  await user.selectOptions(await screen.findByLabelText('Patient'), 'P1');
  await user.click(screen.getByRole('button', { name: 'Generate 7-day plan' }));
  expect((await screen.findByRole<HTMLButtonElement>('button', { name: 'Suggest swaps' })).disabled).toBe(true);
  expect(api.getSubstitutions).not.toHaveBeenCalled();
});

test('a non-approval 409 retains its own recovery message', async () => {
  vi.mocked(api.createPlan).mockRejectedValue(new api.HttpApiError(409, 'other_conflict', {}, 'Reload this plan.'));
  render(<PatientMealPlanScreen />);
  const user = userEvent.setup();
  await user.selectOptions(await screen.findByLabelText('Patient'), 'P1');
  await user.click(screen.getByRole('button', { name: 'Generate 7-day plan' }));
  expect(await screen.findByText('Reload this plan.')).toBeTruthy();
  expect(screen.queryByText(/does not have an approved envelope/)).toBeNull();
});

test('Generate remains disabled during approval and becomes available after completion', async () => {
  const approval = deferred<Envelope>();
  vi.mocked(api.approveEnvelope).mockReturnValue(approval.promise);
  render(<MemoryRouter initialEntries={[`/?envelope=${envelope.id}`]}><ClinicianReviewScreen /></MemoryRouter>);
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: 'Approve' }));
  expect(screen.getByRole<HTMLButtonElement>('button', { name: 'Generate proposed envelope' }).disabled).toBe(true);
  await act(async () => approval.resolve({ ...envelope, status: 'APPROVED' }));
  expect(screen.getByRole<HTMLButtonElement>('button', { name: 'Generate proposed envelope' }).disabled).toBe(false);
});

test('changing patient selection invalidates a late linked-proposal response', async () => {
  const linked = deferred<Envelope>();
  vi.mocked(api.getEnvelope).mockReturnValue(linked.promise);
  render(<MemoryRouter initialEntries={[`/?envelope=${envelope.id}`]}><ClinicianReviewScreen /></MemoryRouter>);
  const user = userEvent.setup();
  await user.click(await screen.findByRole('heading', { name: patient.name }));
  await act(async () => linked.resolve(envelope));
  expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull();
});

test('an unknown linked proposal reports failure without generating a replacement', async () => {
  vi.mocked(api.getEnvelope).mockRejectedValue(new Error('Envelope not found'));
  render(<MemoryRouter initialEntries={['/?envelope=missing']}><ClinicianReviewScreen /></MemoryRouter>);
  expect(await screen.findByText('Envelope not found')).toBeTruthy();
  expect(api.runRules).not.toHaveBeenCalled();
});

test('one pending application disables swap entry controls across every source-plan slot', async () => {
  const source = plan('A');
  source.days[0].slots.push({ ...source.days[0].slots[0], meal: 'lunch', dish_id: 'D2', name: 'Dish D2' });
  vi.mocked(api.getPlan).mockResolvedValue(source);
  const swap = deferred<MealPlan>();
  vi.mocked(api.applySwap).mockReturnValue(swap.promise);
  const user = await loadPlanScreen();
  await user.click(screen.getAllByRole('button', { name: 'Suggest swaps' })[0]);
  await user.click((await screen.findAllByRole('button', { name: 'Apply swap' }))[0]);
  expect(screen.getAllByRole<HTMLButtonElement>('button', { name: 'Suggest swaps' }).every((button) => button.disabled)).toBe(true);
  await act(async () => swap.reject(new Error('Swap unavailable')));
  expect(screen.getAllByRole<HTMLButtonElement>('button', { name: 'Apply swap' }).every((button) => !button.disabled)).toBe(true);
});

test('escalation instructs contact without promising an unimplemented clinician workflow', async () => {
  vi.mocked(api.sendChat).mockResolvedValue({ answer: 'Please contact a clinician.', escalated: true, citations: [] });
  render(<ChatScreen />);
  const user = userEvent.setup();
  await user.selectOptions(await screen.findByLabelText('Patient'), 'P1');
  await user.type(screen.getByPlaceholderText('Type your question…'), 'Medication?');
  await user.click(screen.getByRole('button', { name: 'Send' }));
  expect(await screen.findByText('Contact your clinician about this question.')).toBeTruthy();
  expect(screen.queryByText('A clinician will review this question.')).toBeNull();
});

test('negative minimized variety delta is an improvement and history failure does not hide the comparison', async () => {
  vi.mocked(api.getLatestEnvelope).mockResolvedValue({ ...envelope, status: 'EDITED' });
  vi.mocked(api.listSimulations).mockRejectedValue(new Error('History offline'));
  const simulation: Simulation = { simulation_id: 'SIM1', patient_id: 'P1', proposed_targets: envelope.constraints,
    base: { envelope_id: envelope.id, feasible: true }, simulated: { envelope_id: 'SIM', feasible: true },
    deltas: { cost: 0, nutrient_target_deviation: 0, variety: -0.3, worst_shortfall_pct: 0, meals_changed: 1 } };
  vi.mocked(api.createSimulation).mockResolvedValue(simulation);
  render(<SimulationScreen />);
  const user = userEvent.setup();
  await user.selectOptions(await screen.findByLabelText('Patient'), 'P1');
  expect(await screen.findByText(/Latest envelope is EDITED/)).toBeTruthy();
  await user.click(screen.getByRole('button', { name: 'Run what-if' }));
  const label = await screen.findByText('Variety objective');
  expect(within(label.parentElement!).getByText('-0.3000').className).toContain('text-emerald-700');
  expect(await screen.findByText('History unavailable: History offline')).toBeTruthy();
});

function adherenceFixtures() {
  vi.mocked(api.getCalendarMetadata).mockResolvedValue({ today: '2026-10-11', timezone: 'Pacific/Auckland', utc_offset_minutes: 780 });
  const summary: AdherenceSummary = { patient_id: 'P1', envelope_id: envelope.id, envelope_status: 'APPROVED',
    informational_only: false, notice: null, window: { start: '2026-01-01', end: '2026-01-14', days: 14 },
    days_logged: 1, aggregate: { days_logged: 1, hard_violation_days: 0, hard_violations_by_nutrient: {},
      soft_gaps_by_nutrient: {}, mean_pct_deviation_by_nutrient: {} },
    days: [{ date: '2026-01-01', meals: [], totals: {}, hard_violations: [], soft_gaps: [], compliant: true,
      nutrients: ['over', 'under'].map((direction) => ({ nutrient: 'energy_kcal', kind: 'target', unit: 'kcal',
        limit: 1800, total: direction === 'over' ? 2000 : 1600, deviation: 200, direction: direction as 'over' | 'under',
        status: 'soft_gap', pct_deviation: 11 })) }] };
  const points = [1, 2, 3].map((day) => ({ date: `2026-01-0${day}`, total: 1800, pct: 0, exposure: 0, complete: true }));
  const deviation: AdherenceDeviation = { ...summary, series: {
    sodium_mg: { nutrient: 'sodium_mg', kind: 'max', unit: 'mg', limit: 1800, points },
    protein_g: { nutrient: 'protein_g', kind: 'min', unit: 'g', limit: 50, points: points.map((point) => ({ ...point, complete: false })) },
  }, flags: [] };
  vi.mocked(api.getAdherenceSummary).mockResolvedValue(summary);
  vi.mocked(api.getAdherenceDeviation).mockResolvedValue(deviation);
}

test('adherence uses owner soft-gap direction and distinguishes insufficient complete-day assessment', async () => {
  adherenceFixtures();
  render(<AdherenceScreen />);
  const user = userEvent.setup();
  await user.selectOptions(await screen.findByLabelText('Patient'), 'P1');
  expect(await screen.findByText('Above target')).toBeTruthy();
  expect(screen.getByText('Below target')).toBeTruthy();
  await user.click(screen.getByRole('button', { name: 'Trends' }));
  expect(await screen.findByText('No detected trend')).toBeTruthy();
  expect(screen.getByText('Not assessed: fewer than three complete logged days')).toBeTruthy();
  expect(screen.queryByText('Stable')).toBeNull();
});

test('historical trend cards attach each normalized flag to its own envelope version', async () => {
  adherenceFixtures();
  const base = await vi.mocked(api.getAdherenceDeviation)('P1');
  const series = base.series.sodium_mg;
  const keys = ['ENV-A::v1::sodium_mg', 'ENV-A::v2::sodium_mg'];
  vi.mocked(api.getAdherenceDeviation).mockResolvedValue({ ...base,
    series: { [keys[0]]: series, [keys[1]]: series },
    flags: keys.map((key, index) => ({ nutrient: 'sodium_mg', kind: 'max', series_key: key,
      envelope_id: 'ENV-A', envelope_version: index + 1, slope_pct_per_day: index ? -2 : 2,
      direction: index ? 'improving' : 'worsening', severity: 'review', latest_exposure_pct: 10,
      projected_3d_exposure_pct: 16, reason: `Version ${index + 1} trend` })),
  });
  render(<AdherenceScreen />);
  const user = userEvent.setup();
  await user.selectOptions(await screen.findByLabelText('Patient'), 'P1');
  await user.click(screen.getByRole('button', { name: 'Trends' }));
  expect(await screen.findByText('Worsening')).toBeTruthy();
  expect(screen.getByText('Improving')).toBeTruthy();
  expect(screen.queryByText('No detected trend')).toBeNull();
});

test('dish search rejects stale results and surfaces request failures separately', async () => {
  adherenceFixtures();
  const oldSearch = deferred<Awaited<ReturnType<typeof api.searchDishes>>>();
  vi.mocked(api.searchDishes).mockReturnValueOnce(oldSearch.promise).mockRejectedValueOnce(new Error('Catalogue offline'));
  render(<AdherenceScreen />);
  const user = userEvent.setup();
  await user.selectOptions(await screen.findByLabelText('Patient'), 'P1');
  await user.click(screen.getByRole('button', { name: 'Log a meal' }));
  await user.type(screen.getByLabelText('Search dish'), 'old');
  await vi.waitFor(() => expect(api.searchDishes).toHaveBeenCalledWith('old'));
  await user.clear(screen.getByLabelText('Search dish'));
  await user.type(screen.getByLabelText('Search dish'), 'new');
  expect(await screen.findByText('Search unavailable: Catalogue offline')).toBeTruthy();
  await act(async () => oldSearch.resolve({ count: 1, dishes: [{ dish_id: 'OLD', name: 'Stale dish' }] }));
  expect(screen.queryByText('Stale dish')).toBeNull();
  expect(screen.queryByText('No dishes found')).toBeNull();
});

test('the editor uses server calendar date despite browser/server day mismatch and refreshes on reopen', async () => {
  adherenceFixtures();
  render(<AdherenceScreen />);
  const user = userEvent.setup();
  await user.selectOptions(await screen.findByLabelText('Patient'), 'P1');
  await user.click(screen.getByRole('button', { name: 'Log a meal' }));
  expect(screen.getByLabelText<HTMLInputElement>('Date').value).toBe('2026-10-11');
  await user.click(screen.getByRole('button', { name: 'Summary' }));
  vi.mocked(api.getCalendarMetadata).mockResolvedValueOnce({ today: '2026-10-12', timezone: 'Pacific/Auckland', utc_offset_minutes: 780 });
  await user.click(screen.getByRole('button', { name: 'Log a meal' }));
  expect(screen.getByLabelText<HTMLInputElement>('Date').value).toBe('2026-10-12');
  expect(api.getCalendarMetadata).toHaveBeenCalledTimes(2);
});

test('a late calendar response cannot replace a date the user already entered', async () => {
  adherenceFixtures();
  const calendar = deferred<Awaited<ReturnType<typeof api.getCalendarMetadata>>>();
  vi.mocked(api.getCalendarMetadata).mockReturnValueOnce(calendar.promise);
  render(<AdherenceScreen />);
  const user = userEvent.setup();
  await user.selectOptions(await screen.findByLabelText('Patient'), 'P1');
  await user.click(screen.getByRole('button', { name: 'Log a meal' }));
  await user.type(screen.getByLabelText('Date'), '2026-10-09');
  await act(async () => calendar.resolve({ today: '2026-10-11', timezone: 'UTC', utc_offset_minutes: 0 }));
  expect(screen.getByLabelText<HTMLInputElement>('Date').value).toBe('2026-10-09');
});

test('a calendar response from a closed editor cannot affect the next opening', async () => {
  adherenceFixtures();
  const oldCalendar = deferred<Awaited<ReturnType<typeof api.getCalendarMetadata>>>();
  vi.mocked(api.getCalendarMetadata).mockReturnValueOnce(oldCalendar.promise);
  render(<AdherenceScreen />);
  const user = userEvent.setup();
  await user.selectOptions(await screen.findByLabelText('Patient'), 'P1');
  await user.click(screen.getByRole('button', { name: 'Log a meal' }));
  await user.click(screen.getByRole('button', { name: 'Summary' }));
  await user.click(screen.getByRole('button', { name: 'Log a meal' }));
  await act(async () => oldCalendar.resolve({ today: '2026-10-09', timezone: 'UTC', utc_offset_minutes: 0 }));
  expect(screen.getByLabelText<HTMLInputElement>('Date').value).toBe('2026-10-11');
});

test('calendar metadata failure offers retry and requires confirmation before manual date logging', async () => {
  adherenceFixtures();
  vi.mocked(api.getCalendarMetadata).mockRejectedValueOnce(new Error('Calendar unavailable'))
    .mockResolvedValueOnce({ today: '2026-10-12', timezone: 'UTC', utc_offset_minutes: 0 });
  render(<AdherenceScreen />);
  const user = userEvent.setup();
  await user.selectOptions(await screen.findByLabelText('Patient'), 'P1');
  await user.click(screen.getByRole('button', { name: 'Log a meal' }));
  expect(await screen.findByText(/Server date unavailable/)).toBeTruthy();
  await user.type(screen.getByLabelText('Date'), '2026-10-10');
  expect(screen.queryByRole('button', { name: 'Use this date manually' })).toBeTruthy();
  await user.click(screen.getByRole('button', { name: 'Use this date manually' }));
  await user.click(screen.getByRole('button', { name: 'Retry' }));
  expect(await screen.findByText(/Defaults to the server/)).toBeTruthy();
  expect(screen.getByLabelText<HTMLInputElement>('Date').value).toBe('2026-10-10');
});
