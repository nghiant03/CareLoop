import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import Logging from './Logging';
import Plans from './Plans';
import { localDate, type Food, type Plan } from '../api';
import { Session } from '../state';

const foods: Food[] = ['Rice', 'Fish', 'Vegetables'].map((name, i) => ({
  id: `food-${i}`,
  latest_revision: 1,
  body: {
    name,
    category: 'UI test foods',
    basis: 'g',
    nutrients: { energy: 100, protein: 10, sodium: 100 },
    portions: [{ id: 'portion', label: '100 g', grams: 100 }],
    planning_portions: ['portion'],
    meal_slots: ['breakfast', 'lunch', 'dinner'],
    allergen_status: {},
    vegetarian: null,
    contains_egg: null,
    contains_dairy: null,
    provenance: {
      kind: 'manual',
      source: 'test://fixture',
      notes: 'Test only',
    },
  },
}));
const plan: Plan = {
  id: 'plan-1',
  objective: 'nutrient_fit',
  needs_review: false,
  approved_at: '2026-01-01',
  target_id: 'target-1',
  target_revision: 2,
  request: { start_date: localDate(), days: 1, schedule: ['lunch'] },
  body: {
    meals: foods.slice(0, 2).map((food, i) => ({
      day: 1,
      slot: 'lunch',
      item: i + 1,
      food_id: food.id,
      food_revision: 1,
      food: food.body,
      portion_id: 'portion',
      scale: 1,
      quantity: '100',
      unit: 'g',
    })),
    check: {
      valid: true,
      violations: [],
      daily_totals: { '1': { energy: '200', protein: '20', sodium: '200' } },
    },
  },
};
const request = vi.fn();

beforeEach(() => {
  request.mockImplementation(async (path: string, init?: RequestInit) => {
    let body: unknown = [];
    if (path.startsWith('/api/foods?')) body = foods;
    else if (path.endsWith('/target-readiness'))
      body = {
        targets_ready: true,
        approved_target: { id: 'target-1', approved_revision: 2 },
      };
    else if (path.startsWith('/api/patients/patient-1/plans?')) body = [plan];
    else if (path === '/api/plans/plan-1') body = plan;
    else if (path.includes('target-comparison'))
      body = { target_needs_review: false, comparisons: [] };
    else if (path.includes('meal-log-days'))
      body = {
        complete: false,
        entries: [],
        recorded_totals: { energy: null },
        planned_slots: [],
      };
    else if (path === '/api/plan-requests')
      body = {
        alternatives: [{ ...plan, approved_at: null }],
        outcome: { status: 'drafts_available' },
      };
    else if (init?.method === 'POST') body = {};
    return new Response(JSON.stringify(body), { status: 200 });
  });
  vi.stubGlobal('fetch', request);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

function mount(
  child: React.ReactNode,
  route = '/',
  role: 'patient' | 'clinician' = 'patient',
) {
  render(
    <MemoryRouter initialEntries={[route]}>
      <Session.Provider
        value={{
          actor: { name: `Test ${role}`, role },
          patientId: 'patient-1',
          refreshPatients: vi.fn(),
        }}
      >
        {child}
      </Session.Provider>
    </MemoryRouter>,
  );
}

test('planning sends multi-item counts and exact approved target revision', async () => {
  mount(<Plans />);
  const user = userEvent.setup();
  await user.click(screen.getByText(/Food choices \(optional\)/));
  await user.selectOptions(
    screen.getByRole('combobox', { name: 'Foods to consider' }),
    'selected',
  );
  await user.click(await screen.findByRole('checkbox', { name: /Rice/ }));
  await user.click(screen.getByRole('checkbox', { name: /Fish/ }));
  await user.click(screen.getByRole('checkbox', { name: /Vegetables/ }));
  await user.click(
    screen.getByRole('button', { name: 'Generate three alternatives' }),
  );
  await waitFor(() =>
    expect(request.mock.calls.some(([p]) => p === '/api/plan-requests')).toBe(
      true,
    ),
  );
  const sent = JSON.parse(
    request.mock.calls.find(([p]) => p === '/api/plan-requests')![1].body,
  );
  expect(sent.items_per_slot).toEqual({ breakfast: 2, lunch: 3, dinner: 3 });
  expect(sent.target_revision).toBe(2);
  expect(sent.food_ids).toEqual(foods.map((f) => f.id));
  expect(
    await screen.findByText('Checked draft. Clinician approval is required.'),
  ).toBeTruthy();
});

test('planning searches the catalogue by default without food selection', async () => {
  mount(<Plans />);
  const user = userEvent.setup();
  const generate = screen.getByRole('button', {
    name: 'Generate three alternatives',
  });
  await waitFor(() =>
    expect((generate as HTMLButtonElement).disabled).toBe(false),
  );
  expect(screen.queryByRole('checkbox', { name: /Rice/ })).toBeNull();
  await user.click(generate);
  await waitFor(() =>
    expect(request.mock.calls.some(([p]) => p === '/api/plan-requests')).toBe(
      true,
    ),
  );
  const sent = JSON.parse(
    request.mock.calls.find(([p]) => p === '/api/plan-requests')![1].body,
  );
  expect(sent.food_ids).toBeUndefined();
  expect(sent.excluded_food_ids).toEqual([]);
});

test('plans visibly disclose estimated food composition from stored snapshots', async () => {
  const original = request.getMockImplementation()!;
  const estimated = structuredClone(plan);
  estimated.body.meals[0].food.source_details = {
    careloop_estimates: JSON.stringify({
      estimates: {
        sodium: { value: 100, method: 'cohort_median', confidence: 'low' },
      },
    }),
  };
  request.mockImplementation(async (path: string, init?: RequestInit) =>
    path === '/api/plans/plan-1'
      ? new Response(JSON.stringify(estimated), { status: 200 })
      : original(path, init),
  );
  mount(<Plans />);
  await userEvent
    .setup()
    .click(await screen.findByRole('button', { name: 'Open plan' }));
  expect(
    await screen.findByText(/Uses estimated food composition/),
  ).toBeTruthy();
  expect(screen.getByText('Food estimates and methods')).toBeTruthy();
});

test('optional exclusions leave the rest of the catalogue available', async () => {
  mount(<Plans />);
  const user = userEvent.setup();
  await user.click(screen.getByText(/Food choices \(optional\)/));
  await user.selectOptions(
    screen.getByRole('combobox', { name: 'Foods to consider' }),
    'exclude',
  );
  await user.click(await screen.findByRole('checkbox', { name: /Fish/ }));
  await user.click(
    screen.getByRole('button', { name: 'Generate three alternatives' }),
  );
  await waitFor(() =>
    expect(request.mock.calls.some(([p]) => p === '/api/plan-requests')).toBe(
      true,
    ),
  );
  const sent = JSON.parse(
    request.mock.calls.find(([p]) => p === '/api/plan-requests')![1].body,
  );
  expect(sent.food_ids).toBeUndefined();
  expect(sent.excluded_food_ids).toEqual(['food-1']);
});

test('logging sends the selected meal item, not the first item in its slot', async () => {
  mount(<Logging />, '/patient/meal-log?plan=plan-1');
  const user = userEvent.setup();
  const buttons = await screen.findAllByRole('button', { name: 'Record item' });
  await user.click(buttons[1]);
  await user.selectOptions(
    screen.getByRole('combobox', { name: 'What happened?' }),
    'changed_quantity',
  );
  const scale = screen.getByRole('spinbutton', { name: 'Portion multiplier' });
  await user.clear(scale);
  await user.type(scale, '1.5');
  await user.click(screen.getByRole('button', { name: 'Record intake' }));
  await waitFor(() =>
    expect(
      request.mock.calls.some(
        ([p]) => p === '/api/patients/patient-1/meal-logs',
      ),
    ).toBe(true),
  );
  const sent = JSON.parse(
    request.mock.calls.find(
      ([p]) => p === '/api/patients/patient-1/meal-logs',
    )![1].body,
  );
  expect(sent).toMatchObject({
    plan_id: 'plan-1',
    item: 2,
    slot: 'lunch',
    status: 'changed_quantity',
    scale: 1.5,
  });
  expect(sent.food_id).toBeUndefined();
});

test('clinician plan review hides patient generation and substitution controls', async () => {
  mount(<Plans />, '/clinician/plan-review', 'clinician');
  expect(
    screen.queryByRole('button', { name: 'Generate three alternatives' }),
  ).toBeNull();
  await userEvent
    .setup()
    .click(await screen.findByRole('button', { name: 'Open plan' }));
  expect(screen.queryByRole('button', { name: /Find replacement/ })).toBeNull();
  expect(
    screen
      .getByRole('link', { name: 'Review recorded intake' })
      .getAttribute('href'),
  ).toBe('/clinician/intake-review?plan=plan-1');
});

test('clinician intake view is read-only', async () => {
  mount(<Logging />, '/clinician/intake-review?plan=plan-1', 'clinician');
  await screen.findByText('Rice');
  expect(screen.queryByRole('button', { name: 'Record item' })).toBeNull();
  expect(
    screen.queryByRole('button', { name: 'Confirm whole meal' }),
  ).toBeNull();
  expect(
    screen.queryByRole('button', { name: 'Add independent food entry' }),
  ).toBeNull();
  expect(
    screen.queryByRole('button', { name: 'Mark day complete' }),
  ).toBeNull();
});
