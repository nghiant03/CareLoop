# CareLoop optimiser benchmark — real dish dataset (214 dishes)

Budget mode: **evaluations**. Pymoo search limit: population × nominal generations evaluations. Actual evaluation counts are recorded in the CSV. Nominal generations are not a stopping condition. Wall times include cold-start/compilation overhead and repair; these are not strict latency bounds. GA/greedy/random keep their native budgets.

Setup: 7 days x 3 meals, 214-dish pool (post-exclusion counts vary by envelope), 4 objectives, hard daily MAX ceilings + exclusions (MIN floors / TARGETs are soft objective terms per PLAN.md module 4). HV = pymoo exact hypervolume on min-max normalised objectives (per-envelope bounds across all methods — guaranteed and raw — ref point 1.1^4). Rows labelled `<method>-raw` run the same pymoo algorithm with `guarantee=False` and report their honest hard-constraint violation rate; guaranteed rows carry the repair/greedy feasibility guarantee (violation rate 0 by construction, modulo explicit infeasibility diagnoses). ga / greedy / random are inherently raw baselines.

Algorithm configuration (4 objectives, pop=40, gen=80): **NSGA-III** das-dennis p=4 (35 reference directions), same IntegerRandomSampling + SBX + PM operators as NSGA-II; **MOEA/D** the same 35 weight vectors, T=15 neighbours, PBI decomposition (theta=5), neighbour mating p=0.9, population tied to the weight-vector count (35), unconstrained formulation (pymoo's MOEA/D cannot encode constraints — the guarantee wrapper still fences the reported plan); **AGE-MOEA** geometry-adaptive survival (numba), same operators; **SMSEMOA** exact hypervolume-contribution survival, pop=40 to bound the 4-D HV cost. RNSGA-II skipped: reference points need per-envelope calibration in raw objective units; SMSEMOA already covers the indicator-based corner.

## Summary (main phase: 4 envelopes x 5 seeds, pop=40, gen=80)

| method | guarantee | mean HV | HV std | violation rate | mean runtime (ms) |
|---|---|---|---|---|---|
| nsga2 | yes | 0.5226 | 0.0412 | 0% | 296.0 |
| nsga3 | yes | 0.5580 | 0.0164 | 0% | 321.4 |
| moead | yes | 0.0200 | 0.0084 | 0% | 1419.5 |
| age | yes | 0.5948 | 0.0235 | 0% | 633.7 |
| sms | yes | 0.6459 | 0.0290 | 0% | 713.6 |
| nsga2-raw | no | 0.5226 | 0.0412 | 0% | 289.3 |
| nsga3-raw | no | 0.5535 | 0.0213 | 0% | 316.7 |
| moead-raw | no | 0.0116 | 0.0125 | 50% | 1362.0 |
| age-raw | no | 0.5948 | 0.0235 | 0% | 530.0 |
| sms-raw | no | 0.6459 | 0.0290 | 0% | 705.7 |
| ga | no | 0.3717 | 0.0308 | 0% | 142.2 |
| greedy | no | 0.1701 | 0.0302 | 0% | 9.9 |
| random | no | 0.2375 | 0.0350 | 0% | 52.9 |

## Mean hypervolume per envelope

| envelope | nsga2 | nsga3 | moead | age | sms | nsga2-raw | nsga3-raw | moead-raw | age-raw | sms-raw | ga | greedy | random |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ckd_hyperkalemia | 0.5175 | 0.5598 | 0.0217 | 0.5983 | 0.6650 | 0.5175 | 0.5482 | 0.0193 | 0.5983 | 0.6650 | 0.3589 | 0.1853 | 0.2707 |
| ckd_strict | 0.4972 | 0.5460 | 0.0209 | 0.5723 | 0.6209 | 0.4972 | 0.5327 | 0.0122 | 0.5723 | 0.6209 | 0.3422 | 0.2040 | 0.2288 |
| t2d_htn | 0.5123 | 0.5604 | 0.0116 | 0.5922 | 0.6338 | 0.5123 | 0.5618 | 0.0000 | 0.5922 | 0.6338 | 0.3957 | 0.1549 | 0.2015 |
| t2d_only | 0.5636 | 0.5656 | 0.0259 | 0.6165 | 0.6639 | 0.5636 | 0.5714 | 0.0149 | 0.6165 | 0.6639 | 0.3900 | 0.1359 | 0.2491 |

## NSGA-II pop x gen sweep (1 seed, HV vs main-phase bounds)

| pop | gen | mean HV | mean runtime (ms) |
|---|---|---|---|
| 20 | 40 | 0.4562 | 88.1 |
| 20 | 80 | 0.4689 | 171.2 |
| 20 | 160 | 0.4752 | 334.2 |
| 40 | 40 | 0.5286 | 145.1 |
| 40 | 80 | 0.5246 | 287.6 |
| 40 | 160 | 0.5340 | 577.0 |
| 80 | 40 | 0.5606 | 263.6 |
| 80 | 80 | 0.5897 | 509.2 |
| 80 | 160 | 0.5768 | 1006.0 |

## Recommendation

* Fastest swept NSGA-II config: pop=20, gen=40 (mean HV 0.4562, 88 ms/solve).
* NSGA-II knee point (HV within 2% of the best 0.5897): **pop=80, gen=80** (mean HV 0.5897, 509 ms/solve).
* Best guaranteed method by mean HV: **sms** (HV 0.6459, 714 ms/solve); NSGA-II scores 0.5226 at 296 ms/solve.
* Best raw method by mean HV: sms-raw (HV 0.6459, violation rate 0%) — raw and guaranteed HV figures are directly comparable: HV is computed only over feasible front members (infeasible front members are filtered out before the HV calculation), so raw HV is not inflated by infeasible members. Raw rows differ in that they report honest hard-constraint violation rates and skip the repair step that guarantees the delivered plan.
* **Algorithm recommendation: sms** — highest mean HV among guarantee-carrying methods (0.6459 vs NSGA-II 0.5226) at 2.4x the NSGA-II runtime; it would be a drop-in ``method=`` argument to ``solve()`` (the guarantee path is method-agnostic).
* Budget option: nsga2 is the cheapest guaranteed method (296 ms/solve, HV 0.5226) if latency ever trumps front quality.
* The guarantee wrapper (repair + greedy fallback) is method-agnostic: every guaranteed row reports violation rate 0% regardless of algorithm, so algorithm choice affects front quality and runtime only.
* Interpretation caveat: the HV metric scores the whole Pareto front (front coverage), not the single delivered plan. Single-point baselines (GA scalarisation, greedy) are structurally disadvantaged on full-front HV because they emit one plan per solve; the quality of that single delivered meal plan answers a different question and is assessed separately by the constraint-satisfaction evaluation.
* Work budgets: pymoo methods use actual-evaluation termination (population × generations evaluations by default); counts are recorded from algorithm.evaluator.n_eval in the CSV. Generation-boundary overshoot is possible. CARELOOP_BENCH_BUDGET=time selects wall-time termination with CARELOOP_BENCH_SECONDS (default 0.5). GA/greedy/random retain their native budgets and are not claimed to have equal work. Repair/evaluation outside pymoo is excluded from the search count but included in runtime.
* Total harness wall time: 150s. Baselines: GA scalarises (single-point fronts -> lower HV); greedy is feasibility-aware by construction and near-instant but myopic; random is the floor on quality. Under the module-4 encoding (hard = MAX ceilings + exclusions only) raw methods rarely violate a ceiling on these envelopes, so methods are separated mainly by hypervolume; the repair/greedy guarantee remains the backstop for genuinely tight ceilings.
