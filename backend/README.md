# CareLoop Backend

FastAPI service for CareLoop. It exposes the API surface that the React UI talks
to and enforces the **approval-gate invariant** for live planning and personal
target guidance. Informational views may inspect unapproved envelopes.

## Layout

```
backend/
├── pyproject.toml            # project + deps + pytest config
├── README.md
├── mining/                   # trends / clustering / substitutions (see mining/README.md)
├── optim/                    # meal-plan optimiser (see optim/README.md)
└── app/
    ├── main.py               # FastAPI app: lifespan, CORS, handlers, routers
    ├── api/
    │   ├── patients.py       # GET/POST /patients, GET /patients/{id}
    │   ├── rules.py          # POST /rules/run -> PROPOSED envelope + trace (real CLIPS engine)
    │   ├── envelopes.py      # GET envelope, /explanation, /approve, /edit, /reject
    │   ├── plans.py          # POST /plans (gated on APPROVED; MIN-relaxation disclosure)
    │   ├── chat.py           # POST /chat (grounded RAG pipeline, escalation filter)
    │   ├── mining.py         # trend/substitution queries + persistent validated swaps
    │   └── kb.py             # GET /kb/stats (versioned-KB observability)
    ├── core/
    │   ├── approval_gate.py  # envelope store + gate dependencies (409 invariant)
    │   ├── trace_store.py    # embedded trace serialization + legacy side-store fallback
    │   ├── kb_loader.py      # process KB singleton (rules.json + dishes.json -> KBGraph)
    │   ├── plan_service.py   # envelope prep (MIN-floor relaxation) + plan/UI mapping
    │   ├── graph_versioning.py  # SQLite + NetworkX versioned graph
    │   └── llm_choice.py     # LLM / embedding selection
    ├── chat/
    │   ├── retrieval.py      # BM25 index over KB rule + dish chunks
    │   ├── answers.py        # grounded answer pipeline (citation invariant, refusal)
    │   ├── escalation.py     # regex escalation filter (emergency / diagnosis / dosing / scope)
    │   └── llm.py            # LLM adapter (template answers work with llm=None)
    ├── kb/
    │   └── graph_store.py    # versioned KBGraph (in-memory SQLite + NetworkX)
    ├── explain/
    │   └── views.py          # clinician + patient explanation builders (pure functions)
    ├── models/
    │   ├── envelope.py       # re-export of shared/envelope_schema.py
    │   └── patient.py        # PatientSummary re-export + extended Patient
    └── tests/                # smoke, gate, KB, chat, explain, e2e tests
```

The canonical contracts live in `shared/envelope_schema.py` (Pydantic v2) and
`shared/envelope_schema.json` (JSON Schema). `backend/app/models/envelope.py`
only re-exports them — never redefine the schema in the backend.

## Setup

```bash
# from the repo root
uv venv .venv
uv pip install --python .venv/bin/python -e 'backend[dev]'
```

## Run

```bash
PYTHONPATH=. .venv/bin/uvicorn backend.app.main:app --reload --port 8000
# docs:   http://localhost:8000/docs
# health: http://localhost:8000/healthz
```

Startup warms the versioned knowledge base (rules and dishes -> KBGraph +
BM25 index); a KB load failure never takes the API down (endpoints fall back
to lazy loading).

## API surface

| Method | Path | Purpose | Gated? |
|---|---|---|---|
| GET  | `/healthz` | liveness probe | no |
| GET  | `/patients` | list patients (count + records, raw fields + UI aliases) | no |
| GET  | `/patients/{patient_id}` | fetch one patient (404 if absent) | no |
| POST | `/patients` | create a synthetic patient (durable SQLite profile) | no |
| POST | `/rules/run` | patient id -> PROPOSED `NutrientEnvelope` + full `RuleFire` trace | no |
| GET  | `/envelopes/{envelope_id}` | fetch an envelope | no |
| GET  | `/envelopes/{envelope_id}/explanation` | clinician explanation: fired rules, conflict resolutions, citations | no |
| POST | `/envelopes/{envelope_id}/approve` | PROPOSED/EDITED -> APPROVED | no |
| POST | `/envelopes/{envelope_id}/edit` | mutate targets -> EDITED (re-approval required) | no |
| POST | `/envelopes/{envelope_id}/reject` | -> REJECTED | no |
| POST | `/plans` | generate a 7-day meal plan for a patient | **yes** |
| POST | `/chat` | grounded RAG answer `{answer, citations, escalated, status}` | no |
| GET  | `/mining/trends` | K⁺/PO₄ flags from observations or fixture monthly series | no |
| GET  | `/mining/substitutions?dish_id=&k=` | substitute dishes (nutrient-distance v2) | no |
| GET  | `/kb/stats` | KB node/edge counts, version tag, retrieval-chunk count | no |

Notes:

- `POST /rules/run` body is `{"patient_id": ...}`; the patient is loaded from
  the patient store. The response is `{"envelope": ..., "trace": [...]}`.
- `POST /chat` body is `{"message": ..., "patient_id"?/`envelope_id`?}`. Every
  `answered` response carries at least one citation (`rule_id`, `guideline`,
  `url`); out-of-scope messages return `escalated: true` and are never answered;
  low-confidence messages return `status: "refused"`.
- The plan response includes `feasible`, `engine`, `violation_count`,
  `relaxed_constraints` (disclosed MIN-floor adjustments), `infeasibility_reason`
  and an `explanation` block for the patient view.

## Approval gate invariant

> **Live planning requires an `APPROVED`, scope-eligible envelope with nonempty targets.**

The authoritative contract, including informational reads and chat behavior,
is in [the architecture](../docs/ARCHITECTURE.md#2-the-approval-gate-invariant).

- The rule engine produces eligible `PROPOSED` or scope-rejected envelopes.
- A clinician moves an envelope to `APPROVED` via `POST /envelopes/{id}/approve`.
- Live planning endpoints depend on
  `require_approved_envelope` (or `require_approved_envelope_for_patient` for
  body-keyed routes such as `/plans`).
- That dependency calls `envelope.is_ready_for_optimisation()`. Failure of any
  readiness condition raises `EnvelopeNotApprovedError`, rendered by `main.py` as:

```json
HTTP 409
{"error": "envelope_not_approved", "status": "PROPOSED"}
```

- Editing an approved envelope moves it to `EDITED` and clears approval, so the
  gate blocks it again until a clinician re-confirms.

Envelopes and their embedded rule traces live in the SQLite application journal
(`core/persistence.py`). Lifecycle transitions are implemented in
`core/envelope_lifecycle.py`. Proposal-owned scope eligibility cannot be edited
away. Every transition checks and advances `lifecycle_revision` transactionally;
clients may send `expected_revision` to reject stale reviews with HTTP 409
`envelope_conflict`. The web UI supplies that token. `version` still counts edits.

## Plan generation (`core/plan_service.py`)

`plan_meals` shares preparation, solver execution, and main/side composition
between plan generation, simulations, and Q3 evaluation. It performs no storage
writes. `prepare_envelope_for_pool` calibrates soft MIN floors to the
single-dish-per-meal search bound and discloses changes in `relaxed_constraints`.
If main/side composition succeeds, original aims are restored. Hard MAX ceilings
and exclusions remain unchanged throughout.
`map_plan_result` shapes the optimiser output into the UI contract:
`days[] → slots[] / totals[]` (totals vs targets with per-nutrient `compliant`
flags) plus the patient `explanation`.

## Graph versioning PoC

`core/graph_versioning.py` implements the chosen **SQLite + NetworkX** graph
store (decision gate, PLAN.md §1). Writes are append-only: each logical node /
edge has a version chain and only the newest row is "current" (`valid_to IS
NULL`); prior rows are closed with a `valid_to` timestamp so history survives.
NetworkX materialises the current-state subgraph on demand.

```bash
PYTHONPATH=. python -m backend.app.core.graph_versioning   # self-contained demo
```

DB file: `data/careloop_graph.sqlite3` (override with `CARE_LOOP_GRAPH_DB`).
The runtime KB (`core/kb_loader.py` → `kb/graph_store.py`) uses the same
versioned model in an in-memory SQLite database.

## LLM / embedding choice

`core/llm_choice.py` resolves model configuration without making network calls.

| Role | Default | Override / fallback |
|---|---|---|
| Embedding | `nomic-embed-text` (Ollama) | `CARE_LOOP_LLM_BACKEND=local_st` -> `sentence-transformers/all-MiniLM-L6-v2` |
| Chat LLM | `llama3.2:3b` (Ollama) | `OPENAI_API_KEY` -> `gpt-4o-mini`; `GOOGLE_API_KEY` -> `gemini-2.0-flash` |

Priority: explicit `CARE_LOOP_LLM_BACKEND` override → OpenAI → Google → local
Ollama. This keeps a fully offline demo working with no keys while letting a
developer opt into a hosted model by exporting a single env var. The chat
pipeline is deterministic template composition over retrieved chunks; the LLM
adapter is optional polish on top of an already-grounded answer.

```bash
PYTHONPATH=. python -m backend.app.core.llm_choice   # prints resolved choices
```

## Tests

```bash
.venv/bin/python -m pytest backend -q
.venv/bin/python -m shared.export_schema --check
# or: PYTHONPATH=. python -m backend.app.tests.test_smoke
```

The suite covers imports, `/healthz`, patient create/fetch, the PROPOSED
envelope + trace from `/rules/run`, the approval-gate behaviour (409 while
PROPOSED/EDITED, pass-through once APPROVED), the KB graph + stats endpoint,
grounded chat answers / refusals / escalations, explanation views, and an
end-to-end run → approve → plan flow.
