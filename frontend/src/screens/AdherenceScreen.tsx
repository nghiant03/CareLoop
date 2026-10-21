import { useEffect, useRef, useState } from 'react';
import { listPatients, searchDishes, logMeal, getCalendarMetadata, getAdherenceSummary, getAdherenceDeviation } from '../api';
import type { Patient, Dish, AdherenceSummary, AdherenceDeviation, AdherenceAnalysis } from '../types';
import LoadingState from '../components/LoadingState';
import EmptyState from '../components/EmptyState';
import PageHeader from '../components/PageHeader';
import RangeBar from '../components/RangeBar';
import { useRequestScope } from '../hooks/useRequestScope';

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
  const requests = useRequestScope();
  const selectionIsCurrent = requests.capture();
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
    const isCurrent = requests.start('adherence');
    setSummaryError(null);
    setDeviationError(null);
    setSummaryLoading(true);
    setDeviationLoading(true);
    getAdherenceSummary(patientId)
      .then((data) => { if (isCurrent()) setSummary(data); })
      .catch((err) => { if (isCurrent()) setSummaryError(err.message || 'Failed to load summary'); })
      .finally(() => { if (isCurrent()) setSummaryLoading(false); });
    getAdherenceDeviation(patientId)
      .then((data) => { if (isCurrent()) setDeviation(data); })
      .catch((err) => { if (isCurrent()) setDeviationError(err.message || 'Failed to load trends'); })
      .finally(() => { if (isCurrent()) setDeviationLoading(false); });
  };

  return (
    <main className="pb-12">
      <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
        <PageHeader code="ADH" title="Adherence">
          Log the meals a patient actually eats and see how they compare to their nutrient
          envelope.
        </PageHeader>

        <section className="panel mb-6 p-5">
          <h2 className="micro-label mb-3 border-b border-rule pb-2">
            Select patient
          </h2>
          {patientsError && (
            <div className="notice notice-error mb-4">
              {patientsError}
              <button onClick={() => setPatientsError(null)} className="ml-2 font-semibold underline">
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
                <label htmlFor="adherence-patient" className="micro-label mb-1 block">
                  Patient
                </label>
                <select
                  id="adherence-patient"
                  value={selectedPatient?.id || ''}
                  onChange={(e) => {
                    requests.reset();
                    setSummary(null);
                    setDeviation(null);
                    setSummaryError(null);
                    setDeviationError(null);
                    setSummaryLoading(false);
                    setDeviationLoading(false);
                    const p = patients.find((pt) => pt.id === e.target.value) || null;
                    setSelectedPatient(p);
                    if (p) loadData(p.id);
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
          <div className="mb-6 flex border-b border-rule-2">
            {[
              { key: 'summary', label: 'Summary' },
              { key: 'log', label: 'Log a meal' },
              { key: 'trends', label: 'Trends' },
            ].map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key as typeof activeTab)}
                className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium transition-colors ${
                  activeTab === tab.key
                    ? 'border-ink text-ink'
                    : 'border-transparent text-ink-3 hover:border-rule-2 hover:text-ink'
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
              if (selectionIsCurrent()) loadData(selectedPatient.id);
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
  const [date, setDate] = useState('');
  const dateEdited = useRef(false);
  const [calendarError, setCalendarError] = useState<string | null>(null);
  const [calendarRetry, setCalendarRetry] = useState(0);
  const [manualDateConfirmed, setManualDateConfirmed] = useState(false);
  const searchRequests = useRequestScope();
  const [meal, setMeal] = useState<'breakfast' | 'lunch' | 'dinner'>('breakfast');
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<Dish[]>([]);
  const [searching, setSearching] = useState(false);
  const [logging, setLogging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [items, setItems] = useState<{ dish: Dish; quantity: number }[]>([]);
  const [searchError, setSearchError] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    getCalendarMetadata()
      .then(({ today }) => {
        if (current && !dateEdited.current) setDate(today);
      })
      .catch((err: Error) => {
        if (current) setCalendarError(err.message || 'Could not load the server date.');
      });
    return () => { current = false; };
  }, [calendarRetry]);

  useEffect(() => {
    const isCurrent = searchRequests.start('dish-search');
    if (!query.trim()) return;
    const timer = setTimeout(() => {
      searchDishes(query)
        .then((data) => { if (isCurrent()) setResults(data.dishes || []); })
        .catch((err: Error) => { if (isCurrent()) setSearchError(err.message || 'Dish search unavailable'); })
        .finally(() => { if (isCurrent()) setSearching(false); });
    }, 300);
    return () => {
      clearTimeout(timer);
      searchRequests.reset();
    };
  }, [query, searchRequests]);

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
    <section className="panel p-5">
      <h2 className="text-lg font-bold tracking-tight text-ink">Log a meal</h2>
      <p className="mb-4 mt-1 text-sm text-ink-3">Add each dish and its servings, then save the meal. Saving replaces the existing log for this meal and date.</p>
      {items.length > 0 && (
        <div className="mb-6 border border-rule">
          {items.map(({ dish, quantity }, index) => (
            <div key={`${dish.dish_id}-${index}`} className={`flex flex-wrap items-center gap-3 px-3 py-2.5 ${index > 0 ? 'border-t border-rule' : ''}`}>
              <span className="flex-1 text-sm font-medium text-ink">{dish.name}</span>
              <label className="text-sm text-ink-2">
                Servings
                <input type="number" min="0.25" max="10" step="0.25" value={quantity}
                  aria-label={`Servings of ${dish.name}`} disabled={logging}
                  onChange={(e) => setItems((current) => current.map((item, i) => i === index ? { ...item, quantity: Number(e.target.value) } : item))}
                  className="field num ml-2 w-20! px-2 py-1.5 text-sm" />
              </label>
              <button onClick={() => setItems((current) => current.filter((_, i) => i !== index))}
                disabled={logging} aria-label={`Remove ${dish.name}`}
                className="px-2 py-1.5 text-sm font-medium text-flag underline decoration-flag-rule underline-offset-4">Remove</button>
            </div>
          ))}
          <div className="border-t border-rule bg-panel px-3 py-2.5">
            <button onClick={handleSave}
              disabled={logging || !date || (!!calendarError && !manualDateConfirmed) || items.some((item) => !Number.isFinite(item.quantity) || item.quantity <= 0 || item.quantity > 10)}
              className="btn-primary">
              {logging ? 'Saving meal…' : 'Save meal'}
            </button>
          </div>
        </div>
      )}

      {error && (
        <div className="notice notice-error mb-4">
          {error}
          <button onClick={() => setError(null)} className="ml-2 font-semibold underline">
            Dismiss
          </button>
        </div>
      )}
      {success && (
        <div className="notice notice-ok mb-4">
          {success}
          <button onClick={() => setSuccess(null)} className="ml-2 font-semibold underline">
            Dismiss
          </button>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-3">
        <div>
          <label htmlFor="log-date" className="micro-label mb-1 block">
            Date
          </label>
          <input
            id="log-date"
            type="date"
            value={date}
            onChange={(e) => { dateEdited.current = true; setDate(e.target.value); setManualDateConfirmed(false); }}
            className="field"
          />
          {calendarError ? (
            <div className="mt-1 text-xs text-flag" role="alert">
              <p>Server date unavailable. Retry, or enter a date and confirm manual entry.</p>
              <button type="button" className="mt-1 font-semibold underline" onClick={() => { setCalendarError(null); setCalendarRetry((n) => n + 1); }}>Retry</button>
              {date && <button type="button" className="ml-3 mt-1 font-semibold underline" onClick={() => setManualDateConfirmed(true)}>Use this date manually</button>}
            </div>
          ) : (
            <p className="mt-1 text-xs text-ink-3">{date ? 'Defaults to the server’s calendar date.' : 'Loading server date…'}</p>
          )}
        </div>
        <div>
          <label htmlFor="log-meal" className="micro-label mb-1 block">
            Meal
          </label>
          <select
            id="log-meal"
            value={meal}
            onChange={(e) => setMeal(e.target.value as typeof meal)}
            className="field"
          >
            {MEAL_OPTIONS.map((m) => (
              <option key={m} value={m}>
                {m.charAt(0).toUpperCase() + m.slice(1)}
              </option>
            ))}
          </select>
        </div>
        <div className="sm:col-span-1">
          <label htmlFor="dish-search" className="micro-label mb-1 block">
            Search dish
          </label>
          <input
            id="dish-search"
            type="text"
            value={query}
            onChange={(e) => {
              const value = e.target.value;
              searchRequests.reset();
              setSearchError(null);
              setResults([]);
              setQuery(value);
              if (value.trim()) {
                setSearching(true);
              } else {
                setSearching(false);
                setResults([]);
              }
            }}
            placeholder="e.g. chicken rice"
            className="field"
          />
        </div>
      </div>

      <div className="mt-4">
        {!query.trim() ? (
          <p className="text-sm text-ink-3">Type a dish name to search.</p>
        ) : searching ? (
          <LoadingState text="Searching dishes…" />
        ) : searchError ? (
          <p role="alert" className="text-sm text-flag">Search unavailable: {searchError}</p>
        ) : results.length === 0 ? (
          <EmptyState title="No dishes found" description="Try a different search term." />
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {results.map((dish) => (
              <li key={dish.dish_id}>
                <button
                  onClick={() => handleSelect(dish)}
                  disabled={logging}
                  className="flex h-full w-full flex-col items-start border border-rule bg-card p-4 text-left transition-colors hover:border-ink-3 hover:bg-panel disabled:opacity-60"
                >
                  <span className="text-sm font-semibold text-ink">{dish.name}</span>
                  <span className="text-xs text-ink-3">
                    {dish.category} {dish.cuisine ? `· ${dish.cuisine}` : ''}
                  </span>
                  <span className="num mt-2 border-t border-rule pt-2 text-xs text-ink-2">
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
      <div className="notice notice-error">
        {error}
      </div>
    );
  if (!summary) return null;

  const versions = summary.envelope_versions_used || [];
  const multiVersion = versions.length > 1;

  return (
    <div className="space-y-6">
      {summary.informational_only && summary.notice && (
        <div className="notice notice-warn">
          {summary.notice}
        </div>
      )}

      {!!summary.unattributed_days?.length && <p className="notice notice-warn">
        {summary.unattributed_days.length} logged day(s) have no historical approval and are excluded from target comparisons.
      </p>}

      {multiVersion && (
        <div className="notice notice-info">
          History spans {versions.length} envelope versions.
        </div>
      )}

      <div className="grid grid-cols-1 divide-y divide-rule border border-rule bg-card sm:grid-cols-3 sm:divide-x sm:divide-y-0">
        <SummaryStat label="Days logged" value={summary.aggregate.days_logged} />
        <SummaryStat label="Hard violation days" value={summary.aggregate.hard_violation_days} tone="flag" />
        <SummaryStat
          label="Days without hard violations"
          value={summary.aggregate.days_logged - summary.aggregate.hard_violation_days}
          tone="ok"
        />
      </div>

      <div className="panel p-5">
        <h3 className="mb-4 text-lg font-bold tracking-tight text-ink">
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
    <div className="border border-rule bg-card p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2 border-b border-rule pb-2.5">
        <h4 className="text-sm font-bold text-ink">{formatDate(day.date)}</h4>
        {day.compliant ? (
          <span className="flag flag-ok">Compliant</span>
        ) : (
          <span className="flag flag-bad">Hard violation</span>
        )}
        <span className={`flag ${complete ? 'flag-ok' : 'flag-warn'}`}>
          {complete ? 'Complete' : `${mealsLogged} of ${expectedMeals} meals`}
        </span>
        {day.envelope_id && (
          <span className="num text-xs text-ink-3">
            {day.envelope_id}
            {day.envelope_version ? ` v${day.envelope_version}` : ''}
          </span>
        )}
      </div>
      {day.meals.length > 0 && (
        <p className="mb-3 text-xs text-ink-3">
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
              className="notice notice-error mt-3 text-xs"
            >
              <span className="font-semibold">{v.dish_name || v.dish_id}</span>
              {v.meal ? <span> · {v.meal}</span> : null}
              <p className="mt-0.5">{v.reason}</p>
            </div>
          ))}
    </div>
  );
}

function NutrientSummaryBar({ analysis }: { analysis: AdherenceAnalysis }) {
  const limit = analysis.limit || 1;
  const isViolation = analysis.status === 'hard_violation';
  const isGap = analysis.status === 'soft_gap';
  const contributors = analysis.contributors || [];

  return (
    <div className="border border-rule bg-panel/50 p-3">
      <div className="flex items-center justify-between text-xs">
        <span className="font-medium text-ink">{nutrientLabel(analysis.nutrient)}</span>
        <span className="num text-ink-2">
          {fmt(analysis.total)} / {fmt(analysis.limit)} {analysis.unit}
        </span>
      </div>
      <div className="mt-2">
        <RangeBar
          value={analysis.total}
          limit={limit}
          kind={analysis.kind}
          state={isViolation ? 'over' : isGap ? 'under' : 'ok'}
        />
      </div>
      <div className="mt-1.5 flex items-center gap-1 text-xs">
        {analysis.status === 'hard_violation' && (
          <span className="font-semibold text-flag">Over limit</span>
        )}
        {analysis.status === 'soft_gap' && (
          <span className="font-semibold text-warn">{analysis.kind === 'target' ? (analysis.direction === 'over' ? 'Above target' : analysis.direction === 'under' ? 'Below target' : 'Target deviation') : 'Below aim'}</span>
        )}
        {analysis.status === 'ok' && (
          <span className="font-semibold text-ok">On track</span>
        )}
      </div>
      {contributors.length > 0 && (
        <div className="mt-2 text-xs text-ink-3">
          <span className="font-medium text-ink-2">Top contributors:</span>{' '}
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
      <div className="notice notice-error">
        {error}
      </div>
    );
  if (!deviation) return null;

  const worsening = deviation.flags.filter((f) => f.direction === 'worsening');

  return (
    <div className="space-y-6">
      {deviation.informational_only && deviation.notice && (
        <div className="notice notice-warn">
          {deviation.notice}
        </div>
      )}

      {worsening.length > 0 && (
        <div className="border border-warn-rule bg-warn-bg p-4 text-sm text-warn">
          <p className="font-semibold">Trends to review</p>
          <ul className="mt-1 list-disc space-y-1 pl-5">
            {worsening.map((f) => (
              <li key={f.series_key}>{f.reason}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="panel p-5">
        <h3 className="mb-4 text-lg font-bold tracking-tight text-ink">Nutrient trends</h3>
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
  const assessmentAvailable = series.points.filter((point) => point.complete !== false).length >= 3;
  return (
    <div className="border border-rule bg-card p-4">
      <div className="flex items-center justify-between">
        <span className="text-sm font-semibold text-ink">{nutrientLabel(series.nutrient)}</span>
        <span className="micro-label">{series.kind}</span>
      </div>
      <div className="num mt-2 text-xs text-ink-2">
        Limit {fmt(series.limit)} {series.unit}
      </div>
      {latest && (
        <div className="num mt-1 text-xs text-ink-2">
          Latest {fmt(latest.total)} {series.unit} ({latest.pct > 0 ? '+' : ''}
          {fmt(latest.pct)}%)
        </div>
      )}
      {flag && (
        <div
          className={`notice mt-3 text-xs ${
            flag.direction === 'worsening'
              ? 'notice-error'
              : 'notice-ok'
          }`}
        >
          <span className="font-semibold">
            {flag.direction === 'worsening' ? 'Worsening' : 'Improving'}
          </span>{' '}
          · <span className="num">{flag.slope_pct_per_day > 0 ? '+' : ''}
          {fmt(flag.slope_pct_per_day)} pp/day</span>
          {flag.severity === 'alert' && (
            <span className="ml-1 font-semibold">· Alert</span>
          )}
        </div>
      )}
      {!flag && (
        <div className="mt-3 border border-rule bg-panel px-3 py-2 text-xs text-ink-2">
          {assessmentAvailable ? 'No detected trend' : 'Not assessed: fewer than three complete logged days'}
        </div>
      )}
    </div>
  );
}

function SummaryStat({
  label,
  value,
  tone = 'ink',
}: {
  label: string;
  value: number;
  tone?: 'ink' | 'flag' | 'ok';
}) {
  const toneClass: Record<string, string> = {
    ink: 'text-ink',
    flag: 'text-flag',
    ok: 'text-ok',
  };
  return (
    <div className="p-5">
      <p className={`num text-3xl font-semibold tracking-tight ${toneClass[tone]}`}>{value}</p>
      <p className="micro-label mt-1">{label}</p>
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

function formatDate(iso: string) {
  const d = new Date(iso + 'T00:00:00');
  return d.toLocaleDateString(undefined, { weekday: 'short', year: 'numeric', month: 'short', day: 'numeric' });
}
