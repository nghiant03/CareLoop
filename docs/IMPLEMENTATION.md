# Implementation plan

## Direction

Start from an empty backend design. The user explicitly requested deleting the
old implementation and GitNexus index, preserving only frontend visual/style work
and the agreed requirements. Do not restore the old architecture or create empty
copies of its package tree. The future module layout must follow the workflows
in [REQUIREMENTS.md](REQUIREMENTS.md).

The retained UI uses a deep navy shell, blue selection, white working surfaces,
cool slate backgrounds, Public Sans, tabular measurement numerals, sentence-case
labels, modest corners, and bordered controls. Preserve that visual language while
adapting workflows and API integration.

## First implemented slice — 2026-10-23

- One Python package under `src/careloop`, organized by workflow; one PostgreSQL
  database with explicit transactional/checksum-verified migrations.
- New Compose project `careloop` and volume `database_v1`, isolated from the old
  `careloop-app` resources. API readiness and generated OpenAPI documentation.
- Immutable submitted-text sources; structured rule revisions with verbatim quote
  checks; reviewer-labelled individual/batch/selected-subset approval; explicit
  publication; retirement; transactional audit events and historical read APIs.
- Revision checks and catalogue-generation binding protect against stale edits
  and stale manual conflict reviews. Recorded blockers prevent approval/publication.
- See [architecture](ARCHITECTURE.md) and [run/check commands](../README.md).

Hosted extraction, broader clinical conflict interpretation and chat remain
unimplemented. No clinical recommendations are seeded.

Verification: 11 checks passed against isolated PostgreSQL 16.2, including atomic
batch failure, immutable history, stale review rejection, concurrent edits,
retirement, and restart persistence. Compose configuration validates. Actual
Docker build/start and PostgreSQL 18 checks remain blocked by Docker socket access.
The test environment emitted upstream Starlette/httpx deprecation and Pydantic
schema-generation warnings; these did not fail the workflow checks.

## Second implemented slice — 2026-10-23

- Versioned patient facts/provenance; manual entry and atomic create-only CSV import
  with external identity duplicate checks and clinician demo-role guards.
- Published-rule applicability and exception evaluation, unknown-fact prompts,
  cited proposals, bounded per-kg arithmetic, and explicit competing-target blockers.
- Revision-bound clinician target completion, manual authorship, approval,
  supersession, historical reads, and target-readiness API.
- Patient/evidence changes flag affected targets transactionally. Newly relevant
  rules are detected; unpublished edits and irrelevant publications do not flag.
- Public NHANES DEMO_L acquisition, raw checksums, field/selection manifest, and
  normalized patient CSV. Only respondent ID and survey age are mapped; broader
  demographic/clinical components remain to be audited and imported.
- See [patient contract](PATIENTS.md) and [real-data result](DATA.md).

Verification: **34 checks passed** against temporary PostgreSQL 16.2. These include
concurrent patient-edit/approval, unknown facts, clinician override provenance,
CSV rollback, reassessment, and supersession. A separate real-data check imported
100 downloaded records through the CSV HTTP endpoint and verified unknown facts
and checksum provenance. Its temporary database was removed afterward. Raw data,
CSV, and manifest remain outside the repository. Lint passes; dependency warnings
from the first slice remain. Docker/PostgreSQL 18 execution is still unverified.

## Third implemented slice — 2026-10-23

- Versioned food catalogue, source provenance, reviewer corrections, and pinned
  historical nutrient/portion snapshots.
- Source adapters for FNDDS and the user-supplied Kaggle SG FoodID mirror. Acquisition,
  source translation, CLI orchestration, and database services are separate.
- All 2,689 SG FoodID foods parsed with mass/volume bases, edible-yield adjustments,
  trace/unknown preservation, and a per-serving consistency report. One source
  discrepancy is retained. FNDDS composition and portions were also acquired.
- Bounded 1–7-day meal search with three objectives, independently checked daily
  totals/restrictions, clinician selection/approval, and checked substitution drafts.
- Food/patient/evidence changes flag historical plans without rewriting them;
  new allergens flag affected meals. Stale targets block new planning/substitution.
- Renamed the test directory to conventional `tests/` and updated tooling/docs.
- Contracts and limits: [foods](FOODS.md), [planning](PLANNING.md), [data](DATA.md).

Real-data verification imported 2,689 SG FoodID foods plus 100 FNDDS foods into a
temporary PostgreSQL instance and checked food API retrieval, units, provenance,
and unreviewed state. No persistent deployment was seeded. Raw source snapshots
and manifests are retained outside Git. Planning tests use explicitly labelled
test fixtures; no clinical rule or food-safety annotation is presented as validated.

Verification: **48 tests passed** on temporary PostgreSQL 16.2, including bounded
seven-day alternatives, approval selection, independent nutrient checks, unmet
draft rejection, mandatory restrictions, food/evidence/patient invalidation,
substitution review, and mass/volume/edible-yield handling. Lint, formatting, wheel
build, and Compose configuration checks pass. The renamed `tests/` command and
new `careloop-data` CLI were exercised. Starlette emits one upstream httpx
deprecation warning. Docker image execution/PostgreSQL 18 remain unverified from
the agent environment; database integration checks use the isolated local server.

## Fourth implemented slice — meal logging, 2026-10-23

- Planned-meal confirmation, changed quantities, replacement, skipped meals, and
  independent food/portion entries through patient/clinician API workflows.
- Pinned food snapshots, immutable correction revisions, stale-edit and duplicate
  planned-entry protection, and transactional audit records.
- Decimal recorded-intake totals preserving missing nutrients and g/ml bases;
  optional plan-slot coverage distinguishes skipped and unlogged meals.
- Explicit day-completion declarations; subsequent writes reopen the day.
- Historical approved plans remain loggable without bypassing reassessment or
  approving recorded replacements. See [logging contracts](LOGGING.md).

Verification: **53 tests passed** on isolated PostgreSQL 16.2, including concurrent
confirmation deduplication, stale correction rejection, revision history, missing
nutrients, mass/volume arithmetic, historical food snapshots, and day completeness.
Lint and diff whitespace checks pass. The existing Starlette/httpx deprecation
warning remains. Docker/PostgreSQL 18 execution remains unverified.

## Fifth implemented slice — food mining, 2026-10-23

- Deterministic nutrient clustering, direct nearest-neighbour and same-category
  baselines, with explicit missing-feature exclusions and revision-bound pools.
- Ranked substitution recommendations on current approved plans, using existing
  restrictions and independent whole-plan checks before returning any candidate.
- Nutrient differences, target-fit/dislike scores, and explicit draft/approval
  handoff; similarity never substitutes for suitability checks.
- Reproducible public-food retrieval pilot command and saved report. On 300 SG
  FoodID records, clustering did not improve nutrient similarity/category agreement;
  nearest-neighbour retrieval remains the default. See [mining](MINING.md).

Verification: **60 tests passed** on isolated PostgreSQL 16.2. Coverage includes
deterministic clustering, missing-feature exclusions, all three recommendation
methods, restrictions, whole-day bounds, stale state, approval handoff, and pilot
metric accounting. Lint, wheel build, and diff whitespace checks pass. The existing
Starlette/httpx warning remains; Docker/PostgreSQL 18 execution is still unverified.

## Sixth implemented slice — meal items and evidence acquisition, 2026-10-23

- Multi-item meals with exact per-slot counts (1–5), distinct foods per meal,
  bounded item-level search, independent item coverage and meal/day nutrient totals.
- Item-level substitutions, recommendations, reassessment alerts, logging and
  immutable corrections; atomic whole-meal confirmation/skipping. Old snapshots
  retain implicit item 1, and a migration expands log identity without rewriting history.
- Recorded-intake comparisons against approved target revisions, including unknown,
  partial-day, and stale-target distinctions.
- Approved-domain link discovery, pinned-address HTTPS acquisition, bounded PDF
  parsing with optional page ranges, retained originals/checksums, HTML heading/PDF
  page passages, lexical search, and immutable refresh comparisons.
- Structured population-overlap and same-unit numeric conflict checks at publication.
  Broader clinical interpretation still requires manual review; no automatic rule
  extraction or hosted patient answers are claimed.
- Real KDIGO download and selected-page API import verified in a temporary database;
  raw original and report are outside Git. See [evidence](EVIDENCE.md).

## Delivery sequence

The connected frontend now replaces the mounted legacy workflows in place while
preserving the navy/blue visual system. It supports patient/target review, food
annotations, multi-item plan generation and approval, item/whole-meal logging,
intake comparisons, and evidence acquisition/review/publication. Saved source and
plan lists traverse API pagination. The package is now named `ui`, with active
screens consolidated under `ui/src/screens/`, a direct `App.tsx`, and one API/state
layer. Retired components and their obsolete-contract tests have been removed.
After consolidation, the five active UI contract/component tests pass, as do the
UI production build, lint and Compose configuration validation. The earlier
58-test count included 53 tests for the retired implementation.

Frontend Docker/Nginx configuration and the Compose `web` service serve port 5173.
The development proxy retains `/api`. Actual container execution remains blocked
by Docker permissions. No persistent deployment database has been seeded.

Verification for the current backend: **73 tests passed**, Ruff and wheel build
passed, with one Starlette/httpx deprecation warning. Frontend contract/component
checks: **58 passed**. Live browser checks exercised generation, explicit approval,
whole-meal logging, day completion and reviewer navigation against a temporary API.
Both desktop/mobile capture rounds showed no horizontal overflow or browser
exceptions. Final frontend build/lint, Compose configuration, documentation links,
packaged migrations and diff whitespace checks passed. Temporary UI verification
servers stopped normally and their database storage was removed.

Remaining product work includes the hosted-model pilot, structured extraction and
cited chat, broader NHANES clinical-field integration, the full frozen evaluation,
reviewed public-food suitability/restriction coverage, and deployment verification.
Recipe preparation instructions are not implemented.

1. Specify a minimal new module layout and contracts from the agreed workflows.
2. Establish PostgreSQL, local Docker Compose, demo roles, explicit schema setup,
   and replacement verification commands.
3. Acquire fresh public data; implement normalization, catalogue provenance, and
   independent arithmetic benchmarks before optimization.
4. Implement source discovery/import, extraction, structured review, audit,
   publication, updates, and retirement.
5. Implement manual/CSV patient entry, rule applicability, incomplete proposals,
   clinician completion/approval, and reassessment flags.
6. Implement planning alternatives, independent constraint checking, plan approval,
   substitution review, logging, and food-based mining.
7. Integrate cited chat using the same evidence and approved patient state; adapt
   the preserved frontend to the new contracts.
8. Run the frozen [evaluation](EVALUATION.md), publish the report, and rehearse
   local deployment. Disclose measured limitations and unfinished scope.

## Reset status and external blocker

Local code and dataset reset completed on 2026-10-23: removed backend/rules/shared/
evaluation, tests, deployment, Python manifest/lock/environment, obsolete docs,
GitNexus index/config/generated skills, old secrets, and the external dataset
directory `/home/nghiant/.local/share/careloop/datasets` and the old retrieval report
under `/home/nghiant/.local/share/careloop/artifact-archive`. Git/Jujutsu and agent-session
metadata remain. Replacement implementation status is recorded above. The retained
UI now lives in `ui/`; its historical components and Impeccable files were removed.

Old Compose project: `careloop-app`. Old databases: `careloop_clinical` and
`careloop_knowledge`; old Compose volumes were declared as `postgres_data` and
`run_artifacts`. Exact existing Docker resources could not be listed because the
Docker socket is inaccessible and passwordless sudo is unavailable. Direct local
database connections on port 5433 were also unsuccessful. Do not claim database
volumes were deleted.

The old Compose configuration was copied to
`/tmp/opencode/careloop-reset-compose.yaml` before deletion. An operator with Docker
access can finish the external reset from the repository root:

```sh
sudo docker compose -f /tmp/opencode/careloop-reset-compose.yaml --project-directory "$PWD" -p careloop-app ps -a
sudo docker volume ls --filter label=com.docker.compose.project=careloop-app
sudo docker compose -f /tmp/opencode/careloop-reset-compose.yaml --project-directory "$PWD" -p careloop-app down --volumes --remove-orphans
```

If the temporary copy is gone, recover the old tracked `compose.yaml` from Git
history. Inspect project resources first; do not prune global Docker volumes or
other projects. No new deployment should reuse the old volumes.
