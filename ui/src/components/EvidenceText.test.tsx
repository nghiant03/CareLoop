import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, test } from 'vitest';
import EvidenceText from './EvidenceText';

afterEach(cleanup);

test('retained tables preserve merged cells, entities and surrounding wording', () => {
  render(
    <EvidenceText
      text={
        'Prior prescriptions apply. <table><thead><tr><th>Category</th><th colspan="2">Nutrition &amp; Healthy Eating</th></tr></thead><tbody><tr><td rowspan="2">Hypertension</td><td>Quality</td><td>Limit sodium to 2,000mg</td></tr><tr><td>Use DASH</td><td>Assess needs</td></tr></tbody></table> Source section.'
      }
    />,
  );
  expect(screen.getByRole('table')).toBeTruthy();
  expect(
    screen
      .getByRole('columnheader', { name: 'Nutrition & Healthy Eating' })
      .getAttribute('colspan'),
  ).toBe('2');
  expect(
    screen.getByRole('cell', { name: 'Hypertension' }).getAttribute('rowspan'),
  ).toBe('2');
  expect(screen.getByText('Prior prescriptions apply.')).toBeTruthy();
  expect(
    screen.getByRole('region', { name: 'Source evidence table' }).tabIndex,
  ).toBe(0);
});

test('source markup cannot inject scripts, links, styles or event handlers', () => {
  const { container } = render(
    <EvidenceText
      text={
        '<table onclick="alert(1)"><tbody><tr><td style="position:fixed"><script>alert(1)</script><img src="https://example.org/tracker" onerror="alert(1)"><a href="javascript:alert(1)">Retained words</a><svg onload="alert(1)"></svg></td></tr></tbody></table>'
      }
    />,
  );
  expect(screen.getByText('Retained words')).toBeTruthy();
  expect(
    container.querySelector(
      'script, img, a, svg, [onclick], [onerror], [style]',
    ),
  ).toBeNull();
});

test('plain evidence with comparisons remains literal text', () => {
  render(<EvidenceText text={'Age < 18; eGFR > 60.\nReview context.'} />);
  expect(screen.getByText(/Age < 18; eGFR > 60/)).toBeTruthy();
  expect(screen.queryByRole('table')).toBeNull();
});
