import { useEffect, useRef, useState } from 'react';
import { listPatients, searchDishes, logMeal, getAdherenceSummary, getAdherenceDeviation } from '../api';
import type { Patient, Dish, AdherenceSummary, AdherenceDeviation, AdherenceAnalysis } from '../types';
import LoadingState from '../components/LoadingState';
import EmptyState from '../components/EmptyState';

const TODAY = new Date().toISOString().slice(0, 10);

const NUTRIENT_LABELS: Record<string, string> = {
  energy_kcal: 'Energy',
  protein_g: 'Protein',
  sodium_mg: 'Sodium',
  potassium_mg: 'Potassium',
  phosphorus_mg: 'Phosphorus',
  carbs_g: 'Carbs',
  fat_g: 'Fat',
  sat_fat_g: 'Sat. fat',
  fiber_g: 'Fiber',
  sugar_g: 'Sugar',
};

const MEAL_OPTIONS = ['breakfast', 'lunch', 'dinner'] as const;

export default function AdherenceScreen() {
  const [patients, setPatients] = useState<Patient[]>([]);
  const [loadingPatients, setLoadingPatients] = useState(true);
  const [patientsError, setPatientsError] = useState<string | null>(null);
  const [selectedPatient, setSelectedPatient] = useState<Patient | null>(null);
  const [activeTab, setActiveTab] = useState<'log' | 'summary' | 'trends'>('summary');

  const [summary, setSummary] = useState<AdherenceSummary | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);

  const [deviation, setDeviation] = useState<AdherenceDeviation | null>(null);
  const [deviationLoading, setDeviationLoading] = useState(false);
  const [deviationError, setDeviationError] = useState<string | null>(null);

  useEffect(() => {
    listPatients()
      .then((data) => setPatients(data || []))
      .catch((err) => setPatientsError(err.message || 'Failed to load patients'))
      .finally(() => setLoadingPatients(false));
  }, []);

  const loadData = (patientId: string) => {
    setSummaryError(null);
    setDeviationError(null);
    setSummaryLoading(true);
    setDeviationLoading(true);
    getAdherenceSummary(patientId)
      .then((data) => setSummary(data))
      .catch((err) => setSummaryError(err.message || 'Failed to load summary'))
      .finally(() => setSummaryLoading(false));
    getAdherenceDeviation(patientId)
      .then((data) => setDeviation(data))
      .catch((err) => setDeviationError(err.message || 'Failed to load trends'))
      .finally(() => setDeviationLoading(false));
  };

  return (
    <main className="min-h-screen bg-slate-50 pb-12">
      <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
        <div className="mb-6">
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Adherence</h1>
          <p className="mt-1 text-sm text-slate-500">
            Log the meals a patient actually eats and see how they compare to their nutrient
            envelope.
          </p>
        </div>

        <section className="mb-8 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
            Select patient
          </h2>
          {patientsError && (
            <div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
              {patientsError}
              <button onClick={() => setPatientsError(null)} className="ml-2 font-medium underline">
                Dismiss
              </button>
            </div>
          )}
          {loadingPatients ? (
            <LoadingState text="Loading patients…" />
          ) : patients.length === 0 ? (
            <EmptyState title="No patients found" description="Add patients or start the backend." />
          ) : (
            <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
              <div className="flex-1">
                <label htmlFor="adherence-patient" className="mb-1 block text-sm font-medium text-slate-700">
                  Patient
                </label>
                <select
                  id="adherence-patient"
                  value={selectedPatient?.id || ''}
                  onChange={(e) => {
                    const p = patients.find((pt) => pt.id === e.target.value) || null;
                    setSelectedPatient(p);
                    if (p) loadData(p.id);
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
          <div className="mb-4 rounded-xl border border-slate-200 bg-white p-1 shadow-sm sm:inline-flex">
            {[
              { key: 'summary', label: 'Summary' },
              { key: 'log', label: 'Log a meal' },
              { key: 'trends', label: 'Trends' },
            ].map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key as typeof activeTab)}
                className={`flex-1 rounded-lg px-4 py-2 text-sm font-medium transition-colors sm:flex-none ${
                  activeTab === tab.key
                    ? 'bg-sky-600 text-white'
                    : 'text-slate-600 hover:bg-slate-50'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        )}

        {selectedPatient && activeTab === 'log' && (
          <LogMealSection
            key={selectedPatient.id}
            patient={selectedPatient}
            onLogged={() => {
              loadData(selectedPatient.id);
            }}
          />
        )}

        {selectedPatient && activeTab === 'summary' && (
          <SummarySection summary={summary} loading={summaryLoading} error={summaryError} />
        )}

        {selectedPatient && activeTab === 'trends' && (
          <TrendsSection deviation={deviation} loading={deviationLoading} error={deviationError} />
        )}
      </div>
    </main>
  );
}

function LogMealSection({ patient, onLogged }: { patient: Patient; onLogged: () => void }) {
  const [date, setDate] = useState(TODAY);
  const [meal, setMeal] = useState<'breakfast' | 'lunch' | 'dinner'>('breakfast');
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<Dish[]>([]);
  const [searching, setSearching] = useState(false);
  const [logging, setLogging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [items, setItems] = useState<{ dish: Dish; quantity: number }[]>([]);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!query.trim()) return;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      searchDishes(query)
        .then((data) => setResults(data.dishes || []))
        .catch(() => setResults([]))
        .finally(() => setSearching(false));
    }, 300);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query]);

  const handleSelect = (dish: Dish) => {
    setItems((current) => [...current, { dish, quantity: 1 }]);
    setQuery('');
    setResults([]);
  };

  const handleSave = async () => {
    if (!patient) return;
    setLogging(true);
    setError(null);
    setSuccess(null);
    try {
      await logMeal({
        patient_id: patient.id,
        date,
        meal,
        items: items.map(({ dish, quantity }) => ({ dish_id: dish.dish_id, quantity })),
      });
      setSuccess(`Logged ${items.length} dishes for ${meal} on ${date}.`);
      setItems([]);
      setQuery('');
      setResults([]);
      onLogged();
    } catch (err: any) {
      setError(err.message || 'Failed to log meal');
    } finally {
      setLogging(false);
    }
  };

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="mb-4 text-lg font-semibold text-slate-900">Log a meal</h2>
      <p className="mb-4 text-sm text-slate-600">Add each dish and its servings, then save the meal. Saving replaces the existing log for this meal and date.</p>
      {items.length > 0 && (
        <div className="mb-6 space-y-3">
          {items.map(({ dish, quantity }, index) => (
            <div key={`${dish.dish_id}-${index}`} className="flex flex-wrap items-center gap-3">
              <span className="flex-1 text-sm text-slate-900">{dish.name}</span>
              <label className="text-sm text-slate-700">
                Servings
                <input type="number" min="0.25" max="10" step="0.25" value={quantity}
                  aria-label={`Servings of ${dish.name}`} disabled={logging}
                  onChange={(e) => setItems((current) => current.map((item, i) => i === index ? { ...item, quantity: Number(e.target.value) } : item))}
                  className="ml-2 w-20 rounded border border-slate-300 px-2 py-2 text-base" />
              </label>
              <button onClick={() => setItems((current) => current.filter((_, i) => i !== index))}
                disabled={logging} aria-label={`Remove ${dish.name}`}
                className="px-3 py-2 text-sm text-rose-700 underline">Remove</button>
            </div>
          ))}
          <button onClick={handleSave}
            disabled={logging || items.some((item) => !Number.isFinite(item.quantity) || item.quantity <= 0 || item.quantity > 10)}
            className="rounded-lg bg-sky-600 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-700 disabled:opacity-50">
            {logging ? 'Saving meal…' : 'Save meal'}
          </button>
        </div>
      )}

      {error && (
        <div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
          {error}
          <button onClick={() => setError(null)} className="ml-2 font-medium underline">
            Dismiss
          </button>
        </div>
      )}
      {success && (
        <div className="mb-4 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">
          {success}
          <button onClick={() => setSuccess(null)} className="ml-2 font-medium underline">
            Dismiss
          </button>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-3">
        <div>
          <label htmlFor="log-date" className="mb-1 block text-sm font-medium text-slate-700">
            Date
          </label>
          <input
            id="log-date"
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-sky-500 focus:ring-1 focus:ring-sky-500"
          />
        </div>
        <div>
          <label htmlFor="log-meal" className="mb-1 block text-sm font-medium text-slate-700">
            Meal
          </label>
          <select
            id="log-meal"
            value={meal}
            onChange={(e) => setMeal(e.target.value as typeof meal)}
            className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-sky-500 focus:ring-1 focus:ring-sky-500"
          >
            {MEAL_OPTIONS.map((m) => (
              <option key={m} value={m}>
                {m.charAt(0).toUpperCase() + m.slice(1)}
              </option>
            ))}
          </select>
        </div>
        <div className="sm:col-span-1">
          <label htmlFor="dish-search" className="mb-1 block text-sm font-medium text-slate-700">
            Search dish
          </label>
          <input
            id="dish-search"
            type="text"
            value={query}
            onChange={(e) => {
              const value = e.target.value;
              setQuery(value);
              if (value.trim()) {
                setSearching(true);
              } else {
                setSearching(false);
                setResults([]);
              }
            }}
            placeholder="e.g. chicken rice"
            className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-sky-500 focus:ring-1 focus:ring-sky-500"
          />
        </div>
      </div>

      <div className="mt-4">
        {!query.trim() ? (
          <p className="text-sm text-slate-500">Type a dish name to search.</p>
        ) : searching ? (
          <LoadingState text="Searching dishes…" />
        ) : results.length === 0 ? (
          <EmptyState title="No dishes found" description="Try a different search term." />
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {results.map((dish) => (
              <li key={dish.dish_id}>
                <button
                  onClick={() => handleSelect(dish)}
                  disabled={logging}
                  className="flex h-full w-full flex-col items-start rounded-xl border border-slate-200 bg-white p-4 text-left shadow-sm transition-colors hover:border-sky-300 hover:bg-sky-50/40 disabled:opacity-60"
                >
                  <span className="text-sm font-semibold text-slate-900">{dish.name}</span>
                  <span className="text-xs text-slate-500">
                    {dish.category} {dish.cuisine ? `· ${dish.cuisine}` : ''}
                  </span>
                  <span className="mt-2 text-xs text-slate-500">
                    Na {fmt(dish.sodium_mg)}mg · K {fmt(dish.potassium_mg)}mg · P{' '}
                    {fmt(dish.phosphorus_mg)}mg
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

function SummarySection({
  summary,
  loading,
  error,
}: {
  summary: AdherenceSummary | null;
  loading: boolean;
  error: string | null;
}) {
  if (loading) return <LoadingState text="Loading summary…" />;
  if (error)
    return (
      <div className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
        {error}
      </div>
    );
  if (!summary) return null;

  const versions = summary.envelope_versions_used || [];
  const multiVersion = versions.length > 1;

  return (
    <div className="space-y-6">
      {summary.informational_only && summary.notice && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          {summary.notice}
        </div>
      )}

      {!!summary.unattributed_days?.length && <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
        {summary.unattributed_days.length} logged day(s) have no historical approval and are excluded from target comparisons.
      </p>}

      {multiVersion && (
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm text-slate-600">
          History spans {versions.length} envelope versions.
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard label="Days logged" value={summary.aggregate.days_logged} />
        <StatCard label="Hard violation days" value={summary.aggregate.hard_violation_days} tone="rose" />
        <StatCard
          label="Days without hard violations"
          value={summary.aggregate.days_logged - summary.aggregate.hard_violation_days}
          tone="emerald"
        />
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h3 className="mb-4 text-lg font-semibold text-slate-900">
          Last {summary.window.days} days
        </h3>
        {summary.days.length === 0 ? (
          <EmptyState
            title="No meals logged yet"
            description="Use the Log a meal tab to record what the patient ate."
          />
        ) : (
          <div className="space-y-4">
            {summary.days.map((day) => (
              <DayCard key={day.date} day={day} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function DayCard({ day }: { day: import('../types').AdherenceDay }) {
  const completeness = day.completeness;
  const complete = completeness ? completeness.complete : day.meals.length >= 3;
  const mealsLogged = completeness ? completeness.meals_logged : day.meals.length;
  const expectedMeals = completeness ? completeness.expected_meals : 3;

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h4 className="text-sm font-semibold text-slate-900">{formatDate(day.date)}</h4>
        {day.compliant ? (
          <span className="inline-flex items-center rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-800">
            Compliant
          </span>
        ) : (
          <span className="inline-flex items-center rounded-full bg-rose-100 px-2 py-0.5 text-xs font-medium text-rose-800">
            Hard violation
          </span>
        )}
        <span
          className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
            complete ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800'
          }`}
        >
          {complete ? 'Complete' : `${mealsLogged} of ${expectedMeals} meals`}
        </span>
        {day.envelope_id && (
          <span className="text-xs text-slate-400">
            {day.envelope_id}
            {day.envelope_version ? ` v${day.envelope_version}` : ''}
          </span>
        )}
      </div>
      {day.meals.length > 0 && (
        <p className="mb-3 text-xs text-slate-500">
          {Array.from(new Set(day.meals.map((m) => m.meal)))
            .map((m) => m.charAt(0).toUpperCase() + m.slice(1))
            .join(' · ')}
        </p>
      )}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {day.nutrients.map((n, idx) => (
          <NutrientSummaryBar key={`${n.nutrient}-${idx}`} analysis={n} />
        ))}
      </div>
      {!day.compliant &&
        day.hard_violations
          .filter(
            (v): v is import('../types').ExcludedDishViolation =>
              'type' in v && v.type === 'excluded_dish',
          )
          .map((v) => (
            <div
              key={v.dish_id}
              className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-800"
            >
              <span className="font-medium">{v.dish_name || v.dish_id}</span>
              {v.meal ? <span className="text-rose-600"> · {v.meal}</span> : null}
              <p className="mt-0.5">{v.reason}</p>
            </div>
          ))}
    </div>
  );
}

function NutrientSummaryBar({ analysis }: { analysis: AdherenceAnalysis }) {
  const limit = analysis.limit || 1;
  const pct = Math.min((analysis.total / limit) * 100, 100);
  const isViolation = analysis.status === 'hard_violation';
  const isGap = analysis.status === 'soft_gap';
  const barColor = isViolation ? 'bg-rose-500' : isGap ? 'bg-amber-500' : 'bg-emerald-500';
  const contributors = analysis.contributors || [];

  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50/50 p-3">
      <div className="flex items-center justify-between text-xs text-slate-600">
        <span className="font-medium text-slate-900">{nutrientLabel(analysis.nutrient)}</span>
        <span>
          {fmt(analysis.total)} / {fmt(analysis.limit)} {analysis.unit}
        </span>
      </div>
      <div className="mt-2 h-2 w-full rounded-full bg-slate-100">
        <div className={`h-2 rounded-full ${barColor}`} style={{ width: `${pct}%` }} />
      </div>
      <div className="mt-1.5 flex items-center gap-1 text-xs">
        {analysis.status === 'hard_violation' && (
          <span className="font-medium text-rose-600">Over limit</span>
        )}
        {analysis.status === 'soft_gap' && (
          <span className="font-medium text-amber-600">Below aim</span>
        )}
        {analysis.status === 'ok' && (
          <span className="font-medium text-emerald-600">On track</span>
        )}
      </div>
      {contributors.length > 0 && (
        <div className="mt-2 text-xs text-slate-500">
          <span className="font-medium text-slate-600">Top contributors:</span>{' '}
          {contributors
            .map((c: any) => `${c.dish_name || c.dish_id} ${fmt(c.amount)}${analysis.unit}`)
            .join(', ')}
        </div>
      )}
    </div>
  );
}

function TrendsSection({
  deviation,
  loading,
  error,
}: {
  deviation: AdherenceDeviation | null;
  loading: boolean;
  error: string | null;
}) {
  if (loading) return <LoadingState text="Loading trends…" />;
  if (error)
    return (
      <div className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
        {error}
      </div>
    );
  if (!deviation) return null;

  const worsening = deviation.flags.filter((f) => f.direction === 'worsening');

  return (
    <div className="space-y-6">
      {deviation.informational_only && deviation.notice && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          {deviation.notice}
        </div>
      )}

      {worsening.length > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
          <p className="font-medium">Trends to review</p>
          <ul className="mt-1 list-disc space-y-1 pl-5">
            {worsening.map((f) => (
              <li key={f.series_key}>{f.reason}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h3 className="mb-4 text-lg font-semibold text-slate-900">Nutrient trends</h3>
        {Object.values(deviation.series).length === 0 ? (
          <EmptyState title="No trend data yet" description="Log all three meals on at least three days to assess trends." />
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Object.entries(deviation.series).map(([seriesKey, s]) => {
              const flag = deviation.flags.find((f) => f.series_key === seriesKey);
              return <SeriesCard key={seriesKey} series={s} flag={flag} />;
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function SeriesCard({
  series,
  flag,
}: {
  series: import('../types').AdherenceSeries;
  flag: import('../types').TrendFlag | undefined;
}) {
  const latest = series.points[series.points.length - 1];
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between">
        <span className="text-sm font-semibold text-slate-900">{nutrientLabel(series.nutrient)}</span>
        <span className="text-xs text-slate-500">{series.kind}</span>
      </div>
      <div className="mt-2 text-xs text-slate-600">
        Limit {fmt(series.limit)} {series.unit}
      </div>
      {latest && (
        <div className="mt-1 text-xs text-slate-600">
          Latest {fmt(latest.total)} {series.unit} ({latest.pct > 0 ? '+' : ''}
          {fmt(latest.pct)}%)
        </div>
      )}
      {flag && (
        <div
          className={`mt-3 rounded-lg px-3 py-2 text-xs ${
            flag.direction === 'worsening'
              ? 'bg-rose-50 text-rose-800'
              : 'bg-emerald-50 text-emerald-800'
          }`}
        >
          <span className="font-medium">
            {flag.direction === 'worsening' ? 'Worsening' : 'Improving'}
          </span>{' '}
          · {flag.slope_pct_per_day > 0 ? '+' : ''}
          {fmt(flag.slope_pct_per_day)} pp/day
          {flag.severity === 'alert' && (
            <span className="ml-1 font-medium text-rose-600">· Alert</span>
          )}
        </div>
      )}
      {!flag && (
        <div className="mt-3 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">
          Stable
        </div>
      )}
    </div>
  );
}

function StatCard({
  label,
  value,
  tone = 'sky',
}: {
  label: string;
  value: number;
  tone?: 'sky' | 'rose' | 'emerald';
}) {
  const toneClass: Record<string, string> = {
    sky: 'bg-sky-50 text-sky-800',
    rose: 'bg-rose-50 text-rose-800',
    emerald: 'bg-emerald-50 text-emerald-800',
  };
  return (
    <div className={`rounded-xl border border-slate-200 p-5 ${toneClass[tone]}`}>
      <p className="text-2xl font-semibold">{value}</p>
      <p className="text-xs font-medium opacity-80">{label}</p>
    </div>
  );
}

function fmt(value: number | undefined): string {
  if (value === undefined || value === null) return '—';
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

function nutrientLabel(key: string): string {
  return NUTRIENT_LABELS[key] || key;
}

function formatDate(iso: string): string {
  const d = new Date(iso + 'T00:00:00');
  return d.toLocaleDateString(undefined, { weekday: 'short', year: 'numeric', month: 'short', day: 'numeric' });
}
