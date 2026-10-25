import { useState } from 'react';
import EvidenceText from '../components/EvidenceText';
import {
  api,
  label,
  units,
  type Action,
  type Facts,
  type Patient,
  type Target,
} from '../api';
import {
  Empty,
  Feedback,
  Field,
  Form,
  ListFilter,
  Panel,
} from '../components/shared';
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
  const [facts, setFacts] = useState<Facts>(() => {
    const saved = patient?.body.facts ?? {};
    return {
      ...saved,
      has_ckd: saved.has_ckd ?? (saved.ckd_stage ? true : null),
    };
  });
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
          <Field label="CKD status">
            <select
              name="has_ckd"
              className="field"
              value={facts.has_ckd == null ? '' : String(facts.has_ckd)}
              onChange={(e) => {
                const status =
                  e.target.value === '' ? null : e.target.value === 'true';
                setFacts((current) => ({
                  ...current,
                  has_ckd: status,
                  ckd_stage:
                    status === true ? (current.ckd_stage ?? null) : null,
                }));
              }}
            >
              <option value="">Unknown</option>
              <option value="true">Yes</option>
              <option value="false">No</option>
            </select>
          </Field>
          {facts.has_ckd === true && (
            <Field label="CKD stage">
              <select
                name="ckd_stage"
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
          )}
          {['dialysis', 'vegetarian'].map((key) => (
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
        <details
          key={`life-stage-${facts.sex ?? 'unknown'}`}
          open={facts.sex !== 'male'}
        >
          <summary className="cursor-pointer font-semibold text-line">
            Pregnancy and breastfeeding
            <span className="block text-sm font-normal text-ink-3 mt-1">
              Pregnant:{' '}
              {facts.pregnant == null
                ? 'Unknown'
                : facts.pregnant
                  ? 'Yes'
                  : 'No'}
              {' · '}Breastfeeding:{' '}
              {facts.breastfeeding == null
                ? 'Unknown'
                : facts.breastfeeding
                  ? 'Yes'
                  : 'No'}
            </span>
          </summary>
          <div className="grid gap-4 sm:grid-cols-2 mt-4">
            {['pregnant', 'breastfeeding'].map((key) => (
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
        </details>
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

export function TargetEditor({
  target,
  onSaved,
}: {
  target: Target;
  onSaved: (t: Target) => void;
}) {
  const { actor } = useSession();
  const task = useTask();
  const [reason, setReason] = useState('');
  const storedSelection = [
    ...target.body.items,
    ...(target.body.assessments ?? []),
    ...(target.body.guidance ?? []),
  ].flatMap((item) => (item.rule ? [item.rule.rule_id] : []));
  const storedDispositions = Object.fromEntries(
    [
      ...(target.body.dispositions ?? []),
      ...(target.body.assessments ?? []),
    ].map((d) => [d.rule.rule_id, d.reason]),
  );
  const [selected, setSelected] = useState<string[]>(storedSelection);
  const [dispositions, setDispositions] =
    useState<Record<string, string>>(storedDispositions);
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('');
  const [category, setCategory] = useState('');
  const categoryOf = (e: Target['evaluation'][number]) =>
    e.category ?? (e.status === 'needs_clinician' ? 'assessment' : 'target');
  const requiresDecision = (e: Target['evaluation'][number]) =>
    e.status === 'needs_clinician' ||
    (e.status === 'applicable' && !selected.includes(e.rule_id));
  const unresolved = target.evaluation.filter(
    (e) => requiresDecision(e) && !dispositions[e.rule_id]?.trim(),
  );
  const visible = target.evaluation.filter(
    (e) =>
      (!category || categoryOf(e) === category) &&
      (!status ||
        (status === 'selected'
          ? selected.includes(e.rule_id)
          : status === 'unresolved'
            ? unresolved.includes(e)
            : e.status === status)) &&
      `${e.source_action.subject} ${e.source_action.advice} ${e.citation.quote} ${e.citation.location} ${e.rule_id}`
        .toLowerCase()
        .includes(query.trim().toLowerCase()),
  );
  const hiddenSelected = selected.filter(
    (id) => !visible.some((e) => e.rule_id === id),
  ).length;
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
  const energyIndex = manual.findIndex(
    (item) => item.action.subject === 'energy',
  );
  const energyRule = visible.find(
    (e) =>
      e.source_action.subject === 'energy' && e.status === 'needs_clinician',
  );
  const evidenceEnergy = target.body.items.some(
    (item) =>
      item.origin !== 'clinician' &&
      item.action.subject === 'energy' &&
      item.action.kind === 'range' &&
      !!item.rule &&
      selected.includes(item.rule.rule_id),
  );
  const savedEnergy = target.body.items.some(
    (item) =>
      item.action.subject === 'energy' &&
      item.action.kind === 'range' &&
      item.action.unit === 'kcal/day' &&
      (item.action.amount ?? 0) > 0 &&
      (item.action.upper ?? 0) >= (item.action.amount ?? 0),
  );
  const energyFields = !evidenceEnergy && (
    <EnergyTargetFields
      item={energyIndex >= 0 ? manual[energyIndex] : undefined}
      proposal={target.body.energy_proposal}
      onChange={(item) =>
        setManual((list) =>
          energyIndex < 0
            ? [...list, item]
            : list.map((value, i) => (i === energyIndex ? item : value)),
        )
      }
    />
  );
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
      {!savedEnergy && (
        <p className="notice notice-warn mb-4">
          {target.approved_revision
            ? 'This approved revision has no daily energy range. Create a new proposal, enter the calorie values in Daily energy target, then save and approve.'
            : 'Enter and save a daily energy target before approval. Text in an assessment note does not set calorie values.'}
        </p>
      )}
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
            · {label(item.action.kind)}{' '}
            {item.action.upper_exclusive ? '< ' : ''}
            {item.action.amount ?? ''}
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
                <EvidenceText text={item.citation.quote} />
                <p className="text-ink-3 mt-2">{item.citation.location}</p>
              </blockquote>
            )}
          </li>
        ))}
      </ul>
      {!!target.body.blockers.length && (
        <details className="my-3">
          <summary className="cursor-pointer font-semibold">
            {target.body.blockers.length} stored issues to resolve
          </summary>
          <ul className="list-disc pl-5 mt-2">
            {target.body.blockers.map((entry, i) => {
              const issue = entry as {
                rule_id?: string;
                issue?: string;
                missing?: string[];
                issues?: string[];
              };
              const rule = target.evaluation.find(
                (e) => e.rule_id === issue.rule_id,
              );
              return (
                <li key={i}>
                  {rule ? `${label(rule.source_action.subject)}: ` : ''}
                  {issue.issue ??
                    issue.issues?.join('; ') ??
                    `Missing ${issue.missing?.map(label).join(', ')}`}
                </li>
              );
            })}
          </ul>
          <p className="text-sm text-ink-3 mt-2">
            This list reflects the saved revision. Save your decisions to update
            it.
          </p>
        </details>
      )}
      {(target.body.guidance?.length ?? 0) > 0 && (
        <details className="my-3">
          <summary className="cursor-pointer font-semibold">
            Selected advisory guidance (not planner constraints)
          </summary>
          <ul className="list-disc pl-5">
            {target.body.guidance?.map((g) => (
              <li key={g.rule.rule_id}>{g.action.advice}</li>
            ))}
          </ul>
        </details>
      )}
      <ListFilter
        name="evaluated rules"
        query={query}
        onQuery={setQuery}
        status={status}
        onStatus={setStatus}
        shown={visible.length}
        total={target.evaluation.length}
        statuses={[
          { value: 'unresolved', label: 'Decision needed' },
          { value: 'selected', label: 'Selected' },
          { value: 'applicable', label: 'Applicable target' },
          { value: 'needs_clinician', label: 'Needs clinician' },
          { value: 'advisory', label: 'Advisory guidance' },
          { value: 'incomplete', label: 'Missing information' },
          { value: 'not_applicable', label: 'Not applicable' },
          { value: 'excluded', label: 'Excluded' },
        ]}
      />
      <Field label="Rule category">
        <select
          className="field mb-3"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
        >
          <option value="">All categories</option>
          <option value="target">Executable targets</option>
          <option value="assessment">Required assessments</option>
          <option value="advisory">Advisory guidance</option>
        </select>
      </Field>
      <p className="text-sm text-ink-3 mb-4">
        {selected.length} selected · {hiddenSelected} hidden by filters ·{' '}
        {unresolved.length} decisions needed. Selection does not approve a rule.
      </p>
      {!visible.length && (
        <Empty>
          No rules match. Clear the search, status and category filters.
        </Empty>
      )}
      <Form
        busy={task.busy || locked}
        onSubmit={() =>
          void task.run(async () => {
            if (unresolved.length) {
              setQuery('');
              setStatus('unresolved');
              setCategory('');
              throw new Error(
                `Record a clinical decision for ${unresolved.length} rules before saving. They are now shown below.`,
              );
            }
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
                guidance: target.evaluation
                  .filter(
                    (e) =>
                      e.status === 'advisory' && selected.includes(e.rule_id),
                  )
                  .map(({ rule_id, revision }) => ({ rule_id, revision })),
                assessments: target.evaluation
                  .filter(
                    (e) =>
                      e.status === 'needs_clinician' &&
                      selected.includes(e.rule_id),
                  )
                  .map(({ rule_id, revision }) => ({
                    rule: { rule_id, revision },
                    reason: dispositions[rule_id] || '',
                  })),
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
        {!energyRule && energyFields}
        {visible.map((e) => (
          <div key={e.rule_id} className="border-b border-rule pb-3">
            <label className="flex gap-2">
              <input
                type="checkbox"
                disabled={
                  !['applicable', 'needs_clinician', 'advisory'].includes(
                    e.status,
                  )
                }
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
            <p className="mt-2">{e.source_action.advice}</p>
            {e.rule_id === energyRule?.rule_id && energyFields}
            {e.status === 'needs_clinician' && (
              <p className="text-sm text-ink-3 mt-2">
                Select to include this assessment in the review. Record your
                decision below; add an individual numeric target if needed.
                Selection alone does not complete the assessment.
              </p>
            )}
            {e.status === 'advisory' && (
              <p className="text-sm text-ink-3 mt-2">
                Optional counselling guidance. Selecting it includes it in the
                patient’s guidance; it does not become a planner constraint.
              </p>
            )}
            {e.review_note && (
              <p className="text-sm text-ink-3 mt-2">
                Classification: {e.review_note}
              </p>
            )}
            {e.status === 'excluded' && (
              <p className="text-sm text-ink-3 mt-2">
                A recorded patient exception excludes this rule.
              </p>
            )}
            {e.status === 'not_applicable' && (
              <p className="text-sm text-ink-3 mt-2">
                This patient does not match the rule’s population.
              </p>
            )}
            <details className="mt-2">
              <summary className="cursor-pointer text-sm font-semibold text-line">
                Supporting evidence
              </summary>
              <EvidenceText text={e.citation.quote} />
            </details>
            {e.missing.length > 0 && (
              <p className="text-sm text-warn">
                Clarify: {e.missing.join(', ')}
              </p>
            )}
            {requiresDecision(e) && (
              <Field
                label={
                  e.status === 'needs_clinician'
                    ? e.source_action.subject === 'energy'
                      ? 'Energy assessment note (not calorie values)'
                      : `Clinical decision — ${label(e.source_action.subject)}`
                    : `Reason for not selecting — ${label(e.source_action.subject)}`
                }
              >
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
        {manual.map((item, index) =>
          index === energyIndex && !evidenceEnergy ? null : (
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
          ),
        )}
        <button
          type="button"
          className="btn-ghost"
          onClick={() =>
            setManual((list) => [
              ...list,
              {
                action: {
                  kind: 'range',
                  subject: 'protein',
                  amount: null,
                  upper: null,
                  unit: 'g/day',
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
          disabled={
            dirty ||
            !reason.trim() ||
            !savedEnergy ||
            !!target.body.blockers.length
          }
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
          {dirty
            ? 'Save your edits before approving.'
            : !savedEnergy
              ? 'Approval needs a saved daily energy range.'
              : !reason.trim()
                ? 'Enter a review reason to approve the saved revision.'
                : 'Approval applies to the stored revision shown above.'}
        </p>
      </Form>
    </Panel>
  );
}

function EnergyTargetFields({
  item,
  proposal,
  onChange,
}: {
  item?: { action: Action; rationale: string };
  proposal?: Target['body']['energy_proposal'];
  onChange: (item: { action: Action; rationale: string }) => void;
}) {
  const value = item ?? {
    action: {
      kind: 'range',
      subject: 'energy',
      unit: 'kcal/day',
      amount: null,
      upper: null,
      advice: 'Individual daily energy prescription.',
    },
    rationale: '',
  };
  return (
    <fieldset className="my-4 space-y-3">
      <legend className="font-semibold">Daily energy target</legend>
      <p className="text-sm text-ink-3">
        Enter the calorie range here. These numbers are used for meal planning.
        Both values are required for approval.
      </p>
      {proposal && (
        <section aria-label="Energy starting estimate" className="space-y-2">
          <p>
            {proposal.calculation ??
              'An individual energy assessment is needed.'}
          </p>
          {proposal.issues.map((issue) => (
            <p key={issue} className="text-sm">
              {issue}
            </p>
          ))}
          <ul className="list-disc pl-5 text-sm text-ink-3">
            {proposal.review.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
          <details>
            <summary className="cursor-pointer text-sm font-semibold text-line">
              Source and calculation basis
            </summary>
            <blockquote className="text-sm mt-2">{proposal.quote}</blockquote>
            <a className="text-line underline" href={proposal.source}>
              {proposal.source_title}
            </a>
          </details>
          {proposal.action && (
            <button
              type="button"
              className="btn-ghost"
              disabled={
                value.action.amount != null || value.action.upper != null
              }
              onClick={() =>
                onChange({ ...value, action: { ...proposal.action! } })
              }
            >
              Use as editable energy draft
            </button>
          )}
        </section>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Lower energy (kcal/day)">
          <input
            className="field"
            type="number"
            name="energy-lower"
            min="1"
            step="any"
            required={!!item}
            value={value.action.amount ?? ''}
            onChange={(e) =>
              onChange({
                ...value,
                action: {
                  ...value.action,
                  kind: 'range',
                  unit: 'kcal/day',
                  amount: e.target.value === '' ? null : Number(e.target.value),
                },
              })
            }
          />
        </Field>
        <Field label="Upper energy (kcal/day)">
          <input
            className="field"
            type="number"
            name="energy-upper"
            required={!!item}
            min={value.action.amount || 1}
            step="any"
            value={value.action.upper ?? ''}
            onChange={(e) =>
              onChange({
                ...value,
                action: {
                  ...value.action,
                  kind: 'range',
                  unit: 'kcal/day',
                  upper: e.target.value === '' ? null : Number(e.target.value),
                },
              })
            }
          />
        </Field>
      </div>
      <Field label="Energy target rationale">
        <input
          className="field"
          name="energy-rationale"
          required={!!item}
          value={value.rationale}
          onChange={(e) => onChange({ ...value, rationale: e.target.value })}
        />
      </Field>
    </fieldset>
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
  const numeric = [
    'range',
    'ceiling',
    'minimum',
    'intake',
    'additional',
  ].includes(action.kind);
  const percentage = [
    'protein',
    'carbohydrate',
    'fat',
    'saturated_fat',
    'trans_fat',
    'free_sugars',
  ].includes(action.subject);
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
                amount: null,
                upper: null,
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
              'minimum',
              'intake',
              'additional',
            ].includes(e.target.value);
            onChange({
              ...action,
              kind: e.target.value,
              amount: numeric ? (action.amount ?? null) : null,
              unit: numeric
                ? e.target.value === 'additional' && action.unit === '%energy'
                  ? units[action.subject]
                  : (action.unit ?? units[action.subject] ?? 'g/day')
                : null,
              upper: e.target.value === 'range' ? (action.upper ?? null) : null,
              upper_exclusive:
                e.target.value === 'ceiling'
                  ? (action.upper_exclusive ?? false)
                  : false,
            });
          }}
        >
          {[
            'range',
            'ceiling',
            'minimum',
            'intake',
            'exclusion',
            'timing',
            ...(evidence ? ['additional', 'assessment'] : []),
          ].map((key) => (
            <option key={key} value={key}>
              {key === 'minimum'
                ? 'Minimum (required)'
                : key === 'intake'
                  ? 'Recommended intake (soft goal)'
                  : key}
            </option>
          ))}
        </select>
      </Field>
      {numeric && (
        <Field label="Target unit">
          <select
            className="field"
            value={action.unit ?? units[action.subject]}
            onChange={(e) =>
              onChange({
                ...action,
                unit: e.target.value,
                amount: null,
                upper: null,
              })
            }
          >
            <option value={units[action.subject] ?? 'g/day'}>
              {units[action.subject] ?? 'g/day'}
            </option>
            {percentage && action.kind !== 'additional' && (
              <option value="%energy">% of daily energy</option>
            )}
            {evidence && action.subject === 'protein' && (
              <option value="g/kg/day">g/kg/day</option>
            )}
            {action.unit &&
              ![units[action.subject], '%energy', 'g/kg/day'].includes(
                action.unit,
              ) && <option value={action.unit}>{action.unit}</option>}
          </select>
        </Field>
      )}
      {numeric && (
        <Field label={`Amount (${action.unit})`}>
          <input
            type="number"
            min="0"
            max={action.unit === '%energy' ? 100 : undefined}
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
            max={action.unit === '%energy' ? 100 : undefined}
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
      {action.kind === 'ceiling' && (
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={action.upper_exclusive ?? false}
            onChange={(e) =>
              onChange({ ...action, upper_exclusive: e.target.checked })
            }
          />
          Strictly less than (exclude the limit)
        </label>
      )}
      {numeric && (
        <p className="text-sm text-ink-3 sm:col-span-2 lg:col-span-4">
          Minimums, ceilings and ranges are required daily bounds. Recommended
          intake is a soft goal. Energy percentages use the actual planned daily
          energy, not an assumed 2,000 kcal diet.
        </p>
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
