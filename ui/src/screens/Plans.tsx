import { useState } from 'react';
import { Link } from 'react-router-dom';
import {
  api,
  foodEstimates,
  label,
  localDate,
  quantity,
  slots,
  type Food,
  type Plan,
  type Recommendation,
  type Meal,
} from '../api';
import {
  Details,
  Empty,
  Feedback,
  Field,
  FoodPicker,
  Form,
  Panel,
  ListFilter,
  Totals,
} from '../components/shared';
import { decision, useResource, useSession, useTask } from '../state';
import { paths } from '../navigation';

type PoolMode = 'catalogue' | 'selected' | 'exclude';
type SearchOutcome = {
  status: string;
  blockers?: string[];
  pool_food_count?: number;
  eligible_food_count?: number;
  shortlisted?: boolean;
};
const poolSelection = (mode: PoolMode, foods: Food[]) =>
  mode === 'selected'
    ? { food_ids: foods.map((food) => food.id) }
    : {
        excluded_food_ids:
          mode === 'exclude' ? foods.map((food) => food.id) : [],
      };

export default function Plans() {
  const { actor, patientId } = useSession();
  const task = useTask();
  const [version, setVersion] = useState(0);
  const ready = useResource<{
    targets_ready: boolean;
    approved_target: { id: string; approved_revision: number } | null;
  }>(patientId ? `/patients/${patientId}/target-readiness` : null, version);
  const saved = useResource<Plan[]>(
    patientId ? `/patients/${patientId}/plans` : null,
    version,
    true,
  );
  const [foods, setFoods] = useState<Food[]>([]);
  const [poolMode, setPoolMode] = useState<PoolMode>('catalogue');
  const [counts, setCounts] = useState<Record<string, number>>({
    breakfast: 2,
    lunch: 3,
    dinner: 3,
    snack: 0,
  });
  const [days, setDays] = useState(1);
  const [startDate, setStartDate] = useState(localDate);
  const [alternatives, setAlternatives] = useState<Plan[]>([]);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [outcome, setOutcome] = useState<SearchOutcome | null>(null);
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('');
  const visiblePlans = (saved.data ?? []).filter(
    (p) =>
      (!status ||
        (p.needs_review ? 'review' : p.approved_at ? 'approved' : 'draft') ===
          status) &&
      `${p.objective} ${p.start_date} ${p.id}`
        .toLowerCase()
        .includes(query.toLowerCase().trim()),
  );
  if (!patientId)
    return <Empty>Select a patient to create or review meal plans.</Empty>;
  const changed = (value: Plan) => {
    setPlan(value);
    setVersion((v) => v + 1);
  };
  return (
    <>
      <Feedback task={task} error={ready.error || saved.error} />
      {actor.role === 'patient' && (
        <Panel title="Build a meal plan">
          {ready.loading ? (
            <p role="status">Checking target readiness…</p>
          ) : (
            !ready.data?.targets_ready && (
              <p className="notice notice-warn mb-4">
                Current clinician-approved targets are required. Ask your
                clinician to review your targets.
              </p>
            )
          )}
          <div className="grid gap-6 lg:grid-cols-2">
            <div>
              <p className="text-ink-3 mb-4">
                The planner searches the catalogue and checks foods against your
                recorded allergies, dietary choices, source portions and
                approved targets. You do not need to select foods first.
              </p>
              <details>
                <summary className="cursor-pointer font-semibold text-line">
                  Food choices (optional) ·{' '}
                  {poolMode === 'catalogue'
                    ? 'Full catalogue'
                    : poolMode === 'selected'
                      ? `${foods.length} selected foods`
                      : `${foods.length} excluded foods`}
                </summary>
                <fieldset
                  disabled={task.busy}
                  className="space-y-4 mt-4 min-w-0"
                >
                  <Field label="Foods to consider">
                    <select
                      className="field"
                      value={poolMode}
                      onChange={(e) => setPoolMode(e.target.value as PoolMode)}
                    >
                      <option value="catalogue">
                        All eligible catalogue foods
                      </option>
                      <option value="selected">Only foods I select</option>
                      <option value="exclude">
                        Catalogue except foods I exclude
                      </option>
                    </select>
                  </Field>
                  {poolMode !== 'catalogue' && (
                    <>
                      <p className="text-sm text-ink-3">
                        {poolMode === 'selected'
                          ? 'Choose 1–100 foods to narrow the search.'
                          : 'Choose up to 100 foods to leave out. The rest of the catalogue remains available.'}
                      </p>
                      <FoodPicker selected={foods} onChange={setFoods} />
                    </>
                  )}
                </fieldset>
              </details>
            </div>
            <Form
              busy={task.busy}
              onSubmit={() =>
                void task.run(async () => {
                  const target = ready.data?.approved_target;
                  if (!target)
                    throw new Error('Approve current targets first.');
                  const result = await api<{
                    alternatives: Plan[];
                    outcome: SearchOutcome;
                  }>('/plan-requests', {
                    ...decision(actor, 'Generate multi-item meal alternatives'),
                    target_id: target.id,
                    target_revision: target.approved_revision,
                    start_date: startDate,
                    days,
                    schedule: slots.filter((s) => counts[s] > 0),
                    items_per_slot: Object.fromEntries(
                      slots
                        .filter((s) => counts[s] > 0)
                        .map((s) => [s, counts[s]]),
                    ),
                    ...poolSelection(poolMode, foods),
                  });
                  setAlternatives(result.alternatives);
                  setPlan(result.alternatives[0] ?? null);
                  setOutcome(result.outcome);
                  setVersion((v) => v + 1);
                }, 'Search finished. Review the checked alternatives.')
              }
            >
              <Field label="Start date">
                <input
                  type="date"
                  className="field"
                  required
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                />
              </Field>
              <Field label="Number of days">
                <input
                  type="number"
                  className="field"
                  min="1"
                  max="7"
                  required
                  value={days}
                  onChange={(e) => setDays(Number(e.target.value))}
                />
              </Field>
              <fieldset>
                <legend className="font-semibold mb-3">Items per meal</legend>
                <div className="grid grid-cols-2 gap-3">
                  {slots.map((slot) => (
                    <Field
                      key={slot}
                      label={label(slot)}
                      hint="0 omits this meal"
                    >
                      <input
                        type="number"
                        className="field"
                        min="0"
                        max="5"
                        required
                        value={counts[slot]}
                        onChange={(e) =>
                          setCounts((v) => ({
                            ...v,
                            [slot]: Number(e.target.value),
                          }))
                        }
                      />
                    </Field>
                  ))}
                </div>
              </fieldset>
              <p className="text-sm text-ink-3">
                Each meal uses distinct foods with recorded portions. Every item
                is checked against mandatory restrictions and daily targets.
              </p>
              <button
                className="btn-primary"
                disabled={
                  !ready.data?.targets_ready ||
                  (poolMode === 'selected' && !foods.length) ||
                  (poolMode !== 'catalogue' && foods.length > 100) ||
                  !Object.values(counts).some(Boolean)
                }
              >
                Generate three alternatives
              </button>
            </Form>
          </div>
          {outcome != null && (
            <div className="mt-4" role="status">
              <p className="notice">
                {outcome.status === 'drafts_available'
                  ? 'Checked alternatives are ready below for review.'
                  : outcome.status === 'blocked'
                    ? 'The planner needs more information or eligible foods before it can build a plan.'
                    : 'No valid alternative was found in this bounded search. This does not prove that no suitable plan exists.'}
              </p>
              {outcome.pool_food_count != null && (
                <p className="text-sm text-ink-3 mt-2">
                  {outcome.pool_food_count} foods considered
                  {outcome.eligible_food_count != null
                    ? ` · ${outcome.eligible_food_count} passed food eligibility checks`
                    : ''}
                  .
                  {outcome.shortlisted
                    ? ' A ranked shortlist was used to keep the search bounded.'
                    : ''}
                </p>
              )}
              {outcome.blockers && (
                <ul className="list-disc pl-5 mt-2">
                  {outcome.blockers.map((issue) => (
                    <li key={issue}>{issue}</li>
                  ))}
                </ul>
              )}
              <Details title="Search outcome and exclusions" value={outcome} />
            </div>
          )}
        </Panel>
      )}
      {actor.role === 'clinician' && (
        <p className="notice mb-6">
          Review patient-requested plans and approve a checked alternative.
          Generation and substitution requests are in the patient workspace.
        </p>
      )}
      {!!alternatives.length && (
        <div
          className="flex flex-wrap gap-3 mb-6"
          role="group"
          aria-label="Plan alternatives"
        >
          {alternatives.map((p) => (
            <button
              key={p.id}
              className={plan?.id === p.id ? 'btn-primary' : 'btn-ghost'}
              aria-pressed={plan?.id === p.id}
              disabled={task.busy}
              onClick={() =>
                void task.run(
                  async () => setPlan(await api<Plan>(`/plans/${p.id}`)),
                  '',
                )
              }
            >
              {label(p.objective)}
            </button>
          ))}
        </div>
      )}
      {plan && (
        <PlanDetail
          key={`${plan.id}-${plan.approved_at}-${plan.needs_review}`}
          plan={plan}
          pool={foods}
          poolMode={poolMode}
          onChanged={changed}
        />
      )}
      <Panel title="Saved plans">
        <ListFilter
          name="saved plans"
          query={query}
          onQuery={setQuery}
          status={status}
          onStatus={setStatus}
          shown={visiblePlans.length}
          total={saved.data?.length ?? 0}
          statuses={[
            { value: 'draft', label: 'Draft' },
            { value: 'approved', label: 'Approved' },
            { value: 'review', label: 'Review required' },
          ]}
        />
        {saved.loading ? (
          <p role="status">Loading plans…</p>
        ) : saved.error ? (
          <Empty>
            Plans could not be loaded.{' '}
            <button
              className="btn-ghost"
              onClick={() => setVersion((v) => v + 1)}
            >
              Retry plans
            </button>
          </Empty>
        ) : !visiblePlans.length ? (
          <Empty>
            {saved.data?.length
              ? 'No plans match these filters.'
              : 'No plans saved yet.'}
          </Empty>
        ) : (
          <ul className="divide-y divide-rule">
            {visiblePlans.map((p) => (
              <li key={p.id} className="flex flex-wrap items-center gap-3 py-3">
                <span className="flex-1">
                  <span className="capitalize">{label(p.objective)}</span>
                  <span className="block text-sm text-ink-3">
                    {p.start_date} · {p.id.slice(0, 8)}
                  </span>
                </span>
                <span
                  className={`flag ${p.needs_review ? 'flag-warn' : p.approved_at ? 'flag-ok' : 'flag-neutral'}`}
                >
                  {p.needs_review
                    ? 'Review required'
                    : p.approved_at
                      ? 'Approved'
                      : 'Draft'}
                </span>
                <button
                  className="btn-ghost"
                  disabled={task.busy}
                  onClick={() =>
                    void task.run(
                      async () => setPlan(await api<Plan>(`/plans/${p.id}`)),
                      '',
                    )
                  }
                >
                  Open plan
                </button>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </>
  );
}

function PlanDetail({
  plan,
  pool,
  poolMode,
  onChanged,
}: {
  plan: Plan;
  pool: Food[];
  poolMode: PoolMode;
  onChanged: (p: Plan) => void;
}) {
  const { actor } = useSession();
  const task = useTask();
  const [note, setNote] = useState('');
  const [selected, setSelected] = useState<Meal | null>(null);
  const [recommendations, setRecommendations] = useState<
    Recommendation[] | null
  >(null);
  const [report, setReport] = useState<unknown>(null);
  const estimatedFoods = Array.from(
    new Map(
      plan.body.meals
        .filter((meal) => Object.keys(foodEstimates(meal.food)).length)
        .map((meal) => [
          meal.food_id,
          { name: meal.food.name, estimates: foodEstimates(meal.food) },
        ]),
    ).values(),
  );
  return (
    <Panel title={`${label(plan.objective)} · ${plan.request.start_date}`}>
      <Feedback task={task} />
      <p
        className={`notice mb-4 ${plan.needs_review || !plan.body.check.valid ? 'notice-warn' : ''}`}
      >
        {plan.needs_review
          ? 'Review required. Historical meals remain viewable; request a new plan from current targets.'
          : plan.approved_at
            ? 'Clinician-approved plan.'
            : plan.body.check.valid
              ? 'Checked draft. Clinician approval is required.'
              : 'Unmet draft. This plan cannot be approved.'}
      </p>
      {estimatedFoods.length > 0 && (
        <div className="mb-4">
          <p className="notice notice-warn">
            Uses estimated food composition. Totals and target checks include
            approximations, not verified measurements.
          </p>
          <Details title="Food estimates and methods" value={estimatedFoods} />
        </div>
      )}
      {!plan.body.check.valid && (
        <Details title="Unmet constraints" value={plan.body.check.violations} />
      )}
      {Object.entries(plan.body.check.daily_totals).map(([day, totals]) => (
        <section key={day} className="border-t border-rule pt-5 mt-5">
          <div className="flex flex-wrap gap-4 justify-between mb-4">
            <h3 className="font-bold text-lg">Day {day}</h3>
            <Totals values={totals} />
          </div>
          {plan.request.schedule.map((slot) => (
            <section key={slot} className="py-3">
              <h4 className="font-semibold capitalize mb-2">{slot}</h4>
              {plan.body.check.meal_totals?.[day]?.[slot] && (
                <Totals values={plan.body.check.meal_totals[day][slot]} />
              )}
              <ul className="divide-y divide-rule">
                {plan.body.meals
                  .filter((m) => m.day === Number(day) && m.slot === slot)
                  .map((m) => (
                    <li
                      key={m.item ?? 1}
                      className="flex flex-wrap items-center justify-between gap-3 py-3"
                    >
                      <div>
                        <span className="font-medium">{m.food.name}</span>
                        <p className="text-sm text-ink-3">
                          Item {m.item ?? 1} · {quantity(m.quantity)} {m.unit} ·{' '}
                          {m.scale} ×{' '}
                          {
                            m.food.portions.find((p) => p.id === m.portion_id)
                              ?.label
                          }
                        </p>
                      </div>
                      {actor.role === 'patient' &&
                        plan.approved_at &&
                        !plan.needs_review && (
                          <button
                            className="btn-ghost"
                            disabled={
                              task.busy ||
                              (poolMode === 'selected' && !pool.length) ||
                              (poolMode !== 'catalogue' && pool.length > 100)
                            }
                            onClick={() =>
                              void task.run(async () => {
                                const result = await api<{
                                  recommendations: Recommendation[];
                                }>(
                                  `/plans/${plan.id}/substitution-recommendations`,
                                  {
                                    ...decision(
                                      actor,
                                      'Find an item replacement',
                                    ),
                                    day: m.day,
                                    slot: m.slot,
                                    item: m.item ?? 1,
                                    ...poolSelection(poolMode, pool),
                                  },
                                );
                                setSelected(m);
                                setRecommendations(result.recommendations);
                                setReport(result);
                              }, '')
                            }
                          >
                            Find replacement for item {m.item ?? 1}
                          </button>
                        )}
                    </li>
                  ))}
              </ul>
            </section>
          ))}
        </section>
      ))}
      {recommendations && selected && (
        <section className="border-t border-rule pt-5 mt-5">
          <h3 className="font-bold mb-3">
            Replace {selected.food.name} · day {selected.day}, {selected.slot}
          </h3>
          {!recommendations.length && (
            <Empty>
              No checked replacements in this pool. Expand the pool or inspect
              the exclusions.
            </Empty>
          )}
          {recommendations.map((r) => (
            <div key={r.food_id} className="border-b border-rule py-3">
              <h4 className="font-semibold">{r.name}</h4>
              <p className="text-sm mb-2">
                {quantity(r.quantity)} {r.unit} · Energy change{' '}
                {quantity(r.nutrient_delta.energy)} kcal · Sodium change{' '}
                {quantity(r.nutrient_delta.sodium)} mg
              </p>
              <button
                className="btn-primary"
                disabled={task.busy}
                onClick={() =>
                  void task.run(
                    async () =>
                      onChanged(
                        await api<Plan>(`/plans/${plan.id}/substitutions`, {
                          ...decision(
                            actor,
                            'Request checked item substitution',
                          ),
                          ...r.substitution,
                        }),
                      ),
                    'Substitution draft created for clinician approval.',
                  )
                }
              >
                Create substitution draft
              </button>
            </div>
          ))}
          <Details title="Retrieval and check details" value={report} />
        </section>
      )}
      {!plan.approved_at &&
        !plan.needs_review &&
        plan.body.check.valid &&
        actor.role === 'clinician' && (
          <Form
            busy={task.busy}
            onSubmit={() =>
              void task.run(
                async () =>
                  onChanged(
                    await api<Plan>(`/plans/${plan.id}/approval`, {
                      ...decision(actor, note),
                      review_note: note,
                    }),
                  ),
                'Plan approved.',
              )
            }
          >
            <Field label="Plan review note">
              <textarea
                className="field mt-4"
                required
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
            </Field>
            <button className="btn-approve">Approve this plan</button>
          </Form>
        )}
      {plan.approved_at && (
        <Link
          className="btn-primary mt-5"
          to={`${actor.role === 'clinician' ? paths.intakeReview : paths.mealLog}?plan=${plan.id}`}
        >
          {actor.role === 'clinician'
            ? 'Review recorded intake'
            : 'Log this plan'}
        </Link>
      )}
    </Panel>
  );
}
