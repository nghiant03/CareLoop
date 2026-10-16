import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { getApprovalMode } from '../api';
import ApprovalModeBanner from './ApprovalModeBanner';

vi.mock('../api', () => ({ getApprovalMode: vi.fn() }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

it('shows a persistent honest demo notice and simulated reviewer role', async () => {
  vi.mocked(getApprovalMode).mockResolvedValue('auto');
  render(<ApprovalModeBanner />);
  expect((await screen.findByText(/Demo mode/)).textContent).toContain('not clinically reviewed');
  expect(screen.getByRole('status').textContent).toContain('simulate a clinician role');
});

it('does not show the demo banner in clinician mode', async () => {
  vi.mocked(getApprovalMode).mockResolvedValue('clinician');
  render(<ApprovalModeBanner />);
  await waitFor(() => expect(screen.queryByRole('status')).toBeNull());
});

it('does not imply clinical review when configuration is unavailable', async () => {
  vi.mocked(getApprovalMode).mockRejectedValue(new Error('offline'));
  render(<ApprovalModeBanner />);
  expect((await screen.findByText(/Approval mode unavailable/)).textContent).toContain('Do not assume clinical review');
});
