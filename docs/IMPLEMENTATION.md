# Implementation status

## User-requested food estimates, 2026-10-24

Implemented and applied 2,689 audited food revisions with explicit estimation
metadata. Restored 1,491 source trans-fat values and filled missing composition
using documented category medians, total-sugar proxies and conservative produce
credits. The import adapter now maps trans fat and rejects values above total fat.
See [foods](FOODS.md#explicit-missing-value-estimates-2026-10-24) for methods/counts.
Food and plan screens label estimates; checks report their composition basis.

The updated planner preview for `04a29a39` yielded 2,573 eligible foods and three
one-day alternatives passing checks with estimated values (not clinician approvals).
The live food revisions were read-back verified; a second run prepared zero changes.
The API still reported the old preference schema at verification, so generation
gates/check metadata and UI labels require `sudo docker compose up --build -d api web`.
Re-propose/review targets if the condition-matching upgrade changes applicability.

Verification: full PostgreSQL suite `uv run --with pgserver==0.1.4 python
tests/run_postgres.py -q` passed 226 tests with one Pydantic field-alias warning in
the concurrent evidence-edit test. An earlier plain pytest run had 17 passes and
two database skips; the PostgreSQL run covered them. UI tests passed 31, including
visible estimate disclosure from stored food snapshots. Build, lint, full Ruff and
changed-screen detector passed. Browser visual checks remain unavailable. An audit
summary script initially passed dictionaries instead of their keys to Counter;
corrected and rerun successfully without affecting data revisions.

## Egg/dairy preference removal, 2026-10-24

Removed egg/dairy inclusion controls from Patients and the Evidence fact picker,
and removed their required-fact/food-exclusion checks from generation, final
checking, substitutions and the independent evaluation oracle. Existing values
remain readable as deprecated historical observations; no patient records are
rewritten. Explicit egg/milk allergies retain their separate allergen checks.
Missing nutrient composition remains an independent catalogue blocker.

Verification: `uv run --with pgserver==0.1.4 python tests/run_postgres.py -q
tests/test_planning.py tests/test_catalogue_planning.py tests/test_meal_items.py
tests/test_recommendations.py tests/test_chat.py tests/test_evaluation.py
tests/test_evaluation_workflow.py` passed 46 tests, including generation/approval
with legacy false or unknown preferences. UI tests passed 30; build, lint,
changed-file Ruff and UI detector passed. Browser visual checks are unavailable.
Deploy with `sudo docker compose up --build -d api web`.

## Condition-label matching, 2026-10-24

Replaced exact-only condition comparison with normalized explicit aliases and
directional subtype matching. Prediabetes/Pre-Diabetes now match without rewriting
patient observations. Rule exceptions and conflict analysis share those semantics;
target readiness detects changed applicability even when stored review flags predate
the matcher upgrade. See [patients](PATIENTS.md#rule-applicability-and-calculations).

Verification: `uv run --with pgserver==0.1.4 python tests/run_postgres.py -q
tests/test_condition_matching.py tests/test_condition_rules.py tests/test_patients.py
tests/test_evidence.py tests/test_planning.py tests/test_chat.py` passed 95 tests.
One Pydantic `UnsupportedFieldAttributeWarning` was reported in the concurrent
evidence-edit test. Changed-file Ruff passed after fixing an overlong alias line
and import spacing. API deployment is pending user Docker access:
`sudo docker compose up --build -d api`. Then propose/review fresh affected targets.

## Condition-rule expansion, 2026-10-24

Published and read-back verified 28 source-backed additions (52 active rules total).
See [evidence](EVIDENCE.md#condition-coverage-expansion-published-2026-10-24) for
the population/source matrix, capability limits and idempotent publication command.
No server rebuild is required for these catalogue additions.

The live coverage matrix covers six CKD stages, hypertension, prediabetes, diabetes,
hypoglycaemia risk, pregnancy, lactation, dialysis and two actual historical/current
patient snapshots. Synthea `03c5e223` revision 2 (17 years, G2) now evaluates to two
numeric targets, two required assessments and two advisory rules. Its current
revision 4 (20 years, G4) evaluates to eight numeric targets, four assessments and
five advisory rules, including a 47.84 g/day protein reference at recorded 59.8 kg.
These are evaluations, not clinical approvals. An initial live assertion assumed
the patient still had revision-2 facts; it failed after the record changed to
revision 4. Verification was corrected to read both exact stored revisions and passed.

Verification: `uv run --with pgserver==0.1.4 python tests/run_postgres.py -q
tests/test_condition_rules.py tests/test_rule_categories.py tests/test_patients.py
tests/test_nutrition_constraints.py tests/test_evidence.py` passed 59 tests.
Changed-file Ruff passed after correcting one overlong line. Publisher rerun
confirmed idempotency. No UI changes or browser checks were involved.

## Catalogue-default meal planning, 2026-10-24

Meal generation and substitution recommendations now search the catalogue by
default. Patients can optionally select a smaller pool or exclude foods through
the Food choices disclosure. Eligibility checks precede deterministic bounded
shortlisting; stored requests pin considered revisions. See [planning](PLANNING.md).

Verification: `uv run --with pgserver==0.1.4 python tests/run_postgres.py -q
tests/test_catalogue_planning.py tests/test_planning.py tests/test_recommendations.py
tests/test_meal_items.py tests/test_chat.py` passed 35 tests. `uv run ruff check src
tests` passed. In `ui`, `npm run test -- --reporter=dot` passed 30 tests;
`npm run build` and `npm run lint` passed. Browser visual verification is unavailable.
Deployment remains pending: `sudo docker compose up --build -d api web` requires
user Docker access.

## Rule categories and workspace usability, 2026-10-24

Implemented explicit required/advisory rule roles, reviewer rationale validation,
selectable clinical assessments with recorded decisions, optional selected guidance,
and separation from executable planner targets. Cited chat receives approved
guidance as a separately labelled source. Reviewed all 24 published rules: 10
targets, 8 required assessments, 6 advisory rules. The reviewed manifest is ready;
publication is pending API/web rebuild because the live API still has the old
schema and agent Docker access is denied. See [evidence](EVIDENCE.md).

Inspected Patients, Evidence, Extraction, Foods, Plans, Logging, Chat, the app shell
and shared form/picker controls. Fixed selection affordances and missing filters,
added readable target blocker summaries, differentiated empty search results from
empty catalogues, retained hidden selections, and made the skip-link target
focusable. History filters explicitly state when scoped to the current page/date.
All interaction changes preserve existing role restrictions and stored approvals.

Verification: full PostgreSQL suite (`uv run --with pgserver==0.1.4 python
tests/run_postgres.py -q`) passed 160 tests. UI tests passed 26 tests, including
selecting required assessments/advisory guidance, filtered selection persistence,
revealing unresolved hidden decisions and approved read-only revisions. UI build,
lint, changed-file Ruff and mechanical detector passed (no detector findings).
Initial build caught an unused import; corrected. Browser visual/keyboard checks
remain unavailable; no visual accessibility score or full WCAG claim is made.

## Energy proposal, 2026-10-24

Follow-up: method v2 displays the unadjusted weight-based reference even outside
BMI 18.5–25, with separate underweight/refeeding or overweight/lower-energy review
notes. The existing UI displays the calculation and editable-draft action without
a frontend change. Old snapshots retain v1; rebuild the API and create a fresh
proposal to see v2. Focused verification:
`uv run --with pgserver==0.1.4 python tests/run_postgres.py -q tests/test_energy.py tests/test_patients.py`
passed 23 tests, including overweight proposal/edit/approval/reassessment and both
BMI review notes. Changed-file Ruff and `git diff --check` passed.

New target proposals include a versioned, source-attributed NICE CG32 adult
nutrition-support estimate (25–35 kcal/kg/day). This is a conditional starting
range for clinician review, not a universal maintenance-energy calculation. The
initial supported subset and missing-data behaviour are documented in
[patients](PATIENTS.md#proposal-completion-and-approval). The estimate stays outside
target items until the clinician copies it into an editable manual range, records
a rationale, saves and approves. Source, calculation and original input snapshot
survive subsequent edits; existing energy targets are not replaced. Older target
sets remain readable and need a new proposal to obtain the estimate.

Verification: `uv run --with pgserver==0.1.4 python tests/run_postgres.py -q`
passed 153 tests; frontend `npm run test -- --reporter=dot` passed 23 tests;
`npm run build`, `npm run lint`, changed-file Ruff and `git diff --check` passed.
The mechanical UI detector reported no findings. Browser visual checks were not
available. Deployment is pending: rebuild API/web and generate a fresh proposal;
no evidence publication command or database migration is needed for this feature.

## Nutrition constraints, 2026-10-24

Implemented explicit minimums, strict ceilings, actual-energy percentage targets,
reviewed fruit/vegetable gram contributions and trans-fat composition support.
Historical intake goals and inclusive ceilings retain their semantics. Search,
independent checking, approval/substitutions, recommendation scoring, conflicts,
manual/evidence target validation and logging comparisons use the new contract.
Extraction prompt v4 distinguishes minimums from reference goals. Editors expose
the new units/actions and qualifying food contributions; unknowns remain unknown.
See [planning](PLANNING.md), [foods](FOODS.md), and [evidence](EVIDENCE.md).

Verification: `uv run --with pgserver==0.1.4 python tests/run_postgres.py -q`
passed 140 tests. A subsequent focused run of `tests/test_nutrition_constraints.py`
passed 8 tests, including source-change rejection and the complete publication
command (revision replacement and idempotency) against temporary PostgreSQL/API.
`npm run test -- --reporter=dot` passed 23 UI tests; frontend build, frontend lint,
and Ruff checks of changed Python files passed. Mechanical UI detector: no findings.
Browser visual verification unavailable. Initial backend invocation referenced
nonexistent `tests/test_foods.py`; corrected run then exposed three outdated
extraction fixture failures because strict schema now requires `upper_exclusive`.
Updated the provider fixture for prompt v4; full suite passed afterward.

The user rebuilt API/web; all nine executable rule updates are now published and
read-back verified (publication `1ad13384-0ecd-4da1-b5ce-3a5e53e00be7`). Fixed updater
ambiguity between published child-fibre rules and separate blocked extraction drafts:
prefer the unique published identity, preflight every match before writes, and resume
identical saved revisions. The two extraction drafts are preserved. Focused verification
`uv run --with pgserver==0.1.4 python tests/run_postgres.py -q tests/test_nutrition_constraints.py`
passed 9 tests, including interruption recovery, duplicate drafts, genuine ambiguity
and idempotency; Ruff passed. Live applicability checks confirmed six adult baseline
rules, the additional CKD sodium rule, and the separate child fibre scope.
Food-pool completeness and clinician-approved individual energy ranges still govern
planning availability; no patient facts, target approvals or food annotations were
fabricated to make the new general rules pass.

## First-boot initialization

GPU wheel download resilience: increasing uv's read timeout to 300 seconds did
not resolve repeated GPU wheel stalls. The official locked wheel is approximately
2.87 GB and its CDN advertises byte-range support. The API builder now fetches that
exact URL from `uv.lock` via `scripts/download_paddle.py`, using curl byte-range
resume with eight bounded attempts and a persistent, locked BuildKit wheel cache.
Partial files survive failed attempts/builds; completed downloads pass ZIP CRC
validation before promotion. This detects archive corruption, not publisher identity;
the existing lock entry supplies no cryptographic wheel hash. No mirror or CPU
fallback is introduced. Frozen uv sync installs the remaining locked dependencies;
the GPU wheel is then installed locally with `--no-deps`. Non-GPU builds skip this
download. Source-only rebuilds reuse the dependency layer and downloaded wheel.
Retry with `sudo docker compose up --build -d api`; retain caches between retries.
Compose/static checks and the downloader retry/cache regression test are available
locally; the complete GPU container build still requires user Docker access.

CUDA configuration: Compose now reserves NVIDIA GPU 0, builds the official
PaddlePaddle 3.3.1 CUDA 12.9 wheel from the explicit Paddle index, and sets
`CARELOOP_OCR_DEVICE=gpu:0`. OCR refuses silent CPU fallback when CUDA is requested.
Existing CPU page caches remain resumable after container recreation. Host hardware
inspection found an RTX 5050 with 8 GB VRAM, driver 615.78.08, and NVIDIA Container
Toolkit 1.20.1; container access still requires the user's sudo authentication.
The initial GPU smoke test failed at import with missing `libnvrtc.so.12`;
`ldd` also identified missing CUDA runtime, cuBLAS, cuDNN and cuSOLVER libraries.
Added explicit NVIDIA runtime dependencies and library search paths rather than
relying on the Paddle wheel to bundle them. GPU verification subsequently passed:
Paddle 3.3.1 reported CUDA 12.9 and one GPU, a GPU tensor sum returned 4.0,
and uncached KDIGO page 13 produced six layout blocks and two passages (4,876
characters), recorded as `gpu:0`. The host initially aborted during import when
Mesa loaded system LLVM 23 alongside Paddle's LLVM; selecting NVIDIA GLX/EGL
vendors resolved that host conflict. Docker inference remains unverified.

Parser upgrade (2026-10-24): PDF extraction now uses PaddleOCR PP-StructureV3, with
per-page resumable layout artifacts and model caches in the source-data volume.
HTML table spans, units and heading context are retained. Bootstrap keys include
the parser version and reparse retained default originals as new refresh snapshots;
source acquisition/parsing errors retain actionable messages. See [evidence](EVIDENCE.md)
for dependencies, coverage and limits. This does not resolve the separate extraction
action-validation mismatch or the three-rules-per-passage coverage limit.

Verification: 127 backend tests passed with `uv run --no-sync --with pgserver==0.1.4
python tests/run_postgres.py -q`. Read-only reparsing of the three retained HTML
sources kept all 12 HealthHub tables (including the energy units) and both HPB
tables (including 2,000 mg/day sodium). A real PaddleOCR run on KDIGO original PDF
page 12 recognized 11 layout blocks including two tables, producing seven passages.
The first attempt exposed a cache-directory permission error (fixed by using the
CareLoop data directory), and the next exposed the oneDNN incompatibility noted in
the evidence contract; the corrected CPU run passed. Ruff, Compose configuration,
wheel/source build, and whitespace checks passed. No Docker service was rebuilt or
restarted, and no production records or hosted LLM calls were changed. Full-document
KDIGO OCR and container runtime verification remain unrun.

Compose enables `CARELOOP_BOOTSTRAP=1`. API startup runs migrations and launches a
background worker to import SG FoodID and acquire the default evidence seed URLs,
then extract each parsed passage through the production extraction workflow.
Drafts retain review blockers; nothing is approved or published automatically.
`GET /api/bootstrap` exposes persisted per-stage progress and sanitized failures.
PostgreSQL advisory locking prevents concurrent workers. Import completion markers
are atomic with saved data; completed imports survive restart, and stable extraction
request IDs prevent repeat provider calls after uncertain outcomes. Failed model
calls require explicit review-workspace retry. Raw food artifacts persist in the
Compose `source_data_v1` volume, separate from the database volume.

Verification (2026-10-24): `uv run --with pgserver==0.1.4 python
tests/run_postgres.py -q` passed 119 tests and exposed one stale migration-count
assertion. Updated the expected count to nine; the focused rerun of
`tests/test_evidence.py::test_restart_and_migration_idempotency` passed. Five new
bootstrap tests cover imports/restarts, acquisition recovery, provider-failure
retention, worker exclusion, and startup/shutdown ordering. Ruff, `git diff --check`,
and `docker compose config --quiet` passed. Upstream Starlette/httpx deprecation
and Pydantic alias warnings were observed. Docker services and live downloads/model
calls were not launched for this change; integration tests use controlled responses.

As of 2026-10-23. Product requirements live in [REQUIREMENTS.md](REQUIREMENTS.md);
module and transaction boundaries live in [ARCHITECTURE.md](ARCHITECTURE.md).

## Implemented

- PostgreSQL-backed immutable revisions, transactional audit history, demo-role
  guards, and checksum-verified migrations applied by API startup.
- Evidence discovery and URL/PDF/text acquisition, retained originals, page/heading
  passages, lexical retrieval, refresh comparisons, structured numeric conflict
  checks, review, explicit publication, and retirement. See [evidence](EVIDENCE.md).
- Shared hosted-provider client, model discovery, and extraction API with persisted
  runs, duplicate-call protection, and review-blocked drafts. A model-selection
  notebook uses versioned prompts/validators; GLM 5.3 is the default model.
- Reviewer passage extraction UI with persisted-run status and structured draft
  editing. Patient cited chat uses current approved target/fact snapshots, active
  published quotations, source-labelled citations, and persisted conversation history.
- Chat attachments connect approved meal plans, recorded intake/completeness,
  deterministic target comparisons, and checked substitution suggestions. Selected
  record changes invalidate in-flight answers and mark saved answers historical.
  Patients can explicitly request a suggested replacement as a clinician-review draft.
- Manual/CSV patient entry, cited target proposals, missing-fact handling, clinician
  completion/approval, and reassessment. See [patients](PATIENTS.md).
- Versioned food catalogue and reviewer annotations; SG FoodID, FNDDS, and NHANES
  adapters. Source audits and temporary import results are in [data](DATA.md).
- Acquisition, imports, and evaluation expose Python functions without application
  CLI entry points. PDF extraction uses an isolated function-based process.
- Bounded multi-item planning, three objectives, independent checks, clinician
  approval, substitutions, and transactional invalidation. See [planning](PLANNING.md).
- Planned/independent intake, item and atomic whole-meal logging, immutable
  corrections, completeness, and target comparisons. See [logging](LOGGING.md).
- Checked substitution recommendations and a reproducible public-food retrieval
  pilot. Nearest-neighbour retrieval remains the default; see [mining](MINING.md).
- Frozen evaluation functions for four-family extraction/answer comparisons,
  model-blinded source review, real-food retrieval, planning baselines and independent
  plan/substitution audits. Static team-labelled references cover four real documents.
  The notebook includes offline reporting and explicit opt-in hosted execution.
- Role-scoped `ui` routes for clinician patient/plan/intake review, patient
  planning/logging/questions, and reviewer foods/evidence. API mutation guards
  enforce those demo roles. Docker/Nginx and Compose serve the UI on localhost port 5173.

No persistent deployment database has been seeded. Real-source verification used
temporary databases; raw downloads and reports remain outside Git.

## Visual style

Preserve the deep navy shell, blue selection, white working surfaces, cool slate
backgrounds, Public Sans, tabular measurement numerals, sentence-case labels,
modest corners, and bordered controls.

## Latest verification

- Backend: 114 tests passed on temporary PostgreSQL 16.2; Ruff passed.
  Checks include startup migrations, isolated PDF parsing, and transaction-owned imports.
  One upstream Starlette/httpx deprecation warning remains.
- UI: 15 contract/component tests cover role routing, read-only clinician views,
  extraction, chat recovery/citations, planning and logging; production build and lint passed.
- Desktop/mobile browser checks covered generation, approval, whole-meal logging,
  day completion, and reviewer navigation without exceptions or horizontal overflow.
- Live GLM smoke verification used synthetic source/patient records in a temporary
  database: passage extraction, draft editing, explicit approval/publication, approved
  target explanation with citations, missing-evidence handling, and medication referral
  all succeeded. Desktop/mobile role menus and cross-role URL redirects passed;
  no browser exceptions or horizontal overflow were observed.
- Chat workflow checks cover patient/plan ownership, partial intake, immutable
  citations, changed log/completeness/candidate revisions, checked candidates and
  empty search results. Live GLM plan/intake/substitution checks used synthetic
  records. One early substitution answer was rejected for invalid citation IDs;
  explicit ID allowlists and unknown-difference instructions were added, and a
  subsequent check passed. This is smoke verification, not a clinical benchmark.
- Evaluation tests check independent snapshot/portion auditing, exact-search baselines,
  retained missing facts, exhaustive substitution references, extra-rule penalties,
  evidence-removal expectations, frozen inputs and split leakage. An integrated
  acceptance test covers planning through substitution, intake, chat and reassessment.
- Desktop/mobile chat attachment and explicit replacement-draft controls passed
  with synthetic API fixtures and saved live answers; no browser errors or overflow.
- Compose configuration, documentation links, packaged migrations, and whitespace
  checks passed. Temporary verification servers and databases were removed.
- Docker image execution and PostgreSQL 18 remain unverified due to socket permissions.
- Model-selection notebook tests four aligned nutrition workflows for Qwen and
  GLM in both JSON and JSON Schema modes, with identical prompts and requested
  high reasoning. Structure and bounded content checks are scored separately.
  All 15 completed responses passed JSON/schema validation; 13 passed bounded
  content checks. One host-interrupted request remains unknown. GLM's two content
  failures added an unrelated, uncited protein quantity to missing-potassium answers.
  Results are inline in `notebooks/model_selection.ipynb`; raw responses stay outside Git.

Commands: [backend](../README.md#verify), [UI](../ui/README.md#verify).
These checks are engineering verification, not clinical validation or the full evaluation.

## Unfinished work

- Broader NHANES demographic/clinical-field integration; only respondent ID and
  survey age are currently mapped.
- Public-food restriction coverage and missing nutrients still limit eligible pools.
  Source portions now enter planning directly; meal-slot/portion-enable annotations
  are no longer required.
- Broader source/question evaluation, including conversational explanations of plans,
  partial intake and checked substitutions across diverse real records.
- Real-source comparative planning/checked-substitution runs still need documented
  target specifications: the inspected DASH menu does not specify the daily energy
  range required by the planner. No missing
  restrictions or annotations are filled to make cases executable. See [evaluation](EVALUATION.md).
- Broader held-out source coverage, patient-record chat/retrieval benchmarks, and
  human usability/clinical assessment remain outside the current bounded evaluation.
- Recipe preparation instructions.
- Docker deployment/PostgreSQL 18 verification and persistent deployment seeding.
