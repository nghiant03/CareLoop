import { useEffect, useState } from 'react';
import { listPatients, createPlan } from '../api';
import type { Patient, MealPlan, DailySummary, DailyNutrient } from '../types';
import LoadingState from '../components/LoadingState';
import EmptyState from '../components/EmptyState';

export default function PatientMealPlanScreen() {
  const [patients, setPatients] = useState<Patient[]>([]);
  const [loadingPatients, setLoadingPatients] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedPatient, setSelectedPatient] = useState<Patient | null>(null);
  const [plan, setPlan] = useState<MealPlan | null>(null);
  const [planLoading, setPlanLoading] = useState(false);

  useEffect(() => {
    listPatients()
      .then((data) => setPatients(data || []))
      .catch((err) => setError(err.message || 'Failed to load patients'))
      .finally(() => setLoadingPatients(false));
  }, []);

  const handleGeneratePlan = async () => {
    if (!selectedPatient) return;
    setPlanLoading(true);
    setError(null);
    setPlan(null);
    try {
      const result = await createPlan({ patient_id: selectedPatient.id });
      setPlan(result);
    } catch (err: any) {
      const message = err.message || 'Failed to create plan';
      setError(message);
      if (message.toLowerCase().includes('envelope_not_approved') || err.status === 409) {
        setError('This patient does not have an approved envelope. Approve a proposed envelope in the Clinician review screen first.');
      }
    } finally {
      setPlanLoading(false);
    }
  };

  const needsApproval = error?.toLowerCase().includes('envelope_not_approved') || error?.toLowerCase().includes('approved envelope');

  return (
    <main className="min-h-screen bg-slate-50 pb-12">
      <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
        <div className="mb-6">
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Meal plan</h1>
          <p className="mt-1 text-sm text-slate-500">
            Choose a patient to generate a 7-day, 3-meal plan based on their approved nutrient envelope.
          </p>
        </div>

        {error && (
          <div className={`mb-4 rounded-lg border p-3 text-sm ${needsApproval ? 'border-amber-200 bg-amber-50 text-amber-800' : 'border-rose-200 bg-rose-50 text-rose-800'}`}>
            {error}
            <button
              onClick={() => setError(null)}
              className="ml-2 font-medium underline hover:opacity-80"
            >
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
                <label htmlFor="patient" className="mb-1 block text-sm font-medium text-slate-700">
                  Patient
                </label>
                <select
                  id="patient"
                  value={selectedPatient?.id || ''}
                  onChange={(e) => {
                    const p = patients.find((pt) => pt.id === e.target.value) || null;
                    setSelectedPatient(p);
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
              <button
                onClick={handleGeneratePlan}
                disabled={planLoading || !selectedPatient}
                className="inline-flex items-center justify-center rounded-lg bg-sky-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-sky-700 disabled:bg-sky-300 transition-colors"
              >
                {planLoading ? 'Generating plan…' : 'Generate 7-day plan'}
              </button>
            </div>
          )}
        </section>

        {plan && <PlanView plan={plan} />}
      </div>
    </main>
  );
}

function PlanView({ plan }: { plan: MealPlan }) {
  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">{plan.patient_id} — 7-day plan</h2>
        {plan.explanation && (
          <p className="mt-2 text-sm leading-relaxed text-slate-700">{plan.explanation}</p>
        )}
      </div>

      {plan.days?.length === 0 ? (
        <EmptyState title="No days returned" description="The meal plan response did not include daily details." />
      ) : (
        plan.days?.map((day) => (
          <DayCard key={day.day} day={day} />
        ))
      )}
    </div>
  );
}

function DayCard({ day }: { day: DailySummary }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-base font-semibold text-slate-900">Day {day.day}</h3>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        {day.slots?.map((slot, idx) => (
          <div key={idx} className="rounded-lg border border-slate-200 bg-slate-50/50 p-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              {slot.meal}
            </p>
            <p className="mt-1 text-sm font-medium text-slate-900">{slot.dish}</p>
          </div>
        ))}
      </div>

      <div className="mt-5">
        <h4 className="mb-3 text-sm font-semibold text-slate-900">Daily totals vs targets</h4>
        {day.totals?.length === 0 ? (
          <p className="text-sm text-slate-500">No nutrient totals returned.</p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {day.totals.map((nut, idx) => (
              <NutrientBar key={`${nut.name}-${idx}`} nutrient={nut} />
            ))}
          </div>
        )}
      </div>

      {day.explanation && (
        <div className="mt-4 rounded-lg bg-sky-50 p-3 text-sm text-sky-800">
          {day.explanation}
        </div>
      )}
    </section>
  );
}

function NutrientBar({ nutrient }: { nutrient: DailyNutrient }) {
  const { value, target, max, min, unit } = nutrient;
  let percentage = 0;
  let overLimit = false;

  if (target && target > 0) {
    percentage = Math.min((value / target) * 100, 100);
    overLimit = value > target;
  } else if (max && max > 0) {
    percentage = Math.min((value / max) * 100, 100);
    overLimit = value > max;
  } else if (min && min > 0) {
    percentage = Math.min((value / min) * 100, 100);
    overLimit = value < min;
  }

  const barColor = overLimit ? 'bg-rose-500' : 'bg-sky-500';

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <div className="flex items-center justify-between text-xs text-slate-600">
        <span className="font-medium text-slate-900">{nutrient.name}</span>
        <span>
          {value} / {target ?? max ?? min} {unit}
        </span>
      </div>
      <div className="mt-2 h-2 w-full rounded-full bg-slate-100">
        <div
          className={`h-2 rounded-full transition-all ${barColor}`}
          style={{ width: `${percentage}%` }}
        />
      </div>
      {overLimit && (
        <p className="mt-1.5 text-xs font-medium text-rose-600" role="alert">
          Over limit
        </p>
      )}
    </div>
  );
}
