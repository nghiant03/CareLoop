# CareLoop — Explainable Clinical Decision-Support

CareLoop turns a clinician-approved **nutrient envelope** (targets, ceilings, hard
exclusions) for T2D / hypertension / CKD stage 3–4 patients into a realistic
7-day Singapore meal plan — with full traceability from clinical guideline →
fired rule → approved constraint → plated meal. Patients then log what they
actually ate, and the **adherence loop** measures logged meals against the
envelope: per-day totals, hard-violation / soft-gap classifications and
deviation trend flags. A grounded chatbot answers nutrition questions using
only the versioned knowledge base, always citing the guideline it drew from,
and escalates out-of-scope questions to a clinician instead of answering.

- Rule engine design: [`rules/ENGINE.md`](rules/ENGINE.md)
- Optimiser benchmark: [`backend/optim/benchmark_results.md`](backend/optim/benchmark_results.md)
- Retrieval benchmark: [`backend/app/chat/RETRIEVAL_BENCH.md`](backend/app/chat/RETRIEVAL_BENCH.md)
- Mining method comparison: [`backend/mining/COMPARISON.md`](backend/mining/COMPARISON.md)
- Evaluation report (generated): [`evaluation/EVALUATION.md`](evaluation/EVALUATION.md)
- User guides: [`docs/`](docs/) — clinician, patient, demo script, architecture

---

## Architecture

```
 ┌──────────────┐        ┌───────────────────────────────────────────────┐
 │ React web UI │───────▶│  FastAPI backend  (backend/app, port 8000)    │
 │ Vite :5173   │  /api  │  /patients /rules/run /envelopes /plans       │
 │ clinician +  │        │  /chat /mining /kb /adherence /dishes         │
 │ patient views│        │  /healthz                                     │
 └──────────────┘        └───┬───────────────┬──────────────┬────────────┘
                   ┌─────────▼──────┐ ┌──────▼───────┐ ┌────▼─────────┐
                   │ Rule engine    │ │ Optimiser    │ │ Mining       │
                   │ rules/ (CLIPS, │ │ backend/optim│ │ backend/min- │
                   │ 61 rules,      │ │ (pymoo NSGA- │ │ ing (trends, │
                   │ salience)      │ │ II + repair) │ │ clusters,    │
                   └───────┬────────┘ └──────┬───────┘ │  subst.)     │
                           │                 │         └──────────────┘
                   ┌───────▼─────────────────▼──────────────────────┐
                   │ Approval gate (APPROVED-only) + trace store    │
                   │ + adherence meal-log store                     │
                   └───────┬────────────────────────────────────────┘
                   ┌───────▼────────────────────────────────────────┐
                   │ Versioned KB (SQLite + NetworkX, in-memory):   │
                   │ 61 rules + 214 SG dishes + citations; BM25     │
                   │ retrieval index for the grounded chatbot       │
                   └────────────────────────────────────────────────┘
```

Data flow: patient → rule engine (PROPOSED envelope + `RuleFire` trace) →
**approval gate** (clinician approve/edit/reject; only `APPROVED` passes) →
optimiser (7-day × 3-meal plan, hard-constraint guarantee) → UI. Patients then
log actual meals (`/adherence/log`) and the adherence summary / deviation
endpoints measure logged reality against the latest envelope. The chatbot
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
│   ├── rules.json               61 rules (guideline-sourced + medication/
│   │                            scope/conflict extensions, 2 internal safety)
│   ├── engine.py                CLIPS forward-chaining engine (run_rules)
│   ├── ENGINE.md                Engine design, conflict resolution, trace
│   ├── example_trace.json       Hand-worked CKD4 + HTN + K⁺ 5.4 trace
│   └── clipspy_facts.py / SCHEMA_DECISION.md / neo4j_schema_design.md
├── backend/
│   ├── app/                     FastAPI service
│   │   ├── main.py              uvicorn entry; CORS; 409 gate handler
│   │   ├── api/                 patients / rules / envelopes / plans / chat /
│   │   │                        mining / kb / adherence / dishes
│   │   ├── adherence/           meal-log store + analysis (per-day totals,
│   │   │                        hard/soft classification, Theil–Sen trends)
│   │   ├── core/                approval_gate, envelope_lifecycle, persistence,
│   │   │                        plan_service, plan_storage, trace_store, kb_loader
│   │   ├── chat/                retrieval (BM25), answers, escalation, llm
│   │   ├── kb/                  versioned graph store (SQLite + NetworkX)
│   │   ├── explain/             clinician + patient explanation views
│   │   └── tests/               API, gate, chat, explain, adherence, e2e tests
│   ├── optim/                   Lane B — meal-plan optimiser
│   │   ├── problem.py / real_data.py / solver.py / api.py
│   │   ├── baselines.py / benchmark.py / benchmark_results.md
│   │   └── envelopes.py / spike_pymoo.py / toy_data.py
│   └── mining/                  trends (Theil–Sen + EWMA), clustering,
│                                renal-weighted substitutions, COMPARISON.md
├── data/                        Lane C — 214 SG dishes, 20 synthetic patients, USDA gap filler
├── frontend/                    React 19 + Vite + Tailwind (6 screens)
├── notebooks/                   Exploration notebooks
├── docs/                        User guides, demo script, architecture
└── evaluation/                  Generated evaluation report (EVALUATION.md)
```

---

## How to run

Prereqs: Python 3.11+ and Node for the frontend. Set up the backend from the
repository root with `uv venv .venv`, then
`uv pip install --python .venv/bin/python -e '.[dev]'`.

### 1. Backend (port 8000)

```bash
# from the repo root
.venv/bin/uvicorn backend.app.main:app --reload --port 8000
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

Approvals, embedded traces, created patients, saved plans, meal logs, observations,
simulations and review actions persist in SQLite (`CARELOOP_APP_DB`, default
`$XDG_STATE_HOME/careloop/careloop_app.sqlite3` or
`~/.local/state/careloop/careloop_app.sqlite3`). Existing checkout databases
require explicit migration; see [storage and deployment guidance](docs/STORAGE.md).
New evaluation and benchmark runs write to ignored `artifacts/` directories,
separate from reviewed, committed reports. Proposal IDs are allocated transactionally.
Production plans use main-plus-optional-side meals and normalised adequacy-first
selection. Hard feasibility and original-target adequacy are reported separately;
nutrient values remain unverified and prices are synthetic estimates.

---

## API surface

| Method | Path | Purpose |
|---|---|---|
| GET | `/healthz` | liveness probe (+ `GET /` service banner) |
| GET | `/patients` | list patients (reads `data/patients.json` + overlay) |
| GET | `/patients/{patient_id}` | fetch one patient (404 if absent) |
| POST | `/patients` | create a patient (durable SQLite profile) |
| POST | `/rules/run` | patient id → PROPOSED `NutrientEnvelope` + `RuleFire` trace |
| GET | `/envelopes/{id}` | fetch an envelope |
| GET | `/envelopes/{id}/explanation` | clinician explanation (trace, conflicts, citations) |
| POST | `/envelopes/{id}/approve` | PROPOSED/EDITED → APPROVED |
| POST | `/envelopes/{id}/edit` | mutate targets → EDITED (re-approval required) |
| POST | `/envelopes/{id}/reject` | → REJECTED |
| POST | `/plans` | 7-day meal plan — **gated**: 409 unless APPROVED |
| POST | `/chat` | grounded Q&A `{answer, citations, escalated, status}` |
| POST | `/adherence/log` | log an actual meal `{patient_id, date, meal, dish_id}` (upsert per slot; 404 on unknown patient/dish) |
| GET | `/adherence/{pid}/summary?days=14` | per-day totals vs the latest envelope — hard violations (MAX exceeded) vs soft gaps (MIN/TARGET shortfalls); `informational_only` when the envelope is not APPROVED |
| GET | `/adherence/{pid}/deviation` | per-nutrient deviation-exposure series + Theil–Sen trend flags (`worsening`/`improving`, `alert`/`review`) |
| GET | `/dishes?category=&search=` | dish catalogue for pickers (category filter + name search) |
| GET | `/dishes/{dish_id}` | one full dish record (404 if absent) |
| GET | `/mining/trends` | rising K⁺/PO₄ flags across the cohort (Theil–Sen + EWMA de-escalation) |
| GET | `/mining/substitutions?dish_id=&k=` | healthier substitute dishes (renal-weighted distance) |
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
4. **Hard constraints are never silently broken.** Hard = approved MAX
   ceilings + exclusions (PLAN.md module 4); MIN floors and targets are soft
   objective terms. The optimiser guarantees `violation_count == 0` (repair →
   greedy fallback); when the pool cannot satisfy a ceiling it returns an
   explicit infeasibility diagnosis, and unreachable MIN floors are lowered
   with a full `relaxed_constraints` disclosure in the plan response. Rulebook
   exclusions map to per-serving dish nutrient thresholds via
   `backend/optim/exclusion_mapping.py`.
5. **Chat is grounded or silent.** Answers are composed only from retrieved KB
   chunks (+ the patient's envelope numbers) and always cite
   `rule_id + guideline + section`; low-confidence questions are refused;
   emergencies, medication questions (including "should I stop taking X?",
   "skip my insulin"), diagnosis/dosing requests and out-of-scope topics are
   escalated. Envelope numbers are quoted only when the envelope is APPROVED
   (PROPOSED → pending-review phrasing; REJECTED → a fixed declined response),
   and internal `CONFLICT-*`/`SAFETY-*` rules never surface as patient-facing
   citation anchors. Retrieval is Okapi BM25 with stopword filtering;
   `MIN_SCORE = 2.0` keeps the refusal gate meaningful
   (`backend/app/chat/RETRIEVAL_BENCH.md`).
6. **Versioning is append-only.** Every KB node/edge carries `valid_from` /
   `valid_to`; nothing is deleted.
7. **Clinical safety.** Out-of-scope patients (pregnancy, paediatric, dialysis,
   eGFR < 15) are `REJECTED` with `exclude_from_careloop=true` and never reach
   the optimiser. Approving a REJECTED or empty-target envelope is refused with
   `HTTP 422 {"error": "out_of_scope_envelope"}`; re-running the rule engine
   mints a fresh envelope id (`ENV-<pid>-002`, ...) instead of overwriting a
   prior one, so approvals survive; clinician edits append an explicit
   `CLINICIAN-EDIT` trace row so edited numbers never claim rule provenance.

---

## Tests

```bash
.venv/bin/python -m pytest rules/ -q           # rule engine suite
.venv/bin/python -m pytest backend -q          # API, gate, chat, explain, adherence, e2e
.venv/bin/python -m pytest backend/mining -q   # trends / clustering / substitutions
.venv/bin/python backend/optim/test_real.py    # optimiser on the real dish pool
.venv/bin/python -m shared.export_schema --check
npm --prefix frontend test                   # frontend race and contract regressions
```
