import { useState } from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test } from 'vitest';
import { ActionFields } from './Patients';
import type { Action } from '../api';

afterEach(cleanup);

function Editor() {
  const [action, setAction] = useState<Action>({
    kind: 'ceiling',
    subject: 'free_sugars',
    amount: 10,
    unit: '%energy',
    advice: 'Source',
  });
  return (
    <>
      <ActionFields action={action} onChange={setAction} />
      <output>{JSON.stringify(action)}</output>
    </>
  );
}

test('target editor preserves percentage units across bound changes and clears incompatible values', async () => {
  render(<Editor />);
  const user = userEvent.setup();
  await user.click(
    screen.getByRole('checkbox', {
      name: 'Strictly less than (exclude the limit)',
    }),
  );
  expect(screen.getByRole('status').textContent).toContain(
    '"upper_exclusive":true',
  );
  await user.selectOptions(
    screen.getByRole('combobox', { name: 'Target type' }),
    'minimum',
  );
  expect(
    (screen.getByRole('combobox', { name: 'Target unit' }) as HTMLSelectElement)
      .value,
  ).toBe('%energy');
  expect(screen.getByRole('status').textContent).toContain(
    '"upper_exclusive":false',
  );
  expect(
    (
      screen.getByRole('spinbutton', {
        name: 'Amount (%energy)',
      }) as HTMLInputElement
    ).max,
  ).toBe('100');
  await user.selectOptions(
    screen.getByRole('combobox', { name: 'Nutrient' }),
    'fruit_and_vegetables',
  );
  expect(
    (screen.getByRole('combobox', { name: 'Target unit' }) as HTMLSelectElement)
      .value,
  ).toBe('g/day');
  expect(
    (
      screen.getByRole('spinbutton', {
        name: 'Amount (g/day)',
      }) as HTMLInputElement
    ).value,
  ).toBe('');
  expect(
    screen.queryByRole('option', { name: '% of daily energy' }),
  ).toBeNull();
});
