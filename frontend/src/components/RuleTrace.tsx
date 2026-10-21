import type { TraceEntry } from '../types';

interface RuleTraceProps {
  trace: TraceEntry[];
}

export default function RuleTrace({ trace }: RuleTraceProps) {
  if (!trace || trace.length === 0) {
    return <p className="text-sm text-ink-3">No rules fired.</p>;
  }

  const sorted = [...trace].sort((a, b) => a.priority - b.priority);

  return (
    <ol className="border border-rule bg-card">
      {sorted.map((entry, idx) => (
        <li
          key={`${entry.rule_id}-${idx}`}
          className={`flex gap-4 p-4 ${idx > 0 ? 'border-t border-rule' : ''}`}
        >
          <span className="num mt-0.5 shrink-0 text-xs font-semibold text-ink-3">
            P{entry.priority}
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <span className="font-mono text-sm font-semibold text-ink">{entry.rule_id}</span>
              <span className="text-xs text-ink-3">· {entry.guideline}</span>
              {entry.section && <span className="text-xs text-ink-3">· {entry.section}</span>}
              {entry.overridden_by && (
                <span className="flag flag-bad">
                  Overridden by <span className="font-bold">{entry.overridden_by}</span>
                </span>
              )}
            </div>
            {entry.message && <p className="mt-1 text-sm text-ink-2">{entry.message}</p>}
            {entry.url && (
              <a
                href={entry.url ?? undefined}
                target="_blank"
                rel="noreferrer"
                className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-line hover:underline"
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
