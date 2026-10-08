import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  listPatients,
  getReviewQueue,
  getReviewItems,
  acknowledgeReview,
  actionReview,
  proposalReview,
} from '../api';
import type { Patient, ReviewItem } from '../types';
import LoadingState from '../components/LoadingState';
import EmptyState from '../components/EmptyState';
import { useRequestScope } from '../hooks/useRequestScope';

type ReviewStatus = 'open' | 'acknowledged' | 'actioned' | 'all';

const STATUS_TABS: { key: ReviewStatus; label: string }[] = [
  { key: 'open', label: 'Open' },
  { key: 'acknowledged', label: 'Acknowledged' },
  { key: 'actioned', label: 'Actioned' },
  { key: 'all', label: 'All' },
];

export default function ReviewQueueScreen() {
  const requests = useRequestScope();
  const [patients, setPatients] = useState<Patient[]>([]);
  const [loadingPatients, setLoadingPatients] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedPatientId, setSelectedPatientId] = useState<string>('');
  const [status, setStatus] = useState<ReviewStatus>('open');
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [history, setHistory] = useState<ReviewItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [actionForms, setActionForms] = useState<Record<string, { action: string; note: string }>>({});
  const [working, setWorking] = useState<Record<string, boolean>>({});
  const navigate = useNavigate();

  useEffect(() => {
    listPatients()
      .then((data) => setPatients(data || []))
      .catch((err) => setError(err.message || 'Failed to load patients'))
      .finally(() => setLoadingPatients(false));
  }, []);

  const resetFilter = () => {
    requests.reset();
    setItems([]);
    setHistory([]);
    setError(null);
    setActionForms({});
    setWorking({});
    setLoading(true);
    setHistoryLoading(true);
  };

  const loadQueue = useCallback(() => {
    const isCurrent = requests.start('queue');
    return getReviewQueue(selectedPatientId || null, status)
      .then((result) => { if (isCurrent()) setItems(result.items); })
      .catch((err: Error) => { if (isCurrent()) setError(err.message || 'Failed to load review queue'); })
      .finally(() => { if (isCurrent()) setLoading(false); });
  }, [requests, selectedPatientId, status]);

  const loadHistory = useCallback(() => {
    const isCurrent = requests.start('history');
    return getReviewItems(selectedPatientId || undefined, 'actioned')
      .then((result) => { if (isCurrent()) setHistory(result.items); })
      .catch(() => { if (isCurrent()) setHistory([]); })
      .finally(() => { if (isCurrent()) setHistoryLoading(false); });
  }, [requests, selectedPatientId]);

  useEffect(() => {
    loadQueue();
    loadHistory();
  }, [loadQueue, loadHistory]);

  const handleAcknowledge = async (item: ReviewItem) => {
    const isCurrent = requests.capture();
    setWorking((w) => ({ ...w, [item.review_id]: true }));
    try {
      await acknowledgeReview(item.review_id);
      if (isCurrent()) {
        setLoading(true);
        await loadQueue();
      }
    } catch (err: any) {
      if (isCurrent()) setError(err.message || 'Failed to acknowledge item');
    } finally {
      if (isCurrent()) setWorking((w) => ({ ...w, [item.review_id]: false }));
    }
  };

  const handleAction = async (item: ReviewItem) => {
    const isCurrent = requests.capture();
    const form = actionForms[item.review_id] || { action: '', note: '' };
    if (!form.action.trim()) return;
    setWorking((w) => ({ ...w, [item.review_id]: true }));
    try {
      await actionReview(item.review_id, {
        action: form.action.trim(),
        note: form.note.trim() || undefined,
      });
      if (!isCurrent()) return;
      setActionForms((f) => ({ ...f, [item.review_id]: { action: '', note: '' } }));
      setLoading(true);
      setHistoryLoading(true);
      await loadQueue();
      if (isCurrent()) await loadHistory();
    } catch (err: any) {
      if (isCurrent()) setError(err.message || 'Failed to record action');
    } finally {
      if (isCurrent()) setWorking((w) => ({ ...w, [item.review_id]: false }));
    }
  };

  const handleProposal = async (item: ReviewItem) => {
    const isCurrent = requests.capture();
    setWorking((w) => ({ ...w, [item.review_id]: true }));
    try {
      const result = await proposalReview(item.review_id);
      if (!isCurrent()) return;
      setLoading(true);
      await loadQueue();
      if (isCurrent()) navigate(`/?envelope=${result.envelope_id}`);
    } catch (err: any) {
      if (isCurrent()) setError(err.message || 'Failed to create proposal');
    } finally {
      if (isCurrent()) setWorking((w) => ({ ...w, [item.review_id]: false }));
    }
  };

  const selectedPatient = patients.find((p) => p.id === selectedPatientId) || null;

  return (
    <main className="min-h-screen bg-slate-50 pb-12">
      <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
        <div className="mb-6">
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Review queue</h1>
          <p className="mt-1 text-sm text-slate-500">
            Triage adherence flags, hard-violation days, and lab trends. Acknowledge, record an action,
            or create a revised envelope proposal.
          </p>
        </div>

        {error && (
          <div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
            {error}
            <button onClick={() => setError(null)} className="ml-2 font-medium underline hover:text-rose-900">
              Dismiss
            </button>
          </div>
        )}

        <section className="mb-8 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
            Filter
          </h2>
          {loadingPatients ? (
            <LoadingState text="Loading patients…" />
          ) : patients.length === 0 ? (
            <EmptyState title="No patients found" description="Add patients or start the backend." />
          ) : (
            <div className="flex flex-col gap-4 sm:flex-row sm:items-end">
              <div className="flex-1">
                <label htmlFor="review-patient" className="mb-1 block text-sm font-medium text-slate-700">
                  Patient
                </label>
                <select
                  id="review-patient"
                  value={selectedPatientId}
                  onChange={(e) => { resetFilter(); setSelectedPatientId(e.target.value); }}
                  className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-sky-500 focus:ring-1 focus:ring-sky-500"
                >
                  <option value="">All patients</option>
                  {patients.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name || p.id} — {p.diagnoses?.join(', ')}
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex-1">
                <label htmlFor="review-status" className="mb-1 block text-sm font-medium text-slate-700">
                  Status
                </label>
                <div className="flex flex-wrap gap-2">
                  {STATUS_TABS.map((tab) => (
                    <button
                      key={tab.key}
                      onClick={() => { if (status !== tab.key) { resetFilter(); setStatus(tab.key); } }}
                      className={`rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                        status === tab.key
                          ? 'bg-sky-600 text-white'
                          : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
                      }`}
                    >
                      {tab.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}
        </section>

        {selectedPatient && (
          <div className="mb-6 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <p className="text-sm text-slate-500">
              Selected patient: <span className="font-semibold text-slate-900">{selectedPatient.name || selectedPatient.id}</span>
              {' · '}
              {selectedPatient.age} yrs · {selectedPatient.sex} · {selectedPatient.diagnoses?.join(', ')}
            </p>
          </div>
        )}

        {loading ? (
          <LoadingState text="Loading review queue…" />
        ) : items.length === 0 ? (
          <EmptyState
            title="No review items"
            description={
              selectedPatientId
                ? `No ${status === 'all' ? '' : status} review items for this patient.`
                : `No ${status === 'all' ? '' : status} review items across patients.`
            }
          />
        ) : (
          <div className="space-y-4">
            {items.map((item) => (
              <ReviewCard
                key={item.review_id}
                item={item}
                working={!!working[item.review_id]}
                actionForm={actionForms[item.review_id] || { action: '', note: '' }}
                onActionFormChange={(form) =>
                  setActionForms((f) => ({ ...f, [item.review_id]: form }))
                }
                onAcknowledge={() => handleAcknowledge(item)}
                onAction={() => handleAction(item)}
                onProposal={() => handleProposal(item)}
              />
            ))}
          </div>
        )}

        <section className="mt-10">
          <h2 className="mb-4 text-lg font-semibold text-slate-900">History</h2>
          {historyLoading ? (
            <LoadingState text="Loading history…" />
          ) : history.length === 0 ? (
            <EmptyState title="No history" description="Recorded actions will appear here." />
          ) : (
            <div className="space-y-3">
              {history.map((item) => (
                <HistoryRow key={item.review_id} item={item} />
              ))}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}

function ReviewCard({
  item,
  working,
  actionForm,
  onActionFormChange,
  onAcknowledge,
  onAction,
  onProposal,
}: {
  item: ReviewItem;
  working: boolean;
  actionForm: { action: string; note: string };
  onActionFormChange: (form: { action: string; note: string }) => void;
  onAcknowledge: () => void;
  onAction: () => void;
  onProposal: () => void;
}) {
  const payload = item.payload;
  const canPropose = item.source === 'adherence_flag' || item.source === 'lab_trend';

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <SeverityBadge severity={item.severity} />
            <SourceBadge source={item.source} />
            {item.status !== 'OPEN' && <StatusBadge status={item.status} />}
          </div>
          <p className="mt-2 text-sm text-slate-700">
            <span className="font-medium">{item.patient_id}</span> · {formatDate(item.created_at)}
          </p>
          <p className="mt-1 text-sm text-slate-900">{item.reason}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {item.status === 'OPEN' && (
            <button
              onClick={onAcknowledge}
              disabled={working}
              className="rounded-lg bg-white px-3 py-1.5 text-sm font-semibold text-slate-700 ring-1 ring-slate-300 hover:bg-slate-50 disabled:opacity-50 transition-colors"
            >
              {working ? 'Working…' : 'Acknowledge'}
            </button>
          )}
          {canPropose && item.status !== 'ACTION_RECORDED' && (
            <button
              onClick={onProposal}
              disabled={working}
              className="rounded-lg bg-sky-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-sky-700 disabled:bg-sky-300 transition-colors"
            >
              {working ? 'Working…' : 'Create proposal'}
            </button>
          )}
        </div>
      </div>

      <PayloadDetail payload={payload} source={item.source} />

      {item.status !== 'ACTION_RECORDED' && (
        <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-3">
          <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">
            Record action
          </label>
          <div className="flex flex-col gap-2 sm:flex-row">
            <input
              type="text"
              value={actionForm.action}
              onChange={(e) => onActionFormChange({ ...actionForm, action: e.target.value })}
              placeholder="What action was taken?"
              disabled={working}
              className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-sky-500 focus:ring-1 focus:ring-sky-500"
            />
            <input
              type="text"
              value={actionForm.note}
              onChange={(e) => onActionFormChange({ ...actionForm, note: e.target.value })}
              placeholder="Optional note"
              disabled={working}
              className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-sky-500 focus:ring-1 focus:ring-sky-500"
            />
            <button
              onClick={onAction}
              disabled={working || !actionForm.action.trim()}
              className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-700 disabled:bg-emerald-300 transition-colors"
            >
              {working ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      )}

      {item.action && (
        <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm">
          <p className="font-medium text-slate-900">Recorded action</p>
          <p className="mt-1 text-slate-700">{item.action.action}</p>
          {item.action.note && <p className="mt-1 text-slate-500">{item.action.note}</p>}
          {item.linked_envelope_id && (
            <p className="mt-1 text-slate-500">Linked envelope: {item.linked_envelope_id}</p>
          )}
        </div>
      )}
    </div>
  );
}

function PayloadDetail({ payload, source }: { payload: ReviewItem['payload']; source: ReviewItem['source'] }) {
  if (!payload || typeof payload !== 'object') return null;

  if (source === 'adherence_flag') {
    const p = payload as import('../types').AdherenceFlagPayload;
    return (
      <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <div>
            <span className="text-xs text-slate-500">Nutrient</span>
            <p className="font-medium text-slate-900">{p.nutrient}</p>
          </div>
          <div>
            <span className="text-xs text-slate-500">Slope</span>
            <p className="font-medium text-slate-900">{p.slope_pct_per_day?.toFixed ? p.slope_pct_per_day.toFixed(2) : p.slope_pct_per_day}%/day</p>
          </div>
          <div>
            <span className="text-xs text-slate-500">Latest exposure</span>
            <p className="font-medium text-slate-900">{p.latest_exposure_pct?.toFixed ? p.latest_exposure_pct.toFixed(1) : p.latest_exposure_pct}%</p>
          </div>
          <div>
            <span className="text-xs text-slate-500">Projected 3d</span>
            <p className="font-medium text-slate-900">{p.projected_3d_exposure_pct?.toFixed ? p.projected_3d_exposure_pct.toFixed(1) : p.projected_3d_exposure_pct}%</p>
          </div>
        </div>
        {p.contributors && p.contributors.length > 0 && (
          <div className="mt-2">
            <span className="text-xs text-slate-500">Contributing dishes</span>
            <ul className="mt-1 list-disc space-y-0.5 pl-5 text-slate-700">
              {p.contributors.map((c) => (
                <li key={c.dish_id}>
                  {c.dish_name || c.dish_id} · {c.amount.toFixed(1)} ({c.pct_of_day_total.toFixed(0)}%)
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    );
  }

  if (source === 'hard_violation_day') {
    const p = payload as import('../types').ViolationDayPayload;
    return (
      <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm">
        {p.date && <p className="font-medium text-slate-900">Date: {p.date}</p>}
        {p.meals && p.meals.length > 0 && (
          <ul className="mt-2 list-disc space-y-0.5 pl-5 text-slate-700">
            {p.meals.map((m, idx) => (
              <li key={idx}>
                {m.meal}: {m.dish_name || m.dish_id}
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  if (source === 'lab_trend') {
    const p = payload as import('../types').LabTrendPayload;
    return (
      <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          <div>
            <span className="text-xs text-slate-500">Analyte</span>
            <p className="font-medium text-slate-900">{p.analyte}</p>
          </div>
          <div>
            <span className="text-xs text-slate-500">Direction</span>
            <p className="font-medium text-slate-900 capitalize">{p.direction}</p>
          </div>
          <div>
            <span className="text-xs text-slate-500">Slope</span>
            <p className="font-medium text-slate-900">{p.slope}</p>
          </div>
        </div>
      </div>
    );
  }

  return null;
}

function HistoryRow({ item }: { item: ReviewItem }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-center gap-2">
        <SeverityBadge severity={item.severity} />
        <SourceBadge source={item.source} />
        <StatusBadge status={item.status} />
        <span className="text-xs text-slate-500">{formatDate(item.created_at)}</span>
      </div>
      <p className="mt-1 text-sm text-slate-700">{item.reason}</p>
      {item.action && (
        <p className="mt-1 text-sm text-slate-600">
          Action: <span className="font-medium">{item.action.action}</span>
          {item.action.note && <> · {item.action.note}</>}
        </p>
      )}
    </div>
  );
}

function SeverityBadge({ severity }: { severity: ReviewItem['severity'] }) {
  const isAlert = severity === 'alert';
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${
        isAlert ? 'bg-rose-100 text-rose-800' : 'bg-amber-100 text-amber-800'
      }`}
    >
      {severity === 'alert' ? 'Alert' : 'Review'}
    </span>
  );
}

function SourceBadge({ source }: { source: ReviewItem['source'] }) {
  const labels: Record<ReviewItem['source'], string> = {
    adherence_flag: 'Adherence',
    hard_violation_day: 'Violation day',
    lab_trend: 'Lab trend',
  };
  return (
    <span className="inline-flex items-center rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-semibold text-slate-700">
      {labels[source]}
    </span>
  );
}

function StatusBadge({ status }: { status: ReviewItem['status'] }) {
  const labels: Record<ReviewItem['status'], string> = {
    OPEN: 'Open',
    ACKNOWLEDGED: 'Acknowledged',
    ACTION_RECORDED: 'Actioned',
  };
  return (
    <span className="inline-flex items-center rounded-full bg-sky-100 px-2.5 py-0.5 text-xs font-semibold text-sky-800">
      {labels[status]}
    </span>
  );
}

function formatDate(value: string) {
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}
