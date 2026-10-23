import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import Chat from './Chat';
import Extraction from './Extraction';
import { Session } from '../state';
import type { Actor, ChatRun, ExtractionRun } from '../api';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const context = {
  ready: true,
  patient_revision: 2,
  target_id: 'target-1',
  target_revision: 3,
  evidence_generation: 4,
  facts: {},
  target_items: [],
};
const chatRun: ChatRun = {
  id: 'request-1',
  question: 'What is my protein target?',
  model: 'glm-5.3',
  created_at: '2026-10-23T12:00:00Z',
  state: 'completed',
  error: null,
  context,
  result: {
    answer: 'Your approved protein target is 40 g/day.',
    needs_clinician: false,
    insufficient_evidence: false,
    citations: [
      {
        source_id: 'approved-targets',
        kind: 'approved_target',
        title: 'Clinician-approved nutrition targets',
        location: 'Target revision 3',
        quote: 'Recorded protein target: 40 g/day.',
      },
    ],
  },
};
function mount(child: React.ReactNode, role: Actor['role'] = 'clinician') {
  return render(
    <MemoryRouter>
      <Session.Provider
        value={{
          actor: { name: 'UI test actor', role },
          patientId: 'patient-1',
          refreshPatients: vi.fn(),
        }}
      >
        {child}
      </Session.Provider>
    </MemoryRouter>,
  );
}
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status });

test('extraction sends the selected passage once and opens a saved review draft', async () => {
  let saved: ExtractionRun | null = null;
  const open = vi.fn();
  const fetch = vi.fn(async (path: string, init?: RequestInit) => {
    if (path.includes('/passages?'))
      return json([
        { ordinal: 1, location: 'Page 1', content: 'First passage.' },
        { ordinal: 2, location: 'Page 2', content: 'Second passage.' },
      ]);
    if (init?.method === 'POST') {
      const body = JSON.parse(String(init.body));
      saved = {
        id: body.request_id,
        state: 'completed',
        error: null,
        rule_ids: ['rule-1'],
        created_at: '2026-10-23T12:00:00Z',
        result: { limitations: ['Review the population restriction.'] },
        request: {
          model: 'glm-5.3',
          decision: { passage_ordinal: body.passage_ordinal },
        },
      };
      return json(saved, 201);
    }
    return json(saved ? [saved] : []);
  });
  vi.stubGlobal('fetch', fetch);
  mount(
    <Extraction sourceId="source-1" onDraft={open} onSaved={vi.fn()} />,
    'reviewer',
  );
  const user = userEvent.setup();
  expect(screen.getByText('Saved extraction runs').closest('details')?.open).toBe(false);
  await user.selectOptions(
    await screen.findByRole('combobox', { name: 'Source passage (required)' }),
    '2',
  );
  await screen.findByText('Second passage.');
  await user.type(
    screen.getByRole('textbox', { name: 'Extraction reason (required)' }),
    'Review source guidance',
  );
  await user.click(
    screen.getByRole('button', { name: 'Extract review drafts' }),
  );
  await user.click(
    await screen.findByRole('button', { name: 'Review draft 1' }),
  );
  expect(open).toHaveBeenCalledWith('rule-1');
  expect(screen.getByText(/Saved extraction runs/).closest('details')?.open).toBe(true);
  const posts = fetch.mock.calls.filter(([, init]) => init?.method === 'POST');
  expect(posts).toHaveLength(1);
  expect(JSON.parse(String(posts[0][1]?.body))).toMatchObject({
    passage_ordinal: 2,
    actor: { role: 'reviewer' },
    generation: { response_mode: 'json_object' },
  });
  expect(
    fetch.mock.calls.some(
      ([path]) => path.includes('/approvals') || path.includes('/publications'),
    ),
  ).toBe(false);
});

test('chat pins approved revisions, preserves Enter as a newline, and displays original citations', async () => {
  let saved = false;
  const fetch = vi.fn(async (path: string, init?: RequestInit) => {
    if (path.endsWith('/context')) return json(context);
    if (init?.method === 'POST') {
      saved = true;
      return json(chatRun, 201);
    }
    return json(saved ? [chatRun] : []);
  });
  vi.stubGlobal('fetch', fetch);
  mount(<Chat />, 'patient');
  const user = userEvent.setup();
  await screen.findByText(/Patient revision 2/);
  const question = screen.getByRole('textbox', {
    name: 'Your question (required)',
  });
  await user.type(question, 'What is my protein target?{Enter}');
  expect(
    fetch.mock.calls.filter(([, init]) => init?.method === 'POST'),
  ).toHaveLength(0);
  await user.click(screen.getByRole('button', { name: 'Send question' }));
  await screen.findByText(chatRun.result!.answer);
  const post = fetch.mock.calls.find(([, init]) => init?.method === 'POST')!;
  expect(JSON.parse(String(post[1]?.body))).toMatchObject({
    patient_revision: 2,
    target_id: 'target-1',
    target_revision: 3,
  });
  await user.click(
    screen.getByText(
      /Clinician-approved nutrition targets · Target revision 3/,
    ),
  );
  expect(screen.getByText('Recorded protein target: 40 g/day.')).toBeTruthy();
});

test('a lost chat response can be checked without repeating the provider request', async () => {
  const fetch = vi.fn(async (path: string, init?: RequestInit) => {
    if (path.includes('/plans?')) return json([]);
    if (path.endsWith('/context')) return json(context);
    if (init?.method === 'POST') throw new Error('Connection interrupted');
    if (path.includes('/chat?')) return json([]);
    return json(chatRun);
  });
  vi.stubGlobal('fetch', fetch);
  mount(<Chat />, 'patient');
  const user = userEvent.setup();
  await screen.findByText(/Patient revision 2/);
  await user.type(
    screen.getByRole('textbox', { name: 'Your question (required)' }),
    'What is my protein target?',
  );
  await user.click(screen.getByRole('button', { name: 'Send question' }));
  await screen.findByText('Connection interrupted');
  expect(
    (
      screen.getByRole('button', { name: 'Send question' }) as HTMLButtonElement
    ).matches(':disabled'),
  ).toBe(true);
  await user.click(screen.getByRole('button', { name: 'Check saved answer' }));
  await waitFor(() =>
    expect(
      screen.queryByRole('button', { name: 'Check saved answer' }),
    ).toBeNull(),
  );
  expect(
    fetch.mock.calls.filter(([, init]) => init?.method === 'POST'),
  ).toHaveLength(1);
});

test('stale context blocks new chat questions and labels historical answers', async () => {
  const fetch = vi.fn(async (path: string) =>
    json(
      path.endsWith('/context')
        ? {
            ...context,
            ready: false,
            reason: 'Clinician approval of current targets is required',
          }
        : [chatRun],
    ),
  );
  vi.stubGlobal('fetch', fetch);
  mount(<Chat />, 'patient');
  await screen.findByText(/Historical answer:/);
  expect(
    (
      screen.getByRole('button', { name: 'Send question' }) as HTMLButtonElement
    ).matches(':disabled'),
  ).toBe(true);
  expect(
    screen.getByText(/Ask your clinician to review your targets/),
  ).toBeTruthy();
});

test('non-reviewers cannot start extraction', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => json([])),
  );
  mount(<Extraction sourceId="source-1" onDraft={vi.fn()} onSaved={vi.fn()} />);
  expect(
    (
      screen.getByRole('button', {
        name: 'Extract review drafts',
      }) as HTMLButtonElement
    ).matches(':disabled'),
  ).toBe(true);
});

test('chat attaches selected records, searches without submitting, and requests a checked draft', async () => {
  const meal = {
    day: 1,
    slot: 'lunch',
    item: 2,
    food: { name: 'Original rice' },
  };
  const plan = {
    id: 'plan-1',
    approved_at: '2026-10-23',
    needs_review: false,
    target_id: context.target_id,
    target_revision: context.target_revision,
    start_date: '2026-11-01',
    objective: 'nutrient_fit',
    body: { meals: [meal] },
  };
  const candidate = {
    name: 'Checked rice',
    food_id: 'food-2',
    portion_id: 'serving',
    scale: 1,
    quantity: '100',
    unit: 'g',
    nutrient_delta: { energy: '0' },
    substitution: {
      day: 1,
      slot: 'lunch',
      item: 2,
      food_id: 'food-2',
      portion_id: 'serving',
      scale: 1,
    },
  };
  const run = {
    ...chatRun,
    stale: false,
    result: {
      ...chatRun.result!,
      suggestions: {
        plan_id: plan.id,
        recommendations: [candidate],
        checked_portions: 3,
        eligible_foods: 1,
        approval_required: true,
      },
    },
  };
  let saved = false;
  const fetch = vi.fn(async (path: string, init?: RequestInit) => {
    if (path.endsWith('/context')) return json(context);
    if (path.includes('/patients/patient-1/plans?')) return json([plan]);
    if (path === '/api/plans/plan-1') return json(plan);
    if (path.startsWith('/api/foods?'))
      return json([
        {
          id: 'food-2',
          body: {
            name: 'Checked rice',
            category: 'Grain',
            portions: [{ id: 'serving', label: 'Serving', grams: 100 }],
          },
        },
      ]);
    if (path.endsWith('/substitutions')) return json({ id: 'draft-1' }, 201);
    if (path.endsWith('/chat') && init?.method === 'POST') {
      saved = true;
      return json(run, 201);
    }
    if (path.includes('/chat?')) return json(saved ? [run] : []);
    return json(run);
  });
  vi.stubGlobal('fetch', fetch);
  mount(<Chat />, 'patient');
  const user = userEvent.setup();
  await screen.findByText(/Patient revision 2/);
  await user.click(
    screen.getByText('Include a plan, intake date or substitution search'),
  );
  await user.selectOptions(
    screen.getByRole('combobox', { name: 'Approved meal plan' }),
    'plan-1',
  );
  fireEvent.change(screen.getByLabelText(/Intake date/), {
    target: { value: '2026-11-01' },
  });
  await user.click(
    screen.getByRole('checkbox', { name: 'Find checked substitutions' }),
  );
  await user.selectOptions(
    screen.getByRole('combobox', { name: 'Meal item to replace (required)' }),
    '0',
  );
  await user.type(
    screen.getByRole('textbox', { name: 'Find foods' }),
    'rice{Enter}',
  );
  expect(
    fetch.mock.calls.filter(([, init]) => init?.method === 'POST'),
  ).toHaveLength(0);
  expect(document.querySelector('form form')).toBeNull();
  await user.click(
    await screen.findByRole('checkbox', { name: /Checked rice/ }),
  );
  await user.type(
    screen.getByRole('textbox', { name: 'Your question (required)' }),
    'What can replace lunch?',
  );
  await user.click(screen.getByRole('button', { name: 'Send question' }));
  await user.click(
    await screen.findByRole('button', {
      name: 'Request replacement draft: Checked rice',
    }),
  );
  await screen.findByText(
    'Replacement draft requested. Your clinician must approve it.',
  );
  const posts = fetch.mock.calls.filter(([, init]) => init?.method === 'POST');
  expect(posts).toHaveLength(2);
  expect(JSON.parse(String(posts[0][1]?.body)).workflow).toEqual({
    plan_id: 'plan-1',
    logged_on: '2026-11-01',
    substitution: { day: 1, slot: 'lunch', item: 2, food_ids: ['food-2'] },
  });
  expect(posts[1][0]).toBe('/api/plans/plan-1/substitutions');
  expect(JSON.parse(String(posts[1][1]?.body))).toMatchObject(
    candidate.substitution,
  );
  expect(fetch.mock.calls.some(([path]) => path.endsWith('/approval'))).toBe(
    false,
  );
});

test('changed workflow records mark historical answers even when targets are unchanged', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string) =>
      json(
        path.endsWith('/context')
          ? context
          : path.includes('/plans?')
            ? []
            : [{ ...chatRun, stale: true }],
      ),
    ),
  );
  mount(<Chat />, 'patient');
  await screen.findByText(
    /Historical answer: patient context, evidence or selected records/,
  );
});
