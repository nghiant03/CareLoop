import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';
import Patients from './Patients';
import Evidence from './Evidence';
import { Session } from '../state';
import type { Facts, Role } from '../api';
import type { Rule } from '../api';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test('rule filters combine and preserve explicit selections across hidden results', async () => {
  const rules: Rule[] = [
    {
      id: 'draft',
      latest_revision: 1,
      active_revision: null,
      approved_by: null,
      retired: false,
      draft: {
        source_id: 's1',
        quote: 'Evidence',
        location: 'Page 1',
        applicability: [],
        exceptions: [],
        blockers: ['Review population'],
        population_note: 'Children',
        exception_note: 'None',
        action: {
          kind: 'assessment',
          subject: 'protein',
          advice: 'Assess protein needs',
        },
      },
    },
    {
      id: 'published',
      latest_revision: 1,
      active_revision: 1,
      approved_by: 'Reviewer',
      retired: false,
      draft: {
        source_id: 's2',
        quote: 'Evidence',
        location: 'Page 2',
        applicability: [],
        exceptions: [],
        blockers: [],
        population_note: 'Hypertension',
        exception_note: 'None',
        action: { kind: 'ceiling', subject: 'sodium', advice: 'Limit sodium' },
      },
    },
  ];
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async (path: string) =>
        new Response(
          JSON.stringify(
            path === '/api/evidence/catalogue'
              ? { generation: 1, rules }
              : path.includes('/sources')
                ? [
                    {
                      id: 's1',
                      title: 'Child guideline',
                      edition: '2024',
                      locator: 'https://example.org/child',
                    },
                    {
                      id: 's2',
                      title: 'Adult guideline',
                      edition: '2025',
                      locator: 'https://example.org/adult',
                    },
                  ]
                : { seeds: [] },
          ),
        ),
    ),
  );
  mount(<Evidence />, 'reviewer');
  const user = userEvent.setup();
  await screen.findByText('Assess protein needs');
  await user.selectOptions(
    screen.getByRole('combobox', { name: 'Rule source' }),
    's1',
  );
  await user.selectOptions(
    screen.getByRole('combobox', { name: 'Rule subject' }),
    'protein',
  );
  await user.selectOptions(
    screen.getByRole('combobox', { name: 'Rule status' }),
    'Draft',
  );
  await user.click(
    screen.getByRole('checkbox', { name: 'With review blockers' }),
  );
  await user.type(
    screen.getByRole('searchbox', { name: 'Search rules' }),
    'children',
  );
  expect(screen.queryByText('Limit sodium')).toBeNull();
  await user.click(
    screen.getByRole('button', { name: 'Select visible rules' }),
  );
  await user.selectOptions(
    screen.getByRole('combobox', { name: 'Rule status' }),
    'Published',
  );
  expect(screen.getByText(/No rules match/)).toBeTruthy();
  expect(screen.getByText(/1 selected \(1 hidden by filters\)/)).toBeTruthy();
  await user.click(screen.getByRole('button', { name: 'Clear filters' }));
  expect(screen.getByText('Limit sodium')).toBeTruthy();
  await user.click(screen.getByRole('checkbox', { name: 'Selected only' }));
  expect(screen.queryByText('Limit sodium')).toBeNull();
  expect(screen.getByText('Assess protein needs')).toBeTruthy();
  await user.click(screen.getByRole('button', { name: 'Clear selection' }));
  expect(screen.getByText(/No rules match/)).toBeTruthy();
});

function mount(child: React.ReactNode, role: Role = 'clinician') {
  render(
    <Session.Provider
      value={{
        actor: { name: 'UI test', role },
        patientId: 'p1',
        refreshPatients: vi.fn(),
      }}
    >
      {child}
    </Session.Provider>,
  );
}

function patientFetch(facts: Facts) {
  const fetch = vi.fn(async (path: string, init?: RequestInit) => {
    const body =
      path === '/api/patients/p1' && init?.method !== 'POST'
        ? {
            id: 'p1',
            latest_revision: 1,
            body: { display_name: 'Test patient', facts },
          }
        : [];
    return new Response(JSON.stringify(body));
  });
  vi.stubGlobal('fetch', fetch);
  return fetch;
}

test('CKD No clears the stage and submits an explicit false, while Unknown stays distinct', async () => {
  const fetch = patientFetch({});
  mount(<Patients />);
  const user = userEvent.setup();
  const status = await screen.findByRole('combobox', { name: 'CKD status' });
  expect((status as HTMLSelectElement).value).toBe('');
  expect(screen.queryByRole('combobox', { name: 'CKD stage' })).toBeNull();
  await user.selectOptions(status, 'true');
  await user.selectOptions(
    screen.getByRole('combobox', { name: 'CKD stage' }),
    'G4',
  );
  await user.selectOptions(status, 'false');
  expect(screen.queryByRole('combobox', { name: 'CKD stage' })).toBeNull();
  await user.selectOptions(status, 'true');
  expect(
    (screen.getByRole('combobox', { name: 'CKD stage' }) as HTMLSelectElement)
      .value,
  ).toBe('');
  await user.selectOptions(status, '');
  expect(screen.queryByRole('combobox', { name: 'CKD stage' })).toBeNull();
  await user.selectOptions(status, 'false');
  await user.type(
    screen.getByRole('textbox', { name: 'Reason and observation provenance' }),
    'Correct CKD status',
  );
  await user.click(
    screen.getByRole('button', { name: 'Save patient revision' }),
  );
  await waitFor(() =>
    expect(fetch.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(
      true,
    ),
  );
  const post = fetch.mock.calls.find(([, init]) => init?.method === 'POST')!;
  expect(JSON.parse(String(post[1]?.body)).body.facts).toMatchObject({
    has_ckd: false,
    ckd_stage: null,
  });
});

test('existing stage-only patient records retain their stage and show CKD Yes', async () => {
  patientFetch({ ckd_stage: 'G3b' });
  mount(<Patients />);
  expect(
    (
      (await screen.findByRole('combobox', {
        name: 'CKD status',
      })) as HTMLSelectElement
    ).value,
  ).toBe('true');
  expect(
    (screen.getByRole('combobox', { name: 'CKD stage' }) as HTMLSelectElement)
      .value,
  ).toBe('G3b');
});

test('male collapses life-stage fields; switching sex preserves recorded facts', async () => {
  const fetch = patientFetch({
    sex: 'male',
    pregnant: false,
    breastfeeding: true,
  });
  mount(<Patients />);
  const user = userEvent.setup();
  const summary = await screen.findByText('Pregnancy and breastfeeding');
  expect(summary.closest('details')?.open).toBe(false);
  expect(screen.getByText('Pregnant: No · Breastfeeding: Yes')).toBeTruthy();
  await user.click(summary);
  expect(summary.closest('details')?.open).toBe(true);
  expect(
    (
      screen.getByRole('combobox', {
        name: 'breastfeeding',
      }) as HTMLSelectElement
    ).value,
  ).toBe('true');
  const sex = screen.getByRole('combobox', { name: 'Sex' });
  await user.selectOptions(sex, 'female');
  expect(
    screen.getByText('Pregnancy and breastfeeding').closest('details')?.open,
  ).toBe(true);
  await user.selectOptions(sex, 'male');
  expect(
    screen.getByText('Pregnancy and breastfeeding').closest('details')?.open,
  ).toBe(false);
  await user.type(
    screen.getByRole('textbox', { name: 'Reason and observation provenance' }),
    'Reviewed facts',
  );
  await user.click(
    screen.getByRole('button', { name: 'Save patient revision' }),
  );
  await waitFor(() =>
    expect(fetch.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(
      true,
    ),
  );
  const post = fetch.mock.calls.find(([, init]) => init?.method === 'POST')!;
  expect(JSON.parse(String(post[1]?.body)).body.facts).toMatchObject({
    sex: 'male',
    pregnant: false,
    breastfeeding: true,
  });
});

test('life-stage fields start expanded for unknown sex without assuming No', async () => {
  patientFetch({});
  mount(<Patients />);
  expect(
    (await screen.findByText('Pregnancy and breastfeeding')).closest('details')
      ?.open,
  ).toBe(true);
  expect(
    (screen.getByRole('combobox', { name: 'pregnant' }) as HTMLSelectElement)
      .value,
  ).toBe('');
});

test('rule list and editor identify the rule source even when a different source is selected', async () => {
  const sources = [
    {
      id: 's1',
      title: 'Original guideline',
      edition: '2024',
      locator: 'https://example.org/guideline',
    },
    {
      id: 's2',
      title: 'Other guideline',
      edition: '2026',
      locator: 'https://example.org/other',
    },
  ];
  const rule = {
    id: 'r1',
    latest_revision: 1,
    retired: false,
    approved_by: null,
    active_revision: null,
    draft: {
      source_id: 's1',
      quote: 'Source text.',
      location: 'Page 4',
      applicability: [],
      exceptions: [],
      blockers: ['Review'],
      population_note: 'Test',
      exception_note: 'Test',
      action: { kind: 'assessment', subject: 'protein', advice: 'Test' },
    },
  };
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string) => {
      let body: unknown = [];
      if (path.startsWith('/api/evidence/sources?')) body = sources;
      if (path === '/api/evidence/sources') body = sources;
      if (path === '/api/evidence/sources/s2') body = sources[1];
      if (path === '/api/evidence/catalogue')
        body = { generation: 1, rules: [rule] };
      if (path === '/api/evidence/discovery-seeds') body = { seeds: [] };
      return new Response(JSON.stringify(body));
    }),
  );
  mount(<Evidence />, 'reviewer');
  const user = userEvent.setup();
  const link = await screen.findByRole('link', { name: 'Original guideline' });
  expect(link.getAttribute('href')).toBe('https://example.org/guideline');
  await user.selectOptions(
    screen.getByRole('combobox', { name: 'Saved source' }),
    's2',
  );
  await user.click(screen.getByRole('button', { name: 'Edit rule' }));
  expect(
    screen.getAllByRole('link', { name: 'Original guideline' }),
  ).toHaveLength(2);
  expect(screen.getAllByText('Edition: 2024')).toHaveLength(2);
});
