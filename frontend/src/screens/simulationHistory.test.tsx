import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';
import { listSimulations } from '../api';
import SimulationScreen from './SimulationScreen';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const comparison = {
  base: { envelope_id: 'ENV-P1-001', feasible: true },
  simulated: { envelope_id: 'SIM-ENV-P1-001', feasible: false },
  deltas: { cost: null, nutrient_target_deviation: null, variety: null, worst_shortfall_pct: null, meals_changed: null },
};
const history = { count: 1, simulations: [{
  simulation_id: 'SIM-P1-001', patient_id: 'P1', base_envelope_id: 'ENV-P1-001',
  proposed_targets: [], comparison, status: 'OPEN', created_at: '2026-01-01T00:00:00Z',
}] };

test('persisted comparison records normalize into the simulation view contract', async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(history), { status: 200 }));
  vi.stubGlobal('fetch', fetchMock);
  expect(await listSimulations('P1')).toEqual({ count: 1, simulations: [{
    simulation_id: 'SIM-P1-001', patient_id: 'P1', proposed_targets: [],
    created_at: '2026-01-01T00:00:00Z', ...comparison,
  }] });
  expect(fetchMock).toHaveBeenCalledWith('/api/simulations?patient_id=P1');
});

test('real-shaped nonempty history renders after patient selection', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url === '/api/patients') return new Response(JSON.stringify({ patients: [{
      id: 'P1', name: 'Patient One', age: 60, sex: 'F', diagnoses: [],
    }] }));
    if (url.startsWith('/api/envelopes/latest')) return new Response(JSON.stringify({
      envelope_id: 'ENV-P1-001', patient_id: 'P1', status: 'APPROVED', version: 1,
      lifecycle_revision: 1, scope_eligible: true, targets: [], fired_rules: [],
    }));
    if (url.startsWith('/api/simulations?')) return new Response(JSON.stringify(history));
    throw new Error(`Unexpected request: ${url}`);
  }));
  render(<SimulationScreen />);
  await userEvent.setup().selectOptions(await screen.findByLabelText('Patient'), 'P1');
  expect(await screen.findByText('SIM-P1-001')).toBeTruthy();
  expect(screen.getByText('Feasible')).toBeTruthy();
  expect(screen.getByText('Infeasible')).toBeTruthy();
});

test('history without a saved comparison reports a controlled error', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
    count: 1, simulations: [{ ...history.simulations[0], comparison: null }],
  }))));
  await expect(listSimulations('P1')).rejects.toThrow('Simulation SIM-P1-001 has no saved comparison.');
});

test('empty simulation history remains empty', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ count: 0, simulations: [] }))));
  await expect(listSimulations('P1')).resolves.toEqual({ count: 0, simulations: [] });
});
