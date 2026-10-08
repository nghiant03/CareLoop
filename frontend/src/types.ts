export interface Patient {
  id: string;
  name?: string;
  age: number;
  sex: string;
  diagnoses: string[];
  egfr?: number;
  serum_k?: number;
  serum_po4?: number;
  meds?: string[];
}

export interface NutrientConstraint {
  id?: string;
  nutrient: string;
  kind: 'max' | 'min' | 'target';
  value: number;
  unit: string;
  note?: string;
}

export interface Citation {
  rule_id: string;
  guideline: string;
  section?: string;
  url?: string;
}

export interface TraceEntry {
  rule_id: string;
  priority: number;
  guideline: string;
  section?: string;
  url?: string;
  fired_at?: string;
  message?: string;
  overridden_by?: string;
}

export interface Envelope {
  id: string;
  patient_id: string;
  status: 'PROPOSED' | 'APPROVED' | 'REJECTED' | 'EDITED';
  constraints: NutrientConstraint[];
  exclusions?: string[];
  citations?: Citation[];
  trace?: TraceEntry[];
  created_at?: string;
  updated_at?: string;
}

export interface EditEnvelopePayload {
  targets: NutrientConstraint[];
  exclusions?: unknown[];
  notes?: string;
  edited_by?: string;
}

export interface PlanSlot {
  meal: string;
  dish_id: string;
  name: string;
  category?: string;
  nutrients: Record<string, number | null>;
}

export interface PlanTotalTarget {
  kind: 'max' | 'min' | 'target';
  value: number;
  unit: string;
}

export interface PlanTotal {
  nutrient: string;
  unit: string;
  value: number;
  targets: PlanTotalTarget[];
  compliant: boolean | null;
}

export interface PlanDay {
  day: number;
  slots: PlanSlot[];
  totals: PlanTotal[];
}

export interface PlanViolation {
  nutrient: string;
  kind: 'max' | 'min' | 'target';
  amount: number | null;
  actual: number | null;
  limit: number | null;
}

export interface RelaxedConstraint {
  nutrient: string;
  kind: 'min';
  requested: number;
  relaxed_to: number;
  unit: string;
  reason: string;
}

export interface PatientExplanationDailyTarget {
  label: string;
  text: string;
}

export interface PatientExplanation {
  headline: string;
  daily_targets: PatientExplanationDailyTarget[];
  avoid: string[];
  why: string[];
  approval_note?: string | null;
  plan_summary?: string[] | null;
  relaxation_notes?: string[];
}

export interface AdequacyItem {
  nutrient: string;
  kind: 'min' | 'target';
  unit: string;
  aim: number;
  mean_daily: number;
  worst_day: number;
  worst_daily: number;
  shortfall: number;
  shortfall_pct: number;
  met_days: number;
  total_days: number;
  relaxed_aim: number | null;
}

export interface MealPlan {
  envelope_id: string;
  patient_id: string;
  feasible: boolean;
  engine?: string;
  violation_count: number;
  runtime_ms?: number;
  objectives?: Record<string, number> | null;
  allowed_dish_count?: number;
  infeasibility_reason: string | null;
  violations: PlanViolation[];
  relaxed_constraints: RelaxedConstraint[];
  days: PlanDay[];
  explanation: PatientExplanation;
  status: string;
  adequacy?: AdequacyItem[];
}

export interface ChatMessageResponse {
  answer: string;
  citations: Citation[];
  escalated: boolean;
}

export interface ApiError {
  error: string;
  detail?: string;
}

export interface Dish {
  dish_id: string;
  name: string;
  category?: string;
  cuisine?: string;
  portion_g?: number;
  energy_kcal?: number;
  protein_g?: number;
  sodium_mg?: number;
  potassium_mg?: number;
  phosphorus_mg?: number;
  carbs_g?: number;
  tags?: string[];
}

export interface AdherenceAnalysis {
  nutrient: string;
  kind: 'max' | 'min' | 'target';
  unit: string;
  limit: number;
  total: number;
  deviation: number;
  direction: 'over' | 'under' | null;
  status: 'ok' | 'hard_violation' | 'soft_gap';
  pct_deviation: number;
}

export interface AdherenceDay {
  date: string;
  meals: { meal: string; dish_id: string }[];
  totals: Record<string, number>;
  nutrients: AdherenceAnalysis[];
  hard_violations: AdherenceAnalysis[];
  soft_gaps: AdherenceAnalysis[];
  compliant: boolean;
}

export interface AdherenceAggregate {
  days_logged: number;
  hard_violation_days: number;
  hard_violations_by_nutrient: Record<string, number>;
  soft_gaps_by_nutrient: Record<string, number>;
  mean_pct_deviation_by_nutrient: Record<string, number>;
}

export interface AdherenceSummary {
  patient_id: string;
  envelope_id: string;
  envelope_status: string;
  informational_only: boolean;
  notice: string | null;
  window: { start: string; end: string; days: number };
  days_logged: number;
  days: AdherenceDay[];
  aggregate: AdherenceAggregate;
}

export interface AdherencePoint {
  date: string;
  total: number;
  pct: number;
  exposure: number;
}

export interface AdherenceSeries {
  nutrient: string;
  kind: 'max' | 'min' | 'target';
  unit: string;
  limit: number;
  points: AdherencePoint[];
}

export interface TrendFlag {
  nutrient: string;
  kind: 'max' | 'min' | 'target';
  slope_pct_per_day: number;
  direction: 'worsening' | 'improving';
  severity: 'alert' | 'review';
  latest_exposure_pct: number;
  projected_3d_exposure_pct: number;
  reason: string;
}

export interface AdherenceDeviation {
  patient_id: string;
  envelope_id: string;
  envelope_status: string;
  informational_only: boolean;
  notice: string | null;
  window: { start: string; end: string; days: number };
  series: Record<string, AdherenceSeries>;
  flags: TrendFlag[];
}
