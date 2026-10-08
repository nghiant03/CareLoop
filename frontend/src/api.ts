import type {
  Patient,
  Envelope,
  MealPlan,
  ChatMessageResponse,
  TraceEntry,
  EditEnvelopePayload,
  Dish,
  AdherenceSummary,
  AdherenceDeviation,
} from './types';

const API_PREFIX = '/api';

function normalizeEnvelope(raw: any): Envelope {
  if (!raw) return raw;
  return {
    ...raw,
    id: raw.id ?? raw.envelope_id,
    constraints: raw.constraints || raw.targets || [],
    trace: raw.trace || raw.fired_rules || [],
  } as Envelope;
}

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
  return fetch(`${API_PREFIX}/patients`)
    .then((r) => handleResponse<Patient[] | { patients?: Patient[] }>(r))
    .then((data) => (Array.isArray(data) ? data : (data.patients ?? [])));
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
  })
    .then((r) => handleResponse<{ envelope: any; trace: TraceEntry[] }>(r))
    .then(({ envelope, trace }) => ({ envelope: normalizeEnvelope(envelope), trace }));
}

export async function getEnvelope(id: string): Promise<Envelope> {
  return fetch(`${API_PREFIX}/envelopes/${id}`)
    .then((r) => handleResponse<any>(r))
    .then(normalizeEnvelope);
}

export async function approveEnvelope(
  id: string,
  payload: { clinician_id: string; note?: string }
): Promise<Envelope> {
  return fetch(`${API_PREFIX}/envelopes/${id}/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
    .then((r) => handleResponse<any>(r))
    .then(normalizeEnvelope);
}

export async function editEnvelope(
  id: string,
  payload: EditEnvelopePayload
): Promise<Envelope> {
  return fetch(`${API_PREFIX}/envelopes/${id}/edit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
    .then((r) => handleResponse<any>(r))
    .then(normalizeEnvelope);
}

export async function rejectEnvelope(
  id: string,
  payload: { reason?: string }
): Promise<Envelope> {
  return fetch(`${API_PREFIX}/envelopes/${id}/reject`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
    .then((r) => handleResponse<any>(r))
    .then(normalizeEnvelope);
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

export async function searchDishes(
  search: string,
  category?: string
): Promise<{ count: number; dishes: Dish[] }> {
  const params = new URLSearchParams();
  if (search.trim()) params.set('search', search.trim());
  if (category) params.set('category', category);
  return fetch(`${API_PREFIX}/dishes?${params.toString()}`).then((r) =>
    handleResponse<{ count: number; dishes: Dish[] }>(r)
  );
}

export async function getDish(dishId: string): Promise<Dish> {
  return fetch(`${API_PREFIX}/dishes/${dishId}`).then((r) => handleResponse<Dish>(r));
}

export async function logMeal(payload: {
  patient_id: string;
  date: string;
  meal: 'breakfast' | 'lunch' | 'dinner';
  dish_id: string;
}): Promise<{ patient_id: string; date: string; meal: string; dish_id: string }> {
  return fetch(`${API_PREFIX}/adherence/log`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then((r) => handleResponse<{ patient_id: string; date: string; meal: string; dish_id: string }>(r));
}

export async function getAdherenceSummary(
  patientId: string,
  days = 14
): Promise<AdherenceSummary> {
  return fetch(`${API_PREFIX}/adherence/${patientId}/summary?days=${days}`).then((r) =>
    handleResponse<AdherenceSummary>(r)
  );
}

export async function getAdherenceDeviation(
  patientId: string,
  days = 14
): Promise<AdherenceDeviation> {
  return fetch(`${API_PREFIX}/adherence/${patientId}/deviation?days=${days}`).then((r) =>
    handleResponse<AdherenceDeviation>(r)
  );
}
