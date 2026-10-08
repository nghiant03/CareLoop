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
- Nutrient constraints can carry explicit `ConstraintProvenance`: the exact
  nutrient, kind, value, unit, envelope identity/version, author, and citation.
  `shared/provenance.py` fills missing provenance from matching trace actions;
  clinician target replacements receive clinician-authored provenance. Embedded
  rule traces retain the supporting decision history.

## 2. The approval gate invariant

> Live planning requires an `APPROVED`, scope-eligible envelope with nonempty
> targets. Personal target guidance requires approval; informational views and
> chat may inspect other lifecycle states without presenting unapproved targets
> as personal guidance.

Enforced in the API layer (`backend/app/core/approval_gate.py`), not by
convention:

- `POST /rules/run` produces a `PROPOSED` or scope-rejected envelope and stores it in
  the SQLite journal (transactionally allocated IDs; durable live authority).
- `core/envelope_lifecycle.py` handles clinician transitions:
  `/approve → APPROVED`, `/edit → EDITED` (clears
  approval; re-approval required), `/reject → REJECTED`. Approving an
  envelope with REJECTED status, false `scope_eligible`, or no nutrient targets
  is refused with `HTTP 422 {"error": "out_of_scope_envelope"}` — scope decisions are not
  overridable through edits or approval. Proposal-owned `scope_eligible` is
  independent of editable notes. Rejected proposals require a fresh rule run.
- `lifecycle_revision` advances on every durable transition. SQLite checks the
  previous revision under a write reservation before appending a snapshot;
  stale updates return HTTP 409 `envelope_conflict`. Clients can also send
  `expected_revision` to detect changes since they viewed the envelope. This
  optional request field preserves older clients; the web UI always sends it.
  `version` remains the content-edit version for compatibility with saved plans.
- Re-running the rule engine for a patient never overwrites an existing
  envelope: `put_envelope` mints the next sequential id (`ENV-<pid>-002`,
  ...) and stamps a fresh `proposed_at`, so prior envelopes — including
  APPROVED ones and their approval history — stay intact.
- Clinician edits append an explicit `CLINICIAN-EDIT` trace row: edited
  numbers carry no rule citations, so chat and explanation views can never
  attribute a human override to a guideline.
- Planning-gated endpoints depend on `require_approved_envelope` (path-keyed) or
  `require_approved_envelope_for_patient` (body-keyed, used by `/plans`).
  Failure of any gate condition raises `EnvelopeNotApprovedError`, rendered by
  `main.py` as `HTTP 409 {"error": "envelope_not_approved", "status": "..."}`.
- The rule engine itself rejects out-of-scope patients (pregnancy, paediatric,
  dialysis — by diagnosis or `CKD_stage_5` — eGFR < 15, ketoacid-risk) as
  `REJECTED` with no nutrient targets — they never reach the gate or the
  optimiser.

The durable envelope's embedded `RuleFire` trace is authoritative for explanations.
`trace_store.py` serializes that trace; legacy side-store data is used only for
inputs lacking an embedded trace, never to override a durable snapshot.

## 3. Versioned knowledge base

`backend/app/kb/graph_store.py` loads `rules/rules.json` + `data/dishes.json`
into a graph on an **in-memory SQLite** database (the recorded prototype
decision; `rules/SCHEMA_DECISION.md`) with NetworkX for graph queries.

- Node/edge kinds: `Guideline → Section → Rule → NutrientConstraint`,
  `Diagnosis`, `ExclusionFlag`, `Dish → NutrientProfile` (~61 rules, 214 dishes,
  ~630 edges; see `GET /kb/stats`).
- **Append-only versioning**: every row has `valid_from` and, when superseded,
  `valid_to` — history is never deleted, and "current" means `valid_to IS NULL`.
- `core/kb_loader.py` builds the KB once per process (warmed at startup, lazy
  fallback on failure) and caches a **BM25 retrieval index**
  (`chat/retrieval.py`) over citable chunks: one per rule (guideline, section,
  verbatim quote, constraint actions + plain-language nutrient synonyms) and
  one per dish. Scoring is Okapi BM25 over stopword-filtered word tokens with
  synonym-expanded queries; scores below `MIN_SCORE = 2.0` count as no match
  (calibrated so stopword-only overlap can never look relevant — rationale and
  the eight-configuration comparison in
  `backend/app/chat/RETRIEVAL_BENCH.md`; the previous TF-IDF scorer remains
  documented there as the revert path).

## 4. End-to-end data flow

```
patient ──▶ rules.run_rules ──▶ PROPOSED envelope + RuleFire trace
                │ CLIPS forward-chaining, salience conflicts,
                │ SUPERSEDED markers, scope gates (REJECTED)
                ▼
        clinician gate (approve / edit / reject)          409 ◀── /plans (not approved)
                │ APPROVED, scope-eligible, nonempty targets
                ▼
        plan_service.plan_meals
                │ prepares MIN floors for the single-dish search,
                │ discloses them in relaxed_constraints
                ▼
        optim.api.run (pymoo NSGA-II) → main/side composition
                │ repair → greedy fallback ⇒ violation_count == 0
                │ or explicit infeasibility diagnosis
                ▼
        map_plan_result ──▶ UI: days → slots / totals-vs-targets
                            + patient explanation (+ relaxation notes)

patient logs actual meals ──▶ adherence.analysis ──▶ per-day totals vs approval
                             (upsert per slot)       effective on the logged date
                                                     (uncovered dates unattributed)
                                                     hard violations vs soft gaps
                                                     + deviation series + flags
```

Plan generation, what-if simulations, and Q3 evaluation share `plan_meals`.
It performs no persistence. `core/plan_storage.py` saves generated/swapped plan
documents, while simulations save only their comparison records.

The adherence loop scores each logged date against the most recent approval
effective on that date. Dates without approval coverage are explicitly
unattributed, never backfilled with today's targets. Only complete days enter
trend calculations and soft-gap aggregates; partial-day hard violations remain visible.

- **Adherence** (`backend/app/adherence/` + `api/adherence.py`): durable SQLite
  meal-log store (multiple dishes and serving quantities per meal, newest save wins) and
  a pure analysis module. `MAX` totals that are exceeded are **hard
  violations** (the same semantics the optimiser treats as unbreakable);
  `MIN` shortfalls and absolute `TARGET` deviations are **soft gaps**. The deviation endpoint builds
  a per-nutrient exposure series (magnitude in the "bad" direction) and flags
  Theil–Sen trends as `worsening`/`improving` with `alert`/`review` severity.
- **Dish catalogue** (`api/dishes.py`): deterministic read-only views over
  `data/dishes.json` (`GET /dishes?category=&search=`, `GET /dishes/{id}`) —
  the searchable picker behind the meal-logging screen.

- **Rule engine** (`rules/engine.py`): CLIPS forward-chaining decides *which*
  rules fire (salience = documented priority scale, CKD 90 > safety 88 >
  hyperkalaemia 85 > CKD 80 > DASH 70 > ADA 60 > generic 50); Python assembly
  decides *what the envelope looks like* (per-kg scaling, conflict resolution
  per `(nutrient, kind)` — higher priority wins, ties to the stricter value;
  losers keep their trace rows with a `SUPERSEDED: superseded by <rule>` marker).
  Deterministic: fixed engine clock, total tie-breaks, sorted output.
- **Optimiser** (`backend/optim/`): decision vars are 21 meal slots
  (7 days × 3 meals, multi-dish allowed); 4 objectives (nutrient deviation,
  preference, variety, cost); hard daily MAX ceilings + exclusions (MIN floors
  and TARGETs are soft objective terms per PLAN.md module 4).
  `run()` never returns a violating plan: NSGA-II front → `repair_plan` →
  greedy construction; if no hard-feasible plan is found, the result is
  `feasible=false` + `infeasibility_reason`. `infeasibility_status` distinguishes
  exact single-dish infeasibility from heuristic search exhaustion; neither
  establishes impossibility for the broader main/side encoding. The feasibility
  guarantee is method-agnostic — every pymoo algorithm comparison runs through
  the same `solve(..., method=, guarantee=)` path (`guarantee=False` for raw
  violation-rate measurement). A 13-row algorithm benchmark (NSGA-II/III,
  MOEA/D, AGE-MOEA, SMSEMOA, plus GA/greedy/random baselines) keeps NSGA-II as
  the production default: SMSEMOA posts the best hypervolume (~+24% over
  NSGA-II) at ~2.5× the runtime, and all guaranteed rows hold 0% violations.
  Benchmarks and engine choices: `backend/optim/benchmark_results.md`.
- **Mining** (`backend/mining/`): analysis over patient observations and fixture
  data, plus substitution validation — K⁺/PO₄ trend flags (Theil–Sen raises
  flags; an EWMA-weighted slope with a 2-month half-life can de-escalate an urgent
  trend when recent months flatten, but not an urgent latest dated observation, exposed
  as `ewma_slope_per_month`), k-means cohort clustering, renal-weighted
  substitution ranking (sodium/potassium/phosphorus count double). Method
  choices and comparisons: `backend/mining/COMPARISON.md`.
- **Explanation views** (`backend/app/explain/views.py`): pure functions turning
  an envelope (+ optional day-1 totals) into the clinician explanation
  (trace, conflict resolutions) and the patient explanation (plain-language
  daily targets, "why" bullets citing guidelines, avoid-list, relaxation notes).

## 5. Chat grounding path

`POST /chat` (`chat/answers.answer`) is a deterministic pipeline; the optional
LLM adapter only rephrases an already-grounded answer:

1. **Escalation filter** (`chat/escalation.py`, regex-only, deliberately
   conservative): emergencies (including metabolic emergencies such as
   ketoacidosis signs and extreme glucose readings), diagnosis requests,
   medication changes — including drug-name phrasings like *"should I stop
   taking metformin?"* or *"skip my insulin"* — and out-of-scope topics are
   escalated — never answered.
2. **Retrieval** (`chat/retrieval.py`): Okapi BM25 over the versioned KB
   chunks (stopword-filtered tokens + nutrient synonym expansion); a score
   below `MIN_SCORE = 2.0` counts as no match.
3. **Composition**: the answer is assembled only from retrieved chunk text plus
   the patient's latest envelope numbers; templates pick sentences, nothing
   invents facts. Envelope context honours the approval gate: an APPROVED
   envelope's numbers may be quoted; a PROPOSED/EDITED envelope gets
   pending-review phrasing with no numbers; a REJECTED envelope gets a fixed
   declined response regardless of the question. Internal rule families
   (`CONFLICT-*`, `SAFETY-*`) are excluded from patient-facing citation
   anchors.
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
| `data/` | `shared/` | 214 dishes, 20 patients, generator, USDA filler |
| `backend/optim/` | `shared/` | `run(envelope) → feasible plan` (pymoo + repair; `solve(method=, guarantee=)` for algorithm comparisons) |
| `backend/mining/` | `data/` | trends (Theil–Sen + EWMA) / clustering / substitutions |
| `backend/app/kb/` | `rules/`, `data/` | versioned KBGraph (+ stats) |
| `backend/app/chat/` | `kb/`, `approval_gate`, `llm_choice` | grounded, cited Q&A (BM25 retrieval) |
| `backend/app/adherence/` | `optim.real_data` (dish pool), `approval_gate` | meal-log store + summary/deviation analysis |
| `backend/app/core/` | `shared/`, `kb/`, `optim/`, `explain/` | gate, stores, plan service |
| `backend/app/api/` | all of the above | the REST surface |
| `frontend/` | REST API (`/api` proxy) | clinician / patient / chat / adherence screens |
| `evaluation/` | everything | generated report (`EVALUATION.md`) |

## 7. Known runtime boundaries

- Clinical state survives restart in SQLite, selected by `CARELOOP_APP_DB`.
  Timestamped observations overlay profiles and feed rules and lab trends.
  Observations never automatically approve a new envelope.
- Adherence windows and journal effective dates use the server's local date.
  Logged dates have no timezone; UTC window boundaries are not enforced.
- The KB is rebuilt in memory per process from `rules/rules.json` +
  `data/dishes.json`; dish values are manual-curation estimates
  (`verified: false`, see `data/README.md`).
- Production main/side composition uses normalised original-target adequacy.
  Main/side eligibility is heuristic; constrained patients may retain shortfalls.
  The single-dish fallback discloses soft-floor relaxation when used.
