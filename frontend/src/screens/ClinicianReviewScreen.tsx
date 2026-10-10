import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  listPatients,
  runRules,
  getEnvelope,
  getPatient,
  approveEnvelope,
  rejectEnvelope,
  editEnvelope,
  createObservation,
  listObservations,
} from '../api';
import type { Patient, Envelope, NutrientConstraint, Observation } from '../types';
import PatientCard from '../components/PatientCard';
import LoadingState from '../components/LoadingState';
import EmptyState from '../components/EmptyState';
import ConstraintTable from '../components/ConstraintTable';
import RuleTrace from '../components/RuleTrace';
import EditEnvelopeModal from '../components/EditEnvelopeModal';
import { useRequestScope } from '../hooks/useRequestScope';

export default function ClinicianReviewScreen() {
  const [searchParams, setSearchParams] = useSearchParams();
  const linkedEnvelopeId = searchParams.get('envelope');
  const requests = useRequestScope();
  const selectionIsCurrent = requests.capture();
  const [patients, setPatients] = useState<Patient[]>([]);
  const [loadingPatients, setLoadingPatients] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedPatient, setSelectedPatient] = useState<Patient | null>(null);
  const [envelope, setEnvelope] = useState<Envelope | null>(null);
  const [envelopeLoading, setEnvelopeLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [isEditOpen, setIsEditOpen] = useState(false);
  const [savingEdit, setSavingEdit] = useState(false);
  const [observations, setObservations] = useState<Observation[]>([]);
  const [observationsLoading, setObservationsLoading] = useState(false);

  useEffect(() => {
    listPatients()
      .then((data) => {
        setPatients(data || []);
      })
      .catch((err) => setError(err.message || 'Failed to load patients'))
      .finally(() => setLoadingPatients(false));
  }, []);

  useEffect(() => {
    if (!linkedEnvelopeId) return;
    requests.reset();
    const isCurrent = requests.start('envelope');
    let active = true;
    setEnvelope(null);
    setSelectedPatient(null);
    setObservations([]);
    setIsEditOpen(false);
    setActionLoading(false);
    setSavingEdit(false);
    setEnvelopeLoading(true);
    setError(null);
    const loadLinkedProposal = async () => {
      try {
        const proposal = await getEnvelope(linkedEnvelopeId);
        const patient = await getPatient(proposal.patient_id);
        if (!active || !isCurrent()) return;
        setSelectedPatient(patient);
        setEnvelope(proposal);
        setObservationsLoading(true);
        try {
          const result = await listObservations(patient.id);
          if (active && isCurrent()) setObservations(result.observations);
        } finally {
          if (active && isCurrent()) setObservationsLoading(false);
        }
      } catch (err: any) {
        if (active && isCurrent()) setError(err.message || 'Failed to load linked proposal');
      } finally {
        if (active && isCurrent()) setEnvelopeLoading(false);
      }
    };
    void loadLinkedProposal();
    return () => { active = false; };
  }, [linkedEnvelopeId, requests]);

  const handleSelect = (patient: Patient) => {
    setSearchParams({});
    requests.reset();
    setSelectedPatient(patient);
    setEnvelope(null);
    setObservations([]);
    setError(null);
    setIsEditOpen(false);
    setEnvelopeLoading(false);
    setActionLoading(false);
    setSavingEdit(false);
    loadObservations(patient.id);
  };

  const loadObservations = async (patientId: string) => {
    const isCurrent = requests.start('observations');
    setObservationsLoading(true);
    try {
      const result = await listObservations(patientId);
      if (isCurrent()) setObservations(result.observations || []);
    } catch {
      if (isCurrent()) setObservations([]);
    } finally {
      if (isCurrent()) setObservationsLoading(false);
    }
  };

  const handleGenerate = async () => {
    if (!selectedPatient || envelopeLoading || actionLoading || savingEdit || isEditOpen) return;
    const isCurrent = requests.start('envelope');
    setEnvelopeLoading(true);
    setActionLoading(false);
    setSavingEdit(false);
    setError(null);
    try {
      const result = await runRules(selectedPatient.id);
      if (isCurrent()) setEnvelope(result.envelope);
    } catch (err: any) {
      if (isCurrent()) setError(err.message || 'Failed to generate envelope');
    } finally {
      if (isCurrent()) setEnvelopeLoading(false);
    }
  };

  const handleApprove = async () => {
    if (!envelope || envelopeLoading || actionLoading || savingEdit) return;
    const isCurrent = requests.start('envelope');
    setActionLoading(true);
    try {
      const updated = await approveEnvelope(envelope.id, {
        clinician_id: 'clinician-1', expected_revision: envelope.lifecycle_revision,
      });
      if (isCurrent()) setEnvelope(updated);
    } catch (err: any) {
      if (isCurrent()) setError(err.message || 'Failed to approve envelope');
    } finally {
      if (isCurrent()) setActionLoading(false);
    }
  };

  const handleReject = async () => {
    if (!envelope || envelopeLoading || actionLoading || savingEdit) return;
    const isCurrent = requests.start('envelope');
    setActionLoading(true);
    try {
      const updated = await rejectEnvelope(envelope.id, {
        reason: 'Rejected by clinician', expected_revision: envelope.lifecycle_revision,
      });
      if (isCurrent()) setEnvelope(updated);
    } catch (err: any) {
      if (isCurrent()) setError(err.message || 'Failed to reject envelope');
    } finally {
      if (isCurrent()) setActionLoading(false);
    }
  };

  const handleEdit = () => {
    if (!envelope) return;
    setIsEditOpen(true);
  };

  const handleReloadEnvelope = async () => {
    if (!envelope || envelopeLoading || actionLoading || savingEdit) return;
    const isCurrent = requests.start('envelope');
    setActionLoading(true);
    setIsEditOpen(false);
    try {
      const current = await getEnvelope(envelope.id);
      if (!isCurrent()) return;
      setEnvelope(current);
      setError(null);
    } catch (err: any) {
      if (isCurrent()) setError(err.message || 'Failed to reload envelope');
    } finally {
      if (isCurrent()) setActionLoading(false);
    }
  };

  const handleSaveEdits = async (targets: NutrientConstraint[], notes?: string) => {
    if (!envelope) return;
    const isCurrent = requests.start('envelope');
    setSavingEdit(true);
    try {
      const updated = await editEnvelope(envelope.id, {
        targets,
        notes,
        edited_by: 'clinician-1',
        expected_revision: envelope.lifecycle_revision,
      });
      if (!isCurrent()) return;
      setEnvelope(updated);
      setIsEditOpen(false);
    } finally {
      if (isCurrent()) setSavingEdit(false);
    }
  };

  return (
    <main className="min-h-screen bg-slate-50 pb-12">
      <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
        <div className="mb-6">
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Clinician review</h1>
          <p className="mt-1 text-sm text-slate-500">
            Select a patient, generate a proposed nutrient envelope, then approve or adjust it.
          </p>
        </div>

        {error && (
          <div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
            {error}
            <button
              onClick={() => setError(null)}
              className="ml-2 font-medium underline hover:text-rose-900"
            >
              Dismiss
            </button>
          </div>
        )}

        <section className="mb-8">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
            Patients
          </h2>
          {loadingPatients ? (
            <LoadingState text="Loading patients…" />
          ) : patients.length === 0 ? (
            <EmptyState title="No patients found" description="Check that the backend is running and has patient records." />
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {patients.map((patient) => (
                <PatientCard
                  key={patient.id}
                  patient={patient}
                  selected={selectedPatient?.id === patient.id}
                  onClick={() => handleSelect(patient)}
                />
              ))}
            </div>
          )}
        </section>

        {selectedPatient && (
          <section className="mb-8 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h2 className="text-lg font-semibold text-slate-900">
                  {selectedPatient.name || `Patient ${selectedPatient.id}`}
                </h2>
                <p className="text-sm text-slate-500">
                  {selectedPatient.age} yrs · {selectedPatient.sex} ·{' '}
                  {selectedPatient.diagnoses?.join(', ')}
                </p>
              </div>
              <button
                onClick={handleGenerate}
                disabled={envelopeLoading || actionLoading || savingEdit || isEditOpen}
                className="inline-flex items-center justify-center rounded-lg bg-sky-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-sky-700 focus:outline-none focus:ring-2 focus:ring-sky-500 focus:ring-offset-2 disabled:bg-sky-300 transition-colors"
              >
                {envelopeLoading ? 'Generating…' : 'Generate proposed envelope'}
              </button>
            </div>
          </section>
        )}

        {envelope && (
          <section className="space-y-6">
            <div className="flex flex-col gap-3 rounded-xl border border-slate-200 bg-white p-5 shadow-sm sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h2 className="text-lg font-semibold text-slate-900">Proposed envelope</h2>
                <p className="text-sm text-slate-500">
                  Status:
                  <StatusBadge status={envelope.status} />
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  onClick={handleApprove}
                  disabled={envelopeLoading || savingEdit || actionLoading || envelope.status === 'APPROVED' || envelope.status === 'REJECTED' || !envelope.scope_eligible || (envelope.constraints?.length ?? 0) === 0}
                  title={envelope.status === 'REJECTED' ? 'Out-of-scope proposal — cannot be approved' : undefined}
                  className="inline-flex items-center justify-center rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-700 disabled:bg-emerald-300 disabled:cursor-not-allowed transition-colors"
                >
                  {actionLoading ? 'Working…' : 'Approve'}
                </button>
                <button
                  onClick={handleEdit}
                  disabled={envelopeLoading || savingEdit || actionLoading || envelope.status === 'REJECTED' || !envelope.scope_eligible}
                  className="inline-flex items-center justify-center rounded-lg bg-white px-4 py-2 text-sm font-semibold text-slate-700 ring-1 ring-slate-300 hover:bg-slate-50 transition-colors"
                >
                  Edit
                </button>
                <button
                  onClick={handleReject}
                  disabled={envelopeLoading || savingEdit || actionLoading || envelope.status === 'REJECTED'}
                  className="inline-flex items-center justify-center rounded-lg bg-white px-4 py-2 text-sm font-semibold text-rose-700 ring-1 ring-rose-200 hover:bg-rose-50 transition-colors"
                >
                  {actionLoading ? 'Working…' : 'Reject'}
                </button>
                <button onClick={handleReloadEnvelope} disabled={envelopeLoading || savingEdit || actionLoading}
                  className="rounded-lg px-4 py-2 text-sm font-semibold text-slate-700 underline disabled:opacity-50">
                  Reload envelope
                </button>
              </div>
            </div>

            <div>
              <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
                Nutrient constraints
              </h3>
              <ConstraintTable
                constraints={envelope.constraints || []}
              />
            </div>

            <div>
              <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
                Fired-rule trace
              </h3>
              <RuleTrace trace={envelope.trace || []} />
            </div>
          </section>
        )}

        {envelope && isEditOpen && (
          <EditEnvelopeModal
            envelope={envelope}
            onClose={() => setIsEditOpen(false)}
            onSave={handleSaveEdits}
            isSaving={savingEdit}
          />
        )}

        {selectedPatient && (
          <ObservationsSection
            key={selectedPatient.id}
            patient={selectedPatient}
            observations={observations}
            loading={observationsLoading}
            onRecorded={async () => {
              if (!selectionIsCurrent()) return;
              await loadObservations(selectedPatient.id);
              try {
                const updated = await listPatients();
                if (!selectionIsCurrent()) return;
                setPatients(updated);
                setSelectedPatient((current) => updated.find((p) => p.id === current?.id) || current);
              } catch (err: any) {
                if (selectionIsCurrent()) setError(err.message || 'Failed to refresh patient profile');
              }
            }}
          />
        )}
      </div>
    </main>
  );
}

function ObservationsSection({
  patient,
  observations,
  loading,
  onRecorded,
}: {
  patient: Patient;
  observations: Observation[];
  loading: boolean;
  onRecorded: () => void;
}) {
  const [metric, setMetric] = useState<'serum_K_meq_L' | 'serum_PO4_mg_dL' | 'egfr' | 'hba1c_pct'>('serum_K_meq_L');
  const [value, setValue] = useState('');
  const [unit, setUnit] = useState('');
  const [source, setSource] = useState('');
  const [observedAt, setObservedAt] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const metricUnits: Record<typeof metric, string> = {
    serum_K_meq_L: 'mEq/L',
    serum_PO4_mg_dL: 'mg/dL',
    egfr: 'mL/min/1.73m²',
    hba1c_pct: '%',
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const numValue = parseFloat(value);
    if (Number.isNaN(numValue)) {
      setError('Enter a numeric value.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await createObservation({
        patient_id: patient.id,
        metric,
        value: numValue,
        unit: unit.trim() || metricUnits[metric],
        source: source.trim() || undefined,
        observed_at: observedAt || undefined,
      });
      setValue('');
      setSource('');
      onRecorded();
    } catch (err: any) {
      setError(err.message || 'Failed to record observation');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="mt-8 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
        Clinical observations
      </h2>

      <form onSubmit={handleSubmit} className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end">
        <div>
          <label className="mb-1 block text-xs font-medium text-slate-700">Metric</label>
          <select
            value={metric}
            onChange={(e) => {
              setMetric(e.target.value as typeof metric);
              setUnit('');
            }}
            className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-sky-500 focus:ring-1 focus:ring-sky-500"
          >
            <option value="serum_K_meq_L">Serum K</option>
            <option value="serum_PO4_mg_dL">Serum PO4</option>
            <option value="egfr">eGFR</option>
            <option value="hba1c_pct">HbA1c</option>
          </select>
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-slate-700">Value</label>
          <input
            type="number"
            step="any"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            className="w-32 rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 focus:border-sky-500 focus:ring-1 focus:ring-sky-500"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-slate-700">Unit</label>
          <input
            type="text"
            value={unit}
            onChange={(e) => setUnit(e.target.value)}
            placeholder={metricUnits[metric]}
            className="w-28 rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 focus:border-sky-500 focus:ring-1 focus:ring-sky-500"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-slate-700">Source</label>
          <input
            type="text"
            value={source}
            onChange={(e) => setSource(e.target.value)}
            placeholder="e.g. lab"
            className="w-32 rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 focus:border-sky-500 focus:ring-1 focus:ring-sky-500"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-slate-700">Observed at</label>
          <input
            type="date"
            value={observedAt}
            onChange={(e) => setObservedAt(e.target.value)}
            className="w-40 rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 focus:border-sky-500 focus:ring-1 focus:ring-sky-500"
          />
        </div>
        <button
          type="submit"
          disabled={submitting || value === ''}
          className="inline-flex items-center justify-center rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-700 disabled:bg-emerald-300 transition-colors"
        >
          {submitting ? 'Recording…' : 'Record observation'}
        </button>
      </form>

      {error && (
        <div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
          {error}
          <button onClick={() => setError(null)} className="ml-2 font-medium underline">
            Dismiss
          </button>
        </div>
      )}

      {loading ? (
        <LoadingState text="Loading observations…" />
      ) : observations.length === 0 ? (
        <EmptyState title="No observations" description="Record a follow-up observation after reviewing an alert." />
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-3 py-2 text-left font-semibold text-slate-700">Metric</th>
                <th className="px-3 py-2 text-left font-semibold text-slate-700">Value</th>
                <th className="px-3 py-2 text-left font-semibold text-slate-700">Observed at</th>
                <th className="px-3 py-2 text-left font-semibold text-slate-700">Source</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {observations.map((obs) => (
                <tr key={obs.observation_id} className="hover:bg-slate-50">
                  <td className="px-3 py-2 font-medium text-slate-900">{obs.metric}</td>
                  <td className="px-3 py-2 text-slate-700">
                    {obs.value} {obs.unit}
                  </td>
                  <td className="px-3 py-2 text-slate-700">{obs.observed_at}</td>
                  <td className="px-3 py-2 text-slate-700">{obs.source || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function StatusBadge({ status }: { status: Envelope['status'] }) {
  const classes: Record<Envelope['status'], string> = {
    PROPOSED: 'bg-amber-100 text-amber-800',
    APPROVED: 'bg-emerald-100 text-emerald-800',
    REJECTED: 'bg-rose-100 text-rose-800',
    EDITED: 'bg-sky-100 text-sky-800',
  };
  return (
    <span className={`ml-2 inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold ${classes[status]}`}>
      {status}
    </span>
  );
}
