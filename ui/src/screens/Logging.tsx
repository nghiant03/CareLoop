import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  api,
  label,
  localDate,
  quantity,
  type Day,
  type Food,
  type Log,
  type Meal,
  type Plan,
} from '../api';
import {
  Details,
  Empty,
  Feedback,
  Field,
  FoodPicker,
  Form,
  Panel,
  Totals,
} from '../components/shared';
import { decision, useResource, useSession, useTask } from '../state';

export default function Logging() {
  const { actor, patientId } = useSession();
  const canLog = actor.role === 'patient';
  const [entryHistory, setEntryHistory] = useState<unknown>(null);
  const [params] = useSearchParams();
  const [date, setDate] = useState(localDate);
  const [planId, setPlanId] = useState(params.get('plan') ?? '');
  const [version, setVersion] = useState(0);
  const [editor, setEditor] = useState<{ meal?: Meal; entry?: Log } | null>(
    null,
  );
  const task = useTask();
  const saved = useResource<Plan[]>(
    patientId ? `/patients/${patientId}/plans` : null,
    0,
    true,
  );
  const permittedPlan = saved.data?.some(
    (p) => p.id === planId && p.approved_at,
  )
    ? planId
    : '';
  const plan = useResource<Plan>(
    permittedPlan ? `/plans/${permittedPlan}` : null,
  );
  const dayPath = `/patients/${patientId}/meal-log-days/${date}`;
  const summary = useResource<Day>(
    patientId && date
      ? `${dayPath}${permittedPlan ? `?plan_id=${permittedPlan}` : ''}`
      : null,
    version,
  );
  const comparison = useResource<{
    target_needs_review: boolean;
    comparisons: Array<{
      target_item: { action: { subject: string; unit: string } };
      recorded: string | null;
      status: string;
    }>;
  }>(
    plan.data && date
      ? `${dayPath}/target-comparison?target_id=${plan.data.target_id}`
      : null,
    version,
  );
  if (!patientId)
    return (
      <Empty>Select a patient to log intake and review daily totals.</Empty>
    );
  const refresh = () => {
    setVersion((v) => v + 1);
    setEditor(null);
  };
  const number =
    plan.data && date
      ? Math.round(
          (Date.parse(date) - Date.parse(plan.data.request.start_date)) /
            86400000,
        ) + 1
      : 0;
  const meals = plan.data?.body.meals.filter((m) => m.day === number) ?? [];
  return (
    <>
      <Feedback
        task={task}
        error={saved.error || plan.error || summary.error}
      />
      <Panel title={canLog ? 'Record your meals' : 'Review patient intake'}>
        <div className="grid gap-4 sm:grid-cols-2 mb-4">
          <Field label="Date">
            <input
              type="date"
              className="field"
              required
              value={date}
              onChange={(e) => {
                setDate(e.target.value);
                setEditor(null);
                setEntryHistory(null);
              }}
            />
          </Field>
          <Field label="Approved plan">
            <select
              className="field"
              value={permittedPlan}
              onChange={(e) => {
                  setPlanId(e.target.value);
                  setEditor(null);
                  setEntryHistory(null);
              }}
            >
              <option value="">Independent entries only</option>
              {saved.data
                ?.filter((p) => p.approved_at)
                .map((p) => (
                  <option key={p.id} value={p.id}>
                    {label(p.objective)} · {p.id.slice(0, 8)}
                    {p.needs_review ? ' · historical / review required' : ''}
                  </option>
                ))}
            </select>
          </Field>
        </div>
        {plan.data?.needs_review && (
          <p className="notice notice-warn mb-4">
            This historical plan needs review. Recorded intake remains
            historical; logging does not approve the plan again.
          </p>
        )}
        {plan.data && !meals.length && (
          <p className="text-ink-3">
            No scheduled meals on this date. This plan begins{' '}
            {plan.data.request.start_date} and covers {plan.data.request.days}{' '}
            days.
          </p>
        )}
        {plan.data?.request.schedule.map((slot) => {
          const items = meals.filter((m) => m.slot === slot);
          if (!items.length) return null;
          return (
            <section key={slot} className="border-t border-rule py-4">
              <div className="flex flex-wrap items-center gap-3 justify-between mb-3">
                <h3 className="font-bold capitalize">{slot}</h3>
                <div className="flex flex-wrap gap-2">
                  {canLog &&
                    ['as_planned', 'skipped'].map((status) => (
                      <button
                        key={status}
                        className="btn-ghost"
                        disabled={task.busy || actor.role === 'reviewer'}
                        onClick={() =>
                          void task.run(async () => {
                            await api(
                              `/patients/${patientId}/meal-log-confirmations`,
                              {
                                ...decision(actor, 'Record whole-meal intake'),
                                plan_id: permittedPlan,
                                logged_on: date,
                                slot,
                                status,
                              },
                            );
                            refresh();
                          })
                        }
                      >
                        {status === 'as_planned'
                          ? 'Confirm whole meal'
                          : 'Skip whole meal'}
                      </button>
                    ))}
                </div>
              </div>
              <ul className="divide-y divide-rule">
                {items.map((meal) => {
                  const logged = summary.data?.entries.find(
                    (e) =>
                      e.body.plan_id === permittedPlan &&
                      e.body.slot === slot &&
                      (e.body.item ?? 1) === (meal.item ?? 1),
                  );
                  return (
                    <li
                      key={meal.item ?? 1}
                      className="flex flex-wrap justify-between gap-3 items-center py-3"
                    >
                      <div>
                        <p className="font-medium">{meal.food.name}</p>
                        <p className="text-sm text-ink-3">
                          Item {meal.item ?? 1} · {quantity(meal.quantity)}{' '}
                          {meal.unit} ·{' '}
                          {logged ? label(logged.body.status) : 'Unlogged'}
                        </p>
                      </div>
                      {canLog && (
                        <button
                          className="btn-ghost"
                          onClick={() => setEditor({ meal, entry: logged })}
                        >
                          {logged ? 'Correct entry' : 'Record item'}
                        </button>
                      )}
                    </li>
                  );
                })}
              </ul>
            </section>
          );
        })}
        {canLog && (
          <button
            className="btn-primary mt-4"
            disabled={!date || actor.role === 'reviewer'}
            onClick={() => setEditor({})}
          >
            Add independent food entry
          </button>
        )}
      </Panel>
      {canLog && editor && (
        <LogEditor
          key={`${date}-${editor.entry?.id ?? 'new'}-${editor.meal?.slot ?? ''}-${editor.meal?.item ?? ''}`}
          date={date}
          planId={
            editor.entry?.body.plan_id ?? (editor.meal ? permittedPlan : null)
          }
          meal={editor.meal}
          entry={editor.entry}
          onSaved={refresh}
          onCancel={() => setEditor(null)}
        />
      )}
      <Panel title="Recorded intake">
        <Feedback error={comparison.error} />
        {summary.loading ? (
          <p role="status">Loading daily intake…</p>
        ) : (
          summary.data && (
            <>
              <div className="flex flex-wrap justify-between gap-4 mb-5">
                <Totals values={summary.data.recorded_totals} />
                <span
                  className={`flag ${summary.data.complete ? 'flag-ok' : 'flag-neutral'}`}
                >
                  {summary.data.complete
                    ? 'Day marked complete'
                    : 'Partial day'}
                </span>
              </div>
              {!summary.data.entries.length ? (
                <Empty>
                  No intake recorded on this date. Unlogged meals are not
                  skipped meals.
                </Empty>
              ) : (
                <ul className="divide-y divide-rule">
                  {summary.data.entries.map((entry) => (
                    <li
                      key={entry.id}
                      className="flex flex-wrap items-center justify-between gap-3 py-3"
                    >
                      <div>
                        <strong>
                          {entry.body.consumed?.food.name ?? 'Skipped item'}
                        </strong>
                        <p className="text-sm text-ink-3">
                          {entry.body.slot} · {label(entry.body.status)} ·
                          revision {entry.latest_revision}
                        </p>
                      </div>
                      <button
                        className="btn-ghost"
                        onClick={() =>
                          canLog
                            ? setEditor({ entry })
                            : void task.run(
                                async () =>
                                  setEntryHistory(
                                    await api(
                                      `/patients/${patientId}/meal-logs/${entry.id}`,
                                    ),
                                  ),
                                '',
                              )
                        }
                      >
                        {canLog ? 'Correct entry' : 'View entry history'}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              {canLog && (
                <button
                  className="btn-ghost mt-4"
                  disabled={task.busy || actor.role === 'reviewer'}
                  onClick={() =>
                    void task.run(async () => {
                      await api(dayPath, {
                        ...decision(actor, 'Update daily logging completeness'),
                        complete: !summary.data!.complete,
                      });
                      setVersion((v) => v + 1);
                    })
                  }
                >
                  {summary.data.complete
                    ? 'Reopen this day'
                    : 'Mark day complete'}
                </button>
              )}
              <p className="text-sm text-ink-3 mt-3">
                A complete day includes all reported intake. Later entries or
                corrections reopen the day; unknown nutrient values remain
                unknown.
              </p>
            </>
          )
        )}
      </Panel>
      {entryHistory != null && (
        <Details title="Recorded entry revisions" value={entryHistory} />
      )}
      {comparison.data && (
        <Panel title="Compared with approved targets">
          {comparison.data.target_needs_review && (
            <p className="notice notice-warn mb-3">
              These historical targets need clinician review.
            </p>
          )}
          <ul className="divide-y divide-rule">
            {comparison.data.comparisons.map((item, i) => (
              <li key={i} className="py-3 flex flex-wrap gap-3 justify-between">
                <span>
                  <span className="capitalize">
                    {label(item.target_item.action.subject)}
                  </span>{' '}
                  · {quantity(item.recorded)} {item.target_item.action.unit}
                </span>
                <strong className="font-medium">{label(item.status)}</strong>
              </li>
            ))}
          </ul>
        </Panel>
      )}
    </>
  );
}

function LogEditor({
  date,
  planId,
  meal,
  entry,
  onSaved,
  onCancel,
}: {
  date: string;
  planId: string | null;
  meal?: Meal;
  entry?: Log;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const { actor, patientId } = useSession();
  const task = useTask();
  const [status, setStatus] = useState(
    entry?.body.status ?? (planId ? 'as_planned' : 'independent'),
  );
  const [slot, setSlot] = useState(entry?.body.slot ?? meal?.slot ?? 'snack');
  const [scale, setScale] = useState(
    entry?.body.scale ?? entry?.body.consumed?.scale ?? meal?.scale ?? 1,
  );
  const [note, setNote] = useState(entry?.body.note ?? '');
  const consumed = entry?.body.consumed;
  const [foods, setFoods] = useState<Food[]>(
    consumed && ['independent', 'replaced'].includes(entry?.body.status ?? '')
      ? [
          {
            id: consumed.food_id,
            latest_revision: consumed.food_revision,
            body: consumed.food,
          },
        ]
      : [],
  );
  const [portion, setPortion] = useState(consumed?.portion_id ?? '');
  const [history, setHistory] = useState<unknown>(null);
  const replacement = status === 'replaced' || status === 'independent';
  const food = foods[0];
  return (
    <Panel
      title={
        entry
          ? 'Correct recorded intake'
          : meal
            ? `Record ${meal.food.name}`
            : 'Independent food entry'
      }
    >
      <Feedback task={task} />
      {replacement && (
        <FoodPicker
          multiple={false}
          selected={foods}
          onChange={(next) => {
            setFoods(next);
            setPortion(next[0]?.body.portions[0]?.id ?? '');
          }}
        />
      )}
      <Form
        busy={task.busy || actor.role === 'reviewer'}
        onSubmit={() =>
          void task.run(async () => {
            if (replacement && (!food || !portion))
              throw new Error('Select a food and portion.');
            await api(
              `/patients/${patientId}/meal-logs${entry ? `/${entry.id}/revisions` : ''}`,
              {
                ...decision(actor, note || 'Record patient-reported intake'),
                ...(entry ? { expected_revision: entry.latest_revision } : {}),
                logged_on: date,
                plan_id: planId,
                slot,
                item: entry?.body.item ?? meal?.item ?? 1,
                status,
                note,
                ...(replacement
                  ? { food_id: food.id, portion_id: portion, scale }
                  : status === 'changed_quantity'
                    ? { scale }
                    : {}),
              },
            );
            onSaved();
          })
        }
      >
        <div className="grid gap-4 sm:grid-cols-2 mt-4">
          <Field label="Meal">
            <select
              className="field"
              disabled={!!entry || !!meal}
              value={slot}
              onChange={(e) => setSlot(e.target.value)}
            >
              {['breakfast', 'lunch', 'dinner', 'snack'].map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </Field>
          <Field label="What happened?">
            <select
              className="field"
              value={status}
              onChange={(e) => setStatus(e.target.value)}
            >
              {(planId
                ? ['as_planned', 'changed_quantity', 'replaced', 'skipped']
                : ['independent']
              ).map((s) => (
                <option key={s} value={s}>
                  {label(s)}
                </option>
              ))}
            </select>
          </Field>
          {replacement && (
            <Field label="Portion">
              <select
                className="field"
                required
                value={portion}
                onChange={(e) => setPortion(e.target.value)}
              >
                <option value="">Choose portion</option>
                {food?.body.portions.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                  </option>
                ))}
              </select>
            </Field>
          )}
          {(replacement || status === 'changed_quantity') && (
            <Field label="Portion multiplier">
              <input
                className="field"
                type="number"
                step="any"
                min="0.01"
                max="100"
                required
                value={scale}
                onChange={(e) => setScale(Number(e.target.value))}
              />
            </Field>
          )}
        </div>
        <Field label={entry ? 'Correction reason' : 'Note (optional)'}>
          <textarea
            className="field"
            required={!!entry}
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </Field>
        <div className="flex gap-3">
          <button className="btn-primary">
            {entry ? 'Save correction' : 'Record intake'}
          </button>
          <button type="button" className="btn-ghost" onClick={onCancel}>
            Cancel
          </button>
          {entry && (
            <button
              type="button"
              className="btn-ghost"
              onClick={() =>
                void task.run(
                  async () =>
                    setHistory(
                      await api(`/patients/${patientId}/meal-logs/${entry.id}`),
                    ),
                  '',
                )
              }
            >
              View history
            </button>
          )}
        </div>
      </Form>
      {history != null && (
        <Details title="Recorded revisions" value={history} />
      )}
    </Panel>
  );
}
