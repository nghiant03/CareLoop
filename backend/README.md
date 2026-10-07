# CareLoop Backend

FastAPI service for CareLoop. It exposes the API surface that the React UI talks
to and enforces the **approval-gate invariant** that keeps unapproved clinical
constraints away from the optimiser and any patient-facing view.

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
    │   ├── mining.py         # GET /mining/trends, GET /mining/substitutions
    │   └── kb.py             # GET /kb/stats (versioned-KB observability)
    ├── core/
    │   ├── approval_gate.py  # envelope store + gate dependencies (409 invariant)
    │   ├── trace_store.py    # side-store pinning the RuleFire trace per envelope id
    │   ├── kb_loader.py      # process KB singleton (rules.json + dishes.json -> KBGraph)
    │   ├── plan_service.py   # envelope prep (MIN-floor relaxation) + plan/UI mapping
    │   ├── graph_versioning.py  # SQLite + NetworkX versioned graph
    │   └── llm_choice.py     # LLM / embedding selection
    ├── chat/
    │   ├── retrieval.py      # TF-IDF index over KB rule + dish chunks
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
source .venv/bin/activate
uv pip install fastapi "uvicorn[standard]" httpx pyyaml networkx pytest
# or, once installed editable: uv pip install -e backend
```

## Run

```bash
PYTHONPATH=. .venv/bin/uvicorn backend.app.main:app --reload --port 8000
# docs:   http://localhost:8000/docs
# health: http://localhost:8000/healthz
```

Startup warms the versioned knowledge base (52 rules + 190 dishes -> KBGraph +
TF-IDF index); a KB load failure never takes the API down (endpoints fall back
to lazy loading).

## API surface

| Method | Path | Purpose | Gated? |
|---|---|---|---|
| GET  | `/healthz` | liveness probe | no |
| GET  | `/patients` | list patients (count + records, raw fields + UI aliases) | no |
| GET  | `/patients/{patient_id}` | fetch one patient (404 if absent) | no |
| POST | `/patients` | create a synthetic patient (in-memory overlay) | no |
| POST | `/rules/run` | patient id -> PROPOSED `NutrientEnvelope` + full `RuleFire` trace | no |
| GET  | `/envelopes/{envelope_id}` | fetch an envelope | no |
| GET  | `/envelopes/{envelope_id}/explanation` | clinician explanation: fired rules, conflict resolutions, citations | no |
| POST | `/envelopes/{envelope_id}/approve` | PROPOSED/EDITED -> APPROVED | no |
| POST | `/envelopes/{envelope_id}/edit` | mutate targets -> EDITED (re-approval required) | no |
| POST | `/envelopes/{envelope_id}/reject` | -> REJECTED | no |
| POST | `/plans` | generate a 7-day meal plan for a patient | **yes** |
| POST | `/chat` | grounded RAG answer `{answer, citations, escalated, status}` | no |
| GET  | `/mining/trends` | rising K⁺/PO₄ trend flags over `data/patients.json` | no |
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

> **Only `APPROVED` envelopes may be consumed downstream.**

This is a hard architectural invariant (PLAN.md §2.3), not a convention.

- The rule engine produces envelopes with status `PROPOSED`.
- A clinician moves an envelope to `APPROVED` via `POST /envelopes/{id}/approve`.
- Any endpoint that reads an envelope **must** depend on
  `require_approved_envelope` (or `require_approved_envelope_for_patient` for
  body-keyed routes such as `/plans`).
- That dependency calls `envelope.is_ready_for_optimisation()`. If the status is
  not `APPROVED` it raises `EnvelopeNotApprovedError`, rendered by `main.py` as:

```json
HTTP 409
{"error": "envelope_not_approved", "status": "PROPOSED"}
```

- Editing an approved envelope moves it to `EDITED` and clears approval, so the
  gate blocks it again until a clinician re-confirms.

Envelopes live in a process-local dict (`ENVELOPE_STORE` in
`core/approval_gate.py`) and rule traces in a side-store
(`core/trace_store.py`) keyed by envelope id, so
`GET /envelopes/{id}/explanation` reconstructs the decision exactly as proposed.
Both stores are storage-agnostic by design; swapping in a persistent backing
table does not touch the gate contract or the endpoints.

## Plan generation (`core/plan_service.py`)

`prepare_envelope_for_pool` lowers MIN floors the allowed dish pool provably
cannot reach (e.g. the guideline fibre floor 30 g/d vs a 190-dish pool topping
out at 8 g/dish → 24 g/day best case) **before** solving, and reports every
adjustment in `relaxed_constraints` — the hard-constraint guarantee
(`violation_count == 0`) holds against the envelope actually solved, and the
relaxation is disclosed instead of silently dropping the guideline intent.
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
# or: PYTHONPATH=. python -m backend.app.tests.test_smoke
```

The suite covers imports, `/healthz`, patient create/fetch, the PROPOSED
envelope + trace from `/rules/run`, the approval-gate behaviour (409 while
PROPOSED/EDITED, pass-through once APPROVED), the KB graph + stats endpoint,
grounded chat answers / refusals / escalations, explanation views, and an
end-to-end run → approve → plan flow.
