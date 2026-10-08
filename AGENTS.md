# CareLoop repository context

CareLoop turns clinician-approved nutrient envelopes into meal plans, tracks
logged-meal adherence, and answers nutrition questions with cited evidence.

For API/domain naming changes, substantial refactors, or maintainability review,
use the `maintainable-code` skill. Read [the glossary](docs/GLOSSARY.md) for domain
distinctions and [the architecture](docs/ARCHITECTURE.md) for documented contracts.

## Sources of truth and module responsibilities

- `shared/envelope_schema.py` defines the canonical Python envelope contract;
  `backend/app/models/envelope.py` re-exports it. The JSON Schema in
  `shared/envelope_schema.json` is its cross-language mirror.
- `rules/engine.py` derives proposals and rule traces from `rules/rules.json`.
  See `rules/ENGINE.md` for conflict resolution and scope rules.
- `backend/app/core/` owns approval-gate helpers, durable application storage,
  and plan preparation/mapping. `backend/app/api/` exposes HTTP workflows.
- `backend/optim/` owns search and canonical plan evaluation; `backend/mining/`
  owns trends and substitutions. `backend/app/adherence/` analyzes logged meals.
- `backend/app/chat/` retrieves evidence and composes answers;
  `backend/app/explain/` builds explanation views.
- `frontend/src/api.ts` adapts HTTP responses for the frontend; view contracts
  live in `frontend/src/types.ts`. Check actual response shapes when changing
  either side. Regenerate the JSON Schema with
  `.venv/bin/python -m shared.export_schema` after model changes.
- `evaluation/` contains evaluation workflows and generated reports. Consult
  `evaluation/run.py` and `evaluation/run_eval.py` before regenerating artifacts.

These are documented responsibilities, not an executable import-boundary policy.
Current cross-router imports do not establish a required dependency direction.

## Contracts to preserve

- Only APPROVED envelopes authorize live planning and personal target guidance.
  Editing invalidates approval. Scope-rejected patients must remain excluded;
  `core/envelope_lifecycle.py` owns these transitions. `lifecycle_revision` guards
  every durable update; clients send `expected_revision` to detect stale reviews.
- Hard constraints are MAX ceilings and exclusions. MIN floors and TARGETs are
  soft objectives. Feasibility and adequacy are separate results; disclose any
  relaxed floors and assess adequacy against the original approved aims.
- Fresh proposals receive fresh envelope IDs; edits increment the version of
  an existing envelope. Preserve historical snapshots and citation provenance.
- The SQLite application journal is authoritative for envelope state. Preserve
  embedded traces across restarts; they take precedence over legacy side stores.
- Adherence uses approval coverage effective on the logged date. Uncovered dates
  remain unattributed; only complete logged days enter trend calculations.
- Chat must retain grounding, citation, refusal, and escalation behavior.
- Before renaming a field, inspect HTTP payloads, persisted JSON, schema mirrors,
  frontend consumers, and evaluation fixtures. Internal renames alone do not
  establish wire-format or stored-data compatibility.

## Verification

Run from the repository root using the existing environment:

```sh
.venv/bin/python -m pytest rules backend evaluation -q
.venv/bin/python -m shared.export_schema --check
npm --prefix frontend run lint
npm --prefix frontend test
npm --prefix frontend run build
```

For focused iteration, select the relevant pytest files or directories. The
frontend build includes TypeScript checking. Report the commands and scope run,
including failures, warnings, or unavailable tools; do not weaken checks to pass.

Pytest's root `conftest.py` isolates the application database. For standalone
probes, set `CARELOOP_APP_DB` to a temporary database before importing application
code; the default `data/careloop_app.sqlite3` is tracked application state.

The backend manifest is `backend/pyproject.toml`; the frontend manifest and lock
file are under `frontend/`. Install backend development dependencies with
`uv pip install --python .venv/bin/python -e 'backend[dev]'`. Frontend regression
tests use Vitest and Testing Library. There is no configured Python lint/type-check
command or repository CI workflow; report those verification gaps.

Start with `README.md` and `docs/ARCHITECTURE.md` for current behavior; some older
module READMEs still describe earlier milestones. `PLAN.md` is ignored local
planning material and may be absent from another checkout.
