# CareLoop — Explainable Clinical Decision-Support

An explainable decision-support system that turns a clinician-approved nutrient
envelope (T2D, hypertension, CKD stage 3–4) into realistic Singapore meal
plans, with full traceability from clinical guideline → fired rule → approved
constraint → plated meal.

See [`PLAN.md`](./PLAN.md) for the full 4-week plan, member allocations, and
research-derived stack choices. This README documents the **repository
layout** and **how to run** Week 1 deliverables.

---

## Repository layout

```
CareLoop/
├── PLAN.md                    Full plan: scope, stack, week-by-week, risks
├── shared/                    Cross-cutting contract (single source of truth)
│   ├── envelope_schema.py     Pydantic NutrientEnvelope + supporting models
│   ├── envelope_schema.json   JSON Schema (cross-language contract)
│   └── README.md
├── rules/                     Lane A — Knowledge & Rules (Citable rule spec)
│   ├── rules.json             50 rules from ADA 2026 / AHA-ACC 2025 / KDIGO 2024 / KDOQI 2020
│   ├── example_trace.json     Worked CKD4 + HTN + K+5.4 patient trace
│   ├── clipspy_facts.py       CLIPS deftemplates (import-safe; clippsy optional)
│   ├── neo4j_schema_design.md Graph schema + versioning + SQLite+NetworkX fallback
│   ├── SCHEMA_DECISION.md     Decision gate: SQLite + NetworkX for the prototype
│   └── README.md
├── backend/                   Lane D — Integration & API (FastAPI)
│   ├── pyproject.toml
│   ├── README.md              API surface + approval-gate invariant docs
│   ├── app/
│   │   ├── main.py            FastAPI app (uvicorn entry)
│   │   ├── api/
│   │   │   ├── patients.py    GET/POST /patients
│   │   │   ├── rules.py       POST /rules/run  → PROPOSED envelope
│   │   │   ├── envelopes.py   /approve, /edit, /reject
│   │   │   ├── plans.py       POST /plans      → meal plan (gated on approval)
│   │   │   └── chat.py        POST /chat       (Week 2 stub)
│   │   ├── core/
│   │   │   ├── approval_gate.py    Approval-gate middleware + deps
│   │   │   ├── graph_versioning.py Versioned graph PoC (SQLite + NetworkX)
│   │   │   └── llm_choice.py       LLM/embedding defaults + env switch
│   │   ├── models/            Re-exports of canonical schema
│   │   └── tests/test_smoke.py
│   └── optim/                 Lane B — Optimisation (multi-objective plan search)
│       ├── problem.py         Decision vars, objectives, hard constraints
│       ├── baselines.py       random / greedy / exhaustive / fallback NSGA-II
│       ├── spike_pymoo.py     pymoo spike (lazy-import, fallback when absent)
│       ├── api.py             `run(envelope)` adapter for the /plans endpoint
│       ├── toy_data.py        8-tdish toy pool
│       └── test_smoke.py      9 smoke tests
├── data/                      Lane C — Data & Mining
│   ├── dishes.json            190 curated SG dishes
│   ├── patients.json          20 synthetic patients (deterministic seed)
│   ├── patients_generator.py  Reproducible patient generator
│   ├── usda_fill_gaps.py      USDA FDC API skeleton (K/P gap filler)
│   ├── patient.py             Pydantic Patient model
│   └── README.md
├── frontend/                  Week 3 placeholder (React + Vite + Tailwind)
└── notebooks/                 Exploration notebooks (placeholder)
```

---

## Week 1 status (foundations)

| Exit criterion                                            | Status |
|-----------------------------------------------------------|--------|
| Envelope schema frozen (shared/envelope_schema.py)        | ✅ |
| ≥30 rules specced with citations                          | ✅ 50 rules (ADA / AHA-ACC / KDIGO / KDOQI) |
| Schema decision recorded (Neo4j vs SQLite+NetworkX)       | ✅ SQLite + NetworkX for prototype |
| ≥150 dishes with Na/K/P/carbs                             | ✅ 190 dishes, 8 categories |
| ≥10 synthetic patients                                    | ✅ 20 patients across 9 archetypes |
| Patient generator reproducible                            | ✅ Seeded stdlib RNG (numpy optional) |
| USDA gap-filler skeleton                                  | ✅ urllib + DEMO_KEY, never-crashing |
| Optimisation problem formalised                           | ✅ Decision vars, 4 objectives, hard constraints |
| pymoo spike (or fallback) runs on toy data                | ✅ fallback-nsga2; pymoo path ready when installed |
| Hard constraints never violated                           | ✅ 0 violations on toy envelope; `_repair_plan` guarantees feasibility when any neighbour exists |
| FastAPI skeleton + stub endpoints                         | ✅ /healthz, /patients, /rules/run, /envelopes, /plans, /chat |
| Approval-gate invariant enforced                          | ✅ /plans returns HTTP 409 before approval; 200 after |
| End-to-end live test (POST /rules/run → /envelopes/approve → /plans) | ✅ HTTP 200, 40-plan feasible front |
| Graph versioning PoC (SQLite + NetworkX)                  | ✅ Append-only valid_from/valid_to chains |
| LLM/embedding choice                                      | ✅ Ollama default (nomic-embed-text + llama3.2:3b); OpenAI / Gemini / local-ST fallback |

---

## How to run

### 1. Use the venv

```bash
uv venv --python python3.14 .venv
source .venv/bin/activate
uv pip install pydantic fastapi 'uvicorn[standard]' httpx pyyaml networkx pytest
# (optional, for real NSGA-II rather than fallback):
# uv pip install pymoo numpy
```

### 2. Boot the API

```bash
PYTHONPATH=. uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

### 3. Run an end-to-end smoke (clone the curl recipe below)

```bash
P=127.0.0.1:8000
PATIENT='{"patient_id":"P0001","age":57,"sex":"M","weight_kg":61.6,"diagnoses":["T2D"],"egfr":92.2,"serum_K_meq_L":3.78,"meds":["metformin"]}'

# 1) Run rules -> PROPOSED envelope (50 fired rules)
curl -sS -X POST $P/rules/run -H 'content-type: application/json' -d "$PATIENT" | jq

# 2) Try /plans *before* approval -> 409
curl -sS -w '\nHTTP %{http_code}\n' -X POST $P/plans \
  -H 'content-type: application/json' -d '{"patient_id":"P0001"}'
# {"error":"envelope_not_approved","status":"PROPOSED"}  HTTP 409

# 3) Approve
EID=$(curl -sS -X POST $P/rules/run -H 'content-type: application/json' -d "$PATIENT" | jq -r .envelope_id)
curl -sS -X POST $P/envelopes/$EID/approve -H 'content-type: application/json' -d '{"approved_by":"Dr.Test"}'

# 4) Generate a plan
curl -sS -X POST $P/plans -H 'content-type: application/json' -d '{"patient_id":"P0001"}' | jq
```

### 4. Optimiser spike (toy data)

```bash
PYTHONPATH=. python -m backend.optim.spike_pymoo
# Engine                : fallback-nsga2
# Allowed dishes        : 6 of 8
# Pareto front size     : 40
# Constraint violations : 0
# Runtime               : ~830 ms
```

### 5. Smoke tests

```bash
PYTHONPATH=. python -m backend.app.tests.test_smoke         # API smoke (8 tests)
PYTHONPATH=. python -m backend.optim.test_smoke             # Optimiser smoke (9 tests)
PYTHONPATH=. python -m backend.app.core.graph_versioning   # Graph demo
PYTHONPATH=. python -m backend.app.core.llm_choice          # LLM choice
PYTHONPATH=. python -m data.patients_generator --n 20 --seed 0 --out data/patients.json
```

---

## Architectural invariants

1. **NutrientEnvelope.status == APPROVED is the single gate** to optimisation, RAG
   retrieval, and patient-facing views. Enforced in
   `backend/app/core/approval_gate.py` and verified in the schema's
   `NutrientEnvelope.is_ready_for_optimisation()`.
2. **The contract lives in `shared/envelope_schema.py`.** Rules engine,
   optimiser, and API MUST import from there. Pydantic is the Python truth;
   `shared/envelope_schema.json` is the language-agnostic mirror.
3. **Conflict priority is `CKD > HTN > T2D` on sodium**. CKD also wins for
   protein; potassium and phosphorus are individualised to serum labs.
4. **Versioning is append-only.** Each graph node/edge has `valid_from`
   and (when superseded) `valid_to` — never deleted.
5. **Clinical safety.** Every patient-facing output must trace back to an
   approved envelope. Out-of-scope (pregnancy, prescribing) is rejected with
   `exclude_from_careloop=true`.

---

## What's Week 2

- **A** — implement clipspy rule base + salience-based conflict resolution;
  unit-test against hand-computed cases; clinician explanation view.
- **B** — full optimiser on `data/dishes.json`; verify hard constraints on
  real dishes; collect runtime stats.
- **C** — load KB into graph; cohort clustering (k-means / HDBSCAN); food
  substitution engine v1.
- **D** — versioned-graph read/write used by the API; RAG retrieval pipeline
  indexed over KB chunks; approval gate end-to-end on real envelopes.

See `PLAN.md` §4 for the full Week 2 / 3 / 4 plan and exit criteria.
