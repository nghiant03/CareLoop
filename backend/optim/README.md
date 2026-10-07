# CareLoop Meal Optimiser

Multi-objective meal-plan optimiser that turns a clinician-**APPROVED**
`NutrientEnvelope` into a 7-day × 3-meal plan that never violates the envelope's
hard constraints — on the real 190-dish `data/dishes.json` pool by default.

> **Architectural invariant:** only `EnvelopeStatus.APPROVED` envelopes may be
> consumed. `evaluate()` / `is_feasible()` raise `EnvelopeNotApprovedError`
> otherwise. The optimiser **never** violates a `ConstraintKind.MAX` constraint.

## Files

| File | Purpose |
|---|---|
| `problem.py` | Formal problem spec: decision vars, 4 objectives, hard constraints, `evaluate()`, `is_feasible()`, `constraint_vector()`. |
| `toy_data.py` | Toy pool of 8 Singapore-ish dishes (still used by the spike and smoke tests; the production pool is `data/dishes.json`). |
| `real_data.py` | Real 190-dish pool loader (`load_dishes()`), `FastEvaluator` (numpy mirror of `evaluate`), feasibility precheck, greedy constructive builder, plan repair. |
| `envelopes.py` | Four hand-built APPROVED envelopes (CKD-strict, CKD+hyperkalemia, T2D+HTN, T2D-only) validated against `shared/envelope_schema`. |
| `solver.py` | Production pipeline `solve()`: pymoo NSGA-II + the hard feasibility guarantee (repair → greedy fallback → explicit diagnosis), plus raw GA/greedy/random baselines. |
| `api.py` | Contract glue for `/plans`: `run(envelope, dishes=None, seed=42, pop_size=40, n_gen=80)`. Default pool = real dataset. |
| `spike_pymoo.py` | pymoo NSGA-II spike with lazy import; pure-Python NSGA-II fallback. Writes `spike_pymoo.csv`. |
| `baselines.py` | `random_search`, `greedy_search`, `exhaustive_search`, `nsga2_fallback`. |
| `benchmark.py` | Harness: NSGA-II vs GA vs greedy vs random, 4 envelopes × 5 seeds + pop/gen sweep. Writes `benchmark_results.csv` / `.md`. |
| `test_smoke.py` | 9 assertion tests (`python backend/optim/test_smoke.py`). |
| `test_real.py` | 10 real-data tests (`python backend/optim/test_real.py`). |

## Problem formulation

### Decision variables
A plan is a flat, day-major list of `DAYS × MEALS_PER_DAY = 21` meal slots:

```
plan[day * 3 + meal] = [dish_id, ...]      day ∈ {0..6}, meal ∈ {breakfast, lunch, dinner}
```

Each slot may hold multiple dish ids (the toy spike uses one dish per meal).
Dish ids must exist in the meal pool; the pool is the dish list minus every
`ExclusionFlag` match.

### Objectives (all minimised)

Let `T_d(n)` be the total amount of nutrient `n` on day `d`.

1. **nutrient_target_deviation**
   `(1/D) · Σ_d Σ_{c: kind=TARGET} |T_d(n_c) − value_c|`
2. **preference_fit** — `− mean_dish Σ_{tag} TAG_PREFERENCE[tag]` (placeholder).
3. **variety** — `− (0.5·normalised Shannon entropy + 0.5·distinct-dish ratio)`.
4. **cost** — `Σ_dishes price_sgd`.

### Hard constraints

For every `NutrientConstraint(kind=MAX)` with ceiling `M`:

```
∀ day d :  T_d(n) ≤ M          (daily)
           Σ_d T_d(n) ≤ M · D  (7-day section)
```

For every `NutrientConstraint(kind=MIN)` with floor `m`:

```
∀ day d :  T_d(n) ≥ m          (daily)
```

Plus exclusions (`ingredient`, `dish_category`, `macro_pattern`,
`diet_pattern`) and dish-pool membership.

`constraint_vector(plan, envelope, dishes)` returns these violation magnitudes
in a fixed canonical order (`0` = satisfied), which is fed to pymoo as `G ≤ 0`
and used by the fallback's constraint-dominance.

## Real dataset + feasibility guarantee

`api.run` defaults to the real 190-dish pool (`data/dishes.json` via
`real_data.load_dishes()`). Key guarantees and mechanics:

* **Feasibility guarantee** — `run()` never returns an infeasible plan. If the
  NSGA-II front has no feasible member, the least-violating candidate is
  repaired (`real_data.repair_plan`: per-day hill-climbing, then greedy
  rebuild); failing that, a greedy-constructed feasible plan is returned.
  When the pool provably cannot satisfy the envelope (checked by
  `feasibility_precheck`: empty pool / MIN unreachable / MAX unavoidable), the
  result is an explicit diagnosis: `feasible=False`, `engine="infeasible"`,
  `infeasibility_reason` set, empty plan.
* **FastEvaluator** — numpy mirror of `problem.evaluate` for pool-drawn plans
  (same objectives, same canonical constraint ordering, same EPS tolerance);
  ~50x faster, verified against the canonical evaluator in `test_real.py`.
* **Cost placeholder** — `data/dishes.json` has no `price_sgd`; a
  deterministic synthetic price (`2.5 + 0.004·kcal + 0.02·protein`) keeps the
  cost objective non-degenerate until real pricing lands.
* All hard constraints are per-day, so a plan is feasible iff every day is —
  that is what makes construction/repair decompose into cheap 3-slot problems.

Benchmark (`benchmark_results.md` headline, 4 envelopes × 5 seeds, HV on
normalised objectives): NSGA-II 0.423 mean HV @ ~260 ms, GA 0.282 @ ~116 ms,
greedy 0.084 @ ~8 ms, random 0.065 (infeasible on 75% of strict renal runs).
Sweep knee: pop=80, gen=80. Random search violates hard constraints on the
CKD envelopes — the constraint handling in NSGA-II/GA is what matters.

## Running

```bash
source .venv/bin/activate
PYTHONPATH=. python -m backend.optim.spike_pymoo     # spike (pymoo or fallback)
python backend/optim/test_smoke.py                    # smoke tests
python backend/optim/test_real.py                     # real-data tests
python -m backend.optim.benchmark                     # benchmark harness (~20s)
```

`pymoo` is imported lazily. When pymoo + numpy are installed (they are in the
repo `.venv`), `solve()` uses `pymoo.algorithms.moo.nsga2.NSGA2` and reports
`Engine: pymoo`; if they are missing, the same problem falls back to the
pure-Python NSGA-II in `baselines.py` and the spike reports
`fallback-nsga2`. `api.run` additionally falls back to the greedy builder
(`engine="greedy-fallback"`) when the NSGA-II front has no feasible member, so
the endpoint stays fast and feasible regardless of engine availability.

## Expected output

With numpy/pymoo installed the spike prints `Engine : pymoo`. Without them
(fallback path):

```
Engine                : fallback-nsga2
pymoo unavailable     : ModuleNotFoundError: No module named 'numpy'
                         -> using pure-Python NSGA-II fallback
Allowed dishes        : 6 of 8
(a) Pareto front size : 40
(b) Best plan         : 7 days x 3 meals (e.g. Grilled Salmon, Fish Soup, Yong Tau Foo...)
    objectives         : nutrient_target_deviation=..., preference_fit=..., variety=..., cost=...
(c) Constraint violations: 0
(d) Runtime           : ~800 ms
CSV                   : backend/optim/spike_pymoo.csv
OK: feasible plan found with 0 hard-constraint violations.
```

* `spike_pymoo.csv` holds the front objectives:
  `rank,nutrient_target_deviation,preference_fit,variety,cost,violation_count,feasible`.
* If the front size is `0`, the spike prints a WARNING that the problem is
  over-constrained and exits `2`.
* Exit codes: `0` success, `1` best plan violates constraints, `2` no feasible
  plan.

### Toy envelope (hard-coded in `spike_pymoo.py`)
`patient_id='p-toy'`, `status=APPROVED`, `priority_basis='CKD > HTN > T2D'`,
targets: energy `TARGET=1900 kcal`, sodium `MAX=2000 mg`, protein `MIN=60 g`
`MAX=80 g`; exclusions: ingredient `lard`, category `deep_fried`.

## Baseline comparison

`baselines.py` provides the benchmark comparators. `exhaustive_search`
enumerates all `MEALS_PER_DAY`-meal combinations for one day (true small
exhaustive) and repeats the best day — deliberately variety-poor, so NSGA-II's
front should dominate it. `greedy_search` adds a single-slot local-search pass.

Numbers: see [`benchmark_results.md`](benchmark_results.md) — NSGA-II 0.423 mean
hypervolume @ ~262 ms vs GA 0.282 @ ~117 ms, greedy 0.084 @ ~8 ms, random 0.065
(infeasible on 75% of strict renal runs). Recommended production config:
pop=80, gen=80.
