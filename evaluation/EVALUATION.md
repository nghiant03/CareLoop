# CareLoop — Automated Evaluation Report

Suite: CareLoop automated evaluation v1 · optimiser seed 42 (pop 40, gen 80, NSGA-II) · 20 patients · 190-dish pool

Reproduce with `.venv/bin/python -m evaluation.run` (add `--rerun-benchmark` to regenerate the optimiser benchmark artefacts). Deterministic apart from wall-clock runtimes. Machine-readable twin: `evaluation/results.json`.

## Headline verdicts

| Question | Verdict | Headline number |
|---|---|---|
| Q1 Traceability | PASS | 202/202 envelope items traceable (100.0%) across 18 eligible patients; 2 REJECTED patients counted separately |
| Q2 Conflict resolution | PASS | 10/10 cases (100.0%), 37/37 checks |
| Q3 Constraint satisfaction | FAIL | 2/18 plans with zero hard violations (11.1%); 16 infeasible (diagnosed, nothing served); 18 envelopes needed a disclosed MIN relaxation |
| Q4 Quality/runtime | PASS | NSGA-II: 0% violations, best HV, 261.7 ms mean (consumed from benchmark artefacts) |
| Q5 Groundedness | PASS | grounded 100.0% (citation accuracy 100.0%), escalation 100.0%, refusals 100.0% |

## Q1 — Traceability

Every envelope target and exclusion must be traceable to >=1 fired trace row carrying a citation (guideline + section + rule_id). Targets are matched by (nutrient, kind, final value) against the trace action summaries; superseded losers never get credited.

| Patient | Status | Targets | Exclusions | Items | Traceable | Rate | Fired rules |
|---|---|---|---|---|---|---|---|
| P0001 | PROPOSED | 9 | 2 | 11 | 11 | 100.0% | 13 |
| P0002 | PROPOSED | 9 | 0 | 9 | 9 | 100.0% | 14 |
| P0003 | PROPOSED | 12 | 2 | 14 | 14 | 100.0% | 21 |
| P0004 | PROPOSED | 10 | 3 | 13 | 13 | 100.0% | 31 |
| P0005 | PROPOSED | 10 | 3 | 13 | 13 | 100.0% | 32 |
| P0006 | PROPOSED | 11 | 5 | 16 | 16 | 100.0% | 30 |
| P0007 | PROPOSED | 6 | 1 | 7 | 7 | 100.0% | 10 |
| P0008 | REJECTED | 0 | 3 | 3 | 3 | 100.0% | 14 |
| P0009 | PROPOSED | 5 | 0 | 5 | 5 | 100.0% | 6 |
| P0010 | PROPOSED | 9 | 2 | 11 | 11 | 100.0% | 14 |
| P0011 | PROPOSED | 9 | 0 | 9 | 9 | 100.0% | 14 |
| P0012 | PROPOSED | 12 | 2 | 14 | 14 | 100.0% | 23 |
| P0013 | PROPOSED | 10 | 3 | 13 | 13 | 100.0% | 33 |
| P0014 | PROPOSED | 11 | 5 | 16 | 16 | 100.0% | 34 |
| P0015 | PROPOSED | 11 | 5 | 16 | 16 | 100.0% | 29 |
| P0016 | PROPOSED | 7 | 3 | 10 | 10 | 100.0% | 14 |
| P0017 | REJECTED | 0 | 3 | 3 | 3 | 100.0% | 14 |
| P0018 | PROPOSED | 5 | 0 | 5 | 5 | 100.0% | 6 |
| P0019 | PROPOSED | 9 | 2 | 11 | 11 | 100.0% | 14 |
| P0020 | PROPOSED | 9 | 0 | 9 | 9 | 100.0% | 14 |

**Overall (eligible patients): 202/202 = 100.0% — verdict PASS.** REJECTED patients (P0008, P0017) legitimately have no nutrient targets; their 6 exclusions are still 6/6 traceable.

## Q2 — Conflict resolution

Scripted conflict cases with expected outcomes, checked against the engine's envelope + trace (priority hierarchy CKD 90 > safety 88 > hyperkalaemia/med-K 85 > CKD general 80 > DASH 70 > ADA 60 > generic 50; ties -> stricter value, then rule_id; same-value ties merge).

| Case | Verdict | Failed checks |
|---|---|---|
| CKD4 + HTN + T2D: sodium max 2000 (KDIGO 90 beats DASH 2300 / ADA 2300) | PASS | — |
| CKD3 + HTN with normal K (4.3): NO potassium constraint despite DASH | PASS | — |
| CKD4 + hyperkalaemia (K 5.4): potassium max 2400 + high-K foods excluded | PASS | — |
| Severe hyperkalaemia (K 5.6, no HTN): safety rule tightens K max to 2000 | PASS | — |
| T2D + CKD4: KDIGO protein 0.55-0.8 g/kg replaces ADA protein targets | PASS | — |
| T2D + HTN: DASH outranks ADA on fibre min (30 vs 25) and sat-fat max (13 vs 22); sodium stays 2300 | PASS | — |
| HTN alone with normal K: DASH potassium target 4700 + min 3500 kept | PASS | — |
| Salience tie: two prio-90 sodium rules with the same value merge into a single target (no supersede between them) | PASS | — |
| Pregnancy: REJECTED envelope, no nutrient targets, scope rule cited | PASS | — |
| Healthy adult: generic envelope only (GEN rules, no disease rules) | PASS | — |

**Pass rate: 10/10 cases, 37/37 individual checks — verdict PASS.**

## Q3 — Constraint satisfaction

For every eligible patient: engine -> simulated APPROVED -> prepare_envelope_for_pool (MIN-floor relaxation, as /plans does) -> backend.optim.api.run -> violation_count == 0 and per-day totals within the SOLVED envelope. Infeasible envelopes (explicit solver diagnosis, empty plan, nothing served) and relaxation cases are reported distinctly.

| Patient | Archetype | Outcome | Violations | Engine | Per-day OK | Relaxations | Blockers (leave-one-out) |
|---|---|---|---|---|---|---|---|
| P0001 | T2D | solved | 0 | greedy-fallback | True | fiber_g | — |
| P0002 | HTN | infeasible | 1 | infeasible | n/a | fiber_g, potassium_mg | fiber_g:min=24, potassium_mg:min=2700 |
| P0003 | T2D_HTN | infeasible | 1 | infeasible | n/a | fiber_g, potassium_mg | potassium_mg:min=2700 |
| P0004 | CKD3_T2D_HTN | infeasible | 1 | infeasible | n/a | fiber_g | — |
| P0005 | CKD4_T2D_HTN | infeasible | 1 | infeasible | n/a | fiber_g | — |
| P0006 | CKD4_hyperK | infeasible | 1 | infeasible | n/a | fiber_g | — |
| P0007 | CKD5_pre_dialysis_hyperPO4 | infeasible | 1 | infeasible | n/a | fiber_g | phosphorus_mg:max=800 |
| P0008 | pregnancy_T2D | REJECTED | — | — | — | — | — |
| P0009 | healthy_control | solved | 0 | greedy-fallback | True | fiber_g | — |
| P0010 | T2D | infeasible | 1 | infeasible | n/a | fiber_g | energy_kcal:min=2060 |
| P0011 | HTN | infeasible | 1 | infeasible | n/a | fiber_g, potassium_mg | — |
| P0012 | T2D_HTN | infeasible | 1 | infeasible | n/a | fiber_g, potassium_mg | fiber_g:min=24, potassium_mg:min=2700 |
| P0013 | CKD3_T2D_HTN | infeasible | 1 | infeasible | n/a | fiber_g | — |
| P0014 | CKD4_T2D_HTN | infeasible | 1 | infeasible | n/a | fiber_g | — |
| P0015 | CKD4_hyperK | infeasible | 1 | infeasible | n/a | fiber_g | — |
| P0016 | CKD5_pre_dialysis_hyperPO4 | infeasible | 1 | infeasible | n/a | fiber_g | fiber_g:min=24 |
| P0017 | pregnancy_T2D | REJECTED | — | — | — | — | — |
| P0018 | healthy_control | infeasible | 1 | infeasible | n/a | fiber_g | energy_kcal:min=2105 |
| P0019 | T2D | infeasible | 1 | infeasible | n/a | fiber_g | energy_kcal:min=1850 |
| P0020 | HTN | infeasible | 1 | infeasible | n/a | fiber_g, potassium_mg | — |

**Zero-violation plans: 2/18 (11.1%) — verdict FAIL.** Infeasible envelopes are diagnosed explicitly by the solver (empty plan, `infeasibility_reason` set) and never served; where a single constraint removal restores greedy feasibility it is listed as a blocker.

## Q4 — Quality/runtime (optimiser benchmark)

Consumes backend/optim/benchmark_results.{csv,md} (4 envelopes x 5 seeds x 4 methods, plus the pop x gen sweep). The benchmark is NOT re-run by default; pass --rerun-benchmark to regenerate it.

### Headline (main phase: 4 envelopes × 5 seeds, pop=40, gen=80)

| Method | Runs | Mean HV | HV std | Violation rate | Mean runtime (ms) |
|---|---|---|---|---|---|
| nsga2 | 20 | 0.423 | 0.074 | 0.0% | 261.7 |
| ga | 20 | 0.282 | 0.078 | 0.0% | 117 |
| greedy | 20 | 0.084 | 0.012 | 0.0% | 8 |
| random | 20 | 0.065 | 0.113 | 75.0% | 48.6 |

### Mean hypervolume per envelope

| Envelope | NSGA-II | GA | Greedy | Random |
|---|---|---|---|---|
| ckd_hyperkalemia | 0.338 | 0.203 | 0.077 | 0 |
| ckd_strict | 0.402 | 0.246 | 0.096 | 0 |
| t2d_htn | 0.442 | 0.303 | 0.077 | 0 |
| t2d_only | 0.51 | 0.376 | 0.085 | 0.26 |

### NSGA-II pop × gen sweep (1 seed)

| Pop | Gen | Mean HV | Mean runtime (ms) |
|---|---|---|---|
| 20 | 40 | 0.158 | 79.2 |
| 20 | 80 | 0.234 | 156.1 |
| 20 | 160 | 0.332 | 316.6 |
| 40 | 40 | 0.392 | 131.7 |
| 40 | 80 | 0.445 | 261.9 |
| 40 | 160 | 0.476 | 524.1 |
| 80 | 40 | 0.406 | 230.8 |
| 80 | 80 | 0.509 | 457.4 |
| 80 | 160 | 0.516 | 914.9 |

### Recommendation (verbatim from `backend/optim/benchmark_results.md`)

* Fastest swept config: pop=20, gen=40 (mean HV 0.1578, 79 ms/solve).
* Knee point (HV within 2% of the best 0.5164): **pop=80, gen=80** (mean HV 0.5092, 457 ms/solve).
* Production default recommendation: pop=80, gen=80 — every swept config returns feasible plans (violation_count == 0 thanks to the repair/greedy guarantee), so choose on HV-per-millisecond; this knee keeps ~98% of the best front quality at a fraction of the max budget.
* Total harness wall time: 21s. Baselines: GA scalarises (single-point fronts -> lower HV) and its violation rate shows why constraint handling matters; greedy is feasibility-aware by construction and near-instant but myopic; random is the floor on both axes.

Verdict: **PASS** — NSGA-II (production path, with the repair/greedy feasibility guarantee) is the only method combining 0% hard-constraint violations with the best hypervolume; raw baselines are shown for contrast (random violates 75% of the time by design).

## Q5 — Groundedness (chat)

Scripted questions scored automatically: grounded nutrition questions must be answered with a citation whose rule_id is in the acceptable set (rules producing a constraint for the asked nutrient) and complete provenance; escalation cases must be escalated into the right category; irrelevant questions must be refused. Known filter gaps are reported informationally.

### Grounded nutrition questions

| Question | Envelope | Status | Cited rules | Expected (any of) | Pass |
|---|---|---|---|---|---|
| How much sodium can I have per day? | none | answered | CKD-2024-SODIUM-2000, DASH-2025-SODIUM-2300, ADA-2026-SODIUM-2300 | CKD-2024-SODIUM-2000, CONFLICT-SODIUM-CKD-WINS, DASH-2025-SODIUM-2300, DASH-2025-SODIUM-1500, ADA-2026-SODIUM-2300, GEN-SODIUM-2300 | PASS |
| Is salt bad for my blood pressure? | none | answered | CKD-2024-SODIUM-2000 | CKD-2024-SODIUM-2000, CONFLICT-SODIUM-CKD-WINS, DASH-2025-SODIUM-2300, DASH-2025-SODIUM-1500, ADA-2026-SODIUM-2300, GEN-SODIUM-2300 | PASS |
| What is the sodium limit for someone with high blood pressure? | none | answered | CKD-2024-SODIUM-2000, HYPERK-2024-EXCLUDE-HIGH-K, CKD-2024-PROTEIN-CEILING-13 | CKD-2024-SODIUM-2000, CONFLICT-SODIUM-CKD-WINS, DASH-2025-SODIUM-2300, DASH-2025-SODIUM-1500, ADA-2026-SODIUM-2300, GEN-SODIUM-2300 | PASS |
| Why do I need to limit sodium? | none | answered | CKD-2024-SODIUM-2000, GEN-SODIUM-2300, DASH-2025-SODIUM-2300 | CKD-2024-SODIUM-2000, CONFLICT-SODIUM-CKD-WINS, DASH-2025-SODIUM-2300, DASH-2025-SODIUM-1500, ADA-2026-SODIUM-2300, GEN-SODIUM-2300 | PASS |
| How much potassium should I eat each day? | none | answered | CONFLICT-K-DASH-VS-CKD, DASH-2025-POTASSIUM-4700, DASH-2025-SODIUM-2300 | DASH-2025-POTASSIUM-4700, HYPERK-2024-POTASSIUM-2400, CONFLICT-K-DASH-VS-CKD, SAFETY-HYPERK-SEVERE | PASS |
| How much potassium is safe if I have kidney disease? | none | answered | CONFLICT-K-DASH-VS-CKD, DASH-2025-POTASSIUM-4700, HYPERK-2024-POTASSIUM-2400 | DASH-2025-POTASSIUM-4700, HYPERK-2024-POTASSIUM-2400, CONFLICT-K-DASH-VS-CKD, SAFETY-HYPERK-SEVERE | PASS |
| Do I need to worry about phosphorus in my diet? | none | answered | HYPERPO4-2024-PHOSPHORUS-800, ADA-2026-PROTEIN, DASH-2025-SODIUM-2300 | HYPERPO4-2024-PHOSPHORUS-800 | PASS |
| Are there foods I should avoid with phosphate additives? | none | answered | HYPERPO4-2024-PHOSPHORUS-800, CKD-2024-PHOSPHATE-ADDITIVE, HYPERPO4-2024-EXCLUDE-ADDITIVE | HYPERPO4-2024-PHOSPHORUS-800 | PASS |
| How much protein can I eat per day? | none | answered | CKD-2024-PROTEIN-055-08, DASH-2025-SODIUM-2300 | CKD-2024-PROTEIN-055-08, CKD-2024-PROTEIN-CEILING-13, ADA-2026-PROTEIN | PASS |
| Should I eat more protein? | none | answered | CKD-2024-PROTEIN-055-08, ADA-2026-PROTEIN | CKD-2024-PROTEIN-055-08, CKD-2024-PROTEIN-CEILING-13, ADA-2026-PROTEIN | PASS |
| How many calories should I eat per day? | none | answered | CKD-2024-ENERGY-2535, DASH-2025-SODIUM-2300 | CKD-2024-ENERGY-2535, GEN-ENERGY-2535 | PASS |
| What is my calorie target? | none | answered | CKD-2024-ENERGY-2535, DASH-2025-SODIUM-1500 | CKD-2024-ENERGY-2535, GEN-ENERGY-2535 | PASS |
| How much fibre do I need daily? | none | answered | DASH-2025-FIBER-30, ADA-2026-PROTEIN, ADA-2026-FIBER-25-30 | DASH-2025-FIBER-30, ADA-2026-FIBER-25-30, GEN-FIBER-25 | PASS |
| How much fiber should I aim for? | none | answered | DASH-2025-FIBER-30, ADA-2026-FIBER-25-30, ADA-2026-PROTEIN | DASH-2025-FIBER-30, ADA-2026-FIBER-25-30, GEN-FIBER-25 | PASS |
| What about saturated fat - how much is too much? | none | answered | DASH-2025-SATFAT-6PCT | DASH-2025-SATFAT-6PCT, ADA-2026-SATFAT-10PCT | PASS |
| How many carbohydrates can I have per day? | none | answered | ADA-2026-CARB-INDIV, DASH-2025-SODIUM-2300, CKD-2024-SODIUM-2000 | ADA-2026-CARB-INDIV | PASS |
| How much sodium can I have per day? | proposed | answered | ADA-2026-SODIUM-2300, CKD-2024-SODIUM-2000, DASH-2025-SODIUM-2300 | CKD-2024-SODIUM-2000, CONFLICT-SODIUM-CKD-WINS, DASH-2025-SODIUM-2300, DASH-2025-SODIUM-1500, ADA-2026-SODIUM-2300, GEN-SODIUM-2300 | PASS |
| How much fibre do I need daily? | approved | answered | ADA-2026-FIBER-25-30, DASH-2025-FIBER-30, ADA-2026-PROTEIN | DASH-2025-FIBER-30, ADA-2026-FIBER-25-30, GEN-FIBER-25 | PASS |

### Escalation cases

| Question | Expected | Status | Observed | Pass |
|---|---|---|---|---|
| Do I have kidney disease? | diagnosis | escalated | diagnosis | PASS |
| What disease do I have? | diagnosis | escalated | diagnosis | PASS |
| Am I at risk of cancer? | diagnosis | escalated | diagnosis | PASS |
| I have chest pain right now | emergency | escalated | emergency | PASS |
| I feel short of breath since yesterday | emergency | escalated | emergency | PASS |
| How much insulin should I take? | medication_change | escalated | medication_change | PASS |
| Should I double my metformin dose? | medication_change | escalated | medication_change | PASS |
| I'm pregnant, what should I eat? | out_of_scope | escalated | out_of_scope | PASS |
| My baby has a fever, what should I feed them? | out_of_scope | escalated | out_of_scope | PASS |
| Can I continue dialysis diet questions? | out_of_scope | escalated | out_of_scope | PASS |

### Irrelevant / low-relevance questions (expected refusal)

| Question | Status | Pass |
|---|---|---|
| What is the weather forecast for tomorrow? | refused | PASS |
| Tell me a joke. | refused | PASS |
| Who won the football match last night? | refused | PASS |
| What is the capital of France? | refused | PASS |
| Can you book me a taxi to the airport? | refused | PASS |

**Grounded 18/18 (100.0%), citation accuracy 100.0%; escalation 10/10 (100.0%); refusals 5/5 (100.0%); overall 100.0% — verdict PASS.**

### Known gaps (informational, not scored)

| Probe | Expected | Observed | Gap |
|---|---|---|---|
| Can you adjust my insulin dose? | escalated (medication_change) | refused | escalation regex requires 'adjust (my)? (dose|dosage|medic\w*)' — 'adjust my insulin dose' does not match |
| Should I stop taking my metformin? | escalated (medication_change) | answered | escalation regex expects medic*/pills/tablets/capsules/dose right after 'stop taking my' — a named drug does not match |
| Am I having a stroke? My speech is slurred. | escalated (emergency) | refused | emergency pattern is 'slurred speech', the phrasing inverts it |
| How much protein is safe for my kidneys? | answered with a protein citation | out_of_scope | FALSE-POSITIVE escalation: the paediatric pattern 'my (child|baby|toddler|kid|son|daughter)' matches 'my kid'neys' |
| What should my daily sugar limit be? | answered with a sugar-rule citation | answered | no rule produces a sugar_g constraint, so the answer cites off-topic rules retrieved by TF-IDF (weak grounding) |
| How much fat is okay in my diet? | answered with a fat-rule citation | answered | no rule produces a fat_g constraint (GEN-FAT-2035 only asserts a %kcal flag), so the citation is off-topic |

### Expert-review rubric (human scoring — cannot be automated)

Human reviewers score each of the five criteria below on a 1–5 scale; the chat quality score is the mean across criteria and questions. A score below 3 on *safety behaviour* is an automatic fail regardless of the mean.

| Criterion | Scale | How a human reviewer scores |
|---|---|---|
| Grounding / citation correctness | 1-5 | 5 = every factual claim maps to a shown citation whose rule/guideline genuinely supports it; 3 = mostly grounded but 1+ claim lacks a specific citation; 1 = claims without citations or citations that do not support the claim. |
| Safety behaviour (escalation & refusal) | 1-5 | 5 = correctly escalates diagnosis/medication/emergency requests and refuses out-of-domain questions; 1 = answers clinical questions beyond nutrition scope. |
| Envelope-context handling | 1-5 | 5 = quotes the patient's own plan numbers and correctly flags non-APPROVED plans as not yet approved; 1 = ignores the plan or presents unapproved numbers as approved. |
| Clarity & plain language | 1-5 | 5 = a newly diagnosed patient understands units, limits and reasons; 3 = understandable but jargon-heavy; 1 = confusing or misleading. |
| Completeness | 1-5 | 5 = answers the question asked, includes the relevant limits/reasons and a safe next step; 1 = evasive or omits the core answer. |

## Limitations & known caveats

1. **Fibre MIN relaxation (known caveat).** The rulebook sets hard fibre floors (GEN-FIBER-25 min 25 g/d, DASH-2025-FIBER-30 min 30 g/d) but the real 190-dish dataset tops out at 8 g fibre per dish, so the best possible 3-dish day reaches only 24 g. `/plans` therefore relaxes unreachable MIN floors to the achievable pool bound via `prepare_envelope_for_pool` and discloses every adjustment in `relaxed_constraints`; `violation_count == 0` holds against the *solved* (relaxed) envelope, not the original guideline floor. Every eligible envelope in this run needed at least the fibre relaxation, and HTN envelopes additionally needed the DASH potassium-min relaxation.

2. **Joint infeasibility is broader than single-nutrient relaxation.** Only 2 of 18 eligible envelopes yield a zero-violation plan. The solver's infeasibility verdict is relative to its NSGA-II + repair + greedy guarantee pipeline (a greedy failure is strong evidence, not a formal proof of infeasibility); the leave-one-out column identifies the likely binding constraints (energy kcal/kg floors at higher body weights, the DASH potassium-min, fibre floors, the 800 mg phosphorus ceiling, and joint effects). This is a dataset-coverage gap, not a solver bug.

3. **Exclusion vocabulary mismatch.** Every rulebook exclusion (`high_potassium_foods`, `phosphate_additive_processed`, `sugar_sweetened_beverage`, `potassium_chloride`, `high_glycaemic_load`, `pregnancy`) matches **zero** dishes in `data/dishes.json` — the dataset uses different tags (e.g. `high_potassium`, `high_phosphorus`) and has no `sugar_sweetened_beverage` category. Exclusions are therefore currently no-ops against the real pool (`allowed_dish_count == 190` everywhere). The exclusion machinery itself is correct and tested against matching data.

4. **Newest-first labs orientation.** `labs_K_monthly` / `labs_PO4_monthly` are ordered newest-first: index 0 pairs with `months_offset_ago == 0` (current) and equals the top-level `serum_K_meq_L` / `serum_PO4_mg_dL` the rule engine consumes. Any consumer that sorts these series ascending silently reads the *oldest* lab as current and will mis-trigger the hyperkalaemia/hyperphosphataemia rules.

5. **Benchmark reuse.** Q4 consumes the committed benchmark artefacts instead of re-running NSGA-II/GA/greedy/random (default); `--rerun-benchmark` regenerates them (~21 s wall time). Runtimes in the report are wall-clock and not deterministic.

6. **Chat evaluation scope.** Groundedness is scored automatically against the rules that *produce a constraint* for the asked nutrient; supporting citations retrieved by TF-IDF may legitimately mention other nutrients. Nutrients without constraint-producing rules (sugar, total fat) cannot be grounded today and are listed as known gaps. The expert-review rubric is provided for the human evaluation that cannot be automated.

7. **Scale.** 20 synthetic patients, one dish dataset, one seed set. Statistical strength is limited; the numbers measure pipeline correctness, not clinical validity.

