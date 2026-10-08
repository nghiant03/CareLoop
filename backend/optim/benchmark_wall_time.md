# CareLoop optimiser benchmark — real dish dataset (214 dishes)

Budget mode: **time**. Pymoo search limit: 0.5 seconds per run. Actual evaluation counts are recorded in the CSV. Nominal generations are not a stopping condition. Wall times include cold-start/compilation overhead and repair; these are not strict latency bounds. GA/greedy/random keep their native budgets.

Setup: 7 days x 3 meals, 214-dish pool (post-exclusion counts vary by envelope), 4 objectives, hard daily MAX ceilings + exclusions (MIN floors / TARGETs are soft objective terms per PLAN.md module 4). HV = pymoo exact hypervolume on min-max normalised objectives (per-envelope bounds across all methods — guaranteed and raw — ref point 1.1^4). Rows labelled `<method>-raw` run the same pymoo algorithm with `guarantee=False` and report their honest hard-constraint violation rate; guaranteed rows carry the repair/greedy feasibility guarantee (violation rate 0 by construction, modulo explicit infeasibility diagnoses). ga / greedy / random are inherently raw baselines.

Algorithm configuration (4 objectives, pop=40, gen=80): **NSGA-III** das-dennis p=4 (35 reference directions), same IntegerRandomSampling + SBX + PM operators as NSGA-II; **MOEA/D** the same 35 weight vectors, T=15 neighbours, PBI decomposition (theta=5), neighbour mating p=0.9, population tied to the weight-vector count (35), unconstrained formulation (pymoo's MOEA/D cannot encode constraints — the guarantee wrapper still fences the reported plan); **AGE-MOEA** geometry-adaptive survival (numba), same operators; **SMSEMOA** exact hypervolume-contribution survival, pop=40 to bound the 4-D HV cost. RNSGA-II skipped: reference points need per-envelope calibration in raw objective units; SMSEMOA already covers the indicator-based corner.

## Summary (main phase: 4 envelopes x 5 seeds, pop=40, gen=80)

| method | guarantee | mean HV | HV std | violation rate | mean runtime (ms) |
|---|---|---|---|---|---|
| nsga2 | yes | 0.5450 | 0.0348 | 0% | 511.1 |
| nsga3 | yes | 0.6034 | 0.0184 | 0% | 508.0 |
| moead | yes | 0.0365 | 0.0177 | 0% | 516.6 |
| age | yes | 0.5973 | 0.0788 | 0% | 567.7 |
| sms | yes | 0.6430 | 0.0297 | 0% | 513.5 |
| nsga2-raw | no | 0.5468 | 0.0363 | 0% | 511.1 |
| nsga3-raw | no | 0.6012 | 0.0260 | 0% | 507.8 |
| moead-raw | no | 0.0127 | 0.0201 | 65% | 516.7 |
| age-raw | no | 0.6112 | 0.0282 | 0% | 512.2 |
| sms-raw | no | 0.6443 | 0.0292 | 0% | 515.5 |
| ga | no | 0.3664 | 0.0397 | 0% | 146.9 |
| greedy | no | 0.1779 | 0.0250 | 0% | 9.6 |
| random | no | 0.2498 | 0.0353 | 0% | 51.5 |

## Mean hypervolume per envelope

| envelope | nsga2 | nsga3 | moead | age | sms | nsga2-raw | nsga3-raw | moead-raw | age-raw | sms-raw | ga | greedy | random |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ckd_hyperkalemia | 0.5472 | 0.6189 | 0.0410 | 0.6283 | 0.6610 | 0.5439 | 0.6158 | 0.0148 | 0.6282 | 0.6612 | 0.3537 | 0.1772 | 0.2827 |
| ckd_strict | 0.5191 | 0.5808 | 0.0427 | 0.5220 | 0.6055 | 0.5178 | 0.5704 | 0.0169 | 0.5764 | 0.6059 | 0.3209 | 0.2107 | 0.2383 |
| t2d_htn | 0.5368 | 0.6083 | 0.0196 | 0.6157 | 0.6579 | 0.5467 | 0.6146 | 0.0029 | 0.6205 | 0.6626 | 0.3899 | 0.1652 | 0.2150 |
| t2d_only | 0.5770 | 0.6057 | 0.0429 | 0.6233 | 0.6474 | 0.5789 | 0.6040 | 0.0160 | 0.6197 | 0.6476 | 0.4010 | 0.1584 | 0.2633 |

## NSGA-II pop x gen sweep (1 seed, HV vs main-phase bounds)

| pop | gen | mean HV | mean runtime (ms) |
|---|---|---|---|
| 20 | 40 | 0.5013 | 506.6 |
| 20 | 80 | 0.4738 | 506.6 |
| 20 | 160 | 0.4992 | 506.9 |
| 40 | 40 | 0.5573 | 509.9 |
| 40 | 80 | 0.5572 | 511.0 |
| 40 | 160 | 0.5473 | 510.7 |
| 80 | 40 | 0.5958 | 520.6 |
| 80 | 80 | 0.5927 | 518.6 |
| 80 | 160 | 0.5959 | 519.2 |

## Recommendation

* Fastest swept NSGA-II config: pop=20, gen=80 (mean HV 0.4738, 507 ms/solve).
* NSGA-II knee point (HV within 2% of the best 0.5959): **pop=80, gen=80** (mean HV 0.5927, 519 ms/solve).
* Best guaranteed method by mean HV: **sms** (HV 0.6430, 513 ms/solve); NSGA-II scores 0.5450 at 511 ms/solve.
* Best raw method by mean HV: sms-raw (HV 0.6443, violation rate 0%) — raw and guaranteed HV figures are directly comparable: HV is computed only over feasible front members (infeasible front members are filtered out before the HV calculation), so raw HV is not inflated by infeasible members. Raw rows differ in that they report honest hard-constraint violation rates and skip the repair step that guarantees the delivered plan.
* **Algorithm recommendation: sms** — highest mean HV among guarantee-carrying methods (0.6430 vs NSGA-II 0.5450) at 1.0x the NSGA-II runtime; it would be a drop-in ``method=`` argument to ``solve()`` (the guarantee path is method-agnostic).
* Budget option: nsga3 is the cheapest guaranteed method (508 ms/solve, HV 0.6034) if latency ever trumps front quality.
* The guarantee wrapper (repair + greedy fallback) is method-agnostic: every guaranteed row reports violation rate 0% regardless of algorithm, so algorithm choice affects front quality and runtime only.
* Interpretation caveat: the HV metric scores the whole Pareto front (front coverage), not the single delivered plan. Single-point baselines (GA scalarisation, greedy) are structurally disadvantaged on full-front HV because they emit one plan per solve; the quality of that single delivered meal plan answers a different question and is assessed separately by the constraint-satisfaction evaluation.
* Work budgets: pymoo methods use actual-evaluation termination (population × generations evaluations by default); counts are recorded from algorithm.evaluator.n_eval in the CSV. Generation-boundary overshoot is possible. CARELOOP_BENCH_BUDGET=time selects wall-time termination with CARELOOP_BENCH_SECONDS (default 0.5). GA/greedy/random retain their native budgets and are not claimed to have equal work. Repair/evaluation outside pymoo is excluded from the search count but included in runtime.
* Total harness wall time: 126s. Baselines: GA scalarises (single-point fronts -> lower HV); greedy is feasibility-aware by construction and near-instant but myopic; random is the floor on quality. Under the module-4 encoding (hard = MAX ceilings + exclusions only) raw methods rarely violate a ceiling on these envelopes, so methods are separated mainly by hypervolume; the repair/greedy guarantee remains the backstop for genuinely tight ceilings.
