import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { approveEnvelope, runRules, HttpApiError, getAdherenceDeviation, getCalendarMetadata, setApprovalMode } from './api';
import RuleTrace from './components/RuleTrace';
import type { EnvelopeResponse } from './types';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

test('calendar metadata uses the server-local calendar contract', async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
    today: '2026-10-12', timezone: 'Pacific/Auckland', utc_offset_minutes: 780,
  }), { status: 200 }));
  vi.stubGlobal('fetch', fetchMock);
  await expect(getCalendarMetadata()).resolves.toEqual({
    today: '2026-10-12', timezone: 'Pacific/Auckland', utc_offset_minutes: 780,
  });
  expect(fetchMock).toHaveBeenCalledWith('/api/calendar');
});

test('actual wire trace shape retains citations, action text, and superseded markers in the view', async () => {
  const envelope: EnvelopeResponse = {
    envelope_id: 'ENV-P1-001', patient_id: 'P1', version: 1, lifecycle_revision: 1,
    scope_eligible: true, status: 'PROPOSED', proposed_at: '2026-01-01T00:00:00Z',
    targets: [], exclusions: [], citations: [], fired_rules: [{
      rule_id: 'DASH-SODIUM', priority: 70, fired_at: '2026-01-01T00:00:00Z',
      patient_summary: 'HTN + CKD',
      action_summary: 'set sodium_mg max = 2300 mg | SUPERSEDED: superseded by KDIGO-SODIUM',
      citation: { rule_id: 'DASH-SODIUM', guideline: 'DASH', section: 'Sodium', url: 'https://example.org/guideline' },
    }],
  };
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
    envelope, trace: envelope.fired_rules,
  }), { status: 200 })));
  const response = await runRules('P1');
  render(<RuleTrace trace={response.envelope.trace ?? []} />);
  expect(screen.getByText(/set sodium_mg max = 2300/)).toBeTruthy();
  expect(screen.getByText('KDIGO-SODIUM')).toBeTruthy();
  expect(screen.getByRole('link', { name: /View guideline/ }).getAttribute('href')).toBe('https://example.org/guideline');
  expect(response.trace).toEqual(response.envelope.trace);
});

test('HTTP errors preserve nested code, full body, status and compatible display aliases', async () => {
  const body = { detail: { error: 'plan_context_required', message: 'Choose a saved plan.', plan_id: 'old' } };
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status: 409 })));
  try {
    await approveEnvelope('ENV-P1', { clinician_id: 'reviewer' });
    throw new Error('Expected an HTTP error');
  } catch (error) {
    expect(error).toBeInstanceOf(HttpApiError);
    expect(error).toMatchObject({ status: 409, code: 'plan_context_required', error: 'plan_context_required',
      message: 'Choose a saved plan.', data: 'Choose a saved plan.', body });
  }
});

test('non-JSON HTTP errors retain status text and validation arrays retain their original body', async () => {
  const fetchMock = vi.fn().mockResolvedValueOnce(new Response('Unavailable', { status: 503, statusText: 'Service unavailable' }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ detail: [{ loc: ['body', 'targets'], msg: 'Required' }] }), { status: 422 }));
  vi.stubGlobal('fetch', fetchMock);
  await expect(approveEnvelope('ENV-P1', { clinician_id: 'reviewer' })).rejects.toMatchObject({ status: 503, message: 'Service unavailable' });
  await expect(approveEnvelope('ENV-P1', { clinician_id: 'reviewer' })).rejects.toMatchObject({ status: 422,
    body: { detail: [{ loc: ['body', 'targets'], msg: 'Required' }] } });
});

test('historical flags normalize to exact envelope/version series identities without changing wire keys', async () => {
  const flags = [
    { series_key: 'sodium_mg', envelope_id: 'ENV-A', envelope_version: 1 },
    { series_key: 'sodium_mg', envelope_id: 'ENV-A', envelope_version: 2 },
    { series_key: 'protein_g', envelope_id: 'ENV-B', envelope_version: 1 },
  ];
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
    series: { 'ENV-A::v1::sodium_mg': {}, 'ENV-A::v2::sodium_mg': {}, 'ENV-B::protein_g': {} }, flags,
  }), { status: 200 })));
  expect((await getAdherenceDeviation('P1')).flags.map((flag) => flag.series_key)).toEqual([
    'ENV-A::v1::sodium_mg', 'ENV-A::v2::sodium_mg', 'ENV-B::protein_g',
  ]);
});

test('legacy single-envelope flag keys remain unchanged', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
    series: { sodium_mg: {} }, flags: [{ series_key: 'sodium_mg' }],
  }), { status: 200 })));
  expect((await getAdherenceDeviation('P1')).flags[0].series_key).toBe('sodium_mg');
});

test('lifecycle conflicts retain the server reload instruction and status', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
    error: 'envelope_conflict', message: 'Envelope changed; reload before retrying.',
  }), { status: 409 })));
  await expect(approveEnvelope('ENV-P1', { clinician_id: 'reviewer', expected_revision: 1 }))
    .rejects.toMatchObject({ status: 409, message: 'Envelope changed; reload before retrying.' });
});

test('approval mode switch sends PUT /api/config/approval-mode and validates response', async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
    approval_mode: 'clinician',
  }), { status: 200 }));
  vi.stubGlobal('fetch', fetchMock);
  await expect(setApprovalMode('clinician')).resolves.toBe('clinician');
  expect(fetchMock).toHaveBeenCalledWith('/api/config/approval-mode', expect.objectContaining({
    method: 'PUT',
    body: JSON.stringify({ approval_mode: 'clinician' }),
  }));
});
