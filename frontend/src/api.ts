import type {
  Patient,
  Envelope,
  EnvelopeResponse,
  RuleFire,
  MealPlan,
  ChatMessageResponse,
  TraceEntry,
  EditEnvelopePayload,
  Dish,
  AdherenceSummary,
  AdherenceDeviation,
  CalendarMetadata,
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
  ApiError,
} from './types';

const API_PREFIX = '/api';

export function normalizeEnvelope(raw: EnvelopeResponse): Envelope {
  return {
    id: raw.envelope_id,
    patient_id: raw.patient_id,
    status: raw.status,
    version: raw.version,
    lifecycle_revision: raw.lifecycle_revision,
    scope_eligible: raw.scope_eligible,
    constraints: raw.targets,
    exclusions: raw.exclusions,
    citations: raw.citations,
    trace: raw.fired_rules.map(normalizeTrace),
    created_at: raw.proposed_at,
  };
}

function normalizeTrace(row: RuleFire): TraceEntry {
  return {
    rule_id: row.rule_id,
    priority: row.priority,
    fired_at: row.fired_at,
    guideline: row.citation.guideline,
    section: row.citation.section,
    url: row.citation.url,
    message: row.action_summary,
    overridden_by: row.action_summary.match(/SUPERSEDED: superseded by ([\w-]+)/)?.[1],
  };
}

/** HTTP failures preserve the server body/code and the existing display message. */
export class HttpApiError extends Error implements ApiError {
  readonly status: number;
  readonly code: string | undefined;
  readonly body: unknown;
  readonly error: string;
  readonly detail: string;
  readonly data: string;

  constructor(status: number, code: string | undefined, body: unknown, message: string) {
    super(message);
    this.status = status;
    this.code = code;
    this.body = body;
    this.name = 'HttpApiError';
    this.error = code ?? 'http_error';
    this.detail = message;
    this.data = message; // Retain the old message alias for existing callers.
  }
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    let body: unknown;
    let code: string | undefined;
    try {
      body = await res.json();
      const record = body && typeof body === 'object' ? body as Record<string, unknown> : {};
      const raw = record.detail || record.error || body;
      const nested = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {};
      const serverCode = record.error || nested.error;
      if (typeof serverCode === 'string') code = serverCode;
      const message = record.message || (typeof raw === 'string' ? raw : (nested.message || nested.error || JSON.stringify(raw)));
      if (typeof message === 'string') detail = message;
    } catch {
      // Non-JSON error bodies retain the HTTP status text as the message.
    }
    throw new HttpApiError(res.status, code, body, detail);
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
    .then((r) => handleResponse<{ envelope: EnvelopeResponse; trace: RuleFire[] }>(r))
    .then(({ envelope, trace }) => ({ envelope: normalizeEnvelope(envelope), trace: trace.map(normalizeTrace) }));
}

export async function getEnvelope(id: string): Promise<Envelope> {
  return fetch(`${API_PREFIX}/envelopes/${id}`)
    .then((r) => handleResponse<EnvelopeResponse>(r))
    .then(normalizeEnvelope);
}

/** Latest envelope in any lifecycle state. This lookup does not authorize planning. */
export async function getLatestEnvelope(patientId: string): Promise<Envelope> {
  return fetch(`${API_PREFIX}/envelopes/latest?patient_id=${encodeURIComponent(patientId)}`)
    .then((r) => handleResponse<EnvelopeResponse>(r))
    .then(normalizeEnvelope);
}

export async function approveEnvelope(
  id: string,
  payload: { clinician_id: string; note?: string; expected_revision?: number }
): Promise<Envelope> {
  return fetch(`${API_PREFIX}/envelopes/${id}/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
    .then((r) => handleResponse<EnvelopeResponse>(r))
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
    .then((r) => handleResponse<EnvelopeResponse>(r))
    .then(normalizeEnvelope);
}

export async function rejectEnvelope(
  id: string,
  payload: { reason?: string; expected_revision?: number }
): Promise<Envelope> {
  return fetch(`${API_PREFIX}/envelopes/${id}/reject`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
    .then((r) => handleResponse<EnvelopeResponse>(r))
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

export async function getCalendarMetadata(): Promise<CalendarMetadata> {
  return fetch(`${API_PREFIX}/calendar`).then((r) => handleResponse<CalendarMetadata>(r));
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
  ).then((data) => ({
    ...data,
    // Normalize legacy local flag keys; current keys pass through.
    flags: data.flags.map((flag) => {
      const candidates = [
        `${flag.envelope_id}::v${flag.envelope_version}::${flag.series_key}`,
        `${flag.envelope_id}::${flag.series_key}`,
        flag.series_key,
      ];
      return { ...flag, series_key: candidates.find((key) => key in data.series) ?? flag.series_key };
    }),
  }));
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

/** Omitted planId uses the latest saved plan. Plan-specific UI must supply its saved ID. */
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

/** Replace all occurrences in the saved source; omitted plan_id uses the latest saved plan.
 * Saving is best-effort. An absent response ID does not establish that no commit occurred.
 */
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

/** Derive and persist newly seen review conditions, then list by persisted status. */
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

export async function createReviewProposal(reviewId: string): Promise<ReviewProposalResponse> {
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
