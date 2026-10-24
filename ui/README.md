# CareLoop UI

React, TypeScript, Vite and Tailwind UI connected to the CareLoop API.
The established navy/blue visual system is retained.

## Run

From the repository root, `docker compose up --build -d` serves the application at
<http://localhost:5173>. See the [root README](../README.md) for database setup.

For development, start the API using the root README, then from `ui/`:

```sh
npm ci
npm run dev
```

Vite proxies `/api` unchanged to `http://localhost:8000`. Set
`CARELOOP_API_PROXY` to use a different backend. Production Nginx proxies the same
prefix to the Compose API service and serves client-side routes.

## Workspaces

Foods and meal plans visibly label estimated composition, with expandable methods
and uncertainty details derived from food snapshots. Plan totals using these values
are approximations. Verification: 31 UI tests, build/lint and detector passed.
Deploy with `sudo docker compose up --build -d api web`.

Egg/dairy inclusion preference controls have been removed from the patient editor
and evidence fact picker. The backend no longer uses those legacy preferences as
planning gates. Explicit egg/milk allergies are still handled through allergy
records. Verification: 30 UI tests, build, lint and detector passed; deploy API
and web together with `sudo docker compose up --build -d api web`.

Meal plans default to searching all eligible catalogue foods. Food choices
(optional) lets patients restrict the pool or exclude foods; selecting individual
foods is no longer required. Replacement recommendations use the same scope.
Search outcomes explain blockers and bounded shortlisting. Verification: 30 UI
tests, build and lint passed. Deploy API and web together:
`sudo docker compose up --build -d api web`.

Patient life-stage fields use a native Pregnancy and breastfeeding disclosure:
collapsed by default for male, expanded for other/unknown sex. Switching sex resets
that display default but preserves all recorded Yes/No/Unknown values. The collapsed
summary shows both recorded values. Verification: 28 UI tests, build and lint passed;
mechanical detector reported no findings. Browser visual checks remain unavailable.
Deploy this UI change with `sudo docker compose up --build -d --no-deps web`.

### Usability review, 2026-10-24

| Surface inspected | Changes |
|---|---|
| Patient target review | Select required assessments and advisory guidance; explicit decision fields; text/status/category filters; hidden selections retained; readable saved blockers |
| Evidence | Explicit reviewer assessment category/rationale; guidance-category filter; failed loads no longer described as an empty catalogue |
| Extraction | Current-page history search/status filter, passage empty state, extract action disabled without a selected passage |
| Foods and shared pickers | Clear search/selection, hidden-selection count, accurate no-match vs empty-catalogue text |
| Plans (patient/clinician) | Saved-plan search/status filter; accurate empty/error states and retry |
| Intake (patient/clinician) | Date-scoped entry search/status filter without changing complete-day totals |
| Nutrition questions | Current-page question/answer search and run-status filter |
| App shell/shared forms | Current-page patient search, loading/count feedback, focusable skip-link target; submit handler respects disabled/busy state |

Advisory guidance never becomes a meal-planning constraint. Required assessment
selection still needs a recorded clinical decision; numeric targets can be entered
separately. Existing target sets need a new proposal after the reviewed category
publication. History filters indicate page/date scope instead of implying a global
search. Backend checks enforce category eligibility and duplicate-reference rules.
Verification: 26 UI tests, build and lint passed; mechanical detector found no
issues. Browser visual validation remains unavailable. API/web deployment and the
reviewed category publication are pending; see [evidence](../docs/EVIDENCE.md).

Nutrition target controls now distinguish mandatory minimums from soft intake goals,
offer `% of daily energy` for supported nutrients, and expose strict ceilings.
Food review includes trans fat and documented fruit/vegetable gram contributions.
Changing a target's nutrient/unit clears incompatible amounts. The form keeps native
numeric limits and interaction-based validation. Verification: 23 UI tests, build
and lint passed; deployment needs the updated API and web together. Apply the
source-backed rule batch using the command in [evidence](../docs/EVIDENCE.md).

Evidence tables now render with preserved merged cells, sticky column headers and
keyboard-accessible horizontal scrolling across evidence, patient and chat views.
The shared renderer rebuilds an allowlist of React elements rather than injecting
HTML. Verification: `npm run test -- --reporter=dot` (22 passed), `npm run build`,
and `npm run lint` passed; detector found no findings. Tests cover merged cells,
entities, literal comparisons and removal of executable source markup. Browser
visual verification was unavailable; deployment still requires the web rebuild.

Evidence review now includes combined rule filters, visible-result selection,
hidden-selection counts, scannable advice/population summaries, expandable source
quotes and extraction history, and a cancel action in the rule editor. Acquisition
is collapsed by default; source attribution remains visible on each rule.
Verification for this refinement: `npm run test -- --reporter=dot` (19 passed),
`npm run build`, and `npm run lint` passed. The mechanical UI detector reported no
findings. Browser visual verification remains unavailable in this environment.

| Route | Workflow |
|---|---|
| `/clinician/patients` | Patient entry/CSV, fact revisions, target proposals and explicit approval |
| `/clinician/plan-review` | Inspect patient-requested plans and approve checked alternatives |
| `/clinician/intake-review` | Read-only intake, revision history and target comparisons |
| `/patient/meal-plans` | Multi-item meal search, saved alternatives and substitution requests |
| `/patient/meal-log` | Item/whole-meal logging, corrections and day completeness |
| `/patient/nutrition-questions` | Cited target/plan/intake explanations, checked substitutions and saved history |
| `/reviewer/foods` | Food search, reviewed portions, suitability and nutrient corrections |
| `/reviewer/evidence` | Source acquisition, passage extraction, draft review and publication |

`src/navigation.ts` defines role-scoped, lowercase, hyphenated browser paths.
The same allowlist drives menus and mounted routes. `/` and disallowed URLs
redirect to the selected role's landing page. Reviewers have no patient selector;
clinician planning/logging views expose review rather than patient-entry controls.

Demo roles and actor labels are not authentication. Approval is explicit; no
clinical records or recommendations are automatically seeded. Hosted extraction
and chat use GLM 5.3, JSON mode, high reasoning, and an 8,192-token limit.
Both preserve request IDs and provide status checks after interrupted requests;
refreshing history does not resend provider calls. Chat requires current approved
targets. Optional attachments select an approved plan, intake date, or meal item and
candidate pool for checked substitutions. Suggested replacements can be requested as
drafts for clinician approval. Historical answers are marked when patient context,
evidence, selected intake or candidate-food revisions change.

## Code structure

`src/App.tsx` owns routing and the demo session. Workflow screens live
in `src/screens/`, with reusable controls in `src/components/`. `src/api.ts` is the
single typed API client; `src/state.ts` provides shared session and request state.
Tests live beside the application and screens. Workflow contracts live in `../docs/`.

## Verify

```sh
npm run build
npm run lint
npm run test -- --reporter=dot
```

Component checks cover role-scoped routes, read-only clinician views, extraction,
chat request recovery/citations, multi-item requests and item-specific logging.
They also cover CKD Yes/No/Unknown transitions, clearing inapplicable stages,
legacy stage-only records, and rule-source attribution independent of the library
selection. On 2026-10-24, build/lint and all 18 UI tests passed for these changes.
The accompanying 45 backend checks passed with:

```sh
uv run --with pgserver==0.1.4 python tests/run_postgres.py -q tests/test_ckd_status.py tests/test_patients.py tests/test_evidence.py tests/test_extraction.py tests/test_public_data.py tests/test_applicability.py tests/test_conflicts.py
```

The initial UI regression run exposed a stale test element after a save-triggered
remount; the test was corrected and rerun. An initial backend command named a
nonexistent `test_nhanes.py`; the corrected command above ran successfully.
Two Pydantic field-alias warnings remain in concurrent workflow tests. Browser
visual checks were unavailable (no local Playwright installation/browser).
Deployment requires rebuilding the API and web services together; Docker access
was denied in the agent session and noninteractive sudo required a password.

Live browser verification uses explicitly synthetic
software-test records in a temporary database; it is not clinical validation.
