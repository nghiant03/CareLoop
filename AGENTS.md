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
- `backend/knowledge/` owns operator-only draft/review/publication and runtime
  release selection. In database mode, rules, catalogue, optimizer, mining and
  chat must use the same process-pinned published snapshot; never silently fall
  back to fixture files. See `docs/KNOWLEDGE.md`. Keep clinical and knowledge
  databases separate. Actor labels are attestations, not authenticated identities.
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
- Published catalogue IDs retain nutritional/portion/category/ingredient/tag
  semantics and remain available for historical logs/plans; corrections use new
  IDs. Release changes require a controlled restart, not ad-hoc cache resets.
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
code; the default runtime database uses the user's state directory, never the
checkout. Legacy `data/careloop_app.sqlite3` requires explicit migration or an
override. See `docs/STORAGE.md`; preserve local databases and published evidence.
Main evaluation/optimizer/retrieval runs write to ignored `artifacts/` by default
(`CARELOOP_ARTIFACT_DIR` overrides the root). Publish report snapshots deliberately.

The Python manifest is the repository-root `pyproject.toml` (single `careloop`
distribution covering `backend/`, `shared/`, and `rules/`); the frontend manifest
and lock file are under `frontend/`. Install development dependencies with
`uv pip install --python .venv/bin/python -e '.[dev]'`. The editable install puts
the repository root on the import path, so `backend.*`, `shared.*`, and `rules.*`
resolve without `PYTHONPATH`. Frontend regression
tests use Vitest and Testing Library. There is no configured Python lint/type-check
command or repository CI workflow; report those verification gaps.

Start with `README.md` and `docs/ARCHITECTURE.md` for current behavior; some older
module READMEs still describe earlier milestones. `PLAN.md` is ignored local
planning material and may be absent from another checkout.

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **CareLoop** (3363 symbols, 7837 relationships, 290 execution flows).

> Index stale? Run `node .gitnexus/run.cjs analyze --index-only` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? Bootstrap with `npx`, `bunx`, or `pnpm dlx` — e.g. `bunx gitnexus@latest analyze` (npm 11 npx crash; #1939).

## Always Do

- **MUST run impact before editing.** Use `impact({target: "symbolName", direction: "upstream"})` or `node .gitnexus/run.cjs impact "symbolName" --direction upstream --repo .`; report callers, processes, and risk. Never substitute grep for graph analysis.
- **MUST analyze graph changes before committing.** Use `detect_changes({scope: "all"})` (MCP) or `node .gitnexus/run.cjs detect-changes --scope all --repo .` (CLI fallback). `partial: true` or `truncated: true` is not a clean check — a zero means unseen, not unaffected; re-run it. For regression review: `detect_changes({scope: "compare", base_ref: "main"})` or `node .gitnexus/run.cjs detect-changes --scope compare --base-ref "main" --repo .`.
- MUST warn on HIGH/CRITICAL `risk` pre-edit; never use `riskSharedAxes` to waive a HIGH/CRITICAL `risk` warning. Compare File/symbol: MCP File omits axes; Graph-RAG expands File.
- **MUST treat `risk: UNKNOWN` as unresolved, not as low.** An empty caller set is not evidence the symbol is unused — it can also mean the callers are not resolvable by the index (plain-object property access, dynamic dispatch, cross-language calls). `impact` pairs `UNKNOWN` with a `riskNote` saying so. Confirm with a text search before treating the symbol as safe to change or delete; do not proceed on the strength of a zero.
- **MUST use `query({search_query: "concept"})` for concepts/flows, `context({name: "symbolName"})` for a named symbol, or `impact` for blast radius, on read-only callers, dependencies, imports, or execution flow.** Graph first; text search only for empty/`UNKNOWN`/literals.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method before MCP/CLI impact analysis.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis, and never read `UNKNOWN` as an all-clear — it means the walk could not answer, which is the one verdict that requires confirming by other means.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit before MCP/CLI graph change analysis.

## Resources

| Resource | Use for |
| --- | --- |
| `gitnexus://repo/CareLoop/context` | Codebase overview, check index freshness |
| `gitnexus://repo/CareLoop/clusters` | All functional areas |
| `gitnexus://repo/CareLoop/processes` | All execution flows |
| `gitnexus://repo/CareLoop/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
| --- | --- |
| Understand architecture / "How does X work?" | `.agents/skills/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.agents/skills/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.agents/skills/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.agents/skills/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.agents/skills/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.agents/skills/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
