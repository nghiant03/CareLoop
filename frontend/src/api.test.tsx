import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { approveEnvelope, runRules } from './api';
import RuleTrace from './components/RuleTrace';
import type { EnvelopeResponse } from './types';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

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

test('lifecycle conflicts retain the server reload instruction and status', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
    error: 'envelope_conflict', message: 'Envelope changed; reload before retrying.',
  }), { status: 409 })));
  await expect(approveEnvelope('ENV-P1', { clinician_id: 'reviewer', expected_revision: 1 }))
    .rejects.toMatchObject({ status: 409, message: 'Envelope changed; reload before retrying.' });
});
