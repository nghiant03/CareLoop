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
  ReviewQueueResponse,
  ReviewItem,
  ReviewActionRequest,
  ReviewProposalResponse,
  PlanSummary,
  Observation,
  ObservationRequest,
  ObservationListResponse,
  Simulation,
  SimulationRequest,
  SimulationListResponse,
  SubstitutionResponse,
  SwapApplyRequest,
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
      const raw = body.detail || body.error || body;
      detail = typeof raw === 'string' ? raw : (raw.message || raw.error || JSON.stringify(raw));
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

export async function getLatestEnvelope(patientId: string): Promise<Envelope> {
  return fetch(`${API_PREFIX}/envelopes/latest?patient_id=${encodeURIComponent(patientId)}`)
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
  dish_id?: string;
  items?: { dish_id: string; quantity: number }[];
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

// ---------------------------------------------------------------------------
// Plans
// ---------------------------------------------------------------------------

export async function listPlans(patientId: string): Promise<{ count: number; plans: PlanSummary[] }> {
  return fetch(`${API_PREFIX}/plans?patient_id=${encodeURIComponent(patientId)}`).then((r) =>
    handleResponse<{ count: number; plans: PlanSummary[] }>(r)
  );
}

export async function getPlan(planId: string): Promise<MealPlan> {
  return fetch(`${API_PREFIX}/plans/${encodeURIComponent(planId)}`).then((r) =>
    handleResponse<MealPlan>(r)
  );
}

// ---------------------------------------------------------------------------
// Mining / patient-aware swaps
// ---------------------------------------------------------------------------

export async function getSubstitutions(
  dishId: string,
  patientId: string,
  k = 3,
  planId?: string,
): Promise<SubstitutionResponse> {
  return fetch(
    `${API_PREFIX}/mining/substitutions?dish_id=${encodeURIComponent(dishId)}&patient_id=${encodeURIComponent(patientId)}&k=${k}${planId ? `&plan_id=${encodeURIComponent(planId)}` : ''}`
  ).then((r) => handleResponse<SubstitutionResponse>(r));
}

export async function applySwap(payload: SwapApplyRequest): Promise<MealPlan> {
  return fetch(`${API_PREFIX}/mining/swaps/apply`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then((r) => handleResponse<MealPlan>(r));
}

// ---------------------------------------------------------------------------
// Review queue
// ---------------------------------------------------------------------------

export async function getReviewQueue(
  patientId: string | null,
  status: 'open' | 'acknowledged' | 'actioned' | 'all'
): Promise<ReviewQueueResponse> {
  const params = new URLSearchParams();
  if (patientId) params.set('patient_id', patientId);
  params.set('status', status);
  return fetch(`${API_PREFIX}/review/queue?${params.toString()}`).then((r) =>
    handleResponse<ReviewQueueResponse>(r)
  );
}

export async function getReviewItems(
  patientId?: string,
  status?: 'open' | 'acknowledged' | 'actioned'
): Promise<ReviewQueueResponse> {
  const params = new URLSearchParams();
  if (patientId) params.set('patient_id', patientId);
  if (status) params.set('status', status);
  return fetch(`${API_PREFIX}/review/items?${params.toString()}`).then((r) =>
    handleResponse<ReviewQueueResponse>(r)
  );
}

export async function acknowledgeReview(reviewId: string): Promise<ReviewItem> {
  return fetch(`${API_PREFIX}/review/${encodeURIComponent(reviewId)}/acknowledge`, {
    method: 'POST',
  }).then((r) => handleResponse<ReviewItem>(r));
}

export async function actionReview(reviewId: string, body: ReviewActionRequest): Promise<ReviewItem> {
  return fetch(`${API_PREFIX}/review/${encodeURIComponent(reviewId)}/action`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then((r) => handleResponse<ReviewItem>(r));
}

export async function proposalReview(reviewId: string): Promise<ReviewProposalResponse> {
  return fetch(`${API_PREFIX}/review/${encodeURIComponent(reviewId)}/proposal`, {
    method: 'POST',
  }).then((r) => handleResponse<ReviewProposalResponse>(r));
}

// ---------------------------------------------------------------------------
// Observations
// ---------------------------------------------------------------------------

export async function createObservation(payload: ObservationRequest): Promise<Observation> {
  return fetch(`${API_PREFIX}/observations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then((r) => handleResponse<Observation>(r));
}

export async function listObservations(patientId: string): Promise<ObservationListResponse> {
  return fetch(`${API_PREFIX}/observations?patient_id=${encodeURIComponent(patientId)}`).then((r) =>
    handleResponse<ObservationListResponse>(r)
  );
}

// ---------------------------------------------------------------------------
// What-if simulations
// ---------------------------------------------------------------------------

export async function createSimulation(payload: SimulationRequest): Promise<Simulation> {
  return fetch(`${API_PREFIX}/simulations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then((r) => handleResponse<Simulation>(r));
}

export async function listSimulations(patientId: string): Promise<SimulationListResponse> {
  return fetch(`${API_PREFIX}/simulations?patient_id=${encodeURIComponent(patientId)}`).then((r) =>
    handleResponse<SimulationListResponse>(r)
  );
}
