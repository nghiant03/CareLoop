import { useEffect, useState, type FormEvent } from 'react';
import { reviewRequest, type ReviewDocuments, type ReviewDraft } from '../knowledgeReview';

export function DocumentFields({ rules, dishes, setRules, setDishes, onError }: {
  rules: string; dishes: string; setRules: (value: string) => void; setDishes: (value: string) => void;
  onError: (message: string) => void;
}) {
  async function readFile(file: File | undefined, setValue: (value: string) => void) {
    if (!file) return;
    try { setValue(await file.text()); }
    catch { onError('Unable to read the document. Choose a readable JSON file.'); }
  }
  return <div className="grid gap-6 lg:grid-cols-2">
    <div className="min-w-0 space-y-3">
      <label className="block font-semibold" htmlFor="rules-file">Load rulebook JSON</label>
      <input id="rules-file" name="rules-file" className="field min-h-12 text-base" type="file" accept=".json,application/json" onChange={event => void readFile(event.target.files?.[0], setRules)} />
      <label className="block font-semibold" htmlFor="rules-json">Rulebook JSON (required)</label>
      <textarea id="rules-json" name="rules" className="field min-h-80 font-mono text-base" required spellCheck={false} value={rules} onChange={event => setRules(event.target.value)} />
    </div>
    <div className="min-w-0 space-y-3">
      <label className="block font-semibold" htmlFor="dishes-file">Load catalogue JSON</label>
      <input id="dishes-file" name="dishes-file" className="field min-h-12 text-base" type="file" accept=".json,application/json" onChange={event => void readFile(event.target.files?.[0], setDishes)} />
      <label className="block font-semibold" htmlFor="dishes-json">Dish catalogue JSON (required)</label>
      <textarea id="dishes-json" name="dishes" className="field min-h-80 font-mono text-base" required spellCheck={false} value={dishes} onChange={event => setDishes(event.target.value)} />
    </div>
  </div>;
}

export default function KnowledgeDraftEditor({ draft, documents, token, onChanged, onDirtyChange }: {
  draft: ReviewDraft; documents: ReviewDocuments; token: string; onChanged: () => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const [rules, setRules] = useState(() => JSON.stringify(documents.rules, null, 2));
  const [dishes, setDishes] = useState(() => JSON.stringify(documents.dishes, null, 2));
  const [actor, setActor] = useState('');
  const [note, setNote] = useState('');
  const [releaseId, setReleaseId] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    onDirtyChange(!draft.release_id && (rules !== JSON.stringify(documents.rules, null, 2)
      || dishes !== JSON.stringify(documents.dishes, null, 2)
      || Boolean(actor || note || releaseId || confirmed)));
  }, [rules, dishes, actor, note, releaseId, confirmed, draft.release_id, documents, onDirtyChange]);

  async function save(event: FormEvent<HTMLFormElement>, publish: boolean) {
    event.preventDefault(); setBusy(true); setError(''); setMessage('');
    try {
      const response = await reviewRequest<{ detail?: string }>(`/drafts/${encodeURIComponent(draft.draft_id)}${publish ? '/publish' : ''}`, {
        method: publish ? 'POST' : 'PUT',
        headers: { 'Content-Type': 'application/json', 'X-Review-Token': token },
        body: JSON.stringify({ actor: actor.trim(), note: note.trim(), expected_revision: draft.revision,
          ...(publish ? { release_id: releaseId.trim(), confirmed } : { rules: JSON.parse(rules), dishes: JSON.parse(dishes) }) }),
      });
      setMessage(publish ? response.detail || 'Published. Activation requires a controlled deployment restart.' : 'New revision saved. Previous reviews do not carry forward.');
      onChanged();
    } catch (failure) { setError(failure instanceof SyntaxError ? 'The rulebook or catalogue contains invalid JSON. Correct it before saving.' : failure instanceof Error ? failure.message : 'Unable to save knowledge.'); }
    finally { setBusy(false); }
  }

  return <div className="space-y-8">
    {error && <p role="alert" className="notice notice-error">{error}</p>}
    {message && <p role="status" className="notice notice-ok">{message}</p>}
    <p className="notice notice-info">Edits append a revision and require a new independent review. Published drafts cannot be edited. Published dish IDs must retain their historical meaning.</p>
    <form onSubmit={event => void save(event, false)} className="space-y-5">
      <fieldset className="space-y-5" disabled={busy || Boolean(draft.release_id)}>
        <legend className="mb-4 text-lg font-bold">Edit revision {draft.revision}</legend>
        <DocumentFields rules={rules} dishes={dishes} setRules={setRules} setDishes={setDishes} onError={setError} />
        <label className="block font-semibold" htmlFor="editor-name">Editor name (required)</label>
        <input id="editor-name" name="actor" className="field min-h-12 text-base" required maxLength={200} value={actor} onChange={event => setActor(event.target.value)} />
        <label className="block font-semibold" htmlFor="edit-note">Change rationale (required)</label>
        <textarea id="edit-note" name="note" className="field min-h-28 text-base" required maxLength={10000} value={note} onChange={event => setNote(event.target.value)} />
        <button className="btn-primary" type="submit">{busy ? 'Saving…' : 'Save new revision'}</button>
      </fieldset>
    </form>
    <form onSubmit={event => void save(event, true)} className="border-t border-rule-2 pt-6 space-y-5">
      <h2 className="text-lg font-bold">Publish reviewed knowledge</h2>
      <p className="max-w-prose">Publication freezes this revision. Select the release and restart the deployment to activate it.</p>
      {draft.release_id ? <p className="notice notice-ok">Published as {draft.release_id}.</p>
        : draft.review?.decision !== 'approve' && <p className="notice notice-warn">An independent approving review of this revision is required.</p>}
      <fieldset disabled={busy || Boolean(draft.release_id) || draft.review?.decision !== 'approve'} className="space-y-4">
        <legend className="font-semibold mb-2">Publication details</legend>
        <label className="block font-semibold" htmlFor="release-id">Release ID (required)</label>
        <input id="release-id" name="release_id" className="field min-h-12 text-base" required maxLength={100} pattern="[A-Za-z0-9][A-Za-z0-9._-]*" autoCapitalize="none" spellCheck={false} value={releaseId} onChange={event => setReleaseId(event.target.value)} />
        <label className="block font-semibold" htmlFor="publisher-name">Publisher name (required)</label>
        <input id="publisher-name" name="actor" className="field min-h-12 text-base" required maxLength={200} value={actor} onChange={event => setActor(event.target.value)} />
        <label className="block font-semibold" htmlFor="publication-note">Publication rationale (required)</label>
        <textarea id="publication-note" name="note" className="field min-h-28 text-base" required maxLength={10000} value={note} onChange={event => setNote(event.target.value)} />
        <label className="flex min-h-12 items-start gap-3" htmlFor="confirm-publish"><input id="confirm-publish" name="confirmed" type="checkbox" required checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />I intend to publish this exact reviewed revision, not activate it.</label>
        <button className="btn-primary" type="submit">{busy ? 'Publishing…' : 'Publish revision'}</button>
      </fieldset>
    </form>
  </div>;
}
