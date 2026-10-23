import { useState } from 'react';
import { Link } from 'react-router-dom';
import {
  api,
  label,
  quantity,
  type ChatContext,
  type ChatRun,
  type Plan,
  type Food,
} from '../api';
import {
  Details,
  Empty,
  Feedback,
  Field,
  Form,
  FoodPicker,
  Panel,
} from '../components/shared';
import { decision, useResource, useSession, useTask } from '../state';
import { paths } from '../navigation';

export default function Chat() {
  const { actor, patientId } = useSession();
  const task = useTask();
  const [version, setVersion] = useState(0);
  const [page, setPage] = useState(0);
  const [question, setQuestion] = useState('');
  const [requestId, setRequestId] = useState<string | null>(null);
  const [unresolved, setUnresolved] = useState(false);
  const [composerVersion, setComposerVersion] = useState(0);
  const [planId, setPlanId] = useState('');
  const [loggedOn, setLoggedOn] = useState('');
  const [substitutions, setSubstitutions] = useState(false);
  const [mealIndex, setMealIndex] = useState('');
  const [foods, setFoods] = useState<Food[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const plans = useResource<Plan[]>(
    patientId ? `/patients/${patientId}/plans` : null,
    version,
    true,
  );
  const plan = useResource<Plan>(planId ? `/plans/${planId}` : null, version);
  const base = `/patients/${patientId}/chat`;
  const context = useResource<ChatContext>(
    patientId ? `${base}/context` : null,
    version,
  );
  const history = useResource<ChatRun[]>(
    patientId ? `${base}?limit=20&offset=${page * 20}` : null,
    version,
  );
  const refresh = () => setVersion((v) => v + 1);
  if (!patientId)
    return (
      <Empty>
        Select a patient to ask about their approved targets and published
        nutrition evidence.
      </Empty>
    );
  const current = context.data;
  const allowed = actor.role === 'patient';

  return (
    <>
      <Feedback
        task={task}
        error={context.error || history.error || plans.error || plan.error}
      />
      <Panel title="Ask about nutrition">
        <p className="text-ink-3 max-w-prose mb-4">
          Answers use recorded patient facts, current clinician-approved
          targets, selected meal records, and published source quotations.
          Diagnosis and treatment changes go to the clinician.
        </p>
        <div className="flex flex-wrap items-center gap-3 mb-4">
          <button
            type="button"
            className="btn-ghost"
            disabled={task.busy || context.loading}
            onClick={refresh}
          >
            Refresh context and history
          </button>
          {context.loading && <p role="status">Checking approved context…</p>}
          {current?.ready && (
            <p className="text-sm text-ink-3">
              Patient revision {current.patient_revision} · target revision{' '}
              {current.target_revision} · GLM 5.3
            </p>
          )}
        </div>
        {current && !current.ready && (
          <p className="notice mb-4">
            {current.reason}. Ask your clinician to review your targets.
          </p>
        )}
        {!allowed && (
          <p className="notice mb-4">
            Switch to the patient demo role to ask a question.
          </p>
        )}
        {current?.ready && (
          <Details
            title="Facts and approved targets used for answers"
            value={{ facts: current.facts, targets: current.target_items }}
          />
        )}
        <Form
          key={composerVersion}
          busy={task.busy || !allowed || !current?.ready || unresolved}
          onSubmit={() =>
            void task.run(async () => {
              if (!current?.ready)
                throw new Error('Refresh the approved patient context first.');
              const meal = plan.data?.body.meals[Number(mealIndex)];
              if (
                substitutions &&
                (!planId ||
                  mealIndex === '' ||
                  !meal ||
                  !foods.length ||
                  foods.length > 100)
              )
                throw new Error(
                  'Select a planned meal item and 1–100 candidate foods.',
                );
              const id = crypto.randomUUID();
              setRequestId(id);
              setUnresolved(true);
              const run = await api<ChatRun>(base, {
                ...decision(actor, 'Ask a cited nutrition question'),
                request_id: id,
                question,
                patient_revision: current.patient_revision,
                target_id: current.target_id,
                target_revision: current.target_revision,
                workflow: {
                  plan_id: planId || null,
                  logged_on: loggedOn || null,
                  substitution:
                    substitutions && meal
                      ? {
                          day: meal.day,
                          slot: meal.slot,
                          item: meal.item ?? 1,
                          food_ids: foods.map((food) => food.id),
                        }
                      : null,
                },
              });
              setUnresolved(run.state === 'pending');
              if (run.state === 'completed') {
                setQuestion('');
                setComposerVersion((v) => v + 1);
              }
              setPage(0);
              refresh();
            }, 'Question recorded. Read the answer and its sources below.')
          }
        >
          <details>
            <summary className="cursor-pointer font-semibold text-line">
              Include a plan, intake date or substitution search
            </summary>
            <fieldset className="space-y-4 mt-4">
              <legend className="font-semibold mb-3">
                Records for this question (optional)
              </legend>
              <Field label="Approved meal plan">
                <select
                  name="plan_id"
                  className="field"
                  value={planId}
                  onChange={(e) => {
                    setPlanId(e.target.value);
                    setMealIndex('');
                    setSubstitutions(false);
                  }}
                >
                  <option value="">No plan attached</option>
                  {plans.data
                    ?.filter(
                      (p) =>
                        p.approved_at &&
                        !p.needs_review &&
                        p.target_id === current?.target_id &&
                        p.target_revision === current?.target_revision,
                    )
                    .map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.start_date} · {label(p.objective)} ·{' '}
                        {p.id.slice(0, 8)}
                      </option>
                    ))}
                </select>
              </Field>
              <Field
                label="Intake date"
                hint="Includes all reported intake on this date, its completeness and calculated comparisons."
              >
                <input
                  name="logged_on"
                  type="date"
                  className="field"
                  value={loggedOn}
                  onChange={(e) => setLoggedOn(e.target.value)}
                />
              </Field>
              {planId && (
                <label className="flex items-center gap-3">
                  <input
                    name="substitutions"
                    type="checkbox"
                    checked={substitutions}
                    onChange={(e) => setSubstitutions(e.target.checked)}
                  />
                  Find checked substitutions
                </label>
              )}
              {substitutions && (
                <>
                  <Field label="Meal item to replace (required)">
                    <select
                      name="meal_item"
                      className="field"
                      required
                      value={mealIndex}
                      onChange={(e) => setMealIndex(e.target.value)}
                    >
                      <option value="">Select a meal item</option>
                      {plan.data?.body.meals.map((m, i) => (
                        <option key={i} value={i}>
                          Day {m.day} · {label(m.slot)} · item {m.item ?? 1}:{' '}
                          {m.food.name}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <fieldset>
                    <legend className="font-semibold mb-3">
                      Candidate foods (select 1–100)
                    </legend>
                    <FoodPicker selected={foods} onChange={setFoods} embedded />
                  </fieldset>
                  <p className="text-sm text-ink-3">
                    Each candidate is checked against the whole plan. A
                    suggestion does not change your plan; a replacement draft
                    needs clinician approval.
                  </p>
                </>
              )}
            </fieldset>
          </details>
          {(planId || loggedOn) && (
            <p className="text-sm text-ink-3">
              Attached: {planId ? 'approved plan' : ''}
              {planId && loggedOn ? ' · ' : ''}
              {loggedOn ? `intake on ${loggedOn}` : ''}
              {substitutions ? ' · checked substitution search' : ''}
            </p>
          )}
          <Field label="Your question (required)">
            <textarea
              name="question"
              aria-describedby="question-help"
              className="field min-h-28"
              required
              maxLength={2000}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
            />
          </Field>
          <p id="question-help" className="text-sm text-ink-3">
            Ask one specific question. Enter adds a new line; use Send question
            to submit.
          </p>
          <button type="submit" className="btn-primary">
            Send question
          </button>
        </Form>
        {unresolved && (
          <div className="mt-4 space-y-3">
            <p role="status" className="text-sm break-words">
              Request {requestId} is pending or its outcome is unknown. Check
              the saved result before submitting again.
            </p>
            <div className="flex flex-wrap gap-3">
              <button
                type="button"
                className="btn-ghost"
                disabled={task.busy}
                onClick={() =>
                  void task.run(async () => {
                    const run = await api<ChatRun>(`${base}/${requestId}`);
                    setUnresolved(run.state === 'pending');
                    refresh();
                  }, 'Request status refreshed.')
                }
              >
                Check saved answer
              </button>
              {!task.busy && (
                <button
                  type="button"
                  className="btn-ghost"
                  onClick={() => {
                    setUnresolved(false);
                    setRequestId(null);
                  }}
                >
                  Prepare a separate question
                </button>
              )}
            </div>
          </div>
        )}
        <p className="text-sm text-ink-3 mt-4">
          Manage your plans and replacement drafts in{' '}
          <Link className="underline" to={paths.mealPlans}>
            Meal plans
          </Link>
          . Record or correct intake in{' '}
          <Link className="underline" to={paths.mealLog}>
            Meal log
          </Link>
          .
        </p>
      </Panel>
      <Panel title="Conversation and sources">
        <p className="text-sm text-ink-3 mb-4">
          Newest questions first. The last three completed exchanges for the
          same approved context support follow-up questions.
        </p>
        {history.loading && <p role="status">Loading conversation…</p>}
        {!history.loading && !history.error && !history.data?.length && (
          <Empty>
            No questions yet. Try “What is my approved protein target?”
          </Empty>
        )}
        <ol className="divide-y divide-rule">
          {history.data?.map((run) => {
            const stale =
              run.stale ||
              (current &&
                (!current.ready ||
                  run.context.patient_revision !== current.patient_revision ||
                  run.context.target_id !== current.target_id ||
                  run.context.target_revision !== current.target_revision ||
                  run.context.evidence_generation !==
                    current.evidence_generation));
            return (
              <li key={run.id} className="py-5 space-y-3">
                <h3 className="font-semibold whitespace-pre-wrap break-words">
                  {run.question}
                </h3>
                <p className="text-sm text-ink-3">
                  {new Date(run.created_at).toLocaleString()} · {run.model} ·{' '}
                  {run.state}
                </p>
                {stale && (
                  <p className="notice">
                    Historical answer: patient context, evidence or selected
                    records have changed. Refresh and ask again using current
                    records.
                  </p>
                )}
                {run.state === 'pending' && (
                  <p>
                    Answer pending or outcome unknown. Refresh history to check;
                    no automatic retry is made.
                  </p>
                )}
                {run.error && (
                  <p className="notice notice-error" role="alert">
                    {run.error}
                  </p>
                )}
                {run.result && (
                  <>
                    <p className="whitespace-pre-wrap break-words max-w-prose">
                      {run.result.answer}
                    </p>
                    <div className="flex flex-wrap gap-3 text-sm">
                      {run.result.insufficient_evidence && (
                        <span className="flag flag-warn">
                          Evidence is insufficient
                        </span>
                      )}
                      {run.result.needs_clinician && (
                        <span className="flag flag-warn">
                          Discuss with your clinician
                        </span>
                      )}
                    </div>
                    {run.workflow &&
                      (run.workflow.plan_id || run.workflow.logged_on) && (
                        <p className="text-sm text-ink-3">
                          Records used:{' '}
                          {run.workflow.plan_id
                            ? `plan ${run.workflow.plan_id.slice(0, 8)}`
                            : ''}
                          {run.workflow.logged_on
                            ? ` · intake ${run.workflow.logged_on}`
                            : ''}
                        </p>
                      )}
                    {run.result.suggestions && (
                      <section
                        aria-label="Checked substitution suggestions"
                        className="space-y-3"
                      >
                        <h4 className="font-semibold">Checked substitutions</h4>
                        <p className="text-sm text-ink-3">
                          {run.result.suggestions.checked_portions} portions
                          checked. These are suggestions; your approved plan
                          stays active until a replacement draft is approved.
                        </p>
                        {!run.result.suggestions.recommendations.length && (
                          <p className="notice">
                            No eligible replacement was found in the selected
                            pool. Try different candidate foods; this does not
                            prove that no replacement exists.
                          </p>
                        )}
                        {run.result.suggestions.recommendations.map(
                          (candidate) => {
                            const key = `${run.id}:${candidate.food_id}`;
                            return (
                              <div
                                key={key}
                                className="border-t border-rule pt-3 space-y-2"
                              >
                                <p className="font-semibold">
                                  {candidate.name} ·{' '}
                                  {quantity(candidate.quantity)}{' '}
                                  {candidate.unit}
                                </p>
                                <Details
                                  title="Calculated nutrient differences"
                                  value={candidate.nutrient_delta}
                                />
                                {drafts[key] ? (
                                  <p role="status">
                                    Replacement draft requested. Your clinician
                                    must approve it.
                                  </p>
                                ) : (
                                  <button
                                    type="button"
                                    className="btn-ghost"
                                    disabled={task.busy || !!stale || !allowed}
                                    onClick={() =>
                                      void task.run(async () => {
                                        const latest = await api<ChatRun>(
                                          `${base}/${run.id}`,
                                        );
                                        if (latest.stale) {
                                          refresh();
                                          throw new Error(
                                            'The suggestion context changed. Ask again before requesting a replacement.',
                                          );
                                        }
                                        const draft = await api<Plan>(
                                          `/plans/${run.result!.suggestions!.plan_id}/substitutions`,
                                          {
                                            ...decision(
                                              actor,
                                              'Request a checked substitution from nutrition chat',
                                            ),
                                            ...candidate.substitution,
                                          },
                                        );
                                        setDrafts((value) => ({
                                          ...value,
                                          [key]: draft.id,
                                        }));
                                      }, 'Replacement draft created for clinician review.')
                                    }
                                  >
                                    Request replacement draft: {candidate.name}
                                  </button>
                                )}
                              </div>
                            );
                          },
                        )}
                      </section>
                    )}
                    {run.result.citations.map((citation) => (
                      <details key={citation.source_id} className="text-sm">
                        <summary className="cursor-pointer font-semibold text-line">
                          {citation.title} · {citation.location}
                        </summary>
                        <p className="text-ink-3 mt-2">
                          {label(citation.kind)}
                          {citation.edition ? ` · ${citation.edition}` : ''}
                        </p>
                        {citation.locator && (
                          <p className="break-words text-ink-3">
                            {citation.locator}
                          </p>
                        )}
                        <blockquote className="whitespace-pre-wrap break-words bg-panel p-3 mt-2 max-h-80 overflow-auto">
                          {citation.quote}
                        </blockquote>
                      </details>
                    ))}
                  </>
                )}
              </li>
            );
          })}
        </ol>
        <div className="flex flex-wrap gap-3 mt-4">
          <button
            type="button"
            className="btn-ghost"
            disabled={!page || history.loading}
            onClick={() => setPage((p) => p - 1)}
          >
            Newer questions
          </button>
          <button
            type="button"
            className="btn-ghost"
            disabled={history.data?.length !== 20 || history.loading}
            onClick={() => setPage((p) => p + 1)}
          >
            Older questions
          </button>
        </div>
      </Panel>
    </>
  );
}
