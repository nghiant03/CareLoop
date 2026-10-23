import { useState } from 'react';
import {
  api,
  label,
  units,
  type Action,
  type Facts,
  type Patient,
  type Target,
} from '../api';
import { Details, Empty, Feedback, Field, Form, Panel } from '../components/shared';
import { decision, useResource, useSession, useTask } from '../state';

export default function Patients() {
  const { actor, patientId, refreshPatients } = useSession();
  const [version, setVersion] = useState(0);
  const [creating, setCreating] = useState(false);
  const patient = useResource<Patient>(
    patientId ? `/patients/${patientId}` : null,
    version,
  );
  const targets = useResource<Target[]>(
    patientId ? `/patients/${patientId}/targets` : null,
    version,
  );
  const [target, setTarget] = useState<Target | null>(null);
  const task = useTask();
  const refresh = () => {
    setVersion((v) => v + 1);
    refreshPatients();
  };
  return (
    <>
      <Feedback task={task} error={patient.error || targets.error} />
      <div className="flex flex-wrap gap-3 mb-6">
        <button
          className="btn-primary"
          disabled={actor.role !== 'clinician'}
          onClick={() => setCreating((v) => !v)}
        >
          {creating ? 'Close new patient' : 'Add patient'}
        </button>
        <label className="btn-ghost cursor-pointer">
          Import patient CSV
          <input
            type="file"
            accept=".csv,text/csv"
            className="sr-only"
            disabled={actor.role !== 'clinician' || task.busy}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file)
                void task.run(async () => {
                  if (file.size > 5_000_000)
                    throw new Error('CSV must be at most 5 MB.');
                  await api('/patients/import-csv', {
                    ...decision(actor, 'Patient CSV import'),
                    content: await file.text(),
                  });
                  refresh();
                });
              e.target.value = '';
            }}
          />
        </label>
      </div>
      {creating && (
        <PatientEditor
          key="new"
          onSaved={() => {
            setCreating(false);
            refresh();
          }}
        />
      )}
      {patient.loading && <p role="status">Loading patient…</p>}
      {!patientId && !creating && (
        <Empty>
          Select a patient above, add one manually, or import a patient CSV.
        </Empty>
      )}
      {patient.data && (
        <PatientEditor
          key={`${patientId}-${patient.data.latest_revision}`}
          patient={patient.data}
          onSaved={refresh}
        />
      )}
      {patient.data && (
        <Panel title="Reviewed targets">
          <p className="text-ink-3 mb-4">
            Propose targets from published rules, resolve missing facts, then
            complete and approve the selected revision.
          </p>
          <button
            className="btn-primary mb-4"
            disabled={task.busy || actor.role !== 'clinician'}
            onClick={() =>
              void task.run(async () => {
                const result = await api<Target>(
                  `/patients/${patientId}/targets`,
                  {
                    ...decision(actor, 'Propose targets from current evidence'),
                    expected_patient_revision: patient.data!.latest_revision,
                  },
                );
                setTarget(result);
                setVersion((v) => v + 1);
              }, 'Target proposal created.')
            }
          >
            Propose current targets
          </button>
          <ul className="divide-y divide-rule">
            {targets.data?.map((t) => (
              <li key={t.id} className="flex flex-wrap items-center gap-3 py-3">
                <span
                  className={`flag ${t.needs_review ? 'flag-warn' : t.approved_revision ? 'flag-ok' : 'flag-neutral'}`}
                >
                  {t.needs_review
                    ? 'Review required'
                    : t.approved_revision
                      ? 'Approved'
                      : 'Draft'}
                </span>
                <span className="text-sm">Revision {t.latest_revision}</span>
                <button
                  className="btn-ghost"
                  disabled={task.busy}
                  onClick={() =>
                    void task.run(
                      async () =>
                        setTarget(await api<Target>(`/targets/${t.id}`)),
                      '',
                    )
                  }
                >
                  Open target set
                </button>
              </li>
            ))}
          </ul>
          {targets.data?.length === 0 && <Empty>No target sets yet.</Empty>}
        </Panel>
      )}
      {target && (
        <TargetEditor
          key={`${target.id}-${target.latest_revision}-${target.approved_revision}`}
          target={target}
          onSaved={(t) => {
            setTarget(t);
            setVersion((v) => v + 1);
          }}
        />
      )}
    </>
  );
}

function PatientEditor({
  patient,
  onSaved,
}: {
  patient?: Patient;
  onSaved: () => void;
}) {
  const { actor } = useSession();
  const [name, setName] = useState(patient?.body.display_name ?? '');
  const [facts, setFacts] = useState<Facts>(patient?.body.facts ?? {});
  const [listInputs, setListInputs] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      ['conditions', 'medications', 'allergies', 'dislikes'].map((key) => [
        key,
        (patient?.body.facts[key] as string[] | null)?.join(', ') ?? '',
      ]),
    ),
  );
  const [reason, setReason] = useState('');
  const task = useTask();
  const set = (key: string, value: Facts[string]) =>
    setFacts((v) => ({ ...v, [key]: value }));
  return (
    <Panel
      title={
        patient
          ? `${patient.body.display_name} · revision ${patient.latest_revision}`
          : 'New patient'
      }
    >
      <Feedback task={task} />
      <Form
        busy={task.busy || actor.role !== 'clinician'}
        onSubmit={() =>
          void task.run(async () => {
            await api(
              patient ? `/patients/${patient.id}/revisions` : '/patients',
              {
                ...decision(actor, reason),
                ...(patient
                  ? { expected_revision: patient.latest_revision }
                  : {}),
                body: {
                  display_name: name,
                  facts,
                  provenance: {
                    kind: 'manual',
                    source: 'Clinician entry',
                    notes: reason,
                  },
                },
              },
            );
            onSaved();
          })
        }
      >
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Display name">
            <input
              className="field"
              required
              maxLength={200}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </Field>
          {[
            ['age_years', 'Age (years)', 2, 120],
            ['weight_kg', 'Weight (kg)', 0.01, 700],
            ['height_cm', 'Height (cm)', 0.01, 300],
            ['egfr', 'eGFR', 0, 250],
          ].map(([key, title, min, max]) => (
            <Field key={key} label={String(title)}>
              <input
                className="field"
                type="number"
                step="any"
                min={Number(min)}
                max={Number(max)}
                placeholder="Unknown"
                value={String(facts[String(key)] ?? '')}
                onChange={(e) =>
                  set(
                    String(key),
                    e.target.value === '' ? null : Number(e.target.value),
                  )
                }
              />
            </Field>
          ))}
          <Field label="Observation date">
            <input
              className="field"
              type="date"
              value={String(facts.observed_on ?? '')}
              onChange={(e) => set('observed_on', e.target.value || null)}
            />
          </Field>
          <Field label="Sex">
            <select
              className="field"
              value={String(facts.sex ?? '')}
              onChange={(e) => set('sex', e.target.value || null)}
            >
              <option value="">Unknown</option>
              {['female', 'male', 'other'].map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </Field>
          <Field label="CKD stage">
            <select
              className="field"
              value={String(facts.ckd_stage ?? '')}
              onChange={(e) => set('ckd_stage', e.target.value || null)}
            >
              <option value="">Unknown</option>
              {['G1', 'G2', 'G3a', 'G3b', 'G4', 'G5'].map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </Field>
          {[
            'pregnant',
            'breastfeeding',
            'dialysis',
            'vegetarian',
            'include_eggs',
            'include_dairy',
          ].map((key) => (
            <Field key={key} label={label(key)}>
              <select
                className="field"
                value={facts[key] == null ? '' : String(facts[key])}
                onChange={(e) =>
                  set(
                    key,
                    e.target.value === '' ? null : e.target.value === 'true',
                  )
                }
              >
                <option value="">Unknown</option>
                <option value="true">Yes</option>
                <option value="false">No</option>
              </select>
            </Field>
          ))}
        </div>
        <details>
          <summary className="cursor-pointer font-semibold text-line">
            Conditions, medicines, allergies and preferences
          </summary>
          <div className="grid gap-4 sm:grid-cols-2 mt-4">
            {['conditions', 'medications', 'allergies', 'dislikes'].map(
              (key) => (
                <div key={key}>
                  <Field label={`${label(key)} status`}>
                    <select
                      className="field mb-2"
                      value={facts[key] == null ? 'unknown' : 'recorded'}
                      onChange={(e) => {
                        set(key, e.target.value === 'unknown' ? null : []);
                        setListInputs((v) => ({ ...v, [key]: '' }));
                      }}
                    >
                      <option value="unknown">Unknown</option>
                      <option value="recorded">
                        Recorded (empty means none)
                      </option>
                    </select>
                  </Field>
                  {facts[key] != null && (
                    <Field label={`${label(key)} (comma-separated)`}>
                      <input
                        className="field"
                        value={listInputs[key]}
                        onChange={(e) => {
                          setListInputs((v) => ({
                            ...v,
                            [key]: e.target.value,
                          }));
                          set(
                            key,
                            e.target.value
                              .split(',')
                              .map((s) => s.trim())
                              .filter(Boolean),
                          );
                        }}
                      />
                    </Field>
                  )}
                </div>
              ),
            )}
          </div>
        </details>
        <Field label="Reason and observation provenance">
          <textarea
            className="field"
            required
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </Field>
        <button className="btn-primary">
          {patient ? 'Save patient revision' : 'Create patient'}
        </button>
      </Form>
      {actor.role !== 'clinician' && (
        <p className="text-sm text-ink-3 mt-3">
          Switch to the clinician demo role to edit patient facts or approve
          targets.
        </p>
      )}
    </Panel>
  );
}

function TargetEditor({
  target,
  onSaved,
}: {
  target: Target;
  onSaved: (t: Target) => void;
}) {
  const { actor } = useSession();
  const task = useTask();
  const [reason, setReason] = useState('');
  const storedSelection = target.body.items.flatMap((item) =>
    item.rule ? [item.rule.rule_id] : [],
  );
  const storedDispositions = Object.fromEntries(
    (target.body.dispositions ?? []).map((d) => [d.rule.rule_id, d.reason]),
  );
  const [selected, setSelected] = useState<string[]>(storedSelection);
  const [dispositions, setDispositions] =
    useState<Record<string, string>>(storedDispositions);
  const [manual, setManual] = useState<
    Array<{ action: Action; rationale: string }>
  >(
    target.body.items
      .filter((i) => i.origin === 'clinician')
      .map((i) => ({ action: i.action, rationale: i.rationale ?? '' })),
  );
  const locked =
    actor.role !== 'clinician' ||
    !!target.approved_revision ||
    target.needs_review;
  const dirty =
    JSON.stringify([...selected].sort()) !==
      JSON.stringify([...storedSelection].sort()) ||
    JSON.stringify(dispositions) !== JSON.stringify(storedDispositions) ||
    JSON.stringify(manual) !==
      JSON.stringify(
        target.body.items
          .filter((i) => i.origin === 'clinician')
          .map((i) => ({ action: i.action, rationale: i.rationale ?? '' })),
      );
  return (
    <Panel title={`Target set · revision ${target.latest_revision}`}>
      <Feedback task={task} />
      {target.needs_review && (
        <p className="notice notice-warn mb-4">
          This target set needs review. Create a new proposal from current facts
          and evidence.
        </p>
      )}
      <ul className="divide-y divide-rule mb-4">
        {target.body.items.map((item, i) => (
          <li key={i} className="py-3">
            <strong className="capitalize">{label(item.action.subject)}</strong>{' '}
            · {label(item.action.kind)} {item.action.amount ?? ''}
            {item.action.upper != null ? `–${item.action.upper}` : ''}{' '}
            {item.action.unit}
            <p className="text-sm text-ink-3">
              {item.origin === 'clinician'
                ? `Clinician-authored: ${item.author}`
                : 'Evidence-derived'}{' '}
              · {item.action.advice}
            </p>
            {item.citation && (
              <blockquote className="mt-2 text-sm">
                {item.citation.quote} — {item.citation.location}
              </blockquote>
            )}
          </li>
        ))}
      </ul>
      {!!target.body.blockers.length && (
        <Details
          title={`${target.body.blockers.length} issues to resolve`}
          value={target.body.blockers}
        />
      )}
      <Form
        busy={task.busy || locked}
        onSubmit={() =>
          void task.run(async () => {
            const result = await api<Target>(
              `/targets/${target.id}/revisions`,
              {
                ...decision(actor, reason),
                expected_revision: target.latest_revision,
                selected: target.evaluation
                  .filter(
                    (e) =>
                      selected.includes(e.rule_id) && e.status === 'applicable',
                  )
                  .map(({ rule_id, revision }) => ({ rule_id, revision })),
                manual,
                dispositions: target.evaluation
                  .filter(
                    (e) =>
                      ['applicable', 'needs_clinician'].includes(e.status) &&
                      !selected.includes(e.rule_id),
                  )
                  .map((e) => ({
                    rule: { rule_id: e.rule_id, revision: e.revision },
                    reason: dispositions[e.rule_id] || '',
                  })),
              },
            );
            onSaved(result);
          })
        }
      >
        {target.evaluation.map((e) => (
          <div key={e.rule_id} className="border-b border-rule pb-3">
            <label className="flex gap-2">
              <input
                type="checkbox"
                disabled={e.status !== 'applicable'}
                checked={selected.includes(e.rule_id)}
                onChange={(event) =>
                  setSelected((s) =>
                    event.target.checked
                      ? [...s, e.rule_id]
                      : s.filter((id) => id !== e.rule_id),
                  )
                }
              />
              <span>
                {label(e.source_action.subject)} · {label(e.status)}
              </span>
            </label>
            <p className="text-sm text-ink-3 mt-1">{e.citation.quote}</p>
            {e.missing.length > 0 && (
              <p className="text-sm text-warn">
                Clarify: {e.missing.join(', ')}
              </p>
            )}
            {['applicable', 'needs_clinician'].includes(e.status) &&
              !selected.includes(e.rule_id) && (
                <Field label="Reason for not selecting this rule">
                  <input
                    className="field"
                    required
                    value={dispositions[e.rule_id] ?? ''}
                    onChange={(event) =>
                      setDispositions((v) => ({
                        ...v,
                        [e.rule_id]: event.target.value,
                      }))
                    }
                  />
                </Field>
              )}
          </div>
        ))}
        {manual.map((item, index) => (
          <div key={index} className="border-t border-rule pt-4">
            <ActionFields
              action={item.action}
              onChange={(action) =>
                setManual((list) =>
                  list.map((v, i) => (i === index ? { ...v, action } : v)),
                )
              }
            />
            <Field label="Clinical rationale">
              <input
                className="field mt-2"
                required
                value={item.rationale}
                onChange={(e) =>
                  setManual((list) =>
                    list.map((v, i) =>
                      i === index ? { ...v, rationale: e.target.value } : v,
                    ),
                  )
                }
              />
            </Field>
            <button
              type="button"
              className="btn-ghost mt-2"
              onClick={() =>
                setManual((list) => list.filter((_, i) => i !== index))
              }
            >
              Remove target
            </button>
          </div>
        ))}
        <button
          type="button"
          className="btn-ghost"
          onClick={() =>
            setManual((list) => [
              ...list,
              {
                action: {
                  kind: 'range',
                  subject: 'energy',
                  amount: null,
                  upper: null,
                  unit: 'kcal/day',
                  advice: '',
                },
                rationale: '',
              },
            ])
          }
        >
          Add clinician-authored target
        </button>
        <Field label="Review reason">
          <textarea
            className="field"
            required
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </Field>
        <button className="btn-primary">Save target revision</button>
        <button
          type="button"
          className="btn-approve ml-3"
          disabled={dirty || !reason.trim() || !!target.body.blockers.length}
          onClick={() =>
            void task.run(
              async () =>
                onSaved(
                  await api<Target>(`/targets/${target.id}/approval`, {
                    ...decision(actor, reason),
                    expected_revision: target.latest_revision,
                    completeness_note: reason,
                  }),
                ),
              'Stored target revision approved.',
            )
          }
        >
          Approve stored revision
        </button>
        <p className="text-sm text-ink-3">
          Save edits before approval. Approval applies to the stored revision
          shown above.
        </p>
      </Form>
    </Panel>
  );
}

export function ActionFields({
  action,
  onChange,
  evidence = false,
}: {
  action: Action;
  onChange: (a: Action) => void;
  evidence?: boolean;
}) {
  const numeric = ['range', 'ceiling', 'intake', 'additional'].includes(
    action.kind,
  );
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <Field label={numeric ? 'Nutrient' : 'Subject'}>
        {numeric ? (
          <select
            className="field"
            value={action.subject}
            onChange={(e) =>
              onChange({
                ...action,
                subject: e.target.value,
                unit: units[e.target.value],
              })
            }
          >
            {!units[action.subject] && (
              <option value={action.subject}>{action.subject}</option>
            )}
            {Object.keys(units).map((key) => (
              <option key={key} value={key}>
                {label(key)}
              </option>
            ))}
          </select>
        ) : (
          <input
            className="field"
            required
            value={action.subject}
            onChange={(e) => onChange({ ...action, subject: e.target.value })}
          />
        )}
      </Field>
      <Field label="Target type">
        <select
          className="field"
          value={action.kind}
          onChange={(e) => {
            const numeric = [
              'range',
              'ceiling',
              'intake',
              'additional',
            ].includes(e.target.value);
            onChange({
              ...action,
              kind: e.target.value,
              amount: numeric ? (action.amount ?? null) : null,
              unit: numeric ? (units[action.subject] ?? 'g/day') : null,
              upper: e.target.value === 'range' ? (action.upper ?? null) : null,
            });
          }}
        >
          {[
            'range',
            'ceiling',
            'intake',
            'exclusion',
            'timing',
            ...(evidence ? ['additional', 'assessment'] : []),
          ].map((key) => (
            <option key={key}>{key}</option>
          ))}
        </select>
      </Field>
      {numeric && (
        <Field label={`Amount (${action.unit})`}>
          <input
            type="number"
            min="0"
            step="any"
            className="field"
            required
            value={action.amount ?? ''}
            onChange={(e) =>
              onChange({
                ...action,
                amount: e.target.value === '' ? null : Number(e.target.value),
              })
            }
          />
        </Field>
      )}
      {action.kind === 'range' && (
        <Field label="Upper amount">
          <input
            type="number"
            min={action.amount ?? 0}
            step="any"
            className="field"
            required
            value={action.upper ?? ''}
            onChange={(e) =>
              onChange({
                ...action,
                upper: e.target.value === '' ? null : Number(e.target.value),
              })
            }
          />
        </Field>
      )}
      {numeric && evidence && (
        <Field label="Source unit">
          <input
            className="field"
            required
            value={action.unit ?? ''}
            onChange={(e) => onChange({ ...action, unit: e.target.value })}
          />
        </Field>
      )}
      <div className="sm:col-span-2 lg:col-span-4">
        <Field label="Advice">
          <input
            className="field"
            required
            value={action.advice}
            onChange={(e) => onChange({ ...action, advice: e.target.value })}
          />
        </Field>
      </div>
    </div>
  );
}
