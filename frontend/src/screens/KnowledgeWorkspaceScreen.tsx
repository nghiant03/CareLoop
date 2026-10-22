import { useEffect, useState, type FormEvent } from 'react';
import PageHeader from '../components/PageHeader';
import LoadingState from '../components/LoadingState';
import WorkspaceHeader from '../components/WorkspaceHeader';
import { reviewRequest, type DocumentRecord, type KnowledgeWorkspace, type ReviewDraft } from '../knowledgeReview';
import KnowledgeReviewScreen from './KnowledgeReviewScreen';
import { DocumentFields } from './KnowledgeDraftEditor';

function uploadContent(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error(`Unable to read ${file.name}. Choose a readable source file.`));
    reader.onload = () => resolve(String(reader.result).split(',')[1]);
    reader.readAsDataURL(file);
  });
}

export default function KnowledgeWorkspaceScreen() {
  const [workspace, setWorkspace] = useState<KnowledgeWorkspace>();
  const [refresh, setRefresh] = useState(0);
  const [selectedId, setSelectedId] = useState('');
  const [section, setSection] = useState('Drafts');
  const [actor, setActor] = useState('');
  const [draftId, setDraftId] = useState('');
  const [releaseId, setReleaseId] = useState('');
  const [rules, setRules] = useState('');
  const [dishes, setDishes] = useState('');
  const [sources, setSources] = useState<{ file: File; sourceUrl: string }[]>([]);
  const [instructions, setInstructions] = useState('');
  const [report, setReport] = useState<DocumentRecord>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    reviewRequest<KnowledgeWorkspace>('', { signal: controller.signal }).then(value => {
      setWorkspace(value); setInstructions(current => current || value.instructions); setError('');
    }).catch((failure: Error) => { if (!controller.signal.aborted) setError(failure.message); });
    return () => controller.abort();
  }, [refresh]);

  async function submit(event: FormEvent<HTMLFormElement>, action: 'create' | 'clone' | 'discover') {
    event.preventDefault(); if (!workspace) return;
    setBusy(true); setError('');
    try {
      if (action === 'discover') {
        if (!sources.length || sources.length > 10) throw new Error('Choose between 1 and 10 guideline files. Remove extra files before extracting.');
        const metadata = { instructions, sources: sources.map(source => ({ name: source.file.name, source_url: source.sourceUrl || null, encoding: 'base64', content: '' })) };
        const encodedBytes = sources.reduce((total, source) => total + 4 * Math.ceil(source.file.size / 3), 0)
          + new TextEncoder().encode(JSON.stringify(metadata)).byteLength;
        if (encodedBytes > 32 * 1024 * 1024) throw new Error('These sources exceed the 32 MiB encoded upload limit. Remove files or select smaller guideline excerpts before extracting.');
      }
      const payload = action === 'create' ? { draft_id: draftId.trim(), actor: actor.trim(), rules: JSON.parse(rules), dishes: JSON.parse(dishes) }
        : action === 'clone' ? { draft_id: draftId.trim(), actor: actor.trim(), release_id: releaseId.trim() }
        : { instructions, ...(selectedId ? { draft_id: selectedId } : {}), sources: await Promise.all(sources.map(async source => ({ name: source.file.name, source_url: source.sourceUrl || null, encoding: 'base64', content: await uploadContent(source.file) }))) };
      const value = await reviewRequest<ReviewDraft & DocumentRecord>(action === 'create' ? '/drafts' : `/${action}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Review-Token': workspace.csrf_token }, body: JSON.stringify(payload),
      });
      if (action === 'discover') setReport(value);
      else { setSelectedId(value.draft_id); setRefresh(value => value + 1); }
    } catch (failure) { setError(failure instanceof SyntaxError ? 'The rulebook or catalogue contains invalid JSON. Correct it before creating a draft.' : failure instanceof Error ? failure.message : 'Knowledge operation failed.'); }
    finally { setBusy(false); }
  }

  if (!workspace && !error) return <LoadingState text="Loading knowledge workspace" />;
  if (workspace && selectedId) return <KnowledgeReviewScreen key={selectedId} draftId={selectedId} token={workspace.csrf_token} onBack={() => { setSelectedId(''); setRefresh(value => value + 1); }} />;

  return <div className="knowledge-workspace min-h-screen bg-paper text-ink">
    <a className="skip-link" href="#knowledge-content">Skip to knowledge workspace</a>
    <WorkspaceHeader label="Knowledge workspace"><a href="/api/docs">API reference</a></WorkspaceHeader>
    <main id="knowledge-content" tabIndex={-1} className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      <PageHeader code="KNW" title="Knowledge workspace"><p>Discover evidence, author drafts, review exact revisions and publish knowledge without command-line workflows.</p></PageHeader>
      {error && <div role="alert" className="notice notice-error mb-5"><p>{error}</p><button type="button" className="btn-ghost mt-3" onClick={() => setRefresh(value => value + 1)}>Refresh workspace</button></div>}
      <nav aria-label="Workspace sections" className="review-sections">{['Drafts', 'Create draft', 'Clone release', 'Discover sources'].map(value => <button key={value} type="button" aria-pressed={section === value} className="review-section" onClick={() => setSection(value)}>{value}</button>)}</nav>
      {workspace && section === 'Drafts' && <section>
        <h2 className="mb-4 text-xl font-bold">Knowledge drafts</h2>
        {!workspace.drafts.length ? <div className="panel p-6 space-y-4"><p>No knowledge drafts yet. Create one from a reviewed source rulebook and dish catalogue, or prepare new evidence in Discover sources.</p><button type="button" className="btn-primary" onClick={() => setSection('Create draft')}>Create first draft</button></div>
          : <ul className="divide-y divide-rule">{workspace.drafts.map(draft => <li key={draft.draft_id} className="flex flex-wrap items-center justify-between gap-4 py-5"><div className="min-w-0"><h3 className="font-semibold break-all">{draft.draft_id}</h3><p className="text-sm text-ink-3">Revision {draft.revision} · Author: {draft.author} · {draft.release_id ? `Published as ${draft.release_id}` : draft.review ? `${draft.review.decision} review recorded` : 'Awaiting review'}</p></div><button type="button" className="btn-primary" onClick={() => setSelectedId(draft.draft_id)}>Open {draft.draft_id}</button></li>)}</ul>}
      </section>}
      {workspace && (section === 'Create draft' || section === 'Clone release') && <form onSubmit={event => void submit(event, section === 'Create draft' ? 'create' : 'clone')} className="space-y-5">
        <fieldset disabled={busy} className="space-y-5">
          <legend className="mb-3 text-xl font-bold">{section === 'Create draft' ? 'Create a knowledge draft' : 'Clone a published release'}</legend>
          <p className="max-w-prose">Drafts are not live knowledge. Use a complete executable rulebook and catalogue, not an LLM candidate report. Source and scope validation runs on the server.</p>
          <label className="block font-semibold" htmlFor="new-draft-id">New draft ID (required)</label>
          <input id="new-draft-id" name="draft_id" className="field min-h-12 text-base" required maxLength={100} pattern="[A-Za-z0-9][A-Za-z0-9._-]*" spellCheck={false} autoCapitalize="none" value={draftId} onChange={event => setDraftId(event.target.value)} />
          <label className="block font-semibold" htmlFor="draft-author">Author name (required)</label>
          <input id="draft-author" name="actor" className="field min-h-12 text-base" required maxLength={200} value={actor} onChange={event => setActor(event.target.value)} />
          {section === 'Create draft' ? <DocumentFields rules={rules} dishes={dishes} setRules={setRules} setDishes={setDishes} onError={setError} /> : <>
            <label className="block font-semibold" htmlFor="clone-release">Source release ID (required)</label>
            <input id="clone-release" name="release_id" className="field min-h-12 text-base" required maxLength={100} value={releaseId} onChange={event => setReleaseId(event.target.value)} />
          </>}
          <button type="submit" className="btn-primary">{busy ? 'Saving draft…' : section === 'Create draft' ? 'Create draft' : 'Clone release'}</button>
        </fieldset>
      </form>}
      {workspace && section === 'Discover sources' && <section className="space-y-6">
        <h2 className="text-xl font-bold">Discover nutrition knowledge</h2>
        <p className="max-w-prose">Add any guideline as PDF, HTML, Markdown or text. You are not limited to KDIGO: add ADA, DASH, KDOQI or another appropriately licensed guideline. No manifest, hash registration or source-specific code is required.</p>
        {!workspace.discovery_available && <p className="notice notice-warn">No LLM provider has been selected. You can prepare sources and instructions here, but extraction is unavailable until a provider adapter is connected. There is no static-pattern fallback.</p>}
        <form onSubmit={event => void submit(event, 'discover')} className="space-y-5">
          <fieldset disabled={busy} className="space-y-5">
            <legend className="font-semibold mb-3">Guideline sources and extraction instructions</legend>
            <label className="block font-semibold" htmlFor="guideline-files">Add guideline files (required)</label>
            <p id="source-help" className="text-sm text-ink-3">Up to 10 files; 32 MiB total encoded request. Files are processed temporarily, not added to live knowledge. Do not upload patient records.</p>
            <input id="guideline-files" name="sources" type="file" multiple accept=".pdf,.html,.htm,.md,.txt" className="field min-h-12 text-base" aria-describedby="source-help" onChange={event => { setSources(current => [...current, ...Array.from(event.target.files || []).map(file => ({ file, sourceUrl: '' }))]); setReport(undefined); }} />
            <ul className="space-y-4">{sources.map((source, index) => <li key={`${source.file.name}-${index}`} className="border-b border-rule pb-4 space-y-2"><p className="font-semibold break-all">{source.file.name}</p><label className="block text-sm" htmlFor={`source-url-${index}`}>Original source URL for {source.file.name} (optional)</label><input id={`source-url-${index}`} name={`source_url_${index}`} type="url" className="field min-h-12 text-base" value={source.sourceUrl} onChange={event => setSources(current => current.map((value, position) => position === index ? { ...value, sourceUrl: event.target.value } : value))} /><button type="button" className="btn-ghost" onClick={() => setSources(current => current.filter((_, position) => position !== index))}>Remove {source.file.name}</button></li>)}</ul>
            <label className="block font-semibold" htmlFor="discovery-instructions">Extraction instructions (required)</label>
            <p id="prompt-help" className="text-sm text-ink-3">The default comes from backend/knowledge/prompts/discover_rules.md. Edits apply only to this extraction; they do not overwrite the server file.</p>
            <textarea id="discovery-instructions" name="instructions" className="field min-h-80 text-base" required maxLength={100000} aria-describedby="prompt-help" value={instructions} onChange={event => setInstructions(event.target.value)} />
            <button type="submit" className="btn-primary" disabled={!workspace.discovery_available}>{busy ? 'Extracting candidates…' : 'Extract review candidates'}</button>
          </fieldset>
        </form>
        {report && <section className="space-y-4"><h3 className="text-lg font-bold">Review-only extraction report</h3><p className="notice notice-warn">These are not executable rules. Verify quotations, units, populations and exceptions before authoring a draft. No knowledge was published or activated.</p><pre className="panel p-4 whitespace-pre-wrap break-words text-sm max-h-96 overflow-auto">{JSON.stringify(report, null, 2)}</pre></section>}
      </section>}
    </main>
  </div>;
}
