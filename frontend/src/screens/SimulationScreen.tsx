import { useEffect, useState } from 'react';
import { listPatients, listSimulations, createSimulation, getLatestEnvelope } from '../api';
import type {
  Patient,
  NutrientConstraint,
  Simulation,
  SimulationSide,
  SimulationDeltas,
} from '../types';
import LoadingState from '../components/LoadingState';
import EmptyState from '../components/EmptyState';
import { useRequestScope } from '../hooks/useRequestScope';

export default function SimulationScreen() {
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

  useEffect(() => {
    listPatients()
      .then((data) => setPatients(data || []))
      .catch((err) => setError(err.message || 'Failed to load patients'))
      .finally(() => setLoadingPatients(false));
  }, []);

  const loadPast = async (patientId: string) => {
    const isCurrent = requests.start('past');
    setPastLoading(true);
    try {
      const res = await listSimulations(patientId);
      if (isCurrent()) setPast(res.simulations);
    } catch {
      // past simulations are optional
    } finally {
      if (isCurrent()) setPastLoading(false);
    }
  };

  const handleSelectPatient = async (patient: Patient | null) => {
    requests.reset();
    const isCurrent = requests.start('prefill');
    setSelectedPatient(patient);
    setTargets([]);
    setResult(null);
    setPast([]);
    setPastLoading(false);
    setRunning(false);
    setError(null);
    if (patient) {
      // Prefill the target editor from the patient's current envelope so the
      // clinician edits the actual baseline instead of retyping constraints.
      try {
        const envelope = await getLatestEnvelope(patient.id);
        if (!isCurrent()) return;
        const constraints = (envelope.constraints || []).map((c) => ({
          nutrient: c.nutrient,
          kind: c.kind,
          value: c.value,
          unit: c.unit,
        }));
        if (constraints.length > 0) setTargets(constraints);
      } catch {
        // Prefill is optional; keep the empty editor after any fetch failure.
      }
      if (isCurrent()) await loadPast(patient.id);
    }
  };

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
    <main className="min-h-screen bg-slate-50 pb-12">
      <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
        <div className="mb-6">
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">What-if simulation</h1>
          <p className="mt-1 text-sm text-slate-500">
            Compare a proposed nutrient target change against the current approved envelope. This is a
            simulation and does not change the patient's active plan.
          </p>
        </div>

        {error && (
          <div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
            {error}
            <button onClick={() => setError(null)} className="ml-2 font-medium underline">
              Dismiss
            </button>
          </div>
        )}

        <section className="mb-8 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
            Select patient
          </h2>
          {loadingPatients ? (
            <LoadingState text="Loading patients…" />
          ) : patients.length === 0 ? (
            <EmptyState title="No patients found" description="Add patients or start the backend." />
          ) : (
            <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
              <div className="flex-1">
                <label htmlFor="sim-patient" className="mb-1 block text-sm font-medium text-slate-700">
                  Patient
                </label>
                <select
                  id="sim-patient"
                  value={selectedPatient?.id || ''}
                  onChange={(e) => {
                    const p = patients.find((pt) => pt.id === e.target.value) || null;
                    handleSelectPatient(p);
                  }}
                  className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-sky-500 focus:ring-1 focus:ring-sky-500"
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
          <section className="mb-8 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
              Proposed targets
            </h2>
            {targets.length === 0 ? (
              <EmptyState title="No targets loaded" description="The patient's approved envelope has no editable targets." />
            ) : (
              <div className="space-y-2">
                {targets.map((target, idx) => (
                  <div key={idx} className="flex flex-col gap-2 sm:flex-row sm:items-end">
                    <input
                      type="text"
                      value={target.nutrient}
                      onChange={(e) => updateTarget(idx, { nutrient: e.target.value })}
                      placeholder="Nutrient"
                      className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 focus:border-sky-500 focus:ring-1 focus:ring-sky-500"
                    />
                    <select
                      value={target.kind}
                      onChange={(e) =>
                        updateTarget(idx, { kind: e.target.value as NutrientConstraint['kind'] })
                      }
                      className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 focus:border-sky-500 focus:ring-1 focus:ring-sky-500"
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
                      className="w-32 rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 focus:border-sky-500 focus:ring-1 focus:ring-sky-500"
                    />
                    <input
                      type="text"
                      value={target.unit}
                      onChange={(e) => updateTarget(idx, { unit: e.target.value })}
                      placeholder="Unit"
                      className="w-28 rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 focus:border-sky-500 focus:ring-1 focus:ring-sky-500"
                    />
                    <button
                      onClick={() => removeTarget(idx)}
                      className="rounded-lg bg-white px-3 py-2 text-sm font-semibold text-rose-700 ring-1 ring-rose-200 hover:bg-rose-50 transition-colors"
                    >
                      Remove
                    </button>
                  </div>
                ))}
              </div>
            )}
            <div className="mt-4 flex gap-2">
              <button
                onClick={addTarget}
                className="rounded-lg bg-white px-4 py-2 text-sm font-semibold text-slate-700 ring-1 ring-slate-300 hover:bg-slate-50 transition-colors"
              >
                Add target
              </button>
              <button
                onClick={handleRun}
                disabled={running || targets.length === 0}
                className="rounded-lg bg-sky-600 px-5 py-2 text-sm font-semibold text-white hover:bg-sky-700 disabled:bg-sky-300 transition-colors"
              >
                {running ? 'Running…' : 'Run what-if'}
              </button>
            </div>
          </section>
        )}

        {result && <SimulationResult simulation={result} />}

        {selectedPatient && (
          <section className="mt-10">
            <h2 className="mb-4 text-lg font-semibold text-slate-900">Past simulations</h2>
            {pastLoading ? (
              <LoadingState text="Loading past simulations…" />
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
      <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
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
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h3 className="mb-3 text-base font-semibold text-slate-900">{title}</h3>
      <div className="space-y-3 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          {side.feasible === true && (
            <span className="rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-semibold text-emerald-800">
              Feasible
            </span>
          )}
          {side.feasible === false && (
            <span className="rounded-full bg-rose-100 px-2.5 py-0.5 text-xs font-semibold text-rose-800">
              Infeasible
            </span>
          )}
          {side.violation_count !== null && side.violation_count !== undefined && (
            <span className="text-slate-600">Violations: {side.violation_count}</span>
          )}
        </div>
        {side.plan_id && <p className="text-slate-600">Plan: {side.plan_id}</p>}
        {side.envelope_id && <p className="text-slate-600">Envelope: {side.envelope_id}</p>}
        {typeof side.cost === 'number' && <p className="text-slate-600">Cost: {side.cost.toFixed(2)}</p>}
        {side.infeasibility_reason && (
          <p className="rounded-lg bg-rose-50 p-2 text-rose-800">{side.infeasibility_reason}</p>
        )}
        {side.objectives && <ObjectivesTable objectives={side.objectives} />}
      </div>
    </div>
  );
}

function ObjectivesTable({ objectives }: { objectives: Record<string, number> }) {
  return (
    <div className="mt-2 overflow-x-auto">
      <table className="min-w-full divide-y divide-slate-200 text-sm">
        <thead className="bg-slate-50">
          <tr>
            <th className="px-3 py-2 text-left font-semibold text-slate-700">Objective</th>
            <th className="px-3 py-2 text-left font-semibold text-slate-700">Value</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {Object.entries(objectives).map(([key, value]) => (
            <tr key={key} className="hover:bg-slate-50">
              <td className="px-3 py-2 font-medium text-slate-900">{key}</td>
              <td className="px-3 py-2 text-slate-700">{value.toFixed ? value.toFixed(4) : value}</td>
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
    { label: 'Variety', key: 'variety', lowerIsBetter: false },
    { label: 'Worst shortfall %', key: 'worst_shortfall_pct', lowerIsBetter: true },
    { label: 'Meals changed', key: 'meals_changed', lowerIsBetter: null },
  ] as const;

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h3 className="mb-4 text-base font-semibold text-slate-900">Deltas (simulated − base)</h3>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
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
            <div key={row.key} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{row.label}</p>
              <p className={`mt-1 text-lg font-semibold ${tone}`}>
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
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-sm font-semibold text-slate-900">{simulation.simulation_id}</p>
          <p className="text-xs text-slate-500">{simulation.created_at ? formatDate(simulation.created_at) : ''}</p>
        </div>
        <div className="flex gap-2">
          <FeasibilityBadge feasible={simulation.base.feasible} />
          <FeasibilityBadge feasible={simulation.simulated.feasible} />
        </div>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
        <DeltaValue label="Cost" value={simulation.deltas.cost} lowerIsBetter />
        <DeltaValue label="Deviation" value={simulation.deltas.nutrient_target_deviation} lowerIsBetter />
        <DeltaValue label="Variety" value={simulation.deltas.variety} />
        <DeltaValue label="Meals changed" value={simulation.deltas.meals_changed} />
      </div>
    </div>
  );
}

function FeasibilityBadge({ feasible }: { feasible: boolean | null | undefined }) {
  if (feasible === null || feasible === undefined) return null;
  return feasible ? (
    <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-800">Feasible</span>
  ) : (
    <span className="rounded-full bg-rose-100 px-2 py-0.5 text-xs font-semibold text-rose-800">Infeasible</span>
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
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-2">
      <p className="text-xs text-slate-500">{label}</p>
      <p className={`text-sm font-semibold ${tone}`}>{value === null || value === undefined ? '—' : value.toFixed(4)}</p>
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
