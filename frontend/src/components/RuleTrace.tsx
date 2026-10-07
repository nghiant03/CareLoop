import type { TraceEntry } from '../types';

interface RuleTraceProps {
  trace: TraceEntry[];
}

export default function RuleTrace({ trace }: RuleTraceProps) {
  if (!trace || trace.length === 0) {
    return <p className="text-sm text-slate-500">No rules fired.</p>;
  }

  const sorted = [...trace].sort((a, b) => a.priority - b.priority);

  return (
    <ol className="relative space-y-4 before:absolute before:left-2 before:top-1.5 before:h-full before:w-0.5 before:bg-slate-200">
      {sorted.map((entry, idx) => (
        <li key={`${entry.rule_id}-${idx}`} className="relative pl-8">
          <span
            className={`absolute left-0 top-0 inline-flex h-5 w-5 items-center justify-center rounded-full text-xs font-semibold ring-2 ring-white ${
              entry.overridden_by ? 'bg-rose-100 text-rose-700' : 'bg-sky-100 text-sky-700'
            }`}
          >
            {entry.priority}
          </span>
          <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-semibold text-slate-900">{entry.rule_id}</span>
              <span className="text-xs text-slate-500">· {entry.guideline}</span>
              {entry.section && (
                <span className="text-xs text-slate-500">· {entry.section}</span>
              )}
            </div>
            {entry.message && (
              <p className="mt-1 text-sm text-slate-700">{entry.message}</p>
            )}
            {entry.overridden_by && (
              <div className="mt-2 inline-flex items-center gap-1 rounded-md bg-rose-50 px-2 py-1 text-xs font-medium text-rose-700">
                <span>Overridden by</span>
                <span className="font-semibold">{entry.overridden_by}</span>
              </div>
            )}
            {entry.url && (
              <a
                href={entry.url}
                target="_blank"
                rel="noreferrer"
                className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-sky-600 hover:text-sky-700 hover:underline"
              >
                View guideline
                <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m-6-6L10 14" />
                </svg>
              </a>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}
