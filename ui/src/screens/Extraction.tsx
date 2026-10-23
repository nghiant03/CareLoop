import { useState } from 'react';
import { api, type ExtractionRun, type Passage } from '../api';
import { Empty, Feedback, Field, Form, Panel } from '../components/shared';
import { decision, useResource, useSession, useTask } from '../state';

export default function Extraction({
  sourceId,
  onDraft,
  onSaved,
}: {
  sourceId: string;
  onDraft: (id: string) => void;
  onSaved: () => void;
}) {
  const { actor } = useSession();
  const task = useTask();
  const [version, setVersion] = useState(0);
  const [page, setPage] = useState(0);
  const [runPage, setRunPage] = useState(0);
  const [ordinal, setOrdinal] = useState('');
  const [reason, setReason] = useState('');
  const [requestId, setRequestId] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<ExtractionRun | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const base = `/evidence/sources/${sourceId}`;
  const passages = useResource<Passage[]>(
    `${base}/passages?limit=20&offset=${page * 20}`,
  );
  const runs = useResource<ExtractionRun[]>(
    `${base}/extractions?limit=20&offset=${runPage * 20}`,
    version,
  );
  const selected = passages.data?.find((p) => p.ordinal === Number(ordinal));
  const unresolved =
    requestId !== null && (!outcome || outcome.state === 'pending');
  const refresh = () => setVersion((v) => v + 1);

  return (
    <Panel title="Extract rules from a passage">
      <p className="text-sm text-ink-3 mb-4 max-w-prose">
        GLM 5.3 creates up to three review-blocked drafts. Check the source
        context, resolve blockers, and approve and publish each revision
        separately.
      </p>
      <Feedback task={task} error={passages.error || runs.error} />
      {passages.loading && <p role="status">Loading passages…</p>}
      <Form
        busy={task.busy || actor.role !== 'reviewer' || unresolved}
        onSubmit={() =>
          void task.run(async () => {
            if (!selected) throw new Error('Select a source passage.');
            const id = crypto.randomUUID();
            setRequestId(id);
            setOutcome(null);
            const result = await api<ExtractionRun>(`${base}/extractions`, {
              ...decision(actor, reason),
              request_id: id,
              passage_ordinal: selected.ordinal,
              generation: {
                response_mode: 'json_object',
                reasoning_effort: 'high',
                max_tokens: 8192,
              },
            });
            setOutcome(result);
            setHistoryOpen(true);
            setRunPage(0);
            refresh();
            onSaved();
          }, 'Extraction run recorded. Review the result below.')
        }
      >
        <Field label="Source passage (required)">
          <select
            name="passage_ordinal"
            className="field"
            required
            value={ordinal}
            onChange={(e) => setOrdinal(e.target.value)}
          >
            <option value="">Select a passage</option>
            {passages.data?.map((p) => (
              <option key={p.ordinal} value={p.ordinal}>
                {p.ordinal} · {p.location}
              </option>
            ))}
          </select>
        </Field>
        {selected && (
          <blockquote className="whitespace-pre-wrap break-words text-sm border border-rule p-4 max-h-80 overflow-auto">
            {selected.content}
          </blockquote>
        )}
        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            className="btn-ghost"
            disabled={!page || passages.loading}
            onClick={() => {
              setPage((p) => p - 1);
              setOrdinal('');
            }}
          >
            Previous passages
          </button>
          <button
            type="button"
            className="btn-ghost"
            disabled={passages.data?.length !== 20 || passages.loading}
            onClick={() => {
              setPage((p) => p + 1);
              setOrdinal('');
            }}
          >
            More passages
          </button>
        </div>
        <Field label="Extraction reason (required)">
          <input
            name="reason"
            className="field"
            required
            maxLength={10000}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </Field>
        <button type="submit" className="btn-primary">
          Extract review drafts
        </button>
      </Form>
      {requestId && (
        <div className="my-4 text-sm break-words">
          <p>Request: {requestId}</p>
          {unresolved && (
            <p role="status">
              Outcome pending or unknown. Check the saved request before
              starting another extraction.
            </p>
          )}
          <button
            type="button"
            className="btn-ghost mt-2"
            disabled={task.busy}
            onClick={() =>
              void task.run(async () => {
                setOutcome(
                  await api<ExtractionRun>(`${base}/extractions/${requestId}`),
                );
                refresh();
                onSaved();
              }, 'Saved request status refreshed.')
            }
          >
            Check request status
          </button>
          {unresolved && !task.busy && (
            <button
              type="button"
              className="btn-ghost mt-2 ml-2"
              onClick={() => {
                setRequestId(null);
                setOutcome(null);
              }}
            >
              Prepare a separate request
            </button>
          )}
        </div>
      )}
      <details
        className="mt-6 border-t border-rule pt-4"
        open={historyOpen}
        onToggle={(e) => setHistoryOpen(e.currentTarget.open)}
      >
        <summary className="cursor-pointer font-semibold">
          Saved extraction runs
          {runs.data?.length
            ? ` · ${runs.data.length}${runs.data.length === 20 ? '+' : ''} on this page`
            : ''}
        </summary>
        <div className="flex flex-wrap items-center justify-between gap-3 mt-4 mb-3">
          <p className="text-sm text-ink-3">
            Past results, limitations and links to extracted drafts.
          </p>
          <button
            type="button"
            className="btn-ghost"
            disabled={task.busy || runs.loading}
            onClick={refresh}
          >
            Refresh runs
          </button>
        </div>
        {runs.loading && <p role="status">Loading extraction runs…</p>}
        {!runs.loading && !runs.error && !runs.data?.length && (
          <Empty>No runs yet. Select a passage to create review drafts.</Empty>
        )}
        <ul className="divide-y divide-rule">
          {runs.data?.map((run) => (
            <li key={run.id} className="py-4 space-y-2">
              <p className="font-semibold">
                Passage {run.request.decision.passage_ordinal} · {run.state}
              </p>
              <p className="text-sm text-ink-3">
                {run.request.model} ·{' '}
                {new Date(run.created_at).toLocaleString()}
              </p>
              {run.error && (
                <p className="notice notice-error" role="alert">
                  {run.error}
                </p>
              )}
              {run.state === 'pending' && (
                <p className="text-sm">
                  Provider outcome is pending or unknown. Refresh to check; this
                  run is not automatically retried.
                </p>
              )}
              {run.state === 'completed' && !run.rule_ids.length && (
                <p>No supported rules were extracted from this passage.</p>
              )}
              {run.result?.limitations.map((text, i) => (
                <p className="text-sm text-ink-3" key={i}>
                  {text}
                </p>
              ))}
              <div className="flex flex-wrap gap-3">
                {run.rule_ids.map((id, i) => (
                  <button
                    type="button"
                    key={id}
                    className="btn-ghost"
                    disabled={actor.role !== 'reviewer'}
                    onClick={() => onDraft(id)}
                  >
                    Review draft {i + 1}
                  </button>
                ))}
              </div>
            </li>
          ))}
        </ul>
        <div className="flex flex-wrap gap-3 mt-3">
          <button
            type="button"
            className="btn-ghost"
            disabled={!runPage || runs.loading}
            onClick={() => setRunPage((p) => p - 1)}
          >
            Newer runs
          </button>
          <button
            type="button"
            className="btn-ghost"
            disabled={runs.data?.length !== 20 || runs.loading}
            onClick={() => setRunPage((p) => p + 1)}
          >
            Older runs
          </button>
        </div>
      </details>
    </Panel>
  );
}
