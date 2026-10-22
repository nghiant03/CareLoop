import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import KnowledgeWorkspaceScreen from './KnowledgeWorkspaceScreen';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

function setup(available = false) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const data = String(input).endsWith('/discover') ? { candidates: [{ status: 'NEEDS_REVIEW' }] }
      : { drafts: [], csrf_token: 'token', discovery_available: available, instructions: 'Instructions loaded from a prompt file.' };
    return new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } });
  });
  vi.stubGlobal('fetch', fetchMock);
  render(<KnowledgeWorkspaceScreen />);
  return fetchMock;
}

it('starts with an empty workspace and no account or CLI requirement', async () => {
  setup();
  expect(await screen.findByText(/No knowledge drafts yet/)).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Create first draft' })).toBeTruthy();
  expect(screen.queryByLabelText(/password/i)).toBeNull();
  expect(screen.queryByText(/clinical use|attestations|authenticated accounts/i)).toBeNull();
});

it('discloses unconfigured discovery and allows preparing multiple sources', async () => {
  setup();
  await screen.findByText(/No knowledge drafts yet/);
  await userEvent.click(screen.getByRole('button', { name: 'Discover sources' }));
  expect(screen.getByText(/No LLM provider has been selected/)).toBeTruthy();
  expect((screen.getByRole('button', { name: 'Extract review candidates' }) as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByLabelText('Extraction instructions (required)') as HTMLTextAreaElement).value).toContain('prompt file');
  await userEvent.upload(screen.getByLabelText('Add guideline files (required)'), [new File(['source a'], 'ada.txt'), new File(['source b'], 'dash.md')]);
  expect(screen.getByText('ada.txt')).toBeTruthy();
  expect(screen.getByText('dash.md')).toBeTruthy();
});

it('sends source uploads and edited instructions through the neutral API', async () => {
  const fetchMock = setup(true);
  await screen.findByText(/No knowledge drafts yet/);
  await userEvent.click(screen.getByRole('button', { name: 'Discover sources' }));
  await userEvent.upload(screen.getByLabelText('Add guideline files (required)'), new File(['Source passage'], 'society.txt'));
  await userEvent.clear(screen.getByLabelText('Extraction instructions (required)'));
  await userEvent.type(screen.getByLabelText('Extraction instructions (required)'), 'Custom instructions');
  await userEvent.click(screen.getByRole('button', { name: 'Extract review candidates' }));
  await screen.findByText('Review-only extraction report');
  const call = fetchMock.mock.calls.find(([path]) => String(path).endsWith('/discover'));
  expect(call?.[1]?.headers).toEqual({ 'Content-Type': 'application/json', 'X-Review-Token': 'token' });
  const body = JSON.parse(String(call?.[1]?.body));
  expect(body.instructions).toBe('Custom instructions');
  expect(body.sources[0]).toEqual({ name: 'society.txt', content: btoa('Source passage'), encoding: 'base64', source_url: null });
  expect(JSON.stringify(body)).not.toContain('api_key');
});

it('rejects oversized sources before reading or sending file contents', async () => {
  const fetchMock = setup(true);
  const read = vi.spyOn(FileReader.prototype, 'readAsDataURL');
  await screen.findByText(/No knowledge drafts yet/);
  await userEvent.click(screen.getByRole('button', { name: 'Discover sources' }));
  const file = new File(['tiny test payload'], 'large-guideline.pdf');
  Object.defineProperty(file, 'size', { value: 32 * 1024 * 1024 });
  await userEvent.upload(screen.getByLabelText('Add guideline files (required)'), file);
  await userEvent.click(screen.getByRole('button', { name: 'Extract review candidates' }));
  expect(await screen.findByRole('alert')).toHaveProperty('textContent', expect.stringContaining('exceed the 32 MiB'));
  expect(read).not.toHaveBeenCalled();
  expect(fetchMock.mock.calls.some(([path]) => String(path).endsWith('/discover'))).toBe(false);
});

it('rejects empty or excessive source selections before reading', async () => {
  setup(true);
  const read = vi.spyOn(FileReader.prototype, 'readAsDataURL');
  await screen.findByText(/No knowledge drafts yet/);
  await userEvent.click(screen.getByRole('button', { name: 'Discover sources' }));
  await userEvent.click(screen.getByRole('button', { name: 'Extract review candidates' }));
  expect(await screen.findByRole('alert')).toHaveProperty('textContent', expect.stringContaining('between 1 and 10'));
  await userEvent.upload(screen.getByLabelText('Add guideline files (required)'), Array.from({ length: 11 }, (_, index) => new File(['source'], `guideline-${index}.txt`)));
  await userEvent.click(screen.getByRole('button', { name: 'Extract review candidates' }));
  expect(read).not.toHaveBeenCalled();
});
