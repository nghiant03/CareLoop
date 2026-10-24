export type Role = 'clinician' | 'patient' | 'reviewer';
export type Actor = { name: string; role: Role };
export type Facts = Record<string, string | number | boolean | string[] | null>;
export type Provenance = {
  kind: string;
  source: string;
  notes: string;
  [key: string]: unknown;
};
export type Patient = {
  id: string;
  latest_revision: number;
  body: { display_name: string; facts: Facts; provenance: Provenance };
};
export type Action = {
  upper_exclusive?: boolean;
  kind: string;
  subject: string;
  amount?: number | null;
  upper?: number | null;
  unit?: string | null;
  advice: string;
};
export type RuleRef = { rule_id: string; revision: number };
export type TargetItem = {
  action: Action;
  origin: string;
  author?: string;
  rationale?: string;
  citation?: { quote: string; location: string; source_id: string };
  rule?: RuleRef;
};
export type Target = {
  id: string;
  latest_revision: number;
  approved_revision: number | null;
  needs_review: boolean;
  review_reasons?: string[];
  body: {
    energy_proposal?: {
      method: string;
      source: string;
      source_title: string;
      quote: string;
      review: string[];
      issues: string[];
      calculation: string | null;
      action: Action | null;
    };
    items: TargetItem[];
    blockers: unknown[];
    dispositions?: Array<{ rule: RuleRef; reason: string }>;
    assessments?: Array<{
      rule: RuleRef;
      reason: string;
      action: Action;
      citation: { quote: string; location: string };
    }>;
    guidance?: Array<{
      rule: RuleRef;
      action: Action;
      citation: { quote: string; location: string };
    }>;
  };
  evaluation: Array<
    RuleRef & {
      status: string;
      category?: 'target' | 'assessment' | 'advisory';
      review_note?: string | null;
      source_action: Action;
      missing: string[];
      issues: string[];
      citation: { quote: string; location: string; source_id: string };
    }
  >;
};
export type FoodBody = {
  source_details?: Record<string, string>;
  food_groups?: { fruit_and_vegetables?: number | null };
  name: string;
  category: string;
  basis: 'g' | 'ml';
  nutrients: Record<string, number | null>;
  portions: Array<{
    id: string;
    label: string;
    grams?: number | null;
    millilitres?: number | null;
  }>;
  review_note?: string;
  allergen_status: Record<string, string>;
  vegetarian: boolean | null;
  contains_egg: boolean | null;
  contains_dairy: boolean | null;
  provenance: Provenance;
  import_warnings?: string[];
};
export type Food = { id: string; latest_revision: number; body: FoodBody };
export type Meal = {
  day: number;
  slot: string;
  item?: number;
  food_id: string;
  food_revision: number;
  food: FoodBody;
  portion_id: string;
  scale: number;
  quantity: string;
  unit: string;
};
export type Check = {
  uses_estimates?: boolean;
  estimated_inputs?: unknown[];
  valid: boolean;
  violations: unknown[];
  daily_totals: Record<string, Record<string, string | null>>;
  meal_totals?: Record<string, Record<string, Record<string, string | null>>>;
};

export function foodEstimates(food: FoodBody): Record<string, unknown> {
  try {
    const metadata = JSON.parse(
      food.source_details?.careloop_estimates ?? '{}',
    );
    return metadata?.estimates && typeof metadata.estimates === 'object'
      ? metadata.estimates
      : {};
  } catch {
    return {};
  }
}
export type Plan = {
  id: string;
  start_date?: string;
  objective: string;
  needs_review: boolean;
  review_reasons?: string[];
  approved_at: string | null;
  target_id: string;
  target_revision: number;
  request: { start_date: string; days: number; schedule: string[] };
  body: { meals: Meal[]; check: Check };
};
export type Recommendation = {
  name: string;
  food_id: string;
  portion_id: string;
  scale: number;
  quantity: string;
  unit: string;
  nutrient_delta: Record<string, string | null>;
  substitution: {
    day: number;
    slot: string;
    item: number;
    food_id: string;
    portion_id: string;
    scale: number;
  };
};
export type LogBody = {
  logged_on: string;
  slot: string;
  item?: number;
  plan_id: string | null;
  status: string;
  food_id?: string | null;
  portion_id?: string | null;
  scale?: number | null;
  note?: string;
  consumed: Meal | null;
  nutrients: Record<string, string | null>;
};
export type Log = { id: string; latest_revision: number; body: LogBody };
export type Day = {
  complete: boolean;
  entries: Log[];
  recorded_totals: Record<string, string | null>;
  planned_slots: Array<{ slot: string; item: number; status: string }> | null;
};
export type Source = {
  id: string;
  title: string;
  locator: string;
  edition: string;
  content?: string;
  document?: { metadata: { warnings: string[]; comparison?: unknown } } | null;
};
export type Predicate = {
  fact: string;
  operator: string;
  value: string | number | boolean;
};
export type RuleBody = {
  review_role?: 'required' | 'advisory';
  review_note?: string | null;
  source_id: string;
  quote: string;
  location: string;
  applicability: Predicate[];
  exceptions: Predicate[];
  population_note: string;
  exception_note: string;
  action: Action;
  blockers: string[];
};
export type Rule = {
  id: string;
  latest_revision: number;
  active_revision: number | null;
  retired: boolean;
  approved_by: string | null;
  draft: RuleBody;
};
export type Catalogue = { generation: number; rules: Rule[] };

export type Passage = { ordinal: number; location: string; content: string };
export type ExtractionRun = {
  id: string;
  state: 'pending' | 'completed' | 'failed';
  error: string | null;
  rule_ids: string[];
  created_at: string;
  result: { limitations: string[] } | null;
  request: { model: string; decision: { passage_ordinal: number } };
};
export type ChatContext = {
  ready: boolean;
  reason: string | null;
  patient_revision: number;
  target_id: string | null;
  target_revision: number | null;
  evidence_generation?: number;
  facts?: Facts;
  target_items?: TargetItem[];
  guidance?: Array<{
    rule: RuleRef;
    action: Action;
    citation: { quote: string; location: string };
  }>;
};
export type ChatRun = {
  id: string;
  question: string;
  model: string;
  created_at: string;
  state: 'pending' | 'completed' | 'failed';
  error: string | null;
  stale?: boolean;
  workflow?: { plan_id?: string | null; logged_on?: string | null };
  context: Pick<
    ChatContext,
    'patient_revision' | 'target_id' | 'target_revision' | 'evidence_generation'
  >;
  result: {
    answer: string;
    needs_clinician: boolean;
    insufficient_evidence: boolean;
    suggestions?: {
      plan_id: string;
      recommendations: Recommendation[];
      checked_portions: number;
      eligible_foods: number;
      approval_required: boolean;
    } | null;
    citations: Array<{
      source_id: string;
      title: string;
      kind: string;
      location: string;
      quote: string;
      edition?: string;
      locator?: string;
      document_id?: string;
      target_id?: string;
    }>;
  } | null;
};

export const slots = ['breakfast', 'lunch', 'dinner', 'snack'];
export const units: Record<string, string> = {
  energy: 'kcal/day',
  protein: 'g/day',
  carbohydrate: 'g/day',
  fat: 'g/day',
  saturated_fat: 'g/day',
  trans_fat: 'g/day',
  fruit_and_vegetables: 'g/day',
  fibre: 'g/day',
  free_sugars: 'g/day',
  sodium: 'mg/day',
  potassium: 'mg/day',
  phosphorus: 'mg/day',
};
export const label = (value: string) =>
  value === 'has_ckd' ? 'CKD status' : value.replaceAll('_', ' ');
export const quantity = (value: string | number | null | undefined) =>
  value == null
    ? 'Unknown'
    : Number(value).toLocaleString('en', { maximumFractionDigits: 2 });
export function localDate() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
}

export async function api<T>(
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    signal,
    headers:
      body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const detail = payload.detail;
    const message = Array.isArray(detail)
      ? detail
          .map(
            (d: { loc?: string[]; msg?: string }) =>
              `${d.loc?.join('.')}: ${d.msg}`,
          )
          .join('; ')
      : detail;
    throw new Error(
      typeof message === 'string'
        ? message
        : `Request failed (${response.status}). Retry or check the API connection.`,
    );
  }
  return response.json() as Promise<T>;
}
