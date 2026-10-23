# CareLoop

Local academic nutrition application: one Python/PostgreSQL backend under
`src/careloop`, one frontend under `ui`, and backend tests under `tests`.
See [README](README.md) for run and verification commands.

## Read progressively

- [Requirements](docs/REQUIREMENTS.md): accepted product scope and open decisions.
- [Architecture](docs/ARCHITECTURE.md): layout, transactions, and integration boundaries.
- [Implementation](docs/IMPLEMENTATION.md): current status, visual style, unfinished work, and blockers.
- [Data](docs/DATA.md): public datasets, acquisition, and source audits.
- [Evidence](docs/EVIDENCE.md): clinical sources, acquisition, review, and publication.
- [Patients](docs/PATIENTS.md): facts, CSV, applicability, targets, and reassessment.
- [Foods](docs/FOODS.md): composition units, portions, and reviewer annotations.
- [Planning](docs/PLANNING.md): search, checking, approval, and substitutions.
- [Logging](docs/LOGGING.md): reported intake, corrections, and completeness.
- [Mining](docs/MINING.md): recommendations and the retrieval pilot.
- [Inference](docs/INFERENCE.md): provider configuration, shared library, and model experiment.
- [Evaluation](docs/EVALUATION.md): planned reproducible benchmarks and limits.
- [UI](ui/README.md): frontend structure and development commands.

## Engineering protocol

- Keep focused contracts directly in `docs/`; distinguish requirements, implementation
  choices, and unfinished work. Update existing documents rather than duplicating context.
- Preserve the established UI visual style and single application/API-client structure.
- Keep raw datasets, credentials, and runtime state outside source control.
- Inventory exact CareLoop-owned storage before deletion; other projects are excluded.
- Inspect unfamiliar/uncommitted changes before overwriting. Do not delegate unless asked.
- Document verification commands and report failures, skips, and unavailable tooling honestly.
- Keep comments brief; explain non-obvious reasons or invariants rather than restating code.
