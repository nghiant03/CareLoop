# CareLoop optimiser benchmark — real 190-dish dataset

Setup: 7 days x 3 meals, 190-dish pool (post-exclusion 128-184 allowed), 4 objectives, hard daily MAX/MIN constraints. HV = pymoo exact hypervolume on min-max normalised objectives (per-envelope bounds across all methods, ref point 1.1^4). NSGA-II rows carry the hard feasibility guarantee (repair/greedy fallback); raw baselines report their true violation rate.

## Summary (main phase: 4 envelopes x 5 seeds, pop=40, gen=80)

| method | mean HV | HV std | violation rate | mean runtime (ms) |
|---|---|---|---|---|
| nsga2 | 0.4228 | 0.0742 | 0% | 261.7 |
| ga | 0.2823 | 0.0780 | 0% | 117.0 |
| greedy | 0.0837 | 0.0122 | 0% | 8.0 |
| random | 0.0650 | 0.1129 | 75% | 48.6 |

## Mean hypervolume per envelope

| envelope | nsga2 | ga | greedy | random |
|---|---|---|---|---|
| ckd_hyperkalemia | 0.3380 | 0.2035 | 0.0770 | 0.0000 |
| ckd_strict | 0.4021 | 0.2463 | 0.0964 | 0.0000 |
| t2d_htn | 0.4415 | 0.3035 | 0.0766 | 0.0000 |
| t2d_only | 0.5098 | 0.3762 | 0.0850 | 0.2602 |

## NSGA-II pop x gen sweep (1 seed, HV vs main-phase bounds)

| pop | gen | mean HV | mean runtime (ms) |
|---|---|---|---|
| 20 | 40 | 0.1578 | 79.2 |
| 20 | 80 | 0.2335 | 156.1 |
| 20 | 160 | 0.3320 | 316.6 |
| 40 | 40 | 0.3917 | 131.7 |
| 40 | 80 | 0.4453 | 261.9 |
| 40 | 160 | 0.4756 | 524.1 |
| 80 | 40 | 0.4056 | 230.8 |
| 80 | 80 | 0.5092 | 457.4 |
| 80 | 160 | 0.5164 | 914.9 |

## Recommendation

* Fastest swept config: pop=20, gen=40 (mean HV 0.1578, 79 ms/solve).
* Knee point (HV within 2% of the best 0.5164): **pop=80, gen=80** (mean HV 0.5092, 457 ms/solve).
* Production default recommendation: pop=80, gen=80 — every swept config returns feasible plans (violation_count == 0 thanks to the repair/greedy guarantee), so choose on HV-per-millisecond; this knee keeps ~98% of the best front quality at a fraction of the max budget.
* Total harness wall time: 21s. Baselines: GA scalarises (single-point fronts -> lower HV) and its violation rate shows why constraint handling matters; greedy is feasibility-aware by construction and near-instant but myopic; random is the floor on both axes.
