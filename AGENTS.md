# CareLoop

## Current state

The user requested a fresh start: preserve the UI visual style and agreed requirements,
delete the old implementation and GitNexus index, and rethink the entire code
structure. The replacement under `src/careloop` implements PostgreSQL-backed
evidence publication, patient/CSV entry, reviewed targets, a versioned food
catalogue, checked meal plans/substitutions, and reassessment. Source adapters
translate SG FoodID (the user-supplied Kaggle mirror), FNDDS, and NHANES; downloads
belong to `ingestion.py`, CLI orchestration to `cli.py`, and persistence to workflow
services. Meal logging includes planned/independent intake, correction history,
and daily summaries. Tests live in `tests/`. See `README.md` for run and
verification commands. Git history and repository metadata are preserved.
Food mining provides checked substitution recommendations and a public-data retrieval pilot.
Planning supports multiple items per meal, item-level substitutions/logs, and whole-meal
confirmation. Evidence acquisition retains URL/PDF originals, page/heading passages,
refresh comparisons, and structured numeric publication checks; hosted extraction/chat
remain pending.
The frontend package is now `ui/`, with one application entry point, one API client,
shared controls/state, and five screens. Retired frontend code and Impeccable-generated
files have been removed; do not recreate parallel frontend implementations.
External Docker/database removal is blocked by permissions;
see [implementation status](docs/IMPLEMENTATION.md).

## Read progressively

- [Requirements](docs/REQUIREMENTS.md): product scope, roles, workflows, approvals.
- [Data](docs/DATA.md): public food/participant datasets and acquisition constraints.
- [Evidence](docs/EVIDENCE.md): clinical sources, extraction, review, publication.
- [Inference](docs/INFERENCE.md): hosted-model selection and Neuralwatt Basic budget.
- [Evaluation](docs/EVALUATION.md): reproducible public-data benchmarks and limits.
- [Implementation](docs/IMPLEMENTATION.md): delivery sequence, visual style, reset status.
- [Architecture](docs/ARCHITECTURE.md): implemented structure and transaction contracts.
- [Patients](docs/PATIENTS.md): facts, CSV, applicability, target approval/reassessment.
- [Foods](docs/FOODS.md): composition/portion units, adapters, reviewer annotations.
- [Planning](docs/PLANNING.md): bounded search, checking, approval, substitutions.
- [Logging](docs/LOGGING.md): reported intake, immutable corrections, daily completeness.
- [Mining](docs/MINING.md): nutrient clustering, checked recommendations, retrieval pilot.

Requirements record decisions as of 2026-10-23; implementation status distinguishes
completed slices from the remaining functionality.
Keep requirements directly in `docs/`, with focused documents rather than a
`rebuild/` directory or combined data-and-evidence document.

## Product constraints

- Academic, English-only, single local deployment with PostgreSQL and Docker Compose.
- Preserve frontend visual style; redesign contracts and screens as required.
- Demonstrate decision automation, search/evolutionary optimization, food-based
  clustering/substitutions, and cited natural-language patient questions.
- Singapore/SEA food focus; ages 2+, including pregnancy/breastfeeding, weight
  management, prediabetes/type 2 diabetes, hypertension, hyperlipidaemia, and
  non-dialysis CKD. Enforce evidence-specific applicability and exceptions.
- Demo role switcher, not authentication; all clinicians access all patients.
  Audit actors are labels, not verified identities.
- Use real publicly downloadable data first. Synthetic cohorts are a last resort.
- Source discovery uses approved authoritative domains; reviewers can provide
  URLs, PDFs, or text. Structured draft rules show source passages and exceptions.
- One reviewer can edit and approve, including self-approval. Support individual,
  batch, and partial-batch review. Conflicts block explicit publication.
- Refresh evidence on demand; updates create drafts. Retire incorrect rules and
  preserve audit/history. Published changes flag affected patient targets.
- Published rules propose patient-specific targets; clinicians complete/edit and
  approve them. Manual targets retain clinician authorship. Missing facts prompt
  clarification rather than invented recommendations.
- Clinicians approve selected plans and substitution drafts. Patient/rule changes
  flag affected targets/plans; existing plans remain viewable, while new planning
  and substitutions wait for review. New targets require newly approved plans.
- Plans cover 1–7 days with adjustable breakfast/lunch/dinner/optional-snack schedule.
  Three alternatives emphasize nutrient fit, preference match, and variety;
  mandatory restrictions apply to all usable plans.
- Dislikes are soft preferences; allergies and vegetarian choices are mandatory.
  Patients choose egg/dairy inclusion. Nutrient tables do not prove allergen safety.
- Infeasible requests explain blockers and may show explicitly unmet drafts;
  search failure is not proof of infeasibility.
- Default logging confirms planned meals, with changed quantity/replacement/skipped
  options; also support independent entries. Manual patient entry and CSV import.
- Chat explains plans/targets/logs and offers cited education/substitutions;
  diagnosis and medication changes go to the clinician.
- Reviewers can correct food records with provenance/history.
- Hosted model selection follows a pilot within Neuralwatt Basic's included
  allowance. No overage budget or provider key has been supplied.
- Evaluation runs before the demo through a reproducible command/report. No
  clinician/dietitian is available: measure public-data correctness, not clinical
  validation, acceptance, or health outcomes. Laptop has a 5050 GPU.

## Engineering protocol

Design a minimal coherent structure from these workflows, not the old packages.
Distinguish accepted decisions from open recommendations in the detailed docs.
Keep raw datasets, credentials, and runtime state out of source control. Inventory
exact CareLoop-owned storage before deletion; authorization excludes other projects.
Do not recreate a GitNexus index unless requested. Old graph results and test
commands are no longer authoritative for the replacement backend.

Define verification commands alongside the new implementation. Report checks run,
failures, skips, and unavailable tooling honestly. Inspect unfamiliar/uncommitted
changes before overwriting. Do not delegate unless the user asks for agents.
