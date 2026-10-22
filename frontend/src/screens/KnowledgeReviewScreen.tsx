import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import PageHeader from '../components/PageHeader';
import LoadingState from '../components/LoadingState';
import WorkspaceHeader from '../components/WorkspaceHeader';
import { reviewRequest, safeSourceUrl } from '../knowledgeReview';
import type { DocumentRecord, ReviewDocuments, ReviewEvent, ReviewStatus } from '../knowledgeReview';

function RecordDetails({ value }: { value: unknown }) {
  if (value == null) return <p className="text-sm text-ink-3">Not provided.</p>;
  if (Array.isArray(value)) return <ul className="space-y-2 pl-5 list-disc">{value.map((item, index) => <li key={index}><RecordDetails value={item} /></li>)}</ul>;
  if (typeof value === 'object') return <dl className="divide-y divide-rule">{Object.entries(value as DocumentRecord).map(([key, item]) => <div key={key} className="py-2"><dt className="text-sm font-semibold break-words">{key.replaceAll('_', ' ')}</dt><dd className="mt-1 text-sm break-words"><RecordDetails value={item} /></dd></div>)}</dl>;
  const url = safeSourceUrl(value);
  return url ? <a className="text-line underline break-all" href={url} target="_blank" rel="noreferrer">{String(value)}</a> : <span className="whitespace-pre-wrap break-words">{String(value)}</span>;
}

export default function KnowledgeReviewScreen() {
  const [status, setStatus] = useState<ReviewStatus>();
  const [documents, setDocuments] = useState<ReviewDocuments>();
  const [events, setEvents] = useState<ReviewEvent[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const [query, setQuery] = useState('');
  const [missingEvidence, setMissingEvidence] = useState(false);
  const [selectedId, setSelectedId] = useState('');
  const [section, setSection] = useState('Rules');
  const [baseline, setBaseline] = useState<ReviewDocuments>();
  const [comparisonRevision, setComparisonRevision] = useState('');
  const [comparisonError, setComparisonError] = useState('');
  const [actor, setActor] = useState('');
  const [note, setNote] = useState('');
  const [decision, setDecision] = useState('reject');
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      reviewRequest<ReviewStatus>('', { signal: controller.signal }),
      reviewRequest<ReviewDocuments>('/documents', { signal: controller.signal }),
      reviewRequest<ReviewEvent[]>('/history', { signal: controller.signal }),
    ]).then(([nextStatus, nextDocuments, nextEvents]) => {
      setStatus(nextStatus); setDocuments(nextDocuments); setEvents(nextEvents); setError('');
    }).catch((failure: Error) => { if (!controller.signal.aborted) setError(failure.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [refresh]);

  useEffect(() => {
    if (!comparisonRevision) return;
    const controller = new AbortController();
    reviewRequest<ReviewDocuments>(`/revision?revision=${comparisonRevision}`, { signal: controller.signal })
      .then(setBaseline).catch((failure: Error) => { if (!controller.signal.aborted) setComparisonError(failure.message); });
    return () => controller.abort();
  }, [comparisonRevision]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!status) return;
    setBusy(true); setError(''); setMessage('');
    try {
      await reviewRequest('/decision', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Review-Token': status.csrf_token }, body: JSON.stringify({ actor: actor.trim(), note: note.trim(), decision, expected_revision: status.draft.revision }) });
      setMessage('Review decision recorded. This does not publish or activate the draft.');
      setRefresh(value => value + 1); setNote(''); setConfirmed(false);
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Unable to record decision.'); }
    finally { setBusy(false); }
  }

  if (loading) return <LoadingState text="Loading knowledge review" />;
  if (!status || !documents) return <main className="mx-auto max-w-4xl p-6"><h1 className="text-2xl font-bold">Knowledge review unavailable</h1><p role="alert" className="notice notice-error my-4">{error}</p><button className="btn-primary" onClick={() => { setLoading(true); setRefresh(value => value + 1); }}>Retry loading</button></main>;

  const rules = documents.rules.rules;
  const filtered = rules.filter(rule => JSON.stringify(rule).toLowerCase().includes(query.toLowerCase()) && (!missingEvidence || !rule.verbatim_quote || !safeSourceUrl(rule.url)));
  const selected = filtered.find(rule => rule.rule_id === selectedId) ?? filtered[0];
  const oldRule = baseline?.rules.rules.find(rule => rule.rule_id === selected?.rule_id);
  const current = status.current_draft;
  const stale = current.revision !== status.draft.revision || current.rules_hash !== status.draft.rules_hash || current.dishes_hash !== status.draft.dishes_hash;
  const blockers = status.technical_review?.blockers;
  const canReview = status.review_enabled && !stale && !current.review && !current.release_id;
  const matchingDishes = documents.dishes.filter(dish => JSON.stringify(dish).toLowerCase().includes(query.toLowerCase()));

  return <div className="knowledge-workspace min-h-screen bg-paper text-ink">
    <a href="#knowledge-content" className="skip-link">Skip to knowledge review</a>
    <WorkspaceHeader label="Knowledge review">
      <div className="workspace-tools"><span className="workspace-mode">Unpublished draft</span><a href="/api/docs">API reference</a></div>
    </WorkspaceHeader>
    <main id="knowledge-content" tabIndex={-1} className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      <PageHeader code="KNW" title="Knowledge review"><p>Inspect source evidence, assess rule mappings and record a decision for this draft revision.</p></PageHeader>
      <div className="notice notice-warn mb-5"><strong>Unpublished knowledge. No clinical use.</strong> Planning, patient guidance, editing and publication are disabled. Reviewer names are attestations, not authenticated identities.</div>
      {error && <p role="alert" className="notice notice-error mb-4">{error}</p>}
      {message && <p role="status" className="notice notice-ok mb-4">{message}</p>}
      {stale && <p role="alert" className="notice notice-error mb-4">A newer draft exists. You are inspecting pinned revision {status.draft.revision}. Restart review deployment with the current revision before recording a decision.</p>}
      <section aria-label="Draft summary" className="draft-summary">
        <div className="min-w-0"><h2 className="font-semibold break-all">{status.draft.draft_id}</h2><p className="mt-1 text-sm text-ink-3">Author: {status.draft.author}</p></div>
        <dl className="draft-facts">
          <div><dt>Pinned revision</dt><dd>{status.draft.revision}</dd></div>
          <div><dt>Rules</dt><dd>{rules.length}</dd></div>
          <div><dt>Dishes</dt><dd>{documents.dishes.length}</dd></div>
        </dl>
        <div className="flex flex-wrap items-center gap-3">
          <span className={`flag ${current.review?.decision === 'approve' ? 'flag-ok' : current.review?.decision === 'reject' ? 'flag-bad' : 'flag-warn'}`}>{current.review ? `Decision: ${current.review.decision}` : 'Awaiting review'}</span>
          <button className="btn-ghost" onClick={() => setRefresh(value => value + 1)}>Refresh review status</button>
        </div>
      </section>
      <nav aria-label="Knowledge sections" className="review-sections">{['Rules', 'Blockers & provenance', 'Catalogue', 'History & decision'].map(label => <button key={label} aria-pressed={section === label} className="review-section" onClick={() => { setSection(label); setQuery(''); }}>{label}</button>)}</nav>
      {section === 'Catalogue' && <div className="review-search mb-5"><label className="block text-sm font-semibold mb-2" htmlFor="catalogue-search">Search catalogue</label><input id="catalogue-search" name="search" type="search" className="field" value={query} onChange={event => setQuery(event.target.value)} placeholder="Search dish IDs, names or ingredients" /></div>}
      {section === 'Rules' && <>
        <div className="review-grid">
          <aside className="rule-browser" aria-label="Rule list">
            <div className="rule-filters">
              <label className="block text-sm font-semibold mb-2" htmlFor="knowledge-search">Search rules</label>
              <input id="knowledge-search" name="search" type="search" className="field" value={query} onChange={event => setQuery(event.target.value)} placeholder="ID, nutrient or guideline" />
              <label className="mt-4 flex items-start gap-2 text-sm leading-relaxed"><input className="mt-1" type="checkbox" checked={missingEvidence} onChange={event => setMissingEvidence(event.target.checked)} />Show only rules missing a quote or valid source link</label>
            </div>
            <p role="status" className="rule-count">{filtered.length} matching rules</p>
            <ul className="rule-list">{filtered.map(rule => <li key={rule.rule_id}>
              <button className="rule-option" aria-pressed={selected?.rule_id === rule.rule_id} onClick={() => setSelectedId(rule.rule_id)}>
                <span className="flex items-start justify-between gap-2"><span className="num break-all text-sm font-medium">{rule.rule_id}</span>{selected?.rule_id === rule.rule_id && <span className="rule-selected" aria-hidden="true">Selected</span>}</span>
                <span className="mt-2 block text-sm text-ink-3">{rule.guideline || 'No guideline supplied'}</span>
                {(!rule.verbatim_quote || !safeSourceUrl(rule.url)) && <span className="flag flag-warn mt-2">{!rule.verbatim_quote ? 'Quote missing' : 'Source link missing'}</span>}
              </button>
            </li>)}</ul>
          </aside>
          {selected ? <article className="rule-detail" aria-label="Selected rule">
            <div className="rule-detail-heading"><h2 className="text-xl font-bold break-all">{selected.rule_id}</h2><p className="mt-2 text-sm text-ink-3">{selected.guideline} {selected.section && ` · ${selected.section}`} · Priority <span className="num">{selected.priority ?? 'Not set'}</span></p></div>
            <section className="source-evidence"><h3 className="font-semibold mb-3">Source evidence</h3>{selected.verbatim_quote ? <blockquote className="max-w-prose whitespace-pre-wrap text-base leading-relaxed">“{selected.verbatim_quote}”</blockquote> : <p className="notice notice-warn">No verbatim source quote supplied.</p>}{safeSourceUrl(selected.url) ? <a className="mt-4 inline-block break-all text-sm font-semibold text-line underline" href={safeSourceUrl(selected.url)} target="_blank" rel="noreferrer">Open guideline source</a> : <p className="mt-3 text-sm text-ink-3">No valid HTTP(S) source link supplied.</p>}</section>
            <div className="grid gap-6 sm:grid-cols-2"><section><h3 className="border-b border-rule-2 pb-2 font-semibold">Applies when</h3><RecordDetails value={selected.conditions} /></section><section><h3 className="border-b border-rule-2 pb-2 font-semibold">Proposed actions</h3><RecordDetails value={selected.actions} /></section></div>
            <p className="notice notice-info">MAX ceilings and exclusions are hard constraints. MIN floors and TARGETs are soft aims. A source recommendation does not establish a clinically valid mapping.</p>
            {selected.notes && <section><h3 className="font-semibold mb-2">Author notes</h3><p className="max-w-prose whitespace-pre-wrap text-sm">{selected.notes}</p></section>}
            <section className="border-t border-rule-2 pt-4"><label className="block font-semibold mb-2" htmlFor="compare-revision">Compare with an earlier revision</label><select id="compare-revision" className="field min-h-12" value={comparisonRevision} onChange={event => { setBaseline(undefined); setComparisonError(''); setComparisonRevision(event.target.value); }}><option value="">{status.draft.revision === 1 ? 'First revision: no earlier snapshot' : 'Choose a revision'}</option>{Array.from({ length: status.draft.revision - 1 }, (_, index) => index + 1).map(revision => <option key={revision} value={revision}>Revision {revision}</option>)}</select>{comparisonError && <p role="alert">{comparisonError}</p>}{comparisonRevision && !baseline && !comparisonError && <p role="status">Loading comparison…</p>}{baseline && <div className="mt-4"><p className="flag flag-info mb-3">{!oldRule ? 'New rule' : JSON.stringify(oldRule) === JSON.stringify(selected) ? 'Unchanged rule' : 'Changed rule'}</p>{oldRule && <details><summary className="cursor-pointer font-semibold">Earlier rule, revision {comparisonRevision}</summary><RecordDetails value={oldRule} /></details>}</div>}</section>
            <details><summary className="cursor-pointer font-semibold">Complete rule and additional provenance</summary><RecordDetails value={selected} /></details>
          </article> : <p className="panel p-6">No rules match. Clear the search or evidence filter.</p>}
        </div>
      </>}
      {section === 'Blockers & provenance' && <div className="grid gap-8 lg:grid-cols-2"><section className="min-w-0"><h2 className="mb-4 text-lg font-bold">Publication blockers</h2>{Array.isArray(blockers) && blockers.length ? <div className="notice notice-warn"><RecordDetails value={blockers} /></div> : <p>No authoring blockers supplied. This is not evidence of clinical readiness.</p>}<h3 className="mt-6 mb-3 font-semibold">Technical review</h3><RecordDetails value={status.technical_review} /></section><section className="min-w-0"><h2 className="mb-4 text-lg font-bold">Validation & provenance</h2><RecordDetails value={status.draft.validation} /><h3 className="mt-6 mb-3 font-semibold">Draft provenance</h3><RecordDetails value={status.draft.provenance} /><h3 className="mt-6 mb-3 font-semibold">Pinned document hashes</h3><RecordDetails value={{ rules_sha256: status.draft.rules_hash, dishes_sha256: status.draft.dishes_hash }} /></section></div>}
      {section === 'Catalogue' && <section><h2 className="mb-4 font-semibold">Dish catalogue ({matchingDishes.length})</h2><p className="notice notice-warn mb-4">Catalogue values and verification status are shown as stored; review does not verify nutritional estimates.</p>{matchingDishes.length ? matchingDishes.map(dish => <details key={dish.dish_id} className="border-b border-rule py-3"><summary className="cursor-pointer min-h-12 py-3"><span className="num mr-3">{dish.dish_id}</span>{dish.name} <span className={`flag ml-2 ${dish.verified ? 'flag-neutral' : 'flag-warn'}`}>{dish.verified ? 'Marked verified in source' : 'Unverified'}</span></summary><RecordDetails value={dish} /></details>) : <p>No dishes match this search.</p>}</section>}
      {section === 'History & decision' && <div className="grid gap-8 lg:grid-cols-2"><section><h2 className="text-lg font-bold mb-4">Record a draft-level decision</h2><p className="text-sm mb-4 max-w-prose">Your decision applies to all rules and dishes in revision {status.draft.revision}, not just the selected rule. It does not clear authoring blockers, publish knowledge or enable clinical use.</p>{current.review && <div className="notice notice-info mb-4"><RecordDetails value={current.review} /></div>}{!status.review_enabled && <p className="notice notice-warn mb-4">Inspection only. Review decision recording is unavailable.</p>}<form onSubmit={submit} className="space-y-4"><fieldset disabled={!canReview || busy} className="space-y-4"><legend className="font-semibold mb-3">Revision {status.draft.revision} review</legend><label className="block text-sm font-semibold">Reviewer name (required)<input name="actor" className="field mt-2 min-h-12 text-base" required maxLength={200} value={actor} onChange={event => setActor(event.target.value)} /></label><fieldset><legend className="text-sm font-semibold mb-2">Decision</legend>{['reject', 'approve'].map(value => <label key={value} className="mr-5 inline-flex min-h-12 items-center gap-2"><input type="radio" name="decision" value={value} checked={decision === value} onChange={() => setDecision(value)} />{value === 'reject' ? 'Reject revision' : 'Approve revision'}</label>)}</fieldset><label className="block text-sm font-semibold">Review rationale (required)<textarea name="note" className="field mt-2 min-h-32 text-base" required maxLength={10000} value={note} onChange={event => setNote(event.target.value)} /></label><label className="flex items-start gap-3 text-sm"><input className="mt-1" type="checkbox" required checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />I reviewed this complete revision and its evidence, including the disclosed blockers. I am not an author or editor of this draft.</label><button className="btn-primary min-h-12" type="submit">{busy ? 'Recording decision…' : 'Record review decision'}</button></fieldset></form></section><section className="min-w-0"><h2 className="text-lg font-bold mb-4">Revision and review history</h2>{events.length ? <ol className="divide-y divide-rule">{events.map(event => <li key={event.event_id} className="py-4"><p className="font-semibold">{event.action} · Revision <span className="num">{event.revision}</span></p><p className="text-sm text-ink-3 break-words">{event.actor} · {event.created_at}</p><details className="mt-2"><summary className="text-sm cursor-pointer">Event details</summary><pre className="overflow-x-auto whitespace-pre-wrap break-words text-xs mt-2">{event.detail_json}</pre></details></li>)}</ol> : <p>No history recorded.</p>}</section></div>}
    </main>
  </div>;
}
