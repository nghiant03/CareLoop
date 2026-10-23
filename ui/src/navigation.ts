import type { Role } from './api';

export const paths = {
  patients: '/clinician/patients',
  planReview: '/clinician/plan-review',
  intakeReview: '/clinician/intake-review',
  mealPlans: '/patient/meal-plans',
  mealLog: '/patient/meal-log',
  questions: '/patient/nutrition-questions',
  evidence: '/reviewer/evidence',
  foods: '/reviewer/foods',
} as const;

type Workspace = {
  to: string;
  label: string;
  screen: 'patients' | 'plans' | 'logging' | 'chat' | 'evidence' | 'foods';
};
export const workspaces: Record<Role, Workspace[]> = {
  clinician: [
    { to: paths.patients, label: 'Patients & targets', screen: 'patients' },
    { to: paths.planReview, label: 'Plan review', screen: 'plans' },
    { to: paths.intakeReview, label: 'Intake review', screen: 'logging' },
  ],
  patient: [
    { to: paths.mealPlans, label: 'Meal plans', screen: 'plans' },
    { to: paths.mealLog, label: 'Meal log', screen: 'logging' },
    { to: paths.questions, label: 'Nutrition questions', screen: 'chat' },
  ],
  reviewer: [
    { to: paths.evidence, label: 'Evidence review', screen: 'evidence' },
    { to: paths.foods, label: 'Food catalogue', screen: 'foods' },
  ],
};

export const workspaceDescriptions: Record<Role, string> = {
  clinician:
    'Review patient facts, approve nutrition targets and meal plans, and inspect recorded intake.',
  patient:
    'Request meal plans, record your intake, and ask questions about your approved nutrition targets.',
  reviewer:
    'Review food composition and source evidence, resolve draft issues, and publish approved rules.',
};
