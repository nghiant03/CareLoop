# CareLoop Meal Optimiser (Module 4 — Lane B, Week 1)

Multi-objective meal-plan optimiser that turns a clinician-**APPROVED**
`NutrientEnvelope` into a 7-day × 3-meal plan that never violates the envelope's
hard constraints.

> **Architectural invariant:** only `EnvelopeStatus.APPROVED` envelopes may be
> consumed. `evaluate()` / `is_feasible()` raise `EnvelopeNotApprovedError`
> otherwise. The optimiser **never** violates a `ConstraintKind.MAX` constraint.

## Files

| File | Purpose |
|---|---|
| `problem.py` | Formal problem spec: decision vars, 4 objectives, hard constraints, `evaluate()`, `is_feasible()`, `constraint_vector()`. |
| `toy_data.py` | Week-1 toy pool of 8 Singapore-ish dishes + `load_dishes()` hook for Week 2 `data/dishes.json`. |
| `spike_pymoo.py` | pymoo NSGA-II spike with lazy import; pure-Python NSGA-II fallback. Writes `spike_pymoo.csv`. |
| `baselines.py` | `random_search`, `greedy_search`, `exhaustive_search`, `nsga2_fallback`. |
| `test_smoke.py` | 9 assertion tests (`python backend/optim/test_smoke.py`). |

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

## Running

```bash
source .venv/bin/activate
PYTHONPATH=. python -m backend.optim.spike_pymoo     # spike (pymoo or fallback)
python backend/optim/test_smoke.py                    # smoke tests
```

`pymoo` is imported lazily. The Week-1 venv has **pydantic only** (no
`numpy`/`pymoo`), so the spike automatically uses the pure-Python NSGA-II
fallback in `baselines.py`. When pymoo is installed, the same problem is solved
by `pymoo.algorithms.moo.nsga2.NSGA2` and the spike reports `Engine: pymoo`.

## Expected output

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

`baselines.py` provides the Week-3 benchmark comparators. `exhaustive_search`
enumerates all `MEALS_PER_DAY`-meal combinations for one day (true small
exhaustive) and repeats the best day — deliberately variety-poor, so NSGA-II's
front should dominate it. `greedy_search` adds a single-slot local-search pass.

## Week 2 plans

1. Replace `TOY_DISHES` with `load_dishes("data/dishes.json")` (150–300 HPB/USDA
   dishes) — `Dish` contract already matches.
2. Support multi-dish meals in the GA encoding (currently one dish per meal).
3. Add nutrient-provenance flags for estimated K/P values.
4. Feed real APPROVED envelopes from the rule engine instead of the toy builder.
5. Harden the pymoo path (population/generation tuning) once `pymoo`+`numpy`
   are added to the environment.
