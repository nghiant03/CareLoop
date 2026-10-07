# CareLoop Frontend

React 19 + TypeScript + Vite + Tailwind CSS 4 UI for CareLoop: three role
screens over the FastAPI backend.

## Run

```bash
# backend must be up first (repo root):
PYTHONPATH=. .venv/bin/uvicorn backend.app.main:app --reload --port 8000

# then, from frontend/:
npm install
npm run dev        # http://localhost:5173
```

The Vite dev server proxies every `/api/*` request to
`http://localhost:8000` (`vite.config.ts`, `changeOrigin: true`), so the app
talks to the backend with no CORS setup in dev. Other scripts:
`npm run build` (tsc -b + vite build → `dist/`), `npm run lint` (oxlint),
`npm run preview`.

## Screens (`src/screens/`)

| Route | Screen | What it does |
|---|---|---|
| `/` | `ClinicianReviewScreen` | pick a patient → **Generate proposed envelope** → constraint table + fired-rule trace → Approve / Edit (modal) / Reject |
| `/plan` | `PatientMealPlanScreen` | pick a patient → **Generate 7-day plan** → per-day meals + "daily totals vs targets" bars (red = over limit) + plain-language explanation; explains the 409 "not approved yet" case |
| `/chat` | `ChatScreen` | pick a patient → ask nutrition questions; answers render guideline citations, escalated messages show a banner |

Top navigation lives in `components/TopBar.tsx`; `components/OfflineBanner.tsx`
flags when the backend is unreachable (`/api/healthz` probe).

## Supporting components

- `ConstraintTable` — envelope constraints with citations.
- `RuleTrace` — fired rules sorted by priority with guideline links and
  "Overridden by" markers for superseded rules.
- `EditEnvelopeModal` — adjust constraint values, save via `POST /envelopes/{id}/edit`
  (the envelope returns to EDITED and needs re-approval).
- `PatientCard`, `LoadingState`, `EmptyState` — list/detail plumbing.

## API client (`src/api.ts`)

Thin `fetch` wrappers over the backend endpoints (`listPatients`, `runRules`,
`getEnvelope`, `approveEnvelope`, `editEnvelope`, `rejectEnvelope`,
`createPlan`, `sendChat`, `healthz`) plus a `normalizeEnvelope` adapter that
maps the backend envelope shape (`envelope_id`, `targets`, `fired_rules`) onto
the UI types (`id`, `constraints`, `trace`) declared in `src/types.ts`.

## Tooling notes

- Linting is Oxlint (`.oxlintrc.json`); enable type-aware rules by installing
  `oxlint-tsgolint` if desired.
- `npm run build` type-checks via `tsc -b`; the dev server transpiles only.
