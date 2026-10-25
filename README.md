# CareLoop

## Project Title

CareLoop: Clinician Reviewed Nutrition Planning and Patient Follow Up

**Group 30 — NUS-ISS Intelligent Reasoning Systems Practice Module**

## Executive Summary / Paper Abstract

CareLoop addresses the gap between reviewed nutrition guidance and everyday food
choices. It connects evidence review, patient-specific nutrition targets, meal
planning and patient-reported intake in a single academic decision-support
prototype, with Singapore foods as the primary catalogue context.

Reviewers check and publish structured rules linked to source quotations.
Clinicians review patient facts and explicitly approve target revisions. Patients
request meal alternatives and food replacements, while deterministic beam search
and an independent numerical checker evaluate the requested plans against
approved targets and recorded restrictions. Nutrient-based retrieval supports
food substitutions, and a hosted language model provides cited explanations from
reviewed evidence and approved records. Meal logs preserve reported intake for
follow-up without treating unlogged meals as zero consumption.

The implementation combines a React/TypeScript interface, a FastAPI backend and
PostgreSQL. Its contribution is a traceable workflow that separates proposals,
checks and human approval. The system is an academic prototype; development tests
and pilot experiments do not establish clinical effectiveness or production
readiness.

## Credits / Project Contribution

| Official Full Name | Student ID (MTech Applicable) | Work Items (Who Did What) |
| --- | --- | --- |
| Yeom Dongjun | A0354802H | Frontend development, frontend–backend integration, user workflow integration, and demonstration preparation. |
| Zaiyu Zhang | A0357851U | Requirements analysis, business analysis, experiment design, and evaluation of results. |
| Worameth Wittanakorn | A0356365W | Data and evidence-source research, data cleaning and standardisation, and validation of missing values, units, and source provenance. |
| Nguyen Tri Nghia | A0355672W | Backend development, rule design, reasoning logic, meal-plan generation, and constraint validation. |

**Shared contribution:** All four members participated in researching datasets
and reference materials, reviewing code, and discussing implementation decisions.
The allocation identifies primary responsibilities rather than exclusive
ownership.

## System Documentation and User Guide

CareLoop connects clinician-reviewed nutrition targets with meal planning and
patient-reported intake. It is a local academic decision-support prototype for
helping patients put a reviewed nutrition plan into practice.

The workflow covers evidence review, target approval, checked meal alternatives,
plan approval, and follow-up through meal records and cited explanations.
See the agreed [requirements](docs/REQUIREMENTS.md) for scope.

## Key capabilities

- **Reviewed targets with source context.** Clinicians review cited proposals,
  resolve missing information, and approve an exact target revision.
- **Meal alternatives checked against approved targets.** The planner considers
  recorded restrictions, food portions, nutrient fit, dislikes, and variety.
  An independent checker recomputes the resulting plan before approval.
- **Food replacements checked against the whole plan.** A substitution changes
  one item, retains the other meals, and creates a separate draft for clinician
  approval. It does not overwrite the approved plan.
- **Intake records that preserve uncertainty.** Patients can confirm meals,
  change quantities, record replacements or skips, and correct earlier entries.
  Unlogged intake remains unknown rather than becoming zero.
- **Cited patient explanations.** Chat uses approved targets and selected plan
  or intake records. Checked substitution suggestions use the planning services;
  a chat response does not change targets or approve a plan.
- **Reassessment and history.** Relevant patient, evidence, or food changes can
  trigger review while earlier plans and their recorded values remain readable.

## Workspaces

| Role | Main actions |
| --- | --- |
| Reviewer | Acquire evidence, review and publish rules, maintain food records |
| Clinician | Enter patient facts, review and approve targets, approve plans, review intake |
| Patient | Request meal alternatives and replacements, record intake, ask nutrition questions |

Role selection and actor labels support the local demonstration workflow. They
are **not authentication**. Keep the application on the loopback-bound endpoints
in the supplied configuration.

## Current implementation and limits

The application uses FastAPI and Python, PostgreSQL, and a React/TypeScript
frontend with Vite and Tailwind. Meal generation uses deterministic bounded beam
search with independent numerical checking. Nutrient-based retrieval supports
food substitutions. Hosted extraction and cited chat use an OpenAI-compatible
provider, with GLM 5.3 as the application default. PDF parsing uses PaddleOCR.
See [architecture](docs/ARCHITECTURE.md) for the implemented module boundaries.

The current implementation differs from the original proposal: the application
stores its versioned evidence in PostgreSQL and uses beam search for planning.
Neo4j and a genetic algorithm are proposal-stage choices, not current runtime
components.

The complete public-data evaluation remains pending. Engineering tests and
small development pilots do not establish clinical effectiveness. Some food
composition values are estimates and are labelled in the interface. This is a
decision-support and education prototype, not a diagnosis or prescribing system.
See [implementation status](docs/IMPLEMENTATION.md) and
[evaluation](docs/EVALUATION.md) for completed work and remaining limitations.

## Run

### Prerequisites

The default full-stack Compose configuration requires:

- Docker with Compose support.
- An NVIDIA GPU available as GPU 0, its host driver, and NVIDIA Container Toolkit.
  The API image installs a Linux x86-64 CUDA wheel. The default stack is not an
  out-of-the-box macOS/Apple Silicon setup.
- An OpenAI-compatible provider endpoint and API key for hosted extraction and
  chat. Local planning and numerical checking do not use the language model.
- Network access for the first food/source downloads and OCR model acquisition.

Before the first start, copy `.env.example` to `.env` if you do not already have
one, then set `LLM_BASE_URL` and `LLM_API_KEY`. Keep an existing configuration;
`.env` is Git-ignored. See [inference configuration](docs/INFERENCE.md) for provider
requirements and defaults.

### Start the stack

```sh
docker compose up --build -d
```

The API applies checksum-verified migrations before accepting requests.
Open <http://localhost:5173> for the application,
<http://localhost:8000/docs> for the interactive API and
<http://localhost:8000/api/health> for readiness. Database access is on localhost
port 55432; the Compose password is a public local-demo value, not a secret.
The Compose project/volume is `careloop` / `database_v1`.

On first boot, Compose enables background initialization: the complete SG FoodID
catalogue is downloaded/imported, the four default evidence sources are acquired,
and their parsed passages are processed into review-blocked rule drafts. The app
is available while this runs; downloads and model calls can take time. Put
`LLM_BASE_URL` and `LLM_API_KEY` in `.env` before starting for automatic extraction.
No clinical approvals or publications are created.

PDF parsing uses PaddleOCR PP-StructureV3 on CUDA GPU 0 with layout and table recognition.
Compose reserves NVIDIA GPU 0 and installs the pinned PaddlePaddle CUDA 12.9 wheel.
The host requires the NVIDIA driver and NVIDIA Container Toolkit. Verify access with
`sudo docker compose exec api nvidia-smi`. A requested but unavailable GPU produces
an explicit failure rather than silently falling back to CPU.

If Docker has not yet registered the NVIDIA runtime:

```sh
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
sudo docker compose up --build -d
```

To switch an existing CPU deployment, build the new image first with
`sudo docker compose build api`, then recreate it with
`sudo docker compose up -d --no-deps api` once the NVIDIA runtime is available.
The database and source-data volumes are retained.
The first PDF import downloads model weights; both models and completed OCR pages
persist in `source_data_v1`. Completed CPU pages are reused when switching to CUDA.
HTML imports retain native table structure and heading/unit context.
This parser upgrade reparses previously acquired default source originals into new
snapshots on the next API boot, then extracts new review-blocked drafts. Previous
snapshots and decisions remain available. Rebuild with `docker compose up --build -d`.

Inspect progress and failures at <http://localhost:8000/api/bootstrap> or with:

```sh
docker compose logs -f api
curl -s http://localhost:8000/api/bootstrap
```

Sources and drafts appear in **Reviewer → Evidence review**, foods in **Food
catalogue**. Completed jobs are retained in PostgreSQL; raw food artifacts use the
`source_data_v1` volume. Restarts resume unfinished acquisition without duplicating
imports or overwriting reviewed records. Missing provider configuration can be fixed
in `.env`, then applied with `docker compose up -d --force-recreate api`.
Failed or interrupted model requests remain in extraction history and require an
explicit retry in evidence review; they are not silently sent twice. Initialization
does not refresh completed sources automatically. Use the evidence refresh workflow
for newer editions. Direct development starts opt in with `CARELOOP_BOOTSTRAP=1`
and an external writable `CARELOOP_DATA_DIR`; Compose sets both automatically.

### Local development

For local Python development (Python 3.12+ and `uv`):

```sh
uv sync --frozen
docker compose up -d db
export CARELOOP_DATABASE_URL='postgresql://careloop:local-demo-only@127.0.0.1:55432/careloop'
uv run uvicorn careloop.api:create_app --factory --reload
```

The database-only Compose command above does not start the GPU API service.
For the frontend, follow [UI development](ui/README.md#run), which proxies requests
to the local API. This route does not install or verify an OCR runtime; see
[evidence acquisition](docs/EVIDENCE.md) before testing PDF imports.

## First-use workflow

A fresh installation does not contain a ready-to-use patient or an automatically
approved clinical plan. The background bootstrap imports foods and prepares
review-blocked evidence drafts only.

1. **Reviewer:** inspect acquired sources and rule drafts, resolve blockers,
   approve selected revisions, and publish them. Rule approval and publication
   are separate actions.
2. **Clinician:** create or import a patient, record the required facts, and
   review the proposed targets. Complete an individual daily energy range and
   other required decisions, then approve the target revision.
3. **Patient:** request meal alternatives from the catalogue. Missing facts,
   unsuitable foods, or unmet bounds can block generation; inspect the reported
   reasons rather than treating a failed search as proof that no plan is possible.
4. **Clinician:** review a checked alternative and explicitly approve it.
5. **Patient:** follow the approved plan, record actual intake, or request a
   checked substitution. Nutrition questions can attach the approved plan or
   a selected intake date.
6. **Clinician:** review recorded intake at follow-up and reassess targets when
   the underlying information changes.

For walkthroughs, use explicitly synthetic records and preserve the manual review
and approval steps.
The sections below provide API-level details for each stage.

## Review workflow

Use `/docs` to submit each request with a reviewer demo actor and a reason:

1. `POST /api/evidence/sources`: submit source text, title, locator, and edition.
2. `POST /api/evidence/rules`: create a structured rule with a verbatim quote and
   source location. Record applicability, exceptions, and unresolved blockers.
3. `POST /api/evidence/approvals`: submit selected rule IDs and exact revisions.
4. `GET /api/evidence/catalogue`: inspect drafts and retained published rules,
   resolve conflicts, and obtain the reviewed `generation`.
5. `POST /api/evidence/publications`: submit approved selections, that generation,
   and the manual `conflict_review` note.
6. Create revisions or retire a rule using its expected latest revision.

Approval does not publish. Editing does not replace an existing published version.
Default sources and review-blocked drafts are loaded by Compose initialization;
patients and clinical approvals are not preloaded. Structured
numeric conflicts block publication; broader interpretation remains manual.
Hosted extraction uses the configured provider and creates review-blocked drafts;
see [inference configuration](docs/INFERENCE.md).

## Patient targets and public data

Use a clinician demo actor for the patient workflow:

1. Create a record at `POST /api/patients` or import CSV at
   `POST /api/patients/import-csv`.
2. Generate a proposal at `POST /api/patients/{id}/targets`.
3. Inspect missing facts/citations; complete or override targets through
   `POST /api/targets/{id}/revisions`.
4. Approve the exact revision at `POST /api/targets/{id}/approval`.

Patient/evidence changes flag affected targets without changing historical values.
See [patient contracts](docs/PATIENTS.md) for CSV columns, units, missing-fact
semantics, conflict resolution, and the target-readiness boundary.

Public-data acquisition and imports are reusable functions in `ingestion.py`.
One-time acquisition is performed during development; raw data, normalized exports,
and checksum/field-audit manifests remain outside the repository.
The NHANES adapter maps only respondent ID
and observed survey age; other facts remain unknown. Re-importing the same external
IDs fails atomically rather than overwriting records. See [source audit](docs/DATA.md).

## Singapore foods and planning

All 2,689 records from the supplied SG FoodID mirror have been acquired and
normalized. SG FoodID and FNDDS adapters feed the shared acquisition/import
functions. Raw downloads and manifests stay under `~/.local/share/careloop/public/`.
Compose imports the default catalogue automatically on first boot.

Recorded source portions are available directly; review any required restriction
classifications before requesting plans. `POST /api/plan-requests` creates three
checked alternatives; the clinician approves one through `/api/plans/{id}/approval`.
See [food contracts](docs/FOODS.md) and [planning](docs/PLANNING.md) for the bounded search,
nutrient requirements, substitutions, and reassessment behavior.

## Meal logging

Use `POST /api/patients/{id}/meal-logs` to confirm a planned meal, change its
quantity, record a replacement or skip, or add an independent food entry.
Daily recorded-intake summaries and completion declarations are available at
`/api/patients/{id}/meal-log-days/{YYYY-MM-DD}`. Entries retain food snapshots and
audited correction history. See [logging contracts](docs/LOGGING.md) and `/docs`
for request schemas.

## Substitution recommendations and food mining

`POST /api/plans/{id}/substitution-recommendations` retrieves nutritionally similar
foods from a selected pool, checks each replacement against the whole plan, and
returns ranked choices with nutrient differences. Submit a choice through the
existing substitution-draft workflow for clinician approval. Direct nearest-neighbour,
cluster-assisted, and same-category methods are available.

See [mining](docs/MINING.md) for API parameters, algorithm limits, and the reproducible
SG FoodID retrieval pilot and its saved results.

## Multi-item meals and evidence acquisition

Plan requests accept `items_per_slot`, for example
`{"breakfast": 2, "lunch": 3, "dinner": 3}`. Returned food items carry a 1-based
`item` within each day/slot. Use that selector for substitutions, recommendations,
and logging. Whole-meal confirmation is available through
`POST /api/patients/{id}/meal-log-confirmations`.

Evidence discovery starts at `/api/evidence/discovery-seeds` and `/api/evidence/discover`.
`POST /api/evidence/source-imports` accepts approved-domain URLs or base64 PDFs;
optional page ranges support large guidelines. Originals and searchable passages
are retained. `/api/evidence/conflict-check` reports structured conflicts before
publication. See [evidence](docs/EVIDENCE.md) for limits and real-source verification.

## Verify

UI development and checks are documented in [ui/README.md](ui/README.md).

```sh
uv run ruff check src tests
uv run ruff format --check src tests
docker compose config --quiet
uv run --with pgserver==0.1.4 python tests/run_postgres.py -q
```

The final command starts a temporary PostgreSQL 16.2 instance, runs the complete
suite, and removes its own storage. It requires supported `pgserver` binaries
(verified here on Linux x86-64), but no Docker access. To verify against the
Compose PostgreSQL 18 instance instead:

```sh
CARELOOP_TEST_DATABASE_URL='postgresql://careloop:local-demo-only@127.0.0.1:55432/careloop' uv run pytest -q
```

Database checks create and remove only uniquely named `check_*` schemas. Without
the test database variable, plain `uv run pytest` skips integration checks.

See [architecture](docs/ARCHITECTURE.md), [implementation status](docs/IMPLEMENTATION.md),
and the planned public-data [evaluation](docs/EVALUATION.md). These workflow checks
are engineering verification, not clinical validation or the final evaluation.
