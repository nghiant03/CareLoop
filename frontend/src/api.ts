import type {
  Patient,
  Envelope,
  MealPlan,
  ChatMessageResponse,
  TraceEntry,
} from './types';

const API_PREFIX = '/api';

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || body.error || JSON.stringify(body);
    } catch {
      // ignore
    }
    const err: any = new Error(detail);
    err.status = res.status;
    err.data = detail;
    throw err;
  }
  return res.json() as Promise<T>;
}

export async function healthz(): Promise<{ status: string }> {
  return fetch(`${API_PREFIX}/healthz`).then((r) => handleResponse<{ status: string }>(r));
}

export async function listPatients(): Promise<Patient[]> {
  return fetch(`${API_PREFIX}/patients`).then((r) => handleResponse<Patient[]>(r));
}

export async function getPatient(id: string): Promise<Patient> {
  return fetch(`${API_PREFIX}/patients/${id}`).then((r) => handleResponse<Patient>(r));
}

export interface RulesRunResult {
  envelope: Envelope;
  trace: TraceEntry[];
}

export async function runRules(patientId: string): Promise<RulesRunResult> {
  return fetch(`${API_PREFIX}/rules/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ patient_id: patientId }),
  }).then((r) => handleResponse<RulesRunResult>(r));
}

export async function getEnvelope(id: string): Promise<Envelope> {
  return fetch(`${API_PREFIX}/envelopes/${id}`).then((r) => handleResponse<Envelope>(r));
}

export async function approveEnvelope(
  id: string,
  payload: { clinician_id: string; note?: string }
): Promise<Envelope> {
  return fetch(`${API_PREFIX}/envelopes/${id}/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then((r) => handleResponse<Envelope>(r));
}

export async function editEnvelope(
  id: string,
  payload: { constraints?: unknown[]; note?: string }
): Promise<Envelope> {
  return fetch(`${API_PREFIX}/envelopes/${id}/edit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then((r) => handleResponse<Envelope>(r));
}

export async function rejectEnvelope(
  id: string,
  payload: { note?: string }
): Promise<Envelope> {
  return fetch(`${API_PREFIX}/envelopes/${id}/reject`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then((r) => handleResponse<Envelope>(r));
}

export async function createPlan(
  payload: { patient_id?: string; envelope_id?: string }
): Promise<MealPlan> {
  return fetch(`${API_PREFIX}/plans`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then((r) => handleResponse<MealPlan>(r));
}

export async function sendChat(
  patientId: string,
  message: string
): Promise<ChatMessageResponse> {
  return fetch(`${API_PREFIX}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ patient_id: patientId, message }),
  }).then((r) => handleResponse<ChatMessageResponse>(r));
}
