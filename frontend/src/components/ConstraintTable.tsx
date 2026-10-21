import type { NutrientConstraint } from '../types';
import RangeBar from './RangeBar';

interface ConstraintTableProps {
  constraints: NutrientConstraint[];
}

const KIND_FLAG: Record<NutrientConstraint['kind'], string> = {
  max: 'flag-bad',
  min: 'flag-warn',
  target: 'flag-info',
};

const KIND_TITLE: Record<NutrientConstraint['kind'], string> = {
  max: 'Hard ceiling',
  min: 'Soft floor',
  target: 'Soft aim',
};

export default function ConstraintTable({ constraints }: ConstraintTableProps) {
  if (!constraints || constraints.length === 0) {
    return <p className="text-sm text-ink-3">No nutrient constraints returned.</p>;
  }

  return (
    <div className="overflow-x-auto border border-rule bg-card">
      <table className="data-table">
        <thead>
          <tr>
            <th>Analyte</th>
            <th>Constraint</th>
            <th className="text-right">Limit</th>
            <th className="w-40">Range</th>
            <th>Unit</th>
            <th>Note</th>
            <th>Source</th>
          </tr>
        </thead>
        <tbody>
          {constraints.map((c, idx) => {
            const citation = c.provenance?.citation;
            return (
              <tr key={`${c.nutrient}-${idx}`}>
                <td className="font-medium text-ink">{c.nutrient}</td>
                <td>
                  <span className={`flag ${KIND_FLAG[c.kind]}`} title={KIND_TITLE[c.kind]}>
                    {c.kind}
                  </span>
                </td>
                <td className="num text-right font-medium text-ink">{c.value}</td>
                <td><RangeBar value={null} limit={c.value} kind={c.kind} state="none" /></td>
                <td className="text-ink-3">{c.unit}</td>
                <td className="text-ink-3">{c.note || '—'}</td>
                <td>
                  {citation?.url ? (
                    <a
                      href={citation.url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 font-medium text-line hover:underline"
                    >
                      {citation.guideline}
                      <ExternalLinkIcon />
                    </a>
                  ) : (
                    <span className="text-ink-3">{citation?.guideline || '—'}</span>
                  )}
                  {c.provenance && <p className="mt-0.5 text-xs text-ink-3">Author: {c.provenance.author}</p>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ExternalLinkIcon() {
  return (
    <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m-6-6L10 14" />
    </svg>
  );
}
