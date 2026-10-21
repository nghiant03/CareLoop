import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import KnowledgeReviewScreen from './KnowledgeReviewScreen';

const draft = { draft_id: 'draft-one', revision: 2, author: 'author', rules_hash: 'hash', dishes_hash: 'dish-hash', validation: { clinical_validation: 'not_established' }, provenance: {}, review: null, release_id: null };
const rules = [{ rule_id: 'SODIUM', guideline: 'Guideline', verbatim_quote: 'Limit sodium', url: 'https://example.org/source', actions: [{ kind: 'max', value: 2000 }] }, { rule_id: 'PROTEIN', url: 'javascript:alert(1)' }];

function setup(options: { enabled?: boolean; stale?: boolean; fail?: boolean } = {}) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input);
    if (options.fail) return new Response('', { status: 503 });
    const data = url.endsWith('/documents') ? { rules: { rules }, dishes: [] }
      : url.endsWith('/history') ? []
      : url.includes('/revision?') ? { rules: { rules: [{ ...rules[0], verbatim_quote: 'Earlier quote' }] }, dishes: [] }
      : url.endsWith('/decision') ? { ...draft, review: { decision: 'reject' } }
      : { deployment_mode: 'review', draft, current_draft: { ...draft, revision: options.stale ? 3 : 2 }, technical_review: { blockers: ['Clinical exclusion unresolved'] }, review_enabled: options.enabled ?? true, csrf_token: 'token' };
    return new Response(JSON.stringify(data), { status: 200, headers: { 'Content-Type': 'application/json' } });
  });
  vi.stubGlobal('fetch', fetchMock);
  render(<KnowledgeReviewScreen />);
  return fetchMock;
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('browses rules, filters missing evidence and never links unsafe URLs', async () => {
  setup();
  await screen.findByRole('heading', { name: 'SODIUM' });
  expect(screen.getByText('“Limit sodium”')).toBeTruthy();
  await userEvent.click(screen.getByLabelText('Show only rules missing a quote or valid source link'));
  expect(screen.getByRole('heading', { name: 'PROTEIN' })).toBeTruthy();
  expect(screen.queryByRole('link', { name: /javascript/ })).toBeNull();
  await userEvent.type(screen.getByLabelText('Search rules'), 'not-present');
  expect(screen.getByText('No rules match. Clear the search or evidence filter.')).toBeTruthy();
});

it('shows blockers and compares the earlier revision', async () => {
  setup();
  await screen.findByRole('heading', { name: 'SODIUM' });
  await userEvent.selectOptions(screen.getByLabelText('Compare with an earlier revision'), '1');
  await screen.findByText('Changed rule');
  await userEvent.click(screen.getByText('Earlier rule, revision 1'));
  expect(screen.getByText('Earlier quote')).toBeTruthy();
  await userEvent.click(screen.getByRole('button', { name: 'Blockers & provenance' }));
  expect(screen.getAllByText('Clinical exclusion unresolved').length).toBeGreaterThan(0);
});

it('records an explicit revision-bound decision with a CSRF token', async () => {
  const fetchMock = setup();
  await screen.findByRole('heading', { name: 'SODIUM' });
  await userEvent.click(screen.getByRole('button', { name: 'History & decision' }));
  await userEvent.type(screen.getByLabelText('Reviewer name (required)'), 'independent-reviewer');
  await userEvent.type(screen.getByLabelText('Review rationale (required)'), 'Evidence incomplete');
  await userEvent.click(screen.getByRole('checkbox'));
  await userEvent.click(screen.getByRole('button', { name: 'Record review decision' }));
  await screen.findByText('Review decision recorded. This does not publish or activate the draft.');
  const call = fetchMock.mock.calls.find(([path]) => String(path).endsWith('/decision'));
  expect(call?.[1]?.headers).toEqual({ 'Content-Type': 'application/json', 'X-Review-Token': 'token' });
  expect(JSON.parse(String(call?.[1]?.body))).toEqual({ actor: 'independent-reviewer', note: 'Evidence incomplete', decision: 'reject', expected_revision: 2 });
});

it('disables decisions for stale snapshots', async () => {
  setup({ stale: true });
  await screen.findByRole('heading', { name: 'SODIUM' });
  expect(screen.getByRole('alert').textContent).toContain('A newer draft exists');
  await userEvent.click(screen.getByRole('button', { name: 'History & decision' }));
  expect((screen.getByLabelText('Reviewer name (required)') as HTMLInputElement).closest('fieldset')?.disabled).toBe(true);
});

it('offers recovery when loading fails', async () => {
  setup({ fail: true });
  await screen.findByRole('heading', { name: 'Knowledge review unavailable' });
  expect(screen.getByRole('alert').textContent).toContain('503');
  expect(screen.getByRole('button', { name: 'Retry loading' })).toBeTruthy();
  await waitFor(() => expect(screen.queryByText('Loading knowledge review')).toBeNull());
});
