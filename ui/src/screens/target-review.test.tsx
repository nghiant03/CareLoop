import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';
import { TargetEditor } from './Patients';
import { Session } from '../state';
import type { Target } from '../api';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const citation = {
  source_id: 'source',
  quote: 'Retained source',
  location: 'Section 1',
};
const target: Target = {
  id: 't1',
  latest_revision: 1,
  approved_revision: null,
  needs_review: false,
  body: {
    items: [],
    blockers: [
      { rule_id: 'required', issue: 'Clinician disposition required' },
    ],
  },
  evaluation: [
    {
      rule_id: 'required',
      revision: 1,
      status: 'needs_clinician',
      category: 'assessment',
      source_action: {
        kind: 'assessment',
        subject: 'energy',
        advice: 'Individualise energy',
      },
      missing: [],
      issues: [],
      citation,
    },
    {
      rule_id: 'advice',
      revision: 1,
      status: 'advisory',
      category: 'advisory',
      source_action: {
        kind: 'assessment',
        subject: 'fat',
        advice: 'Prefer unsaturated fats',
      },
      missing: [],
      issues: [],
      citation,
    },
    {
      rule_id: 'excluded',
      revision: 1,
      status: 'excluded',
      category: 'target',
      source_action: {
        kind: 'ceiling',
        subject: 'sodium',
        advice: 'Limit sodium',
      },
      missing: [],
      issues: [],
      citation,
    },
  ],
};

function mount(value = target) {
  render(
    <Session.Provider
      value={{
        actor: { name: 'Clinician', role: 'clinician' },
        patientId: 'p1',
        refreshPatients: vi.fn(),
      }}
    >
      <TargetEditor target={value} onSaved={vi.fn()} />
    </Session.Provider>,
  );
}

test('clinician can select assessments and advice; filters preserve decisions and separate payloads', async () => {
  const fetch = vi.fn(async () => new Response(JSON.stringify(target)));
  vi.stubGlobal('fetch', fetch);
  mount();
  const user = userEvent.setup();
  const assessment = screen.getByRole('checkbox', {
    name: 'energy · needs clinician',
  }) as HTMLInputElement;
  expect(assessment.disabled).toBe(false);
  await user.click(assessment);
  expect(assessment.checked).toBe(true);
  await user.type(
    screen.getByRole('textbox', { name: 'Clinical decision — energy' }),
    'Reviewed energy needs and documented the individual target.',
  );
  await user.click(screen.getByRole('checkbox', { name: 'fat · advisory' }));
  const excluded = screen.getByRole('checkbox', {
    name: 'sodium · excluded',
  }) as HTMLInputElement;
  expect(excluded.disabled).toBe(true);
  await user.selectOptions(
    screen.getByRole('combobox', { name: 'evaluated rules status' }),
    'advisory',
  );
  expect(screen.queryByText('Individualise energy')).toBeNull();
  expect(screen.getByText(/2 selected · 1 hidden by filters/)).toBeTruthy();
  await user.type(
    screen.getByRole('textbox', { name: 'Review reason' }),
    'Reviewed guidance and assessment',
  );
  await user.click(
    screen.getByRole('button', { name: 'Save target revision' }),
  );
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
  const request = fetch.mock.calls[0] as unknown as [string, RequestInit];
  const payload = JSON.parse(String(request[1].body));
  expect(payload.selected).toEqual([]);
  expect(payload.guidance).toEqual([{ rule_id: 'advice', revision: 1 }]);
  expect(payload.assessments[0].rule.rule_id).toBe('required');
  expect(payload.dispositions).toEqual([]);
});

test('hidden unresolved assessments are revealed before a save', async () => {
  const fetch = vi.fn();
  vi.stubGlobal('fetch', fetch);
  mount();
  const user = userEvent.setup();
  await user.selectOptions(
    screen.getByRole('combobox', { name: 'Rule category' }),
    'advisory',
  );
  await user.type(
    screen.getByRole('textbox', { name: 'Review reason' }),
    'Review',
  );
  await user.click(
    screen.getByRole('button', { name: 'Save target revision' }),
  );
  expect(fetch).not.toHaveBeenCalled();
  expect(
    await screen.findByText(/Record a clinical decision for 1 rules/),
  ).toBeTruthy();
  expect(
    screen.getByRole('textbox', { name: 'Clinical decision — energy' }),
  ).toBeTruthy();
});

test('saved advisory and assessment selections reopen while approved revisions are read-only', () => {
  mount({
    ...target,
    approved_revision: 2,
    latest_revision: 2,
    body: {
      ...target.body,
      assessments: [
        {
          rule: { rule_id: 'required', revision: 1 },
          reason: 'Reviewed',
          action: target.evaluation[0].source_action,
          citation,
        },
      ],
      guidance: [
        {
          rule: { rule_id: 'advice', revision: 1 },
          action: target.evaluation[1].source_action,
          citation,
        },
      ],
    },
  });
  const checkbox = screen.getByRole('checkbox', {
    name: 'energy · needs clinician',
  }) as HTMLInputElement;
  expect(checkbox.checked).toBe(true);
  expect(checkbox.closest('fieldset')?.disabled).toBe(true);
  expect(
    (
      screen.getByRole('checkbox', {
        name: 'fat · advisory',
      }) as HTMLInputElement
    ).checked,
  ).toBe(true);
});
