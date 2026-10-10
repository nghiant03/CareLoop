import { createContext, useContext, useEffect, useRef, useState } from 'react';
import { HttpApiError, listPatients, createPlan, listPlans, getPlan, getSubstitutions, applySwap } from '../api';
import type {
  Patient,
  MealPlan,
  PlanDay,
  PlanSlot,
  PlanTotal,
  PatientExplanation,
  AdequacyItem,
  PlanSummary,
  SubstituteDish,
} from '../types';
import LoadingState from '../components/LoadingState';
import EmptyState from '../components/EmptyState';
import { useRequestScope } from '../hooks/useRequestScope';

const SwapApplicationContext = createContext<{ pending: boolean; begin: () => boolean; end: () => void }>({ pending: false, begin: () => false, end: () => {} });

export default function PatientMealPlanScreen() {
  const requests = useRequestScope();
  // Invalidate swap callbacks as soon as a different plan is requested, before its response.
  const planRequests = useRequestScope();
  const selectionIsCurrent = requests.capture();
  const planIsCurrent = planRequests.capture();
  const [patients, setPatients] = useState<Patient[]>([]);
  const [loadingPatients, setLoadingPatients] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [needsApproval, setNeedsApproval] = useState(false);
  const [selectedPatient, setSelectedPatient] = useState<Patient | null>(null);
  const [plan, setPlan] = useState<MealPlan | null>(null);
  const [planLoading, setPlanLoading] = useState(false);
  const [savedPlans, setSavedPlans] = useState<PlanSummary[]>([]);
  const [savedPlansLoading, setSavedPlansLoading] = useState(false);

  useEffect(() => {
    listPatients()
      .then((data) => setPatients(data || []))
      .catch((err) => setError(err.message || 'Failed to load patients'))
      .finally(() => setLoadingPatients(false));
  }, []);

  const loadSavedPlans = async (patientId: string) => {
    const isCurrent = requests.start('saved-plans');
    setSavedPlansLoading(true);
    try {
      const data = await listPlans(patientId);
      if (isCurrent()) setSavedPlans(data.plans || []);
    } catch {
      if (isCurrent()) setSavedPlans([]);
    } finally {
      if (isCurrent()) setSavedPlansLoading(false);
    }
  };

  const handleGeneratePlan = async () => {
    if (!selectedPatient) return;
    const isCurrent = requests.start('plan');
    planRequests.reset();
    setPlanLoading(true);
    setError(null);
    setNeedsApproval(false);
    setPlan(null);
    try {
      const result = await createPlan({ patient_id: selectedPatient.id });
      if (!isCurrent()) return;
      planRequests.reset();
      setPlan(result);
      await loadSavedPlans(selectedPatient.id);
    } catch (err: any) {
      if (!isCurrent()) return;
      const message = err.message || 'Failed to create plan';
      setError(message);
      if (err instanceof HttpApiError && err.code === 'envelope_not_approved') {
        setNeedsApproval(true);
        setError('This patient does not have an approved envelope. Approve a proposed envelope in the Clinician review screen first.');
      }
    } finally {
      if (isCurrent()) setPlanLoading(false);
    }
  };

  const handleLoadPlan = async (planId: string) => {
    const isCurrent = requests.start('plan');
    planRequests.reset();
    setPlanLoading(true);
    setError(null);
    setNeedsApproval(false);
    try {
      const loaded = await getPlan(planId);
      if (isCurrent()) {
        planRequests.reset();
        setPlan(loaded);
      }
    } catch (err: any) {
      if (isCurrent()) setError(err.message || 'Failed to load plan');
    } finally {
      if (isCurrent()) setPlanLoading(false);
    }
  };

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
                    requests.reset();
                    planRequests.reset();
                    const p = patients.find((pt) => pt.id === e.target.value) || null;
                    setSelectedPatient(p);
                    setPlan(null);
                    setSavedPlans([]);
                    setError(null);
                    setPlanLoading(false);
                    setSavedPlansLoading(false);
                    if (p) loadSavedPlans(p.id);
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

        {selectedPatient && (
          <SavedPlansSection
            plans={savedPlans}
            loading={savedPlansLoading}
            onLoad={handleLoadPlan}
            currentPlanId={plan?.plan_id}
          />
        )}

        {plan && !planLoading && (
          <PlanView
            key={plan.plan_id || 'unsaved'}
            plan={plan}
            onPlanUpdate={(newPlan) => {
              if (!selectionIsCurrent() || !planIsCurrent()) return;
              planRequests.reset();
              setPlan(newPlan);
              if (selectedPatient) {
                loadSavedPlans(selectedPatient.id);
              }
            }}
            onError={(message) => { if (selectionIsCurrent() && planIsCurrent()) setError(message); }}
          />
        )}
      </div>
    </main>
  );
}

function SavedPlansSection({
  plans,
  loading,
  onLoad,
  currentPlanId,
}: {
  plans: PlanSummary[];
  loading: boolean;
  onLoad: (planId: string) => void;
  currentPlanId?: string;
}) {
  return (
    <section className="mb-8 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
        Saved plans
      </h2>
      {loading ? (
        <LoadingState text="Loading saved plans…" />
      ) : plans.length === 0 ? (
        <EmptyState title="No saved plans" description="Generate a plan to save one." />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {plans.map((p) => (
            <div
              key={p.plan_id}
              className={`rounded-lg border p-4 ${
                currentPlanId === p.plan_id
                  ? 'border-sky-300 bg-sky-50'
                  : 'border-slate-200 bg-slate-50'
              }`}
            >
              <p className="text-sm font-semibold text-slate-900">{p.plan_id}</p>
              <p className="text-xs text-slate-500">{new Date(p.created_at).toLocaleString()}</p>
              <div className="mt-2 flex flex-wrap gap-1">
                <span
                  className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
                    p.feasible ? 'bg-emerald-100 text-emerald-800' : 'bg-rose-100 text-rose-800'
                  }`}
                >
                  {p.feasible ? 'Feasible' : 'Infeasible'}
                </span>
                {p.engine && (
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-700">
                    {p.engine}
                  </span>
                )}
                {p.derived_from && (
                  <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800">
                    after swap
                  </span>
                )}
              </div>
              <button
                onClick={() => onLoad(p.plan_id)}
                className="mt-3 rounded-lg bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 ring-1 ring-slate-300 hover:bg-slate-50 transition-colors"
              >
                Load plan
              </button>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function PlanView({
  plan,
  onPlanUpdate,
  onError,
}: {
  plan: MealPlan;
  onPlanUpdate: (plan: MealPlan) => void;
  onError: (msg: string) => void;
}) {
  const [swapPending, setSwapPending] = useState(false);
  // Share one lock across slots; the ref rejects another click before React commits disabled controls.
  const swapLock = useRef(false);
  const swapApplications = {
    pending: swapPending,
    begin: () => {
      if (swapLock.current) return false;
      swapLock.current = true;
      setSwapPending(true);
      return true;
    },
    end: () => {
      swapLock.current = false;
      setSwapPending(false);
    },
  };
  return (
    <SwapApplicationContext.Provider value={swapApplications}>
    <div className="space-y-6">
      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">{plan.patient_id} — 7-day plan</h2>
        <PlanStatus plan={plan} />
        <ExplanationView explanation={plan.explanation} />
      </div>

      {!plan.feasible && (
        <InfeasibilityView
          reason={plan.infeasibility_reason}
          status={plan.infeasibility_status}
          violations={plan.violations || []}
        />
      )}

      {((plan.relaxed_constraints?.length || 0) > 0 || (plan.explanation?.relaxation_notes?.length || 0) > 0) && (
        <RelaxationCallout
          constraints={plan.relaxed_constraints || []}
          notes={plan.explanation?.relaxation_notes || []}
        />
      )}

      {plan.adequacy && plan.adequacy.length > 0 && <AdequacyPanel items={plan.adequacy} />}

      {plan.days?.length === 0 ? (
        <EmptyState title="No days returned" description="The meal plan response did not include daily details." />
      ) : (
        plan.days?.map((day) => (
          <DayCard key={day.day} day={day} plan={plan} onPlanUpdate={onPlanUpdate} onError={onError} />
        ))
      )}
    </div>
    </SwapApplicationContext.Provider>
  );
}

function PlanStatus({ plan }: { plan: MealPlan }) {
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
      <span
        className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${
          plan.feasible ? 'bg-emerald-100 text-emerald-800' : 'bg-rose-100 text-rose-800'
        }`}
      >
        {plan.feasible ? 'Hard constraints met' : 'No plan returned'}
      </span>
      {plan.feasible && <span className="text-amber-800">
        {plan.adequate ? 'All nutrient aims met' : 'Some nutrient aims remain unmet — see adequacy below'}
      </span>}
      {plan.feasible && !plan.meal_complete && <span className="text-amber-800">Meal composition incomplete</span>}
      {plan.data_quality && <p className="basis-full text-slate-600">
        Nutrient data: {plan.data_quality.unverified_dishes} of {plan.data_quality.dish_count} catalogue dishes unverified.
        {plan.data_quality.cost_is_estimated && ' Costs are synthetic estimates, not measured prices.'}
      </p>}
      {plan.engine && (
        <span className="text-slate-500">
          Engine: <span className="font-medium text-slate-700">{plan.engine}</span>
        </span>
      )}
      {typeof plan.violation_count === 'number' && (
        <span className="text-slate-500">
          Violations: <span className="font-medium text-slate-700">{plan.violation_count}</span>
        </span>
      )}
      {typeof plan.runtime_ms === 'number' && (
        <span className="text-slate-500">
          Runtime: <span className="font-medium text-slate-700">{plan.runtime_ms} ms</span>
        </span>
      )}
      {typeof plan.allowed_dish_count === 'number' && (
        <span className="text-slate-500">
          Allowed dishes: <span className="font-medium text-slate-700">{plan.allowed_dish_count}</span>
        </span>
      )}
      {plan.plan_id && (
        <span className="text-slate-500">
          Plan ID: <span className="font-medium text-slate-700">{plan.plan_id}</span>
        </span>
      )}
    </div>
  );
}

function ExplanationView({ explanation }: { explanation?: PatientExplanation | null }) {
  if (!explanation) return null;
  return (
    <div className="mt-4 rounded-lg border border-sky-100 bg-sky-50 p-4 text-sm text-sky-900">
      {explanation.headline && (
        <h3 className="mb-2 font-semibold text-sky-900">{explanation.headline}</h3>
      )}
      {explanation.daily_targets && explanation.daily_targets.length > 0 && (
        <ul className="mb-3 space-y-1">
          {explanation.daily_targets.map((target, idx) => (
            <li key={idx} className="leading-relaxed">
              {target.text}
            </li>
          ))}
        </ul>
      )}
      {explanation.why && explanation.why.length > 0 && (
        <div className="mb-3">
          <p className="mb-1 font-medium text-sky-900">Why these targets?</p>
          <ul className="list-disc space-y-1 pl-5 text-sky-800">
            {explanation.why.map((item, idx) => (
              <li key={idx}>{item}</li>
            ))}
          </ul>
        </div>
      )}
      {explanation.avoid && explanation.avoid.length > 0 && (
        <div className="mb-3">
          <p className="mb-1 font-medium text-sky-900">Avoid</p>
          <ul className="list-disc space-y-1 pl-5 text-sky-800">
            {explanation.avoid.map((item, idx) => (
              <li key={idx}>{item}</li>
            ))}
          </ul>
        </div>
      )}
      {explanation.plan_summary && explanation.plan_summary.length > 0 && (
        <div className="mb-3">
          <p className="mb-1 font-medium text-sky-900">Plan summary</p>
          <ul className="list-disc space-y-1 pl-5 text-sky-800">
            {explanation.plan_summary.map((item, idx) => (
              <li key={idx}>{item}</li>
            ))}
          </ul>
        </div>
      )}
      {explanation.approval_note && (
        <p className="mt-2 font-medium text-amber-700">{explanation.approval_note}</p>
      )}
    </div>
  );
}

function InfeasibilityView({
  reason,
  status,
  violations,
}: {
  reason: string | null;
  status?: 'proven_infeasible' | 'search_exhausted' | null;
  violations: { nutrient?: string; kind?: string; amount?: number | null; actual?: number | null; limit?: number | null }[];
}) {
  return (
    <section className="rounded-xl border border-rose-200 bg-rose-50 p-5 shadow-sm">
      <h3 className="text-base font-semibold text-rose-900">Plan could not be generated</h3>
      <p className="mt-1 text-sm text-rose-800">
        {status === 'search_exhausted' ? 'Search ended without finding a plan. This does not prove that no feasible plan exists.' : status === 'proven_infeasible' ? 'No feasible plan exists under the current meal encoding and constraints.' : ''}
      </p>
      {reason && <p className="mt-1 text-sm text-rose-800">{reason}</p>}
      {violations && violations.length > 0 && (
        <div className="mt-3">
          <h4 className="mb-2 text-sm font-semibold text-rose-900">Constraint violations</h4>
          <ul className="divide-y divide-rose-100 rounded-lg border border-rose-200 bg-white text-sm">
            {violations.map((v, idx) => (
              <li key={idx} className="p-3">
                <span className="font-medium text-slate-900">{v.nutrient || 'Unknown nutrient'}</span>
                <span className="ml-2 text-slate-600">({v.kind || 'constraint'})</span>
                <div className="mt-1 text-slate-600">
                  {v.actual !== null && v.actual !== undefined && <span>Actual: {v.actual} </span>}
                  {v.limit !== null && v.limit !== undefined && <span>Limit: {v.limit} </span>}
                  {v.amount !== null && v.amount !== undefined && (
                    <span className="text-rose-700">Excess: {v.amount}</span>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function RelaxationCallout({
  constraints,
  notes,
}: {
  constraints: { nutrient: string; requested: number; relaxed_to: number; unit: string; reason: string }[];
  notes: string[];
}) {
  return (
    <section className="rounded-xl border border-amber-200 bg-amber-50 p-5 shadow-sm">
      <h3 className="mb-2 text-base font-semibold text-amber-900">Relaxation notes</h3>
      <p className="mb-3 text-sm text-amber-800">
        Some targets were relaxed to make a feasible plan. A clinician can review these changes.
      </p>
      {notes.map((note, idx) => (
        <p key={idx} className="mb-2 text-sm text-amber-900">
          {note}
        </p>
      ))}
      {constraints.map((c, idx) => (
        <div
          key={idx}
          className="mb-2 rounded-lg border border-amber-200 bg-white p-3 text-sm text-amber-900"
        >
          <p className="font-medium">
            {c.nutrient}: {c.requested} → {c.relaxed_to} {c.unit}
          </p>
          <p className="mt-1 text-amber-800">{c.reason}</p>
        </div>
      ))}
    </section>
  );
}

function AdequacyPanel({ items }: { items: AdequacyItem[] }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h3 className="mb-4 text-base font-semibold text-slate-900">Adequacy vs. approved goals</h3>
      <p className="mb-3 text-sm text-slate-600">Minimums show shortfall; targets show distance above or below the approved value.</p>
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-slate-200 text-sm">
          <thead className="bg-slate-50">
            <tr>
              <th className="px-3 py-2 text-left font-semibold text-slate-700">Nutrient</th>
              <th className="px-3 py-2 text-left font-semibold text-slate-700">Aim</th>
              <th className="px-3 py-2 text-left font-semibold text-slate-700">Mean daily</th>
              <th className="px-3 py-2 text-left font-semibold text-slate-700">Worst day</th>
              <th className="px-3 py-2 text-left font-semibold text-slate-700">Aim gap</th>
              <th className="px-3 py-2 text-left font-semibold text-slate-700">Met days</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {items.map((item, idx) => {
              const severity = adequacySeverity(item);
              return (
                <tr key={idx} className="hover:bg-slate-50">
                  <td className="px-3 py-2 font-medium text-slate-900">
                    {item.nutrient}
                    <span className="ml-1 text-xs font-normal text-slate-500">({item.kind})</span>
                  </td>
                  <td className="px-3 py-2 text-slate-700">
                    {item.aim} {item.unit}
                    {item.relaxed_aim !== null && (
                      <span className="ml-1 text-xs text-amber-700">relaxed to {item.relaxed_aim}</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-slate-700">
                    {item.mean_daily.toFixed(1)} {item.unit}
                  </td>
                  <td className="px-3 py-2 text-slate-700">
                    Day {item.worst_day}: {item.worst_daily.toFixed(1)} {item.unit}
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold ${severity.class}`}
                    >
                      {item.shortfall.toFixed(1)} {item.unit} ({item.shortfall_pct.toFixed(0)}%)
                    </span>
                  </td>
                  <td className="px-3 py-2 text-slate-700">
                    {item.met_days} / {item.total_days}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function adequacySeverity(item: AdequacyItem) {
  if (item.met_days === item.total_days && item.shortfall <= 0) {
    return { class: 'bg-emerald-100 text-emerald-800' };
  }
  if (item.shortfall_pct >= 25 || item.met_days === 0) {
    return { class: 'bg-rose-100 text-rose-800' };
  }
  if (item.shortfall_pct >= 10 || item.met_days < item.total_days / 2) {
    return { class: 'bg-amber-100 text-amber-800' };
  }
  return { class: 'bg-emerald-100 text-emerald-800' };
}

function DayCard({
  day,
  plan,
  onPlanUpdate,
  onError,
}: {
  day: PlanDay;
  plan: MealPlan;
  onPlanUpdate: (plan: MealPlan) => void;
  onError: (msg: string) => void;
}) {
  const meals = groupSlotsByMeal(day.slots || []);

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-base font-semibold text-slate-900">Day {day.day}</h3>
      </div>

      <div className="space-y-4">
        {Object.entries(meals).map(([meal, slots]) => (
          <div key={meal}>
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
              {meal}
            </h4>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {slots.map((slot, idx) => (
                <SlotCard key={`${meal}-${idx}-${slot.dish_id}`} slot={slot} plan={plan} onPlanUpdate={onPlanUpdate} onError={onError} />
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="mt-6">
        <h4 className="mb-3 text-sm font-semibold text-slate-900">Daily totals vs targets</h4>
        {day.totals?.length === 0 ? (
          <p className="text-sm text-slate-500">No nutrient totals returned.</p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {day.totals.map((nut, idx) => (
              <NutrientBar key={`${nut.nutrient}-${idx}`} nutrient={nut} />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function groupSlotsByMeal(slots: PlanSlot[]) {
  const grouped: Record<string, PlanSlot[]> = {};
  slots.forEach((slot) => {
    if (!grouped[slot.meal]) grouped[slot.meal] = [];
    grouped[slot.meal].push(slot);
  });
  return grouped;
}

function SlotCard({
  slot,
  plan,
  onPlanUpdate,
  onError,
}: {
  slot: PlanSlot;
  plan: MealPlan;
  onPlanUpdate: (plan: MealPlan) => void;
  onError: (msg: string) => void;
}) {
  const nutrients = slot.nutrients || {};
  const summary = [
    { label: 'Energy', value: nutrients.kcal ?? nutrients.energy_kcal, unit: 'kcal' },
    { label: 'Protein', value: nutrients.protein_g, unit: 'g' },
    { label: 'Sodium', value: nutrients.sodium_mg, unit: 'mg' },
    { label: 'Potassium', value: nutrients.potassium_mg, unit: 'mg' },
    { label: 'Phosphorus', value: nutrients.phosphorus_mg, unit: 'mg' },
  ]
    .filter((entry) => typeof entry.value === 'number')
    .slice(0, 3);

  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50/50 p-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{slot.meal}</p>
      <p className="mt-1 text-sm font-medium text-slate-900">{slot.name}</p>
      {slot.category && <p className="text-xs text-slate-500">{slot.category}</p>}
      {summary.length > 0 && (
        <p className="mt-2 text-xs text-slate-600">
          {summary.map((entry) => `${entry.label} ${Number(entry.value).toFixed(1)} ${entry.unit}`).join(' · ')}
        </p>
      )}
      <SwapButton slot={slot} plan={plan} onPlanUpdate={onPlanUpdate} onError={onError} />
    </div>
  );
}

function SwapButton({
  slot,
  plan,
  onPlanUpdate,
  onError,
}: {
  slot: PlanSlot;
  plan: MealPlan;
  onPlanUpdate: (plan: MealPlan) => void;
  onError: (msg: string) => void;
}) {
  const requests = useRequestScope();
  const applications = useContext(SwapApplicationContext);
  const savedPlanId = plan.plan_id?.trim() ? plan.plan_id : undefined;
  const [open, setOpen] = useState(false);
  const [substitutions, setSubstitutions] = useState<SubstituteDish[]>([]);
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [informationalOnly, setInformationalOnly] = useState(false);

  const handleSuggest = async () => {
    if (!savedPlanId || applications.pending) return;
    const isCurrent = requests.start('suggestions');
    setLoading(true);
    try {
      const result = await getSubstitutions(slot.dish_id, plan.patient_id, 3, savedPlanId);
      if (!isCurrent()) return;
      setSubstitutions(result.substitutions || []);
      setNotice(result.notice);
      setInformationalOnly(result.informational_only);
      setOpen(true);
    } catch (err: any) {
      if (isCurrent()) onError(err.message || 'Failed to load substitutions');
    } finally {
      if (isCurrent()) setLoading(false);
    }
  };

  const handleApply = async (sub: SubstituteDish) => {
    if (!savedPlanId || informationalOnly || !applications.begin()) return;
    const isCurrent = requests.capture();
    setApplying(sub.dish_id);
    try {
      const newPlan = await applySwap({
        patient_id: plan.patient_id,
        dish_id: slot.dish_id,
        replacement_dish_id: sub.dish_id,
        plan_id: savedPlanId,
      });
      if (!isCurrent()) return;
      onPlanUpdate(newPlan);
      setOpen(false);
    } catch (err: any) {
      if (isCurrent()) onError(err.message || 'Failed to apply swap');
    } finally {
      applications.end();
      if (isCurrent()) setApplying(null);
    }
  };

  return (
    <>
      <button
        onClick={handleSuggest}
        disabled={loading || applications.pending || !savedPlanId}
        className="mt-2 rounded-lg bg-white px-2.5 py-1 text-xs font-semibold text-sky-700 ring-1 ring-sky-200 hover:bg-sky-50 disabled:text-slate-400 transition-colors"
      >
        {loading ? 'Loading…' : 'Suggest swaps'}
      </button>
      {!savedPlanId && <p className="mt-2 text-xs text-amber-800">Swaps require a saved plan ID. Reload a saved plan to choose its exact source.</p>}
      {open && (
        <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/40 p-4 backdrop-blur-sm sm:items-center">
          <div className="w-full max-w-3xl rounded-xl bg-white p-5 shadow-2xl ring-1 ring-slate-900/10">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-lg font-semibold text-slate-900">
                Swap suggestions for {slot.name}
              </h3>
              <button onClick={() => setOpen(false)} className="text-sm text-slate-500 hover:text-slate-700">
                Close
              </button>
            </div>
            <p className="mb-3 text-sm text-slate-600">Applying a swap replaces every occurrence of this dish in this saved plan.</p>
            {notice && (
              <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
                {notice}
              </div>
            )}
            {substitutions.length === 0 ? (
              <EmptyState title="No suggestions" description="No validated substitutions were found." />
            ) : (
              <div className="space-y-3">
                {substitutions.map((sub) => (
                  <SubstitutionCard
                    key={sub.dish_id}
                    sub={sub}
                    disabled={informationalOnly || applications.pending || applying !== null}
                    onApply={() => handleApply(sub)}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}

function SubstitutionCard({
  sub,
  disabled,
  onApply,
}: {
  sub: SubstituteDish;
  disabled: boolean;
  onApply: () => void;
}) {
  const days = Object.keys(sub.day_deltas || {});
  const nutrients = days.length > 0 ? Object.keys(sub.day_deltas[days[0]] || {}) : [];
  const highlight = ['sodium_mg', 'potassium_mg', 'phosphorus_mg'];

  return (
    <div className="rounded-lg border border-slate-200 p-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="font-semibold text-slate-900">{sub.name}</p>
          <p className="text-xs text-slate-500">
            {sub.category_match ? 'Same category' : 'Different category'} · ranking score {(sub.ranking_score ?? sub.distance).toFixed(2)} · cost Δ{' '}
            {sub.cost_delta.toFixed(2)}
          </p>
        </div>
        <button
          onClick={onApply}
          disabled={disabled}
          className="rounded-lg bg-sky-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-sky-700 disabled:bg-sky-300 transition-colors"
        >
          Apply swap
        </button>
      </div>
      <p className="mt-2 text-sm text-slate-700">{sub.reason}</p>
      {nutrients.length > 0 && (
        <div className="mt-3 overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-2 py-1 text-left text-xs font-semibold text-slate-700">Day</th>
                {nutrients.map((n) => (
                  <th
                    key={n}
                    className={`px-2 py-1 text-left text-xs font-semibold ${
                      highlight.includes(n) ? 'text-rose-700' : 'text-slate-700'
                    }`}
                  >
                    {n}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {days.map((day) => (
                <tr key={day}>
                  <td className="px-2 py-1 text-slate-900">Day {day}</td>
                  {nutrients.map((n) => {
                    const value = sub.day_deltas[day][n];
                    const isHighlight = highlight.includes(n);
                    return (
                      <td
                        key={n}
                        className={`px-2 py-1 text-xs ${
                          value > 0 ? 'text-rose-700' : value < 0 ? 'text-emerald-700' : 'text-slate-600'
                        } ${isHighlight ? 'font-semibold' : ''}`}
                      >
                        {value > 0 ? '+' : ''}
                        {value.toFixed(1)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function NutrientBar({ nutrient }: { nutrient: PlanTotal }) {
  const { value, unit, targets, compliant } = nutrient;
  const maxTarget = targets?.find((t) => t.kind === 'max');
  const minTarget = targets?.find((t) => t.kind === 'min');
    const target = maxTarget || minTarget || targets?.find((t) => t.kind === 'target');

  let percentage = 0;
  let overLimit = false;
  let belowMinimum = false;

  if (maxTarget && maxTarget.value > 0) {
    percentage = Math.min((value / maxTarget.value) * 100, 100);
    overLimit = value > maxTarget.value;
  } else if (minTarget && minTarget.value > 0) {
    percentage = Math.min((value / minTarget.value) * 100, 100);
    belowMinimum = value < minTarget.value && compliant !== true;
  } else if (target && target.value > 0) {
    percentage = Math.min((value / target.value) * 100, 100);
  }

  const barColor = overLimit ? 'bg-rose-500' : belowMinimum ? 'bg-amber-500' : 'bg-sky-500';

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <div className="flex items-center justify-between text-xs text-slate-600">
        <span className="font-medium text-slate-900">{nutrient.nutrient}</span>
        <span>
          {value} {unit}
        </span>
      </div>
      <div className="mt-2 h-2 w-full rounded-full bg-slate-100">
        <div className={`h-2 rounded-full transition-all ${barColor}`} style={{ width: `${percentage}%` }} />
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-1">
        {targets?.map((t, idx) => (
          <span key={idx} className="text-xs text-slate-500">
            {t.kind} {t.value} {t.unit}
          </span>
        ))}
        {compliant === true && (
          <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-800">OK</span>
        )}
        {compliant === false && (
          <span className="rounded-full bg-rose-100 px-2 py-0.5 text-xs font-semibold text-rose-800">Over limit</span>
        )}
        {compliant === null && (
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-600">No hard rule</span>
        )}
      </div>
      {overLimit && <p className="mt-1.5 text-xs font-medium text-rose-600" role="alert">Over limit</p>}
      {belowMinimum && <p className="mt-1.5 text-xs font-medium text-amber-600" role="alert">Below minimum</p>}
    </div>
  );
}
