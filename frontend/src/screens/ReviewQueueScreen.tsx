import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  listPatients,
  getReviewQueue,
  getReviewItems,
  acknowledgeReview,
  actionReview,
  createReviewProposal,
} from '../api';
import type { Patient, ReviewItem } from '../types';
import LoadingState from '../components/LoadingState';
import EmptyState from '../components/EmptyState';
import PageHeader from '../components/PageHeader';
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
      const result = await createReviewProposal(item.review_id);
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
    <main className="pb-12">
      <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
        <PageHeader code="QUE" title="Review queue">
          Triage adherence flags, hard-violation days, and lab trends. Acknowledge, record an action,
          or create a revised envelope proposal.
        </PageHeader>

        {error && (
          <div className="notice notice-error mb-4">
            {error}
            <button onClick={() => setError(null)} className="ml-2 font-semibold underline hover:opacity-80">
              Dismiss
            </button>
          </div>
        )}

        <section className="panel mb-8 p-5">
          <h2 className="micro-label mb-3 border-b border-rule pb-2">
            Filter
          </h2>
          {loadingPatients ? (
            <LoadingState text="Loading patients…" />
          ) : patients.length === 0 ? (
            <EmptyState title="No patients found" description="Add patients or start the backend." />
          ) : (
            <div className="flex flex-col gap-4 sm:flex-row sm:items-end">
              <div className="flex-1">
                <label htmlFor="review-patient" className="micro-label mb-1 block">
                  Patient
                </label>
                <select
                  id="review-patient"
                  value={selectedPatientId}
                  onChange={(e) => { resetFilter(); setSelectedPatientId(e.target.value); }}
                  className="field"
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
                <span className="micro-label mb-1 block" id="review-status-label">
                  Status
                </span>
                <div className="flex flex-wrap divide-x divide-rule border border-rule" role="group" aria-labelledby="review-status-label">
                  {STATUS_TABS.map((tab) => (
                    <button
                      key={tab.key}
                      onClick={() => { if (status !== tab.key) { resetFilter(); setStatus(tab.key); } }}
                      className={`px-3 py-2 text-sm font-medium transition-colors ${
                        status === tab.key
                          ? 'bg-ink text-paper'
                          : 'bg-card text-ink-2 hover:bg-panel'
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
          <div className="panel mb-6 p-4">
            <p className="text-sm text-ink-3">
              Selected patient: <span className="font-semibold text-ink">{selectedPatient.name || selectedPatient.id}</span>
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
          <h2 className="mb-4 text-lg font-bold tracking-tight text-ink">History</h2>
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
    <div className="panel p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <SeverityBadge severity={item.severity} />
            <SourceBadge source={item.source} />
            {item.status !== 'OPEN' && <StatusBadge status={item.status} />}
          </div>
          <p className="mt-2 text-sm text-ink-3">
            <span className="num font-medium text-ink">{item.patient_id}</span> · {formatDate(item.created_at)}
          </p>
          <p className="mt-1 text-sm text-ink">{item.reason}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {item.status === 'OPEN' && (
            <button
              onClick={onAcknowledge}
              disabled={working}
              className="btn-ghost px-3 py-1.5"
            >
              {working ? 'Working…' : 'Acknowledge'}
            </button>
          )}
          {canPropose && item.status !== 'ACTION_RECORDED' && (
            <button
              onClick={onProposal}
              disabled={working}
              className="btn-primary px-3 py-1.5"
            >
              {working ? 'Working…' : 'Create proposal'}
            </button>
          )}
        </div>
      </div>

      <PayloadDetail payload={payload} source={item.source} />

      {item.status !== 'ACTION_RECORDED' && (
        <div className="mt-4 border-t border-rule pt-4">
          <label className="micro-label mb-1 block">
            Record action
          </label>
          <div className="flex flex-col gap-2 sm:flex-row">
            <input
              type="text"
              value={actionForm.action}
              onChange={(e) => onActionFormChange({ ...actionForm, action: e.target.value })}
              placeholder="What action was taken?"
              disabled={working}
              className="field flex-1"
            />
            <input
              type="text"
              value={actionForm.note}
              onChange={(e) => onActionFormChange({ ...actionForm, note: e.target.value })}
              placeholder="Optional note"
              disabled={working}
              className="field flex-1"
            />
            <button
              onClick={onAction}
              disabled={working || !actionForm.action.trim()}
              className="btn-primary"
            >
              {working ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      )}

      {item.action && (
        <div className="mt-3 border border-rule bg-panel p-3 text-sm">
          <p className="micro-label">Recorded action</p>
          <p className="mt-1 font-medium text-ink">{item.action.action}</p>
          {item.action.note && <p className="mt-1 text-ink-3">{item.action.note}</p>}
          {item.linked_envelope_id && (
            <p className="num mt-1 text-ink-3">Linked envelope: {item.linked_envelope_id}</p>
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
      <div className="mt-3 border border-rule bg-panel p-3 text-sm">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <div>
            <span className="micro-label">Nutrient</span>
            <p className="font-medium text-ink">{p.nutrient}</p>
          </div>
          <div>
            <span className="micro-label">Slope</span>
            <p className="num font-medium text-ink">{p.slope_pct_per_day?.toFixed ? p.slope_pct_per_day.toFixed(2) : p.slope_pct_per_day}%/day</p>
          </div>
          <div>
            <span className="micro-label">Latest exposure</span>
            <p className="num font-medium text-ink">{p.latest_exposure_pct?.toFixed ? p.latest_exposure_pct.toFixed(1) : p.latest_exposure_pct}%</p>
          </div>
          <div>
            <span className="micro-label">Projected 3d</span>
            <p className="num font-medium text-ink">{p.projected_3d_exposure_pct?.toFixed ? p.projected_3d_exposure_pct.toFixed(1) : p.projected_3d_exposure_pct}%</p>
          </div>
        </div>
        {p.contributors && p.contributors.length > 0 && (
          <div className="mt-2 border-t border-rule pt-2">
            <span className="micro-label">Contributing dishes</span>
            <ul className="mt-1 list-disc space-y-0.5 pl-5 text-ink-2">
              {p.contributors.map((c) => (
                <li key={c.dish_id}>
                  {c.dish_name || c.dish_id} · <span className="num">{c.amount.toFixed(1)}</span> ({c.pct_of_day_total.toFixed(0)}%)
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
      <div className="mt-3 border border-rule bg-panel p-3 text-sm">
        {p.date && <p className="num font-medium text-ink">Date: {p.date}</p>}
        {p.meals && p.meals.length > 0 && (
          <ul className="mt-2 list-disc space-y-0.5 pl-5 text-ink-2">
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
      <div className="mt-3 border border-rule bg-panel p-3 text-sm">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          <div>
            <span className="micro-label">Analyte</span>
            <p className="font-medium text-ink">{p.analyte}</p>
          </div>
          <div>
            <span className="micro-label">Direction</span>
            <p className="font-medium capitalize text-ink">{p.direction}</p>
          </div>
          <div>
            <span className="micro-label">Slope</span>
            <p className="num font-medium text-ink">{p.slope}</p>
          </div>
        </div>
      </div>
    );
  }

  return null;
}

function HistoryRow({ item }: { item: ReviewItem }) {
  return (
    <div className="border border-rule bg-card p-4">
      <div className="flex flex-wrap items-center gap-2">
        <SeverityBadge severity={item.severity} />
        <SourceBadge source={item.source} />
        <StatusBadge status={item.status} />
        <span className="num text-xs text-ink-3">{formatDate(item.created_at)}</span>
      </div>
      <p className="mt-1 text-sm text-ink-2">{item.reason}</p>
      {item.action && (
        <p className="mt-1 text-sm text-ink-3">
          Action: <span className="font-medium text-ink">{item.action.action}</span>
          {item.action.note && <> · {item.action.note}</>}
        </p>
      )}
    </div>
  );
}

function SeverityBadge({ severity }: { severity: ReviewItem['severity'] }) {
  const isAlert = severity === 'alert';
  return (
    <span className={`flag ${isAlert ? 'flag-bad' : 'flag-warn'}`}>
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
    <span className="flag flag-neutral">
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
    <span className="flag flag-info">
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
