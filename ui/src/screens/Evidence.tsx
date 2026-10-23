import { useEffect, useRef, useState } from 'react';
import {
  api,
  label,
  type Catalogue,
  type Predicate,
  type Rule,
  type RuleBody,
  type Source,
} from '../api';
import { ActionFields } from './Patients';
import {
  Details,
  Empty,
  Feedback,
  Field,
  Form,
  Panel,
} from '../components/shared';
import { decision, useResource, useSession, useTask } from '../state';
import Extraction from './Extraction';

export default function Evidence() {
  const { actor } = useSession();
  const task = useTask();
  const [version, setVersion] = useState(0);
  const sources = useResource<Source[]>('/evidence/sources', version, true);
  const catalogue = useResource<Catalogue>('/evidence/catalogue', version);
  const seeds = useResource<{ seeds: Array<{ title: string; url: string }> }>(
    '/evidence/discovery-seeds',
  );
  const [sourceId, setSourceId] = useState('');
  const source = useResource<Source>(
    sourceId ? `/evidence/sources/${sourceId}` : null,
    version,
  );
  const [mode, setMode] = useState('url');
  const [title, setTitle] = useState('');
  const [edition, setEdition] = useState('');
  const [locator, setLocator] = useState('');
  const [content, setContent] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [firstPage, setFirstPage] = useState(1);
  const [lastPage, setLastPage] = useState('');
  const [refresh, setRefresh] = useState(false);
  const [discovered, setDiscovered] = useState<Array<{
    title: string;
    url: string;
  }> | null>(null);
  const [chosen, setChosen] = useState<string[]>([]);
  const [note, setNote] = useState('');
  const [check, setCheck] = useState<{
    generation: number;
    blocking_conflicts: unknown[];
    review_findings: unknown[];
  } | null>(null);
  const [edit, setEdit] = useState<Rule | 'new' | null>(null);
  const editor = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (edit) {
      editor.current?.focus();
      editor.current?.scrollIntoView?.({ block: 'start' });
    }
  }, [edit]);
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('');
  const [filterSource, setFilterSource] = useState('');
  const [subject, setSubject] = useState('');
  const [blockedOnly, setBlockedOnly] = useState(false);
  const [selectedOnly, setSelectedOnly] = useState(false);
  const rules = catalogue.data?.rules ?? [];
  const sourceMap = new Map(sources.data?.map((s) => [s.id, s]));
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const visible = rules.filter((r) => {
    const text = [
      r.draft.action.subject,
      r.draft.action.kind,
      r.draft.action.advice,
      r.draft.quote,
      r.draft.population_note,
      r.draft.exception_note,
      r.draft.location,
      sourceMap.get(r.draft.source_id)?.title,
      ...r.draft.applicability.map((p) => `${label(p.fact)} ${p.value}`),
    ]
      .join(' ')
      .toLowerCase();
    return (
      (!status || ruleStatus(r) === status) &&
      (!filterSource || r.draft.source_id === filterSource) &&
      (!subject || r.draft.action.subject === subject) &&
      (!blockedOnly || r.draft.blockers.length > 0) &&
      (!selectedOnly || chosen.includes(r.id)) &&
      terms.every((term) => text.includes(term))
    );
  });
  const hiddenSelected = chosen.filter(
    (id) => !visible.some((r) => r.id === id),
  ).length;
  const clearFilters = () => {
    setQuery('');
    setStatus('');
    setFilterSource('');
    setSubject('');
    setBlockedOnly(false);
    setSelectedOnly(false);
  };
  const selected =
    catalogue.data?.rules.filter((r) => chosen.includes(r.id)) ?? [];
  const selection = {
    ...decision(actor, note || 'Review selected rule revisions'),
    rules: selected.map((r) => ({
      rule_id: r.id,
      revision: r.latest_revision,
    })),
  };
  const reload = () => {
    setVersion((v) => v + 1);
    setCheck(null);
  };
  return (
    <>
      <Feedback
        task={task}
        error={sources.error || catalogue.error || source.error}
      />
      <details className="panel p-5 mb-6">
        <summary className="cursor-pointer text-lg font-bold">
          Acquire source evidence
        </summary>
        <div className="mt-4">
          <p className="text-ink-3 mb-4">
            Import an authoritative page, upload a PDF, or retain
            reviewer-provided text. Acquisition creates a source snapshot; it
            does not publish rules.
          </p>
          <div className="mb-4">
            <Field label="Research entry point">
              <select
                className="field"
                value=""
                onChange={(e) => {
                  setLocator(e.target.value);
                  setMode('url');
                }}
              >
                <option value="">Choose an authoritative source</option>
                {seeds.data?.seeds.map((seed) => (
                  <option key={seed.url} value={seed.url}>
                    {seed.title}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <Form
            busy={task.busy || actor.role !== 'reviewer'}
            onSubmit={() =>
              void task.run(async () => {
                let payload: Record<string, unknown> = {
                  ...decision(actor, 'Retain submitted source for review'),
                  title,
                  edition,
                };
                if (mode === 'text') payload = { ...payload, locator, content };
                else {
                  payload = {
                    ...payload,
                    first_page: firstPage,
                    ...(lastPage ? { last_page: Number(lastPage) } : {}),
                    ...(refresh && sourceId ? { refresh_of: sourceId } : {}),
                  };
                  if (mode === 'url') payload.url = locator;
                  else {
                    if (!file || file.size > 10_000_000)
                      throw new Error('Choose a PDF no larger than 10 MB.');
                    const bytes = new Uint8Array(await file.arrayBuffer());
                    let binary = '';
                    for (let start = 0; start < bytes.length; start += 8192)
                      binary += String.fromCharCode(
                        ...bytes.subarray(start, start + 8192),
                      );
                    payload.pdf_base64 = btoa(binary);
                    payload.locator = locator;
                  }
                }
                const result = await api<Source>(
                  mode === 'text'
                    ? '/evidence/sources'
                    : '/evidence/source-imports',
                  payload,
                );
                setSourceId(result.id);
                reload();
              }, 'Source saved. Review its passages before creating rules.')
            }
          >
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Input type">
                <select
                  className="field"
                  value={mode}
                  onChange={(e) => {
                    setMode(e.target.value);
                    setRefresh(false);
                  }}
                >
                  <option value="url">HTTPS URL</option>
                  <option value="pdf">PDF upload</option>
                  <option value="text">Pasted text</option>
                </select>
              </Field>
              <Field label="Title">
                <input
                  className="field"
                  required
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                />
              </Field>
              <Field label="Edition / publication date">
                <input
                  className="field"
                  required
                  value={edition}
                  onChange={(e) => setEdition(e.target.value)}
                />
              </Field>
              <Field
                label={
                  mode === 'url'
                    ? 'Approved-domain URL'
                    : 'Source locator / reference'
                }
              >
                <input
                  className="field"
                  required
                  type={mode === 'url' ? 'url' : 'text'}
                  value={locator}
                  onChange={(e) => setLocator(e.target.value)}
                />
              </Field>
            </div>
            {mode === 'text' ? (
              <Field label="Source text">
                <textarea
                  className="field min-h-40"
                  required
                  maxLength={1000000}
                  value={content}
                  onChange={(e) => setContent(e.target.value)}
                />
              </Field>
            ) : (
              <>
                {mode === 'pdf' && (
                  <Field label="PDF document">
                    <input
                      type="file"
                      accept="application/pdf,.pdf"
                      required
                      className="field"
                      onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                    />
                  </Field>
                )}
                <div className="grid sm:grid-cols-2 gap-4">
                  <Field label="First PDF page">
                    <input
                      className="field"
                      type="number"
                      min="1"
                      max="500"
                      value={firstPage}
                      onChange={(e) => setFirstPage(Number(e.target.value))}
                    />
                  </Field>
                  <Field label="Last PDF page (optional)">
                    <input
                      className="field"
                      type="number"
                      min={firstPage}
                      max="500"
                      value={lastPage}
                      onChange={(e) => setLastPage(e.target.value)}
                    />
                  </Field>
                </div>
                {sourceId && (
                  <label className="flex gap-2">
                    <input
                      type="checkbox"
                      checked={refresh}
                      onChange={(e) => setRefresh(e.target.checked)}
                    />
                    Compare with the selected source as a new refresh snapshot
                  </label>
                )}
              </>
            )}
            <div className="flex flex-wrap gap-3">
              <button className="btn-primary">Save source snapshot</button>
              {mode === 'url' && (
                <button
                  type="button"
                  className="btn-ghost"
                  disabled={!locator}
                  onClick={() =>
                    void task.run(async () => {
                      const result = await api<{
                        candidates: Array<{ title: string; url: string }>;
                      }>('/evidence/discover', {
                        ...decision(
                          actor,
                          'Discover authoritative source links',
                        ),
                        url: locator,
                      });
                      setDiscovered(result.candidates);
                    }, '')
                  }
                >
                  Discover links on this page
                </button>
              )}
            </div>
          </Form>
          {discovered && (
            <div className="max-h-64 overflow-y-auto mt-4">
              {!discovered.length && (
                <Empty>No approved-domain links found on this page.</Empty>
              )}
              {discovered.map((candidate) => (
                <button
                  className="block text-left text-line underline py-2 break-words"
                  key={candidate.url}
                  onClick={() => {
                    setLocator(candidate.url);
                    setTitle(candidate.title);
                    setDiscovered(null);
                  }}
                >
                  {candidate.title}
                </button>
              ))}
            </div>
          )}
        </div>
      </details>
      <Panel title="Source library">
        <Field label="Saved source">
          <select
            className="field"
            value={sourceId}
            onChange={(e) => {
              setSourceId(e.target.value);
              setRefresh(false);
              setEdit(null);
            }}
          >
            <option value="">Choose a source</option>
            {sources.data?.map((s) => (
              <option key={s.id} value={s.id}>
                {s.title} · {s.edition}
              </option>
            ))}
          </select>
        </Field>
        {source.loading && <p role="status">Loading source…</p>}
        {source.data && (
          <>
            <h3 className="font-semibold mt-4">{source.data.title}</h3>
            <p className="text-sm break-words text-ink-3">
              {source.data.locator}
            </p>
            {source.data.document && (
              <>
                <a
                  className="btn-ghost my-3"
                  href={`/api/evidence/sources/${sourceId}/document`}
                >
                  Download retained original
                </a>
                <ul className="text-sm text-warn">
                  {source.data.document.metadata.warnings.map((w) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
              </>
            )}
            <details className="my-4">
              <summary className="cursor-pointer text-sm font-semibold text-line">
                Read retained source text
              </summary>
              <pre className="font-sans text-sm whitespace-pre-wrap break-words max-h-96 overflow-auto border border-rule p-4 my-4">
                {source.data.content}
              </pre>
            </details>
            <button
              className="btn-primary"
              disabled={actor.role !== 'reviewer'}
              onClick={() => setEdit('new')}
            >
              Create structured rule draft
            </button>
            {source.data.document?.metadata.comparison != null && (
              <Details
                title="Refresh comparison"
                value={source.data.document.metadata.comparison}
              />
            )}
          </>
        )}
      </Panel>
      {sourceId && (
        <Extraction
          key={sourceId}
          sourceId={sourceId}
          onSaved={reload}
          onDraft={(id) =>
            void task.run(async () => {
              const row = await api<
                Omit<Rule, 'draft' | 'approved_by'> & {
                  revisions: Array<{
                    revision: number;
                    body: RuleBody;
                    approved_by: string | null;
                  }>;
                }
              >(`/evidence/rules/${id}`);
              const latest = row.revisions.find(
                (r) => r.revision === row.latest_revision,
              )!;
              setEdit({
                ...row,
                draft: latest.body,
                approved_by: latest.approved_by,
              });
            }, '')
          }
        />
      )}
      <div id="rule-editor" ref={editor} tabIndex={-1}>
        {edit && (edit !== 'new' || sourceId) && (
          <RuleEditor
            key={
              edit === 'new' ? sourceId : `${edit.id}-${edit.latest_revision}`
            }
            sourceId={sourceId}
            source={sources.data?.find(
              (s) =>
                s.id === (edit === 'new' ? sourceId : edit.draft.source_id),
            )}
            rule={edit === 'new' ? undefined : edit}
            onCancel={() => setEdit(null)}
            onSaved={() => {
              setEdit(null);
              reload();
            }}
          />
        )}
      </div>
      <Panel title="Review and publish rules">
        <p className="text-sm text-ink-3 mb-4">
          Select individual rules or a subset for approval and publication.
          Edits require approval of the new revision.
        </p>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4 mb-4">
          <Field label="Search rules">
            <input
              type="search"
              className="field"
              value={query}
              placeholder="Advice, population, source…"
              onChange={(e) => setQuery(e.target.value)}
            />
          </Field>
          <Field label="Rule status">
            <select
              className="field"
              value={status}
              onChange={(e) => setStatus(e.target.value)}
            >
              <option value="">All statuses</option>
              {['Draft', 'Approved, unpublished', 'Published', 'Retired'].map(
                (s) => (
                  <option key={s}>{s}</option>
                ),
              )}
            </select>
          </Field>
          <Field label="Rule source">
            <select
              className="field"
              value={filterSource}
              onChange={(e) => setFilterSource(e.target.value)}
            >
              <option value="">All sources</option>
              {[...new Set(rules.map((r) => r.draft.source_id))].map((id) => (
                <option key={id} value={id}>
                  {sourceMap.get(id)?.title ?? id}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Rule subject">
            <select
              className="field"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
            >
              <option value="">All subjects</option>
              {[...new Set(rules.map((r) => r.draft.action.subject))]
                .sort()
                .map((s) => (
                  <option key={s} value={s}>
                    {label(s)}
                  </option>
                ))}
            </select>
          </Field>
        </div>
        <div className="flex flex-wrap items-center gap-4 mb-4">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={blockedOnly}
              onChange={(e) => setBlockedOnly(e.target.checked)}
            />
            With review blockers
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={selectedOnly}
              onChange={(e) => setSelectedOnly(e.target.checked)}
            />
            Selected only
          </label>
          <button className="btn-ghost" onClick={clearFilters}>
            Clear filters
          </button>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 border-y border-rule py-3">
          <p role="status" className="text-sm text-ink-3">
            Showing {visible.length} of {rules.length} rules · {chosen.length}{' '}
            selected
            {hiddenSelected > 0 ? ` (${hiddenSelected} hidden by filters)` : ''}
          </p>
          <div className="flex flex-wrap gap-2">
            <button
              className="btn-ghost"
              disabled={
                actor.role !== 'reviewer' || !visible.some((r) => !r.retired)
              }
              onClick={() => {
                setChosen((ids) => [
                  ...new Set([
                    ...ids,
                    ...visible.filter((r) => !r.retired).map((r) => r.id),
                  ]),
                ]);
                setCheck(null);
              }}
            >
              Select visible rules
            </button>
            <button
              className="btn-ghost"
              disabled={!chosen.length}
              onClick={() => {
                setChosen([]);
                setCheck(null);
              }}
            >
              Clear selection
            </button>
          </div>
        </div>
        {catalogue.loading && <p role="status">Loading rules…</p>}
        {!catalogue.data?.rules.length && !catalogue.loading && (
          <Empty>
            No structured rules yet. Create a draft from retained source text.
          </Empty>
        )}
        {!!rules.length && !visible.length && (
          <Empty>
            No rules match these filters. Clear filters or try another search.
          </Empty>
        )}
        <ul className="divide-y divide-rule">
          {visible.map((rule) => (
            <li key={rule.id} className="py-4">
              <div className="flex flex-wrap gap-3 items-start">
                <label className="flex gap-3 flex-1">
                  <input
                    type="checkbox"
                    className="mt-1"
                    disabled={rule.retired || actor.role !== 'reviewer'}
                    checked={chosen.includes(rule.id)}
                    onChange={(e) => {
                      setChosen((ids) =>
                        e.target.checked
                          ? [...ids, rule.id]
                          : ids.filter((id) => id !== rule.id),
                      );
                      setCheck(null);
                    }}
                  />
                  <span>
                    <strong className="capitalize">
                      {label(rule.draft.action.subject)} ·{' '}
                      {label(rule.draft.action.kind)}
                    </strong>
                    <span className="text-sm text-ink-3 block">
                      Revision {rule.latest_revision} · {ruleStatus(rule)}
                    </span>
                  </span>
                </label>
                <button
                  className="btn-ghost"
                  disabled={rule.retired || actor.role !== 'reviewer'}
                  onClick={() => setEdit(rule)}
                >
                  Edit rule
                </button>
              </div>
              <p className="mt-3 font-medium break-words">
                {rule.draft.action.advice}
              </p>
              <p className="text-sm text-ink-3 mt-1">
                Population: {rule.draft.population_note}
              </p>
              {!!rule.draft.blockers.length && (
                <p className="text-sm text-warn mt-2">
                  {rule.draft.blockers.length} review blocker
                  {rule.draft.blockers.length === 1 ? '' : 's'}
                </p>
              )}
              <SourceAttribution
                sourceId={rule.draft.source_id}
                source={sources.data?.find(
                  (s) => s.id === rule.draft.source_id,
                )}
              />
              <details className="my-3">
                <summary className="cursor-pointer text-sm font-semibold text-line">
                  Supporting quote · {rule.draft.location}
                </summary>
                <blockquote className="text-sm mt-3 whitespace-pre-wrap break-words">
                  {rule.draft.quote}
                </blockquote>
              </details>
              <Details
                title="Applicability, exceptions and provenance"
                value={rule.draft}
              />
            </li>
          ))}
        </ul>
        <div className="border-t border-rule pt-5 mt-4">
          <h3 className="font-semibold mb-2">
            Review selected revisions ({chosen.length})
          </h3>
          <p className="text-sm text-ink-3 mb-4">
            Add a review note, approve revisions, then check conflicts before
            publishing. Actions include selections hidden by filters.
          </p>
          <Form
            busy={task.busy || actor.role !== 'reviewer'}
            onSubmit={() =>
              void task.run(async () => {
                if (!check) throw new Error('Run conflict analysis first.');
                await api('/evidence/publications', {
                  ...selection,
                  expected_generation: check.generation,
                  conflict_review: note,
                });
                setChosen([]);
                reload();
              }, 'Selected revisions published. Affected targets have been flagged.')
            }
          >
            <Field label="Review and conflict-resolution note">
              <textarea
                className="field"
                required
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
            </Field>
            <div className="flex flex-wrap gap-3">
              <button
                type="button"
                className="btn-approve"
                disabled={!chosen.length || !note.trim()}
                onClick={() =>
                  void task.run(async () => {
                    await api('/evidence/approvals', selection);
                    reload();
                  }, 'Selected rule revisions approved; publication is separate.')
                }
              >
                Approve selected revisions
              </button>
              <button
                type="button"
                className="btn-ghost"
                disabled={!chosen.length}
                onClick={() =>
                  void task.run(
                    async () =>
                      setCheck(
                        await api('/evidence/conflict-check', selection),
                      ),
                    'Conflict analysis complete. Review all findings before publication.',
                  )
                }
              >
                Check conflicts
              </button>
              <button
                className="btn-primary"
                disabled={
                  !check ||
                  !!check.blocking_conflicts.length ||
                  !chosen.length ||
                  selected.some(
                    (r) =>
                      !r.approved_by || r.active_revision === r.latest_revision,
                  )
                }
              >
                Publish selected revisions
              </button>
              <button
                type="button"
                className="btn-danger"
                disabled={chosen.length !== 1 || !note.trim()}
                onClick={() =>
                  void task.run(async () => {
                    const r = selected[0];
                    await api(`/evidence/rules/${r.id}/retirement`, {
                      ...decision(actor, note),
                      expected_revision: r.latest_revision,
                    });
                    setChosen([]);
                    reload();
                  }, 'Rule retired. Historical records remain available.')
                }
              >
                Retire selected rule
              </button>
            </div>
          </Form>
          {check && (
            <Details
              title={`${check.blocking_conflicts.length} blockers · ${check.review_findings.length} findings for review`}
              value={check}
            />
          )}
        </div>
      </Panel>
    </>
  );
}

function ruleStatus(rule: Rule) {
  return rule.retired
    ? 'Retired'
    : rule.active_revision === rule.latest_revision
      ? 'Published'
      : rule.approved_by
        ? 'Approved, unpublished'
        : 'Draft';
}

function SourceAttribution({
  sourceId,
  source,
}: {
  sourceId: string;
  source?: Source;
}) {
  return (
    <div className="text-sm mt-3 break-words">
      <p>
        <span className="font-semibold">Source: </span>
        {source && /^https?:\/\//i.test(source.locator) ? (
          <a
            className="text-line underline"
            href={source.locator}
            target="_blank"
            rel="noreferrer"
          >
            {source.title}
          </a>
        ) : (
          (source?.title ?? sourceId)
        )}
      </p>
      {source && <p className="text-ink-3">Edition: {source.edition}</p>}
    </div>
  );
}

function RuleEditor({
  sourceId,
  source,
  rule,
  onSaved,
  onCancel,
}: {
  sourceId: string;
  source?: Source;
  rule?: Rule;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const { actor } = useSession();
  const task = useTask();
  const [body, setBody] = useState<RuleBody>(
    rule?.draft ?? {
      source_id: sourceId,
      quote: '',
      location: '',
      population_note: '',
      exception_note: '',
      applicability: [],
      exceptions: [],
      blockers: [],
      action: {
        kind: 'ceiling',
        subject: 'sodium',
        amount: null,
        upper: null,
        unit: 'mg/day',
        advice: '',
      },
    },
  );
  const [reason, setReason] = useState('');
  return (
    <Panel
      title={
        rule
          ? `Edit rule revision ${rule.latest_revision}`
          : 'Structured rule draft'
      }
    >
      <Feedback task={task} />
      <SourceAttribution sourceId={body.source_id} source={source} />
      <Form
        busy={task.busy || actor.role !== 'reviewer'}
        onSubmit={() =>
          void task.run(async () => {
            await api(
              rule ? `/evidence/rules/${rule.id}/revisions` : '/evidence/rules',
              {
                ...decision(actor, reason),
                body,
                ...(rule ? { expected_revision: rule.latest_revision } : {}),
              },
            );
            onSaved();
          }, 'Draft saved. It is not active until approved and published.')
        }
      >
        <Field label="Supporting source quote (verbatim)">
          <textarea
            className="field min-h-28"
            required
            value={body.quote}
            onChange={(e) => setBody((b) => ({ ...b, quote: e.target.value }))}
          />
        </Field>
        <Field label="Source page / section">
          <input
            className="field"
            required
            value={body.location}
            onChange={(e) =>
              setBody((b) => ({ ...b, location: e.target.value }))
            }
          />
        </Field>
        <ActionFields
          evidence
          action={body.action}
          onChange={(action) => setBody((b) => ({ ...b, action }))}
        />
        <PredicateFields
          title="Applicability (all conditions)"
          predicates={body.applicability}
          onChange={(applicability) =>
            setBody((b) => ({ ...b, applicability }))
          }
        />
        <Field label="Population explanation">
          <textarea
            className="field"
            required
            value={body.population_note}
            onChange={(e) =>
              setBody((b) => ({ ...b, population_note: e.target.value }))
            }
          />
        </Field>
        <PredicateFields
          title="Exceptions (any condition excludes)"
          predicates={body.exceptions}
          onChange={(exceptions) => setBody((b) => ({ ...b, exceptions }))}
        />
        <Field label="Exception explanation">
          <textarea
            className="field"
            required
            value={body.exception_note}
            onChange={(e) =>
              setBody((b) => ({ ...b, exception_note: e.target.value }))
            }
          />
        </Field>
        <Field label="Blocking review issues (one per line)">
          <textarea
            className="field"
            value={body.blockers.join('\n')}
            onChange={(e) =>
              setBody((b) => ({
                ...b,
                blockers: e.target.value ? e.target.value.split('\n') : [],
              }))
            }
          />
        </Field>
        <Field label="Reason for this revision">
          <input
            className="field"
            required
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </Field>
        <div className="flex flex-wrap gap-3">
          <button className="btn-primary">Save structured draft</button>
          <button type="button" className="btn-ghost" onClick={onCancel}>
            Cancel editing
          </button>
        </div>
      </Form>
    </Panel>
  );
}

function PredicateFields({
  title,
  predicates,
  onChange,
}: {
  title: string;
  predicates: Predicate[];
  onChange: (p: Predicate[]) => void;
}) {
  const numeric = ['age_years', 'weight_kg', 'height_cm', 'egfr'];
  const booleans = [
    'has_ckd',
    'pregnant',
    'breastfeeding',
    'dialysis',
    'vegetarian',
    'include_eggs',
    'include_dairy',
  ];
  const lists = ['conditions', 'medications', 'allergies', 'dislikes'];
  const change = (index: number, patch: Partial<Predicate>) =>
    onChange(predicates.map((p, i) => (i === index ? { ...p, ...patch } : p)));
  return (
    <fieldset className="space-y-3">
      <legend className="font-semibold mb-2">{title}</legend>
      {predicates.map((p, i) => (
        <div key={i} className="grid sm:grid-cols-4 gap-3 items-end">
          <Field label="Patient fact">
            <select
              className="field"
              value={p.fact}
              onChange={(e) =>
                change(i, {
                  fact: e.target.value,
                  operator: lists.includes(e.target.value) ? 'contains' : 'eq',
                  value: numeric.includes(e.target.value)
                    ? 0
                    : booleans.includes(e.target.value)
                      ? false
                      : '',
                })
              }
            >
              {[...numeric, ...booleans, ...lists, 'sex', 'ckd_stage'].map(
                (f) => (
                  <option key={f} value={f}>
                    {label(f)}
                  </option>
                ),
              )}
            </select>
          </Field>
          <Field label="Operator">
            <select
              className="field"
              value={p.operator}
              onChange={(e) => change(i, { operator: e.target.value })}
            >
              {(numeric.includes(p.fact)
                ? ['eq', 'gte', 'lte']
                : lists.includes(p.fact)
                  ? ['contains']
                  : ['eq']
              ).map((op) => (
                <option key={op}>{op}</option>
              ))}
            </select>
          </Field>
          <Field label="Value">
            {booleans.includes(p.fact) ? (
              <select
                className="field"
                value={String(p.value)}
                onChange={(e) =>
                  change(i, { value: e.target.value === 'true' })
                }
              >
                <option value="false">No</option>
                <option value="true">Yes</option>
              </select>
            ) : (
              <input
                className="field"
                required
                type={numeric.includes(p.fact) ? 'number' : 'text'}
                step="any"
                value={String(p.value)}
                onChange={(e) =>
                  change(i, {
                    value: numeric.includes(p.fact)
                      ? Number(e.target.value)
                      : e.target.value,
                  })
                }
              />
            )}
          </Field>
          <button
            type="button"
            className="btn-ghost"
            onClick={() => onChange(predicates.filter((_, j) => i !== j))}
          >
            Remove condition
          </button>
        </div>
      ))}
      <button
        type="button"
        className="btn-ghost"
        onClick={() =>
          onChange([
            ...predicates,
            { fact: 'age_years', operator: 'gte', value: 2 },
          ])
        }
      >
        Add condition
      </button>
    </fieldset>
  );
}
