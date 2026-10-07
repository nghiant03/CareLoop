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

export interface MealSlot {
  day: number;
  meal: 'breakfast' | 'lunch' | 'dinner';
  dish: string;
}

export interface DailyNutrient {
  name: string;
  value: number;
  unit: string;
  target?: number;
  max?: number;
  min?: number;
}

export interface DailySummary {
  day: number;
  slots: MealSlot[];
  totals: DailyNutrient[];
  explanation?: string;
}

export interface MealPlan {
  id: string;
  patient_id: string;
  envelope_id: string;
  days: DailySummary[];
  explanation?: string;
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
