import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import App from './App';

const patient = {
  id: 'patient-1',
  latest_revision: 1,
  body: {
    display_name: 'UI test patient',
    facts: {},
    provenance: {
      kind: 'manual',
      source: 'test://fixture',
      notes: 'Test only',
    },
  },
};
const request = vi.fn();

beforeEach(() => {
  request.mockImplementation(async (path: string) => {
    let body: unknown = [];
    if (path.startsWith('/api/patients?')) body = [patient];
    else if (path === '/api/patients/patient-1') body = patient;
    else if (path.endsWith('/target-readiness'))
      body = { targets_ready: false, approved_target: null };
    else if (path === '/api/health') body = { status: 'ok' };
    else if (path === '/api/evidence/catalogue')
      body = { generation: 0, rules: [] };
    else if (path === '/api/evidence/discovery-seeds') body = { seeds: [] };
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  });
  vi.stubGlobal('fetch', request);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

test('new contracts load patient context and retain it across demo roles without automatic approval', async () => {
  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );
  const user = userEvent.setup();
  await screen.findByRole('option', { name: 'UI test patient' });
  await user.selectOptions(
    screen.getByRole('combobox', { name: 'Patient' }),
    'patient-1',
  );
  await screen.findByRole('heading', { name: 'UI test patient · revision 1' });
  await user.selectOptions(
    screen.getByRole('combobox', { name: 'Demo role' }),
    'patient',
  );
  expect(
    await screen.findByRole('heading', { name: 'Meal plans' }),
  ).toBeTruthy();
  expect(
    (screen.getByRole('combobox', { name: 'Patient' }) as HTMLSelectElement)
      .value,
  ).toBe('patient-1');
  expect(screen.queryByRole('link', { name: 'Patients & targets' })).toBeNull();
  expect(screen.queryByText(/auto-approved/i)).toBeNull();
  expect(
    request.mock.calls.every(
      ([, init]) => !init?.method || init.method === 'GET',
    ),
  ).toBe(true);
  expect(
    request.mock.calls.some(([path]) => String(path).includes('approval-mode')),
  ).toBe(false);
});

test('reviewer role opens evidence workflows and records the edited actor label', async () => {
  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );
  const user = userEvent.setup();
  await user.selectOptions(
    screen.getByRole('combobox', { name: 'Demo role' }),
    'reviewer',
  );
  await screen.findByRole('heading', { name: 'Evidence review' });
  await user.clear(
    screen.getByRole('textbox', { name: 'Recorded actor label' }),
  );
  await user.type(
    screen.getByRole('textbox', { name: 'Recorded actor label' }),
    'Named reviewer',
  );
  await user.selectOptions(
    screen.getByRole('combobox', { name: 'Input type' }),
    'text',
  );
  await user.type(
    screen.getByRole('textbox', { name: 'Title' }),
    'Source title',
  );
  await user.type(
    screen.getByRole('textbox', { name: 'Edition / publication date' }),
    '2026',
  );
  await user.type(
    screen.getByRole('textbox', { name: 'Source locator / reference' }),
    'test://source',
  );
  await user.type(
    screen.getByRole('textbox', { name: 'Source text' }),
    'A quoted passage.',
  );
  await user.click(
    screen.getByRole('button', { name: 'Save source snapshot' }),
  );
  await waitFor(() =>
    expect(
      request.mock.calls.some(
        ([path, init]) =>
          path === '/api/evidence/sources' && init?.method === 'POST',
      ),
    ).toBe(true),
  );
  const call = request.mock.calls.find(
    ([path, init]) =>
      path === '/api/evidence/sources' && init?.method === 'POST',
  )!;
  expect(JSON.parse(call[1].body).actor).toEqual({
    name: 'Named reviewer',
    role: 'reviewer',
  });
});

test('API failures have an explicit retry path instead of appearing as an empty catalogue', async () => {
  request.mockResolvedValue(
    new Response(JSON.stringify({ detail: 'Database unavailable' }), {
      status: 503,
    }),
  );
  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );
  expect(await screen.findByText('Database unavailable')).toBeTruthy();
  expect(
    screen.getByRole('button', { name: 'Retry API connection' }),
  ).toBeTruthy();
});

function RouteProbe() {
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <>
      <output aria-label="Current route">{location.pathname}</output>
      <button onClick={() => navigate('/patient/nutrition-questions')}>
        Open patient URL
      </button>
    </>
  );
}

test('role-scoped URLs and menus prevent cross-role workspace access', async () => {
  render(
    <MemoryRouter initialEntries={['/reviewer/evidence']}>
      <App />
      <RouteProbe />
    </MemoryRouter>,
  );
  const user = userEvent.setup();
  await waitFor(() =>
    expect(screen.getByLabelText('Current route').textContent).toBe(
      '/clinician/patients',
    ),
  );
  expect(screen.getByRole('link', { name: 'Plan review' })).toBeTruthy();
  expect(
    screen.queryByRole('link', { name: 'Nutrition questions' }),
  ).toBeNull();
  expect(screen.queryByRole('link', { name: 'Food catalogue' })).toBeNull();
  await user.selectOptions(
    screen.getByRole('combobox', { name: 'Demo role' }),
    'reviewer',
  );
  expect(screen.getByRole('link', { name: 'Evidence review' })).toBeTruthy();
  expect(screen.getByRole('link', { name: 'Food catalogue' })).toBeTruthy();
  expect(screen.queryByRole('link', { name: 'Plan review' })).toBeNull();
  expect(
    screen.queryByRole('combobox', { name: 'Patient' }),
  ).toBeNull();
  await user.click(screen.getByRole('button', { name: 'Open patient URL' }));
  await waitFor(() =>
    expect(screen.getByLabelText('Current route').textContent).toBe(
      '/reviewer/evidence',
    ),
  );
  expect(
    request.mock.calls.some(([path]) => String(path).includes('/chat')),
  ).toBe(false);
  await user.selectOptions(
    screen.getByRole('combobox', { name: 'Demo role' }),
    'patient',
  );
  expect(
    screen
      .getByRole('link', { name: 'Nutrition questions' })
      .getAttribute('href'),
  ).toBe('/patient/nutrition-questions');
  expect(screen.queryByRole('link', { name: 'Evidence review' })).toBeNull();
});
