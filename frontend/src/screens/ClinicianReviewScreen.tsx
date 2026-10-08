import { useEffect, useState } from 'react';
import {
  listPatients,
  runRules,
  approveEnvelope,
  rejectEnvelope,
  editEnvelope,
} from '../api';
import type { Patient, Envelope, NutrientConstraint } from '../types';
import PatientCard from '../components/PatientCard';
import LoadingState from '../components/LoadingState';
import EmptyState from '../components/EmptyState';
import ConstraintTable from '../components/ConstraintTable';
import RuleTrace from '../components/RuleTrace';
import EditEnvelopeModal from '../components/EditEnvelopeModal';

export default function ClinicianReviewScreen() {
  const [patients, setPatients] = useState<Patient[]>([]);
  const [loadingPatients, setLoadingPatients] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedPatient, setSelectedPatient] = useState<Patient | null>(null);
  const [envelope, setEnvelope] = useState<Envelope | null>(null);
  const [envelopeLoading, setEnvelopeLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [isEditOpen, setIsEditOpen] = useState(false);
  const [savingEdit, setSavingEdit] = useState(false);

  useEffect(() => {
    listPatients()
      .then((data) => {
        setPatients(data || []);
      })
      .catch((err) => setError(err.message || 'Failed to load patients'))
      .finally(() => setLoadingPatients(false));
  }, []);

  const handleSelect = (patient: Patient) => {
    setSelectedPatient(patient);
    setEnvelope(null);
  };

  const handleGenerate = async () => {
    if (!selectedPatient) return;
    setEnvelopeLoading(true);
    setError(null);
    try {
      const result = await runRules(selectedPatient.id);
      const env = result.envelope || (result as any);
      setEnvelope(env);
    } catch (err: any) {
      setError(err.message || 'Failed to generate envelope');
    } finally {
      setEnvelopeLoading(false);
    }
  };

  const handleApprove = async () => {
    if (!envelope) return;
    setActionLoading(true);
    try {
      const updated = await approveEnvelope(envelope.id, { clinician_id: 'clinician-1' });
      setEnvelope(updated);
    } catch (err: any) {
      setError(err.message || 'Failed to approve envelope');
    } finally {
      setActionLoading(false);
    }
  };

  const handleReject = async () => {
    if (!envelope) return;
    setActionLoading(true);
    try {
      const updated = await rejectEnvelope(envelope.id, { note: 'Rejected by clinician' });
      setEnvelope(updated);
    } catch (err: any) {
      setError(err.message || 'Failed to reject envelope');
    } finally {
      setActionLoading(false);
    }
  };

  const handleEdit = () => {
    if (!envelope) return;
    setIsEditOpen(true);
  };

  const handleSaveEdits = async (targets: NutrientConstraint[], notes?: string) => {
    if (!envelope) return;
    setSavingEdit(true);
    try {
      const updated = await editEnvelope(envelope.id, {
        targets,
        notes,
        edited_by: 'clinician-1',
      });
      setEnvelope(updated);
      setIsEditOpen(false);
    } finally {
      setSavingEdit(false);
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
                disabled={envelopeLoading}
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
                  disabled={actionLoading || envelope.status === 'APPROVED' || envelope.status === 'REJECTED' || (envelope.constraints?.length ?? 0) === 0}
                  title={envelope.status === 'REJECTED' ? 'Out-of-scope proposal — cannot be approved' : undefined}
                  className="inline-flex items-center justify-center rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-700 disabled:bg-emerald-300 disabled:cursor-not-allowed transition-colors"
                >
                  {actionLoading ? 'Working…' : 'Approve'}
                </button>
                <button
                  onClick={handleEdit}
                  disabled={actionLoading}
                  className="inline-flex items-center justify-center rounded-lg bg-white px-4 py-2 text-sm font-semibold text-slate-700 ring-1 ring-slate-300 hover:bg-slate-50 transition-colors"
                >
                  Edit
                </button>
                <button
                  onClick={handleReject}
                  disabled={actionLoading || envelope.status === 'REJECTED'}
                  className="inline-flex items-center justify-center rounded-lg bg-white px-4 py-2 text-sm font-semibold text-rose-700 ring-1 ring-rose-200 hover:bg-rose-50 transition-colors"
                >
                  {actionLoading ? 'Working…' : 'Reject'}
                </button>
              </div>
            </div>

            <div>
              <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
                Nutrient constraints
              </h3>
              <ConstraintTable
                constraints={envelope.constraints || []}
                citations={envelope.citations || []}
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
      </div>
    </main>
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
