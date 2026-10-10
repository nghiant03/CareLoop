import type { NutrientConstraint } from '../types';

interface ConstraintTableProps {
  constraints: NutrientConstraint[];
}

export default function ConstraintTable({ constraints }: ConstraintTableProps) {
  if (!constraints || constraints.length === 0) {
    return <p className="text-sm text-slate-500">No nutrient constraints returned.</p>;
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
      <table className="min-w-full text-left text-sm">
        <thead className="bg-slate-50 text-slate-700">
          <tr>
            <th className="px-4 py-3 font-semibold">Nutrient</th>
            <th className="px-4 py-3 font-semibold">Type</th>
            <th className="px-4 py-3 font-semibold">Value</th>
            <th className="px-4 py-3 font-semibold">Unit</th>
            <th className="px-4 py-3 font-semibold">Note</th>
            <th className="px-4 py-3 font-semibold">Source</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {constraints.map((c, idx) => {
            const citation = c.provenance?.citation;
            return (
              <tr key={`${c.nutrient}-${idx}`} className="hover:bg-slate-50/60">
                <td className="px-4 py-3 font-medium text-slate-900">{c.nutrient}</td>
                <td className="px-4 py-3">
                  <span
                    className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                      c.kind === 'max'
                        ? 'bg-rose-50 text-rose-700'
                        : c.kind === 'min'
                        ? 'bg-emerald-50 text-emerald-700'
                        : 'bg-sky-50 text-sky-700'
                    }`}
                  >
                    {c.kind}
                  </span>
                </td>
                <td className="px-4 py-3 tabular-nums text-slate-700">{c.value}</td>
                <td className="px-4 py-3 text-slate-500">{c.unit}</td>
                <td className="px-4 py-3 text-slate-500">{c.note || '—'}</td>
                <td className="px-4 py-3">
                  {citation?.url ? (
                    <a
                      href={citation.url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 text-sky-600 hover:text-sky-700 hover:underline"
                    >
                      {citation.guideline}
                      <ExternalLinkIcon />
                    </a>
                  ) : (
                    <span className="text-slate-500">{citation?.guideline || '—'}</span>
                  )}
                  {c.provenance && <p className="text-xs text-slate-500">Author: {c.provenance.author}</p>}
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
