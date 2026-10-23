# Implementation status

## First-boot initialization

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
