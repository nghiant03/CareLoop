# CareLoop Architecture

Concise module/dependency write-up. The full historical plan (team allocation,
week-by-week scope) lives in `PLAN.md`; this document is self-contained and
describes the system as built.

## 1. The envelope contract is the hub

Every module speaks one data shape: the **nutrient envelope**
(`shared/envelope_schema.py`, Pydantic v2, mirrored as
`shared/envelope_schema.json`). It carries:

- `targets[]` — per-nutrient constraints (`MAX` / `MIN` / `TARGET`, canonical
  units from `NutrientKind`),
- `exclusions[]` — hard exclusions (`ingredient`, `dish_category`,
  `macro_pattern`, `diet_pattern`),
- `status` — `PROPOSED → APPROVED / EDITED / REJECTED` lifecycle,
- `citations[]` + `fired_rules[]` — per-rule provenance (`RuleFire` rows:
  rule id, priority, guideline, section, quote, action summary),
- `patient_snapshot` — the patient state the envelope was computed from.

Rules:

- Engine, optimiser and API all import the schema from `shared/`; the backend
  `models/` package only re-exports it.
- Per-kg guideline rules (protein g/kg/d, energy kcal/kg/d) are expanded to
  absolute grams/kcal by the engine, not carried as coefficients.
- Per-constraint provenance is carried by the fired rule's citation plus the
  trace row's `action_summary` (`[guideline / section]` attribution), a
  deliberate consequence of the frozen constraint schema.

## 2. The approval gate invariant

> Only `APPROVED` envelopes may be consumed downstream (optimiser, RAG chat,
> patient-facing views).

Enforced in the API layer (`backend/app/core/approval_gate.py`), not by
convention:

- `POST /rules/run` produces a `PROPOSED` envelope and stores it in
  `ENVELOPE_STORE` (process-local dict behind a lock).
- Clinician actions move it: `/approve → APPROVED`, `/edit → EDITED` (clears
  approval; re-approval required), `/reject → REJECTED`.
- Downstream endpoints depend on `require_approved_envelope` (path-keyed) or
  `require_approved_envelope_for_patient` (body-keyed, used by `/plans`).
  Non-APPROVED status raises `EnvelopeNotApprovedError`, rendered by `main.py`
  as `HTTP 409 {"error": "envelope_not_approved", "status": "..."}`.
- The rule engine itself rejects out-of-scope patients (pregnancy, paediatric,
  dialysis, ketoacid-risk) as `REJECTED` with no nutrient targets — they never
  reach the gate or the optimiser.

The gate contract is storage-agnostic: `trace_store.py` pins each envelope's
`RuleFire` trace beside it so `/envelopes/{id}/explanation` reconstructs the
decision exactly as proposed. Both stores are process-local; swapping in a
persistent backing table does not change the contracts.

## 3. Versioned knowledge base

`backend/app/kb/graph_store.py` loads `rules/rules.json` + `data/dishes.json`
into a graph on an **in-memory SQLite** database (the recorded prototype
decision; `rules/SCHEMA_DECISION.md`) with NetworkX for graph queries.

- Node/edge kinds: `Guideline → Section → Rule → NutrientConstraint`,
  `Diagnosis`, `ExclusionFlag`, `Dish → NutrientProfile` (~52 rules, 190 dishes,
  ~600 edges; see `GET /kb/stats`).
- **Append-only versioning**: every row has `valid_from` and, when superseded,
  `valid_to` — history is never deleted, and "current" means `valid_to IS NULL`.
- `core/kb_loader.py` builds the KB once per process (warmed at startup, lazy
  fallback on failure) and caches a **TF-IDF retrieval index**
  (`chat/retrieval.py`) over citable chunks: one per rule (guideline, section,
  verbatim quote, constraint actions + plain-language nutrient synonyms) and
  one per dish.

## 4. End-to-end data flow

```
patient ──▶ rules.run_rules ──▶ PROPOSED envelope + RuleFire trace
                │ CLIPS forward-chaining, salience conflicts,
                │ SUPERSEDED markers, scope gates (REJECTED)
                ▼
        clinician gate (approve / edit / reject)          409 ◀── /plans (not approved)
                │ APPROVED only
                ▼
        plan_service.prepare_envelope_for_pool
                │ lowers provably-unreachable MIN floors,
                │ discloses them in relaxed_constraints
                ▼
        optim.api.run (pymoo NSGA-II)
                │ repair → greedy fallback ⇒ violation_count == 0
                │ or explicit infeasibility diagnosis
                ▼
        map_plan_result ──▶ UI: days → slots / totals-vs-targets
                            + patient explanation (+ relaxation notes)
```

- **Rule engine** (`rules/engine.py`): CLIPS forward-chaining decides *which*
  rules fire (salience = documented priority scale, CKD 90 > safety 88 >
  hyperkalaemia 85 > CKD 80 > DASH 70 > ADA 60 > generic 50); Python assembly
  decides *what the envelope looks like* (per-kg scaling, conflict resolution
  per `(nutrient, kind)` — higher priority wins, ties to the stricter value;
  losers keep their trace rows with a `SUPERSEDED: superseded by <rule>` marker).
  Deterministic: fixed engine clock, total tie-breaks, sorted output.
- **Optimiser** (`backend/optim/`): decision vars are 21 meal slots
  (7 days × 3 meals, multi-dish allowed); 4 objectives (nutrient deviation,
  preference, variety, cost); hard daily MAX/MIN constraints + exclusions.
  `run()` never returns a violating plan: NSGA-II front → `repair_plan` →
  greedy construction; if the pool provably cannot satisfy the envelope the
  result is `feasible=false` + `infeasibility_reason`. Benchmarks and engine
  choices: `backend/optim/benchmark_results.md`.
- **Mining** (`backend/mining/`): read-only over the dataset — Theil–Sen K⁺/PO₄
  trend flags, k-means cohort clustering, nutrient-distance substitutions.
- **Explanation views** (`backend/app/explain/views.py`): pure functions turning
  an envelope (+ optional day-1 totals) into the clinician explanation
  (trace, conflict resolutions) and the patient explanation (plain-language
  daily targets, "why" bullets citing guidelines, avoid-list, relaxation notes).

## 5. Chat grounding path

`POST /chat` (`chat/answers.answer`) is a deterministic pipeline; the optional
LLM adapter only rephrases an already-grounded answer:

1. **Escalation filter** (`chat/escalation.py`, regex-only, deliberately
   conservative): emergencies, diagnosis requests, medication/dosing changes and
   out-of-scope topics are escalated — never answered.
2. **Retrieval** (`chat/retrieval.py`): TF-IDF over the versioned KB chunks;
   cosine score below `MIN_SCORE` counts as no match.
3. **Composition**: the answer is assembled only from retrieved chunk text plus
   the patient's latest envelope numbers; templates pick sentences, nothing
   invents facts. Envelope context honours the approval gate — a non-APPROVED
   envelope is surfaced transparently with a "not approved yet" notice.
4. **Citation invariant**: every `answered` response carries at least one
   citation (`rule_id`, `guideline`, `section`); if no rule can be cited, the
   answer is refused instead.
5. **Low-confidence refusal**: no nutrient detected + best score below
   threshold → refuse and point to the clinician.

## 6. Module dependency map

| Module | Depends on | Provides |
|---|---|---|
| `shared/` | — | envelope + trace contracts (Pydantic + JSON Schema) |
| `rules/` | `shared/` | `run_rules(patient) → {envelope, trace}` (CLIPS) |
| `data/` | `shared/` | 190 dishes, 20 patients, generator, USDA filler |
| `backend/optim/` | `shared/` | `run(envelope) → feasible plan` (pymoo + repair) |
| `backend/mining/` | `data/` | trends / clustering / substitutions |
| `backend/app/kb/` | `rules/`, `data/` | versioned KBGraph (+ stats) |
| `backend/app/chat/` | `kb/`, `approval_gate`, `llm_choice` | grounded, cited Q&A |
| `backend/app/core/` | `shared/`, `kb/`, `optim/`, `explain/` | gate, stores, plan service |
| `backend/app/api/` | all of the above | the REST surface |
| `frontend/` | REST API (`/api` proxy) | clinician / patient / chat screens |
| `evaluation/` | everything | generated report (`EVALUATION.md`) |

## 7. Known runtime boundaries

- Envelope store, trace store and created patients are process-local; a backend
  restart resets them. The contracts are designed so a persistent store drops in
  without endpoint changes.
- The KB is rebuilt in memory per process from `rules/rules.json` +
  `data/dishes.json`; dish values are manual-curation estimates
  (`verified: false`, see `data/README.md`).
- The dish pool cannot reach some guideline MIN floors (notably fibre); the
  optimiser path lowers them with explicit `relaxed_constraints` disclosure
  rather than failing or silently violating.
