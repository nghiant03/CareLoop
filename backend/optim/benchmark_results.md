# CareLoop optimiser benchmark — real dish dataset (214 dishes)

Setup: 7 days x 3 meals, 214-dish pool (post-exclusion counts vary by envelope), 4 objectives, hard daily MAX ceilings + exclusions (MIN floors / TARGETs are soft objective terms per PLAN.md module 4). HV = pymoo exact hypervolume on min-max normalised objectives (per-envelope bounds across all methods, ref point 1.1^4). NSGA-II rows carry the hard feasibility guarantee (repair/greedy fallback); raw baselines report their true violation rate.

## Summary (main phase: 4 envelopes x 5 seeds, pop=40, gen=80)

| method | mean HV | HV std | violation rate | mean runtime (ms) |
|---|---|---|---|---|
| nsga2 | 0.5722 | 0.0417 | 0% | 303.1 |
| ga | 0.3453 | 0.0532 | 0% | 145.7 |
| greedy | 0.1703 | 0.0368 | 0% | 9.6 |
| random | 0.2495 | 0.0360 | 0% | 51.9 |

## Mean hypervolume per envelope

| envelope | nsga2 | ga | greedy | random |
|---|---|---|---|---|
| ckd_hyperkalemia | 0.5704 | 0.3413 | 0.1627 | 0.2849 |
| ckd_strict | 0.5499 | 0.2808 | 0.2166 | 0.2378 |
| t2d_htn | 0.5951 | 0.3638 | 0.1776 | 0.2265 |
| t2d_only | 0.5733 | 0.3952 | 0.1244 | 0.2490 |

## NSGA-II pop x gen sweep (1 seed, HV vs main-phase bounds)

| pop | gen | mean HV | mean runtime (ms) |
|---|---|---|---|
| 20 | 40 | 0.5029 | 93.2 |
| 20 | 80 | 0.5097 | 179.7 |
| 20 | 160 | 0.5132 | 356.0 |
| 40 | 40 | 0.5843 | 158.4 |
| 40 | 80 | 0.5706 | 302.0 |
| 40 | 160 | 0.5697 | 600.1 |
| 80 | 40 | 0.6261 | 278.8 |
| 80 | 80 | 0.6437 | 543.4 |
| 80 | 160 | 0.6171 | 1074.3 |

## Recommendation

* Fastest swept config: pop=20, gen=40 (mean HV 0.5029, 93 ms/solve).
* Knee point (HV within 2% of the best 0.6437): **pop=80, gen=80** (mean HV 0.6437, 543 ms/solve).
* Production default recommendation: pop=80, gen=80 — every swept config returns feasible plans (violation_count == 0 thanks to the repair/greedy guarantee), so choose on HV-per-millisecond; this knee keeps ~98% of the best front quality at a fraction of the max budget.
* Total harness wall time: 25s. Baselines: GA scalarises (single-point fronts -> lower HV); greedy is feasibility-aware by construction and near-instant but myopic; random is the floor on quality. Under the module-4 encoding (hard = MAX ceilings + exclusions only) raw random search rarely violates a ceiling, so methods are separated by hypervolume rather than violations; the repair/greedy guarantee on the NSGA-II path remains the backstop for genuinely tight ceilings.
