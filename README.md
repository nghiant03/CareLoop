# CareLoop — Explainable Clinical Decision-Support

CareLoop turns a clinician-approved **nutrient envelope** (targets, ceilings, hard
exclusions) for T2D / hypertension / CKD stage 3–4 patients into a realistic
7-day Singapore meal plan — with full traceability from clinical guideline →
fired rule → approved constraint → plated meal. A grounded chatbot answers
nutrition questions using only the versioned knowledge base, always citing the
guideline it drew from, and escalates out-of-scope questions to a clinician
instead of answering.

- Rule engine design: [`rules/ENGINE.md`](rules/ENGINE.md)
- Optimiser benchmark: [`backend/optim/benchmark_results.md`](backend/optim/benchmark_results.md)
- Evaluation report (generated): [`evaluation/EVALUATION.md`](evaluation/EVALUATION.md)
- User guides: [`docs/`](docs/) — clinician, patient, 5-minute demo script, architecture

---

## Architecture

```
 ┌──────────────┐        ┌───────────────────────────────────────────────┐
 │ React web UI │───────▶│  FastAPI backend  (backend/app, port 8000)    │
 │ Vite :5173   │  /api  │  /patients /rules/run /envelopes /plans       │
 │ clinician +  │        │  /chat /mining /kb /healthz                   │
 │ patient views│        └───┬───────────────┬──────────────┬────────────┘
 └──────────────┘            │               │              │
                   ┌─────────▼──────┐ ┌──────▼───────┐ ┌────▼─────────┐
                   │ Rule engine    │ │ Optimiser    │ │ Mining       │
                   │ rules/ (CLIPS, │ │ backend/optim│ │ backend/min- │
                   │ 52 rules,      │ │ (pymoo NSGA- │ │ ing (trends, │
                   │ salience)      │ │ II + repair) │ │ clusters,    │
                   └───────┬────────┘ └──────┬───────┘ │  subst.)     │
                           │                 │         └──────────────┘
                   ┌───────▼─────────────────▼──────────────────────┐
                   │ Approval gate (APPROVED-only) + trace store    │
                   └───────┬────────────────────────────────────────┘
                   ┌───────▼────────────────────────────────────────┐
                   │ Versioned KB (SQLite + NetworkX, in-memory):   │
                   │ 52 rules + 190 SG dishes + citations; TF-IDF   │
                   │ retrieval index for the grounded chatbot       │
                   └────────────────────────────────────────────────┘
```

Data flow: patient → rule engine (PROPOSED envelope + `RuleFire` trace) →
**approval gate** (clinician approve/edit/reject; only `APPROVED` passes) →
optimiser (7-day × 3-meal plan, hard-constraint guarantee) → UI. The chatbot
retrieves from the versioned KB + the patient's latest envelope and never
answers without a citation. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Repository layout

```
CareLoop/
├── shared/                      Cross-cutting contract (single source of truth)
│   ├── envelope_schema.py       Pydantic NutrientEnvelope + RuleFire + ...
│   └── envelope_schema.json     JSON Schema (language-agnostic mirror)
├── rules/                       Lane A — knowledge & rules
│   ├── rules.json               52 rules (50 guideline + 2 internal safety)
│   ├── engine.py                CLIPS forward-chaining engine (run_rules)
│   ├── ENGINE.md                Engine design, conflict resolution, trace
│   ├── example_trace.json       Hand-worked CKD4 + HTN + K⁺ 5.4 trace
│   └── clipspy_facts.py / SCHEMA_DECISION.md / neo4j_schema_design.md
├── backend/
│   ├── app/                     FastAPI service
│   │   ├── main.py              uvicorn entry; CORS; 409 gate handler
│   │   ├── api/                 patients / rules / envelopes / plans / chat / mining / kb
│   │   ├── core/                approval_gate, trace_store, kb_loader,
│   │   │                        plan_service (MIN-floor relaxation), graph_versioning, llm_choice
│   │   ├── chat/                retrieval (TF-IDF), answers, escalation, llm
│   │   ├── kb/                  versioned graph store (SQLite + NetworkX)
│   │   ├── explain/             clinician + patient explanation views
│   │   └── tests/               API, gate, chat, explain, e2e tests
│   ├── optim/                   Lane B — meal-plan optimiser
│   │   ├── problem.py / real_data.py / solver.py / api.py
│   │   ├── baselines.py / benchmark.py / benchmark_results.md
│   │   └── envelopes.py / spike_pymoo.py / toy_data.py
│   └── mining/                  trends (Theil–Sen), clustering, substitutions
├── data/                        Lane C — 190 SG dishes, 20 synthetic patients, USDA gap filler
├── frontend/                    React 19 + Vite + Tailwind (3 screens)
├── notebooks/                   Exploration notebooks
├── docs/                        User guides, demo script, architecture
└── evaluation/                  Generated evaluation report (EVALUATION.md)
```

---

## How to run

Prereqs: Python venv at `.venv/` (FastAPI, uvicorn, clipspy, pymoo, numpy,
scikit-learn, networkx, pytest) and Node for the frontend.

### 1. Backend (port 8000)

```bash
# from the repo root
PYTHONPATH=. .venv/bin/uvicorn backend.app.main:app --reload --port 8000
# docs:   http://localhost:8000/docs
# health: http://localhost:8000/healthz
```

### 2. Frontend (port 5173)

```bash
cd frontend && npm install && npm run dev
# http://localhost:5173 — Vite proxies /api to the backend on :8000
```

### 3. End-to-end in four calls

```bash
P=http://127.0.0.1:8000

# 1) Run the rule engine -> PROPOSED envelope + fired-rule trace
EID=$(curl -sS -X POST $P/rules/run -H 'content-type: application/json' \
  -d '{"patient_id":"P0005"}' | jq -r .envelope.envelope_id)

# 2) /plans before approval -> 409 envelope_not_approved
curl -sS -w '\nHTTP %{http_code}\n' -X POST $P/plans \
  -H 'content-type: application/json' -d '{"patient_id":"P0005"}'

# 3) Clinician approves
curl -sS -X POST $P/envelopes/$EID/approve \
  -H 'content-type: application/json' -d '{"approved_by":"Dr.Demo"}' | jq .status

# 4) Generate the 7-day plan (or see the infeasibility diagnosis)
curl -sS -X POST $P/plans -H 'content-type: application/json' \
  -d '{"patient_id":"P0005"}' | jq '{feasible, engine, violation_count, infeasibility_reason, relaxed_constraints}'
```

Envelopes, traces and created patients live in process-local stores; a backend
restart resets them (the contracts are storage-agnostic by design).

---

## API surface

| Method | Path | Purpose |
|---|---|---|
| GET | `/healthz` | liveness probe (+ `GET /` service banner) |
| GET | `/patients` | list patients (reads `data/patients.json` + overlay) |
| GET | `/patients/{patient_id}` | fetch one patient (404 if absent) |
| POST | `/patients` | create a patient (process-local overlay) |
| POST | `/rules/run` | patient id → PROPOSED `NutrientEnvelope` + `RuleFire` trace |
| GET | `/envelopes/{id}` | fetch an envelope |
| GET | `/envelopes/{id}/explanation` | clinician explanation (trace, conflicts, citations) |
| POST | `/envelopes/{id}/approve` | PROPOSED/EDITED → APPROVED |
| POST | `/envelopes/{id}/edit` | mutate targets → EDITED (re-approval required) |
| POST | `/envelopes/{id}/reject` | → REJECTED |
| POST | `/plans` | 7-day meal plan — **gated**: 409 unless APPROVED |
| POST | `/chat` | grounded Q&A `{answer, citations, escalated, status}` |
| GET | `/mining/trends` | rising K⁺/PO₄ flags across the cohort |
| GET | `/mining/substitutions?dish_id=&k=` | healthier substitute dishes |
| GET | `/kb/stats` | versioned-KB node/edge counts + retrieval-index size |

Interactive docs: `http://localhost:8000/docs`.

---

## Architectural invariants

1. **The approval gate.** `NutrientEnvelope.status == APPROVED` is the single
   gate to the optimiser, RAG chat and patient-facing views. Enforced in
   `backend/app/core/approval_gate.py`; violations render as
   `HTTP 409 {"error": "envelope_not_approved", "status": ...}`.
2. **The contract lives in `shared/envelope_schema.py`.** Engine, optimiser and
   API import it; `shared/envelope_schema.json` is the language-agnostic mirror.
3. **Conflict priority `CKD > HTN > T2D` on sodium** (KDIGO 2000 mg overrides
   DASH/ADA 2300 mg). Losing rules keep their trace rows with an explicit
   `SUPERSEDED: superseded by <rule> ...` marker. Potassium and phosphorus are
   individualised to serum labs.
4. **Hard constraints are never silently broken.** The optimiser guarantees
   `violation_count == 0` (repair → greedy fallback); when the dish pool cannot
   satisfy an envelope it returns an explicit infeasibility diagnosis, and
   unreachable MIN floors are lowered with a full `relaxed_constraints`
   disclosure in the plan response.
5. **Chat is grounded or silent.** Answers are composed only from retrieved KB
   chunks (+ the patient's envelope numbers) and always cite
   `rule_id + guideline + section`; low-confidence questions are refused;
   emergencies, diagnosis/dosing requests and out-of-scope topics are escalated.
6. **Versioning is append-only.** Every KB node/edge carries `valid_from` /
   `valid_to`; nothing is deleted.
7. **Clinical safety.** Out-of-scope patients (pregnancy, paediatric, dialysis)
   are `REJECTED` with `exclude_from_careloop=true` and never reach the
   optimiser.

---

## Tests

```bash
.venv/bin/python -m pytest rules/ -q           # rule engine suite
.venv/bin/python -m pytest backend -q          # API, gate, chat, explain, e2e
.venv/bin/python -m pytest backend/mining -q   # trends / clustering / substitutions
.venv/bin/python backend/optim/test_real.py    # optimiser on the real dish pool
```
