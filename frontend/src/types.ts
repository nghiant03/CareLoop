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

export interface CalendarMetadata {
  today: string;
  timezone: string;
  utc_offset_minutes: number;
}

export interface NutrientConstraint {
  nutrient: string;
  kind: 'max' | 'min' | 'target';
  value: number;
  unit: string;
  note?: string;
  provenance?: ConstraintProvenance | null;
}

export interface ConstraintProvenance {
  nutrient: string;
  kind: NutrientConstraint['kind'];
  value: number;
  unit: string;
  envelope_id: string;
  version: number;
  author: string;
  citation: Citation;
}

export interface RuleFire {
  rule_id: string;
  priority: number;
  fired_at: string;
  patient_summary: string;
  action_summary: string;
  citation: Citation;
}

export interface ExclusionFlag {
  kind: 'ingredient' | 'dish_category' | 'macro_pattern' | 'diet_pattern';
  value: string;
  reason: string;
  citation: Citation;
}

export interface EnvelopeResponse {
  envelope_id: string;
  patient_id: string;
  status: Envelope['status'];
  version: number;
  lifecycle_revision: number;
  scope_eligible: boolean;
  targets: NutrientConstraint[];
  exclusions: ExclusionFlag[];
  citations: Citation[];
  fired_rules: RuleFire[];
  proposed_at: string;
}

export interface Citation {
  rule_id: string;
  guideline: string;
  section?: string;
  url?: string | null;
}

export interface TraceEntry {
  rule_id: string;
  priority: number;
  guideline: string;
  section?: string;
  url?: string | null;
  fired_at?: string;
  message?: string;
  overridden_by?: string;
}

export interface Envelope {
  id: string;
  patient_id: string;
  status: 'PROPOSED' | 'APPROVED' | 'REJECTED' | 'EDITED';
  constraints: NutrientConstraint[];
  version: number;
  lifecycle_revision: number;
  scope_eligible: boolean;
  exclusions?: ExclusionFlag[];
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
  expected_revision?: number;
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
  /** MAX ceilings only; null when this nutrient has no MAX constraint. */
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
  /** One-based day with the largest deviation; earliest day wins a tie. */
  worst_day: number;
  worst_daily: number;
  /** Compatibility name: MIN shortfall or absolute TARGET deviation, including overshoot. */
  shortfall: number;
  /** Same deviation as a percentage of the original aim; zero when aim <= 1e-9. */
  shortfall_pct: number;
  met_days: number;
  total_days: number;
  relaxed_aim: number | null;
}

export interface MealPlan {
  envelope_version?: number;
  adequate?: boolean;
  meal_complete?: boolean;
  data_quality?: { unverified_dishes: number; dish_count: number; cost_is_estimated: boolean };
  hard_feasible?: boolean;
  infeasibility_status?: 'proven_infeasible' | 'search_exhausted' | null;
  exact_reference?: { feasible_day: boolean; feasible_combo_count: number; pool_size: number } | null;
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
  plan_id?: string;
  saved_at?: string | null;
  derived_from?: string | null;
  applied_swap?: AppliedSwap | null;
}

export interface AppliedSwap {
  dish_id: string;
  replacement_dish_id: string;
  affected_days: number[];
  occurrences_replaced: number;
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
  contributors?: Contributor[];
}

export interface AdherenceDay {
  date: string;
  meals: { meal: string; dish_id: string }[];
  totals: Record<string, number>;
  nutrients: AdherenceAnalysis[];
  hard_violations: (AdherenceAnalysis | ExcludedDishViolation)[];
  soft_gaps: AdherenceAnalysis[];
  compliant: boolean;
  completeness?: { meals_logged: number; expected_meals: number; complete: boolean };
  envelope_id?: string;
  envelope_version?: number;
}

export interface ExcludedDishViolation {
  type: 'excluded_dish';
  dish_id: string;
  dish_name?: string | null;
  meal?: string | null;
  exclusion_kind: string;
  exclusion_value: string;
  reason: string;
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
  envelope_versions_used?: EnvelopeVersionUsed[];
  unattributed_days?: string[];
}

export interface AdherencePoint {
  /** Absent on older responses; the backend treats those points as complete. */
  complete?: boolean;
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
  envelope_id?: string;
  envelope_version?: number;
  nutrient: string;
  series_key: string;
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
  envelope_versions_used?: EnvelopeVersionUsed[];
  unattributed_days?: string[];
}

export interface EnvelopeVersionUsed {
  envelope_id: string;
  version: number;
  status: string;
  days: string[];
}

export interface PlanSummary {
  plan_id: string;
  patient_id: string;
  envelope_id: string;
  envelope_version?: number;
  engine?: string;
  feasible: boolean;
  violation_count: number;
  kb_version?: string | null;
  created_at: string;
  derived_from?: string | null;
}

export interface Contributor {
  dish_id: string;
  dish_name?: string | null;
  amount: number;
  pct_of_day_total: number;
}

export interface SubstituteDish {
  dish_id: string;
  name: string;
  distance: number;
  /** Adjusted ranking score; lower is better and may be negative. distance is its legacy alias. */
  ranking_score?: number;
  nutrient_distance: number;
  category_match: boolean;
  reason: string;
  day_deltas: Record<string, Record<string, number>>;
  cost_delta: number;
  passes_hard_checks: boolean;
  worst_aim_shortfall_pct?: number | null;
}

export interface SubstitutionResponse {
  dish_id: string;
  k: number;
  patient_id: string;
  plan_id: string;
  informational_only: boolean;
  notice: string | null;
  affected_days: number[];
  substitutions: SubstituteDish[];
}

export interface ReviewContributor {
  dish_id: string;
  dish_name?: string | null;
  amount: number;
  pct_of_day_total: number;
}

export interface AdherenceFlagPayload {
  nutrient: string;
  kind: 'max' | 'min' | 'target';
  slope_pct_per_day: number;
  direction: 'worsening' | 'improving';
  severity: 'alert' | 'review';
  latest_exposure_pct: number;
  projected_3d_exposure_pct: number;
  reason: string;
  contributors?: ReviewContributor[];
}

export interface ViolationDayPayload {
  date: string;
  meals: { meal: string; dish_id: string; dish_name?: string | null }[];
  totals: Record<string, number>;
  nutrients: AdherenceAnalysis[];
  hard_violations: (AdherenceAnalysis | ExcludedDishViolation)[];
  soft_gaps: AdherenceAnalysis[];
  compliant: boolean;
  completeness?: { meals_logged: number; expected_meals: number; complete: boolean };
  envelope_id?: string;
  envelope_version?: number;
}

export interface LabTrendPayload {
  analyte: string;
  patient_id: string;
  slope: number;
  direction: 'rising' | 'falling' | string;
  severity: 'urgent' | 'review' | string;
  reason: string;
}

export type ReviewItemPayload = AdherenceFlagPayload | ViolationDayPayload | LabTrendPayload | Record<string, unknown>;

export type ReviewSource = 'adherence_flag' | 'hard_violation_day' | 'lab_trend';

export interface ReviewAction {
  action: string;
  note?: string | null;
  linked_envelope_id?: string | null;
  recorded_at?: string;
}

export interface ReviewItem {
  review_id: string;
  patient_id: string;
  source: ReviewSource;
  key?: string | null;
  kind?: string | null;
  severity: 'alert' | 'review';
  reason: string;
  status: 'OPEN' | 'ACKNOWLEDGED' | 'ACTION_RECORDED';
  created_at: string;
  acknowledged_at?: string | null;
  payload: ReviewItemPayload;
  action?: ReviewAction | null;
  linked_envelope_id?: string | null;
}

export interface ReviewQueueResponse {
  count: number;
  items: ReviewItem[];
}

export interface ReviewActionRequest {
  action: string;
  note?: string;
}

export interface ReviewProposalResponse {
  review_item: ReviewItem;
  envelope_id: string;
}

export interface Observation {
  observation_id: string;
  patient_id: string;
  metric: 'serum_K_meq_L' | 'serum_PO4_mg_dL' | 'egfr' | 'hba1c_pct';
  value: number;
  unit: string;
  source?: string | null;
  observed_at: string;
  recorded_at: string;
}

export interface ObservationRequest {
  patient_id: string;
  metric: 'serum_K_meq_L' | 'serum_PO4_mg_dL' | 'egfr' | 'hba1c_pct';
  value: number;
  unit: string;
  source?: string;
  observed_at?: string;
}

export interface ObservationListResponse {
  patient_id: string;
  count: number;
  observations: Observation[];
}

export interface SimulationSide {
  envelope_id: string;
  plan_id?: string | null;
  feasible?: boolean | null;
  violation_count?: number | null;
  objectives?: Record<string, number> | null;
  adequacy_summary?: AdequacyItem[];
  cost?: number | null;
  infeasibility_reason?: string | null;
  infeasibility_status?: string | null;
  relaxed_constraints?: RelaxedConstraint[];
}

export interface SimulationDeltas {
  cost: number | null;
  nutrient_target_deviation: number | null;
  variety: number | null;
  worst_shortfall_pct: number | null;
  meals_changed: number | null;
}

export interface Simulation {
  simulation_id: string;
  patient_id: string;
  proposed_targets: NutrientConstraint[];
  base: SimulationSide;
  simulated: SimulationSide;
  deltas: SimulationDeltas;
  created_at?: string;
}

export interface SimulationListResponse {
  count: number;
  simulations: Simulation[];
}

export interface SimulationRequest {
  patient_id: string;
  targets: NutrientConstraint[];
}

export interface SwapApplyRequest {
  patient_id: string;
  dish_id: string;
  replacement_dish_id: string;
  plan_id?: string;
}
