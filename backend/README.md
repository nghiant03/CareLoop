# CareLoop Backend

FastAPI service for CareLoop. It exposes the API surface that the React UI talks
to and enforces the **approval-gate invariant** that keeps unapproved clinical
constraints away from the optimiser and any patient-facing view.

## Layout

```
backend/
├── pyproject.toml            # project + deps + pytest config
├── README.md
└── app/
    ├── __init__.py           # puts repo root on sys.path (shared/ importable)
    ├── main.py               # FastAPI app: lifespan, CORS, handlers, routers
    ├── api/
    │   ├── patients.py       # GET/POST /patients  (reads data/patients.json)
    │   ├── rules.py          # POST /rules/run     -> PROPOSED envelope (stub)
    │   ├── envelopes.py      # approve / edit / reject
    │   ├── plans.py          # POST /plans         (gated on APPROVED)
    │   └── chat.py           # POST /chat          (RAG stub, Week 2)
    ├── core/
    │   ├── approval_gate.py  # envelope store + gate dependencies
    │   ├── graph_versioning.py  # SQLite + NetworkX versioned graph PoC
    │   └── llm_choice.py     # LLM / embedding selection
    ├── models/
    │   ├── envelope.py       # re-export of shared/envelope_schema.py
    │   └── patient.py        # PatientSummary re-export + extended Patient
    └── tests/
        └── test_smoke.py     # imports + ASGI smoke + gate invariant
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
uvicorn backend.app.main:app --reload --port 8000
# docs:   http://localhost:8000/docs
# health: http://localhost:8000/healthz
```

## API surface (Week 1)

| Method | Path | Purpose | Gated? |
|---|---|---|---|
| GET  | `/healthz` | liveness probe | no |
| GET  | `/patients` | list synthetic patients | no |
| GET  | `/patients/{patient_id}` | fetch one patient (404 if absent) | no |
| POST | `/patients` | create a synthetic patient (in-memory overlay) | no |
| POST | `/rules/run` | PatientSummary -> PROPOSED `NutrientEnvelope` (stub, no clipspy yet) | no |
| GET  | `/envelopes/{envelope_id}` | fetch an envelope | no |
| POST | `/envelopes/{envelope_id}/approve` | PROPOSED/EDITED -> APPROVED | no |
| POST | `/envelopes/{envelope_id}/edit` | mutate targets -> EDITED (re-approval required) | no |
| POST | `/envelopes/{envelope_id}/reject` | -> REJECTED | no |
| POST | `/plans` | generate a meal plan for a patient | **yes** |
| POST | `/chat` | RAG chatbot (stub, citation-required) | no |

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

Week 1 stores envelopes in a process-local dict (`ENVELOPE_STORE` in
`core/approval_gate.py`); the gate contract is storage-agnostic and Week 2 swaps
in a persistent store without touching endpoints.

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

## LLM / embedding choice

`core/llm_choice.py` resolves model configuration without making network calls.

| Role | Default | Override / fallback |
|---|---|---|
| Embedding | `nomic-embed-text` (Ollama) | `CARE_LOOP_LLM_BACKEND=local_st` -> `sentence-transformers/all-MiniLM-L6-v2` |
| Chat LLM | `llama3.2:3b` (Ollama) | `OPENAI_API_KEY` -> `gpt-4o-mini`; `GOOGLE_API_KEY` -> `gemini-2.0-flash` |

Priority: explicit `CARE_LOOP_LLM_BACKEND` override → OpenAI → Google → local
Ollama. This keeps a fully offline demo working with no keys while letting a
developer opt into a hosted model by exporting a single env var.

```bash
PYTHONPATH=. python -m backend.app.core.llm_choice   # prints resolved choices
```

## Tests

```bash
PYTHONPATH=. python -m backend.app.tests.test_smoke
# or: pytest backend
```

The smoke suite asserts imports, `/healthz`, patient create/fetch, the PROPOSED
stub envelope from `/rules/run`, and the approval-gate behaviour (409 while
PROPOSED/EDITED, pass-through once APPROVED).
