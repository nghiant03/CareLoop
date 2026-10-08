# CareLoop optimiser benchmark — real dish dataset (214 dishes)

Setup: 7 days x 3 meals, 214-dish pool (post-exclusion counts vary by envelope), 4 objectives, hard daily MAX ceilings + exclusions (MIN floors / TARGETs are soft objective terms per PLAN.md module 4). HV = pymoo exact hypervolume on min-max normalised objectives (per-envelope bounds across all methods — guaranteed and raw — ref point 1.1^4). Rows labelled `<method>-raw` run the same pymoo algorithm with `guarantee=False` and report their honest hard-constraint violation rate; guaranteed rows carry the repair/greedy feasibility guarantee (violation rate 0 by construction, modulo explicit infeasibility diagnoses). ga / greedy / random are inherently raw baselines.

Algorithm configuration (4 objectives, pop=40, gen=80): **NSGA-III** das-dennis p=4 (35 reference directions), same IntegerRandomSampling + SBX + PM operators as NSGA-II; **MOEA/D** the same 35 weight vectors, T=15 neighbours, PBI decomposition (theta=5), neighbour mating p=0.9, population tied to the weight-vector count (35), unconstrained formulation (pymoo's MOEA/D cannot encode constraints — the guarantee wrapper still fences the reported plan); **AGE-MOEA** geometry-adaptive survival (numba), same operators; **SMSEMOA** exact hypervolume-contribution survival, pop=40 to bound the 4-D HV cost. RNSGA-II skipped: reference points need per-envelope calibration in raw objective units; SMSEMOA already covers the indicator-based corner.

## Summary (main phase: 4 envelopes x 5 seeds, pop=40, gen=80)

| method | guarantee | mean HV | HV std | violation rate | mean runtime (ms) |
|---|---|---|---|---|---|
| nsga2 | yes | 0.5220 | 0.0423 | 0% | 287.6 |
| nsga3 | yes | 0.5534 | 0.0193 | 0% | 314.7 |
| moead | yes | 0.0235 | 0.0119 | 0% | 1195.0 |
| age | yes | 0.5944 | 0.0244 | 0% | 617.2 |
| sms | yes | 0.6459 | 0.0298 | 0% | 706.0 |
| nsga2-raw | no | 0.5220 | 0.0423 | 0% | 287.5 |
| nsga3-raw | no | 0.5499 | 0.0200 | 0% | 314.3 |
| moead-raw | no | 0.0143 | 0.0158 | 45% | 1196.0 |
| age-raw | no | 0.5944 | 0.0244 | 0% | 525.5 |
| sms-raw | no | 0.6459 | 0.0298 | 0% | 705.9 |
| ga | no | 0.3715 | 0.0329 | 0% | 134.4 |
| greedy | no | 0.1700 | 0.0302 | 0% | 9.3 |
| random | no | 0.2367 | 0.0362 | 0% | 50.7 |

## Mean hypervolume per envelope

| envelope | nsga2 | nsga3 | moead | age | sms | nsga2-raw | nsga3-raw | moead-raw | age-raw | sms-raw | ga | greedy | random |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ckd_hyperkalemia | 0.5174 | 0.5618 | 0.0274 | 0.5982 | 0.6649 | 0.5174 | 0.5571 | 0.0274 | 0.5982 | 0.6649 | 0.3588 | 0.1853 | 0.2706 |
| ckd_strict | 0.4980 | 0.5405 | 0.0207 | 0.5727 | 0.6222 | 0.4980 | 0.5422 | 0.0110 | 0.5727 | 0.6222 | 0.3371 | 0.2039 | 0.2283 |
| t2d_htn | 0.5069 | 0.5435 | 0.0155 | 0.5875 | 0.6297 | 0.5069 | 0.5327 | 0.0000 | 0.5875 | 0.6297 | 0.3981 | 0.1545 | 0.1978 |
| t2d_only | 0.5658 | 0.5678 | 0.0304 | 0.6192 | 0.6667 | 0.5658 | 0.5678 | 0.0189 | 0.6192 | 0.6667 | 0.3919 | 0.1361 | 0.2501 |

## NSGA-II pop x gen sweep (1 seed, HV vs main-phase bounds)

| pop | gen | mean HV | mean runtime (ms) |
|---|---|---|---|
| 20 | 40 | 0.4553 | 89.1 |
| 20 | 80 | 0.4678 | 171.6 |
| 20 | 160 | 0.4738 | 339.4 |
| 40 | 40 | 0.5284 | 146.9 |
| 40 | 80 | 0.5243 | 284.2 |
| 40 | 160 | 0.5336 | 564.1 |
| 80 | 40 | 0.5600 | 264.2 |
| 80 | 80 | 0.5892 | 513.3 |
| 80 | 160 | 0.5760 | 1016.4 |

## Recommendation

* Fastest swept NSGA-II config: pop=20, gen=40 (mean HV 0.4553, 89 ms/solve).
* NSGA-II knee point (HV within 2% of the best 0.5892): **pop=80, gen=80** (mean HV 0.5892, 513 ms/solve).
* Best guaranteed method by mean HV: **sms** (HV 0.6459, 706 ms/solve); NSGA-II scores 0.5220 at 288 ms/solve.
* Best raw method by mean HV: sms-raw (HV 0.6459, violation rate 0%) — raw and guaranteed HV figures are directly comparable: HV is computed only over feasible front members (infeasible front members are filtered out before the HV calculation), so raw HV is not inflated by infeasible members. Raw rows differ in that they report honest hard-constraint violation rates and skip the repair step that guarantees the delivered plan.
* **Algorithm recommendation: sms** — highest mean HV among guarantee-carrying methods (0.6459 vs NSGA-II 0.5220) at 2.5x the NSGA-II runtime; it would be a drop-in ``method=`` argument to ``solve()`` (the guarantee path is method-agnostic).
* Budget option: nsga2 is the cheapest guaranteed method (288 ms/solve, HV 0.5220) if latency ever trumps front quality.
* The guarantee wrapper (repair + greedy fallback) is method-agnostic: every guaranteed row reports violation rate 0% regardless of algorithm, so algorithm choice affects front quality and runtime only.
* Interpretation caveat: the HV metric scores the whole Pareto front (front coverage), not the single delivered plan. Single-point baselines (GA scalarisation, greedy) are structurally disadvantaged on full-front HV because they emit one plan per solve; the quality of that single delivered meal plan answers a different question and is assessed separately by the constraint-satisfaction evaluation.
* Equal-work caveat: nominal population x generations is not an equal-work budget across all methods (e.g. MOEA/D's population is tied to its reference-direction count, so its per-generation work differs from population-sized methods); evaluation counts are estimated from the algorithm configuration rather than recorded per run.
* Total harness wall time: 141s. Baselines: GA scalarises (single-point fronts -> lower HV); greedy is feasibility-aware by construction and near-instant but myopic; random is the floor on quality. Under the module-4 encoding (hard = MAX ceilings + exclusions only) raw methods rarely violate a ceiling on these envelopes, so methods are separated mainly by hypervolume; the repair/greedy guarantee remains the backstop for genuinely tight ceilings.
