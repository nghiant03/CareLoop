# CareLoop Meal Optimiser

Multi-objective meal-plan optimiser that turns a clinician-**APPROVED**
`NutrientEnvelope` into a 7-day × 3-meal plan that never violates the envelope's
hard constraints — on the external 214-dish curated fixture pool or published release.

> **Architectural invariant:** only `EnvelopeStatus.APPROVED` envelopes may be
> consumed. `evaluate()` / `is_feasible()` raise `EnvelopeNotApprovedError`
> otherwise. The optimiser **never** violates a `ConstraintKind.MAX` constraint.
>
> **Hard/soft encoding (PLAN.md module 4):** hard constraints = approved MAX
> ceilings + exclusions. MIN floors and `TARGET` values are soft objective
> terms (deviation from the band) — they guide the search and never cause
> violations or infeasibility.

## Files

| File | Purpose |
|---|---|
| `problem.py` | Formal problem spec: decision vars, 4 objectives, hard constraints (MAX + exclusions), `evaluate()`, `is_feasible()`, `constraint_vector()`. |
| `toy_data.py` | Toy pool of 8 Singapore-ish dishes for explicit spike/smoke tests; normal catalogue input is external or database-managed. |
| `exclusion_mapping.py` | Documented bridge from rulebook exclusion values (e.g. `high_potassium_foods`) to per-serving dish nutrient thresholds — without it the rulebook exclusions match zero dataset dishes. |
| `real_data.py` | Real dish-pool loader (`load_dishes()`), `FastEvaluator` (numpy mirror of `evaluate`), feasibility precheck, greedy constructive builder, plan repair. |
| `envelopes.py` | Four hand-built APPROVED envelopes (CKD-strict, CKD+hyperkalemia, T2D+HTN, T2D-only) validated against `shared/envelope_schema`. |
| `solver.py` | Production pipeline `solve()`: pymoo NSGA-II + the hard feasibility guarantee (repair → greedy fallback → explicit diagnosis), plus raw GA/greedy/random baselines. |
| `api.py` | Contract glue for `/plans`: `run(envelope, dishes=None, seed=42, pop_size=40, n_gen=80)`. Default pool = real dataset. |
| `spike_pymoo.py` | pymoo NSGA-II spike with lazy import; pure-Python NSGA-II fallback. Writes `spike_pymoo.csv`. |
| `baselines.py` | `random_search`, `greedy_search`, `exhaustive_search`, `nsga2_fallback`. |
| `benchmark.py` | Harness: NSGA-II vs GA vs greedy vs random, 4 envelopes × 5 seeds + pop/gen sweep. Writes `benchmark_results.csv` / `.md`. |
| `test_smoke.py` | 9 assertion tests (`python backend/optim/test_smoke.py`). |
| `test_real.py` | 11 real-data tests (`python backend/optim/test_real.py`). |

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

Let `T_d(n)` be the total amount of nutrient `n` on day `d`. The deviation
objective measures distance from the envelope's nutrient **band**:

1. **nutrient_target_deviation**
   `(1/D) · Σ_d Σ_c dev(T_d(n_c), c)` where `dev` is `|T_d(n_c) − value_c|`
   for `kind=TARGET`, `max(0, value_c − T_d(n_c))` (shortfall) for `kind=MIN`,
   and `max(0, T_d(n_c) − value_c)` (excess, zero for hard-feasible plans) for
   `kind=MAX`.
2. **preference_fit** — `− mean_dish Σ_{tag} TAG_PREFERENCE[tag]` (placeholder).
3. **variety** — `− (0.5·normalised Shannon entropy + 0.5·distinct-dish ratio)`.
4. **cost** — `Σ_dishes price_sgd`.

### Hard constraints

Per PLAN.md module 4 ("objectives = nutrient-target deviation, preference fit,
variety, cost; hard constraints = approved ceilings/exclusions"), only MAX
ceilings are hard. For every `NutrientConstraint(kind=MAX)` with ceiling `M`:

```
∀ day d :  T_d(n) ≤ M          (daily)
           Σ_d T_d(n) ≤ M · D  (7-day section)
```

Plus exclusions (`ingredient`, `dish_category`, `macro_pattern`,
`diet_pattern`) and dish-pool membership. `MIN` floors and `TARGET` values are
**soft**: they appear only in the deviation objective above, so guideline
floors (fibre, potassium, energy) guide the search instead of making envelopes
unsolvable.

`constraint_vector(plan, envelope, dishes)` returns the hard violation
magnitudes in a fixed canonical order (`0` = satisfied), which is fed to pymoo
as `G ≤ 0` and used by the fallback's constraint-dominance.

## Real dataset + feasibility guarantee

`api.run` defaults to the external 214-dish curated pool (via
`real_data.load_dishes()`). Key guarantees and mechanics:

* **Feasibility guarantee** — `run()` never returns an infeasible plan. If the
  NSGA-II front has no feasible member, the least-violating candidate is
  repaired (`real_data.repair_plan`: per-day hill-climbing, then greedy
  rebuild); failing that, a greedy-constructed feasible plan is returned.
  When the pool provably cannot satisfy the hard constraints (checked by
  `feasibility_precheck`: empty pool / MAX unavoidable), the
  result is an explicit diagnosis: `feasible=False`, `engine="infeasible"`,
  `infeasibility_reason` set, empty plan.
* **FastEvaluator** — numpy mirror of `problem.evaluate` for pool-drawn plans
  (same objectives, same canonical constraint ordering, same EPS tolerance);
  ~50x faster, verified against the canonical evaluator in `test_real.py`.
* **Cost placeholder** — the external dish fixture has no `price_sgd`; a
  deterministic synthetic price (`2.5 + 0.004·kcal + 0.02·protein`) keeps the
  cost objective non-degenerate until real pricing lands.
* All hard constraints are per-day, so a plan is feasible iff every day is —
  that is what makes construction/repair decompose into cheap 3-slot problems.

Benchmark (`benchmark_results.md` headline, 4 envelopes × 5 seeds, HV on
normalised objectives, module-4 encoding): NSGA-II 0.580 mean HV @ ~285 ms,
GA 0.353 @ ~134 ms, greedy 0.178 @ ~9 ms, random 0.244 @ ~51 ms — all methods
0% hard violations (only MAX ceilings are hard now, and the pools have headroom
under them; the NSGA-II path keeps the repair/greedy guarantee as the backstop
for genuinely tight ceilings). Sweep knee: pop=80, gen=80.

## Running

```bash
source .venv/bin/activate
python -m backend.optim.spike_pymoo     # spike (pymoo or fallback)
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

Numbers: see [`benchmark_results.md`](benchmark_results.md) — NSGA-II 0.580 mean
hypervolume @ ~285 ms vs GA 0.353 @ ~134 ms, greedy 0.178 @ ~9 ms, random 0.244
@ ~51 ms (module-4 encoding: hard = MAX ceilings + exclusions; all methods 0%
hard violations). Recommended production config: pop=80, gen=80.
