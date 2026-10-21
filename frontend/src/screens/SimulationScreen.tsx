import { useEffect, useState } from 'react';
import { HttpApiError, listPatients, listSimulations, createSimulation, getLatestEnvelope } from '../api';
import type {
  Patient,
  NutrientConstraint,
  Simulation,
  SimulationSide,
  SimulationDeltas,
} from '../types';
import LoadingState from '../components/LoadingState';
import EmptyState from '../components/EmptyState';
import PageHeader from '../components/PageHeader';
import { useRequestScope } from '../hooks/useRequestScope';
import { useDemo } from '../demo/context';
import { useSharedPatient } from '../demo/useSharedPatient';

export default function SimulationScreen() {
  const demo = useDemo();
  const requests = useRequestScope();
  const [patients, setPatients] = useState<Patient[]>([]);
  const [loadingPatients, setLoadingPatients] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedPatient, setSelectedPatient] = useState<Patient | null>(null);
  const [targets, setTargets] = useState<NutrientConstraint[]>([]);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<Simulation | null>(null);
  const [past, setPast] = useState<Simulation[]>([]);
  const [pastLoading, setPastLoading] = useState(false);
  const [pastError, setPastError] = useState<string | null>(null);
  const [prefillLoading, setPrefillLoading] = useState(false);
  const [prefillNotice, setPrefillNotice] = useState<string | null>(null);

  useEffect(() => {
    listPatients()
      .then((data) => setPatients(data || []))
      .catch((err) => setError(err.message || 'Failed to load patients'))
      .finally(() => setLoadingPatients(false));
  }, []);

  const loadPast = async (patientId: string) => {
    const isCurrent = requests.start('past');
    setPastLoading(true);
    setPastError(null);
    try {
      const res = await listSimulations(patientId);
      if (isCurrent()) setPast(res.simulations);
    } catch (err: any) {
      if (isCurrent()) setPastError(err.message || 'Simulation history unavailable');
    } finally {
      if (isCurrent()) setPastLoading(false);
    }
  };

  const handleSelectPatient = async (patient: Patient | null) => {
    requests.reset();
    const isCurrent = requests.start('prefill');
    demo.setPatientId(patient?.id || null);
    setSelectedPatient(patient);
    setTargets([]);
    setResult(null);
    setPast([]);
    setPastLoading(false);
    setPastError(null);
    setPrefillLoading(!!patient);
    setPrefillNotice(null);
    setRunning(false);
    setError(null);
    if (patient) {
      try {
        const envelope = await getLatestEnvelope(patient.id);
        if (!isCurrent()) return;
        if (envelope.status !== 'APPROVED') setPrefillNotice(`Latest envelope is ${envelope.status}; approval is required before simulation.`);
        const constraints = (envelope.constraints || []).map((c) => ({
          nutrient: c.nutrient,
          kind: c.kind,
          value: c.value,
          unit: c.unit,
        }));
        if (constraints.length > 0) setTargets(constraints);
      } catch (err: any) {
        if (isCurrent()) setPrefillNotice(err instanceof HttpApiError && err.code === 'envelope_not_found'
          ? 'No envelope exists for this patient. Generate a proposal in Clinician review first.'
          : `Latest envelope unavailable: ${err.message || 'targets were not loaded'}`);
      } finally {
        if (isCurrent()) setPrefillLoading(false);
      }
      if (isCurrent()) await loadPast(patient.id);
    }
  };

  useSharedPatient(patients, selectedPatient?.id, (p) => { void handleSelectPatient(p); });

  const handleRun = async () => {
    if (!selectedPatient) return;
    const isCurrent = requests.start('simulation');
    setRunning(true);
    setError(null);
    try {
      const sim = await createSimulation({
        patient_id: selectedPatient.id,
        targets: targets.filter((t) => t.nutrient && t.value !== undefined),
      });
      if (!isCurrent()) return;
      setResult(sim);
      await loadPast(selectedPatient.id);
    } catch (err: any) {
      if (isCurrent()) setError(err.message || 'Failed to run simulation');
    } finally {
      if (isCurrent()) setRunning(false);
    }
  };

  const addTarget = () => {
    setTargets((prev) => [...prev, { nutrient: '', kind: 'max', value: 0, unit: '' }]);
  };

  const updateTarget = (index: number, updates: Partial<NutrientConstraint>) => {
    setTargets((prev) => prev.map((t, i) => (i === index ? { ...t, ...updates } : t)));
  };

  const removeTarget = (index: number) => {
    setTargets((prev) => prev.filter((_, i) => i !== index));
  };

  return (
    <main className="pb-12">
      <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
        <PageHeader code="SIM" title="What-if simulation">
          Compare a proposed nutrient target change against the current approved envelope. This is a
          simulation and does not change the patient's active plan.
        </PageHeader>

        {error && (
          <div className="notice notice-error mb-4">
            {error}
            <button onClick={() => setError(null)} className="ml-2 font-semibold underline">
              Dismiss
            </button>
          </div>
        )}

        <section className="panel mb-8 p-5">
          <h2 className="micro-label mb-3 border-b border-rule pb-2">
            Select patient
          </h2>
          {loadingPatients ? (
            <LoadingState text="Loading patients…" />
          ) : patients.length === 0 ? (
            <EmptyState title="No patients found" description="Add patients or start the backend." />
          ) : (
            <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
              <div className="flex-1">
                <label htmlFor="sim-patient" className="micro-label mb-1 block">
                  Patient
                </label>
                <select
                  id="sim-patient"
                  value={selectedPatient?.id || ''}
                  onChange={(e) => {
                    const p = patients.find((pt) => pt.id === e.target.value) || null;
                    handleSelectPatient(p);
                  }}
                  className="field"
                >
                  <option value="">Select a patient</option>
                  {patients.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name || p.id} — {p.diagnoses?.join(', ')}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          )}
        </section>

        {selectedPatient && (
          <section className="panel mb-8 p-5">
            <h2 className="micro-label mb-3 border-b border-rule pb-2">
              Proposed targets
            </h2>
            {prefillNotice && <p role="status" className="notice notice-warn mb-3">{prefillNotice}</p>}
            {prefillLoading && <LoadingState text="Loading latest envelope…" />}
            {targets.length === 0 ? (
              <EmptyState title="No targets loaded" description="No editable targets have been loaded from the latest envelope." />
            ) : (
              <div className="space-y-2">
                {targets.map((target, idx) => (
                  <div key={idx} className="flex flex-col gap-2 sm:flex-row sm:items-end">
                    <input
                      type="text"
                      value={target.nutrient}
                      onChange={(e) => updateTarget(idx, { nutrient: e.target.value })}
                      placeholder="Nutrient"
                      className="field flex-1"
                    />
                    <select
                      value={target.kind}
                      onChange={(e) =>
                        updateTarget(idx, { kind: e.target.value as NutrientConstraint['kind'] })
                      }
                      className="field sm:w-28"
                    >
                      <option value="max">max</option>
                      <option value="min">min</option>
                      <option value="target">target</option>
                    </select>
                    <input
                      type="number"
                      value={target.value}
                      onChange={(e) => updateTarget(idx, { value: Number(e.target.value) })}
                      placeholder="Value"
                      className="field num sm:w-32"
                    />
                    <input
                      type="text"
                      value={target.unit}
                      onChange={(e) => updateTarget(idx, { unit: e.target.value })}
                      placeholder="Unit"
                      className="field sm:w-28"
                    />
                    <button
                      onClick={() => removeTarget(idx)}
                      className="btn-danger"
                    >
                      Remove
                    </button>
                  </div>
                ))}
              </div>
            )}
            <div className="mt-4 flex gap-2 border-t border-rule pt-4">
              <button
                onClick={addTarget}
                className="btn-ghost"
              >
                Add target
              </button>
              <button
                onClick={handleRun}
                disabled={running || targets.length === 0}
                className="btn-primary"
              >
                {running ? 'Running…' : 'Run what-if'}
              </button>
            </div>
          </section>
        )}

        {result && <SimulationResult simulation={result} />}

        {selectedPatient && (
          <section className="mt-10">
            <h2 className="mb-4 text-lg font-bold tracking-tight text-ink">Past simulations</h2>
            {pastLoading ? (
              <LoadingState text="Loading past simulations…" />
            ) : pastError ? (
              <p role="alert" className="text-sm text-flag">History unavailable: {pastError}</p>
            ) : past.length === 0 ? (
              <EmptyState title="No past simulations" description="Run a what-if to see comparisons here." />
            ) : (
              <div className="space-y-3">
                {past.map((sim) => (
                  <SimulationCard key={sim.simulation_id} simulation={sim} />
                ))}
              </div>
            )}
          </section>
        )}
      </div>
    </main>
  );
}

function SimulationResult({ simulation }: { simulation: Simulation }) {
  return (
    <section className="space-y-6">
      <div className="notice notice-warn">
        This is a simulation. The patient's active plan and approved envelope are unchanged.
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <SideCard title="Base (current approved envelope)" side={simulation.base} />
        <SideCard title="Simulated (proposed targets)" side={simulation.simulated} />
      </div>

      <DeltasCard deltas={simulation.deltas} />
    </section>
  );
}

function SideCard({ title, side }: { title: string; side: SimulationSide }) {
  return (
    <div className="panel p-5">
      <h3 className="mb-3 border-b border-rule pb-2 text-base font-bold tracking-tight text-ink">{title}</h3>
      <div className="space-y-3 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          {side.feasible === true && (
            <span className="flag flag-ok">Feasible</span>
          )}
          {side.feasible === false && (
            <span className="flag flag-bad">Infeasible</span>
          )}
          {side.violation_count !== null && side.violation_count !== undefined && (
            <span className="text-ink-3">Violations: <span className="num">{side.violation_count}</span></span>
          )}
        </div>
        {side.plan_id && <p className="text-ink-2">Plan: <span className="num">{side.plan_id}</span></p>}
        {side.envelope_id && <p className="text-ink-2">Envelope: <span className="num">{side.envelope_id}</span></p>}
        {typeof side.cost === 'number' && <p className="text-ink-2">Cost: <span className="num">{side.cost.toFixed(2)}</span></p>}
        {side.infeasibility_reason && (
          <p className="notice notice-error">{side.infeasibility_reason}</p>
        )}
        {side.objectives && <ObjectivesTable objectives={side.objectives} />}
      </div>
    </div>
  );
}

function ObjectivesTable({ objectives }: { objectives: Record<string, number> }) {
  return (
    <div className="mt-2 overflow-x-auto border border-rule">
      <table className="data-table">
        <thead>
          <tr>
            <th>Objective</th>
            <th className="text-right">Value</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(objectives).map(([key, value]) => (
            <tr key={key}>
              <td className="font-medium text-ink">{key}</td>
              <td className="num text-right text-ink-2">{value.toFixed ? value.toFixed(4) : value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DeltasCard({ deltas }: { deltas: SimulationDeltas }) {
  const rows = [
    { label: 'Cost', key: 'cost', lowerIsBetter: true },
    { label: 'Nutrient target deviation', key: 'nutrient_target_deviation', lowerIsBetter: true },
    { label: 'Variety objective', key: 'variety', lowerIsBetter: true },
    { label: 'Worst shortfall %', key: 'worst_shortfall_pct', lowerIsBetter: true },
    { label: 'Meals changed', key: 'meals_changed', lowerIsBetter: null },
  ] as const;

  return (
    <div className="panel p-5">
      <h3 className="mb-4 text-base font-bold tracking-tight text-ink">Deltas (simulated − base)</h3>
      <div className="grid grid-cols-1 divide-y divide-rule border border-rule sm:grid-cols-2 sm:divide-y-0 lg:grid-cols-5 lg:divide-x">
        {rows.map((row) => {
          const value = deltas[row.key as keyof SimulationDeltas];
          let tone: string;
          if (value === null || value === undefined) {
            tone = 'text-slate-500';
          } else if (row.lowerIsBetter === null) {
            tone = 'text-slate-900';
          } else {
            const isBetter = row.lowerIsBetter ? (value as number) < 0 : (value as number) > 0;
            const isWorse = row.lowerIsBetter ? (value as number) > 0 : (value as number) < 0;
            tone = isBetter ? 'text-emerald-700' : isWorse ? 'text-rose-700' : 'text-slate-900';
          }
          return (
            <div key={row.key} className="bg-card p-4">
              <p className="micro-label">{row.label}</p>
              <p className={`num mt-1 text-lg font-semibold ${tone}`}>
                {value === null || value === undefined ? '—' : typeof value === 'number' ? value.toFixed(4) : String(value)}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function SimulationCard({ simulation }: { simulation: Simulation }) {
  return (
    <div className="panel p-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="num text-sm font-semibold text-ink">{simulation.simulation_id}</p>
          <p className="num text-xs text-ink-3">{simulation.created_at ? formatDate(simulation.created_at) : ''}</p>
        </div>
        <div className="flex gap-2">
          <FeasibilityBadge feasible={simulation.base.feasible} />
          <FeasibilityBadge feasible={simulation.simulated.feasible} />
        </div>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
        <DeltaValue label="Cost" value={simulation.deltas.cost} lowerIsBetter />
        <DeltaValue label="Deviation" value={simulation.deltas.nutrient_target_deviation} lowerIsBetter />
        <DeltaValue label="Variety objective" value={simulation.deltas.variety} lowerIsBetter />
        <DeltaValue label="Meals changed" value={simulation.deltas.meals_changed} />
      </div>
    </div>
  );
}

function FeasibilityBadge({ feasible }: { feasible: boolean | null | undefined }) {
  if (feasible === null || feasible === undefined) return null;
  return feasible ? (
    <span className="flag flag-ok">Feasible</span>
  ) : (
    <span className="flag flag-bad">Infeasible</span>
  );
}

function DeltaValue({
  label,
  value,
  lowerIsBetter,
}: {
  label: string;
  value: number | null;
  lowerIsBetter?: boolean;
}) {
  let tone = 'text-slate-900';
  if (value !== null && value !== undefined && lowerIsBetter !== undefined) {
    const isBetter = lowerIsBetter ? value < 0 : value > 0;
    const isWorse = lowerIsBetter ? value > 0 : value < 0;
    tone = isBetter ? 'text-emerald-700' : isWorse ? 'text-rose-700' : 'text-slate-900';
  }
  return (
    <div className="border border-rule bg-panel p-2">
      <p className="micro-label">{label}</p>
      <p className={`num text-sm font-semibold ${tone}`}>{value === null || value === undefined ? '—' : value.toFixed(4)}</p>
    </div>
  );
}

function formatDate(value: string) {
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}
