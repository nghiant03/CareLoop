"""Main + optional side search, scored against original approved aims.

Catalogue roles are explicitly heuristic, not verified recipe annotations.
MAX/exclusions remain hard; nutritional adequacy is a separate soft objective.
The canonical evaluator checks every candidate returned to the application.
"""
from collections import Counter
from time import perf_counter

import numpy as np

from .problem import NUTRIENT_KEYS, allowed_dishes, evaluate


def is_main(dish):
    return (dish.category not in {"dessert", "drink", "kopitiam"}
            and dish.nutrient("energy_kcal") >= 200 and dish.nutrient("protein_g") >= 5)


def is_side(dish):
    return (dish.nutrient("energy_kcal") <= 300
            and (dish.category in {"healthy", "soup", "cai_png"} or "vegetable" in dish.tags))


def complete_meals(plan, dishes):
    lookup = {d.dish_id: d for d in dishes}
    return bool(plan) and all(
        1 <= len(meal) <= 2 and is_main(lookup[meal[0]])
        and (len(meal) == 1 or is_side(lookup[meal[1]])) for meal in plan
    )


def improve_meals(result, envelope, dishes, seed=42):
    """Search complete meals with normalised, adequacy-first coordinate descent.

    Independent daily multistarts permit main/side replacements while preserving
    daily ceilings. Seven days are selected from the best daily candidates,
    with repetition as a tie-break. Search failure is explicitly not a proof
    of infeasibility for this richer encoding.
    """
    start = perf_counter()
    pool = sorted(allowed_dishes(envelope, dishes), key=lambda d: d.dish_id)
    main = [i for i, d in enumerate(pool) if is_main(d)]
    side = [i for i, d in enumerate(pool) if is_side(d)]
    empty = len(pool)
    metadata = {"meal_encoding": "main_optional_side", "seed": seed,
                "selection": "normalised_adequacy_first", "role_annotations": "heuristic"}
    if not main:
        return {**result, **metadata, "meal_complete": False}
    nutrients = np.array([[d.nutrient(k) for k in NUTRIENT_KEYS] for d in pool] + [[0.] * len(NUTRIENT_KEYS)])
    prices = np.array([d.price_sgd for d in pool] + [0.])
    constraints = list(envelope.targets)
    cols = [NUTRIENT_KEYS.index(c.nutrient.value) for c in constraints]
    aims = np.array([c.value for c in constraints])
    denom = np.maximum(aims, 1.)
    hard = np.array([c.kind.value == "max" for c in constraints])
    target = np.array([c.kind.value == "target" for c in constraints])

    def scores(totals, members):
        delta = totals[:, cols] - aims
        excess = np.where(hard, np.maximum(delta - 1e-9, 0.) / denom, 0.).sum(axis=1)
        relative = np.where(target, np.abs(delta), np.maximum(-delta, 0.)) / denom
        relative[:, hard] = 0.
        worst = relative.max(axis=1) if constraints else np.zeros(len(totals))
        mean = relative.sum(axis=1)
        repetitions = np.array([len([x for x in row if x != empty]) - len(set(row) - {empty}) for row in members])
        return np.column_stack((excess, worst, mean, repetitions, prices[members].sum(axis=1)))

    rng = np.random.default_rng(seed)
    choices = [np.array(main), np.array(side + [empty])] * 3
    candidates = {}
    for _ in range(32):
        member = np.array([rng.choice(options) for options in choices])
        for _ in range(12):
            changed = False
            for slot in rng.permutation(6):
                options = choices[slot]
                alternatives = np.tile(member, (len(options), 1))
                alternatives[:, slot] = options
                totals = nutrients[alternatives].sum(axis=1)
                values = scores(totals, alternatives)
                best = int(np.lexsort(tuple(values[:, i] for i in reversed(range(5))))[0])
                old = member[slot]
                member = alternatives[best].copy()
                changed |= old != member[slot]
            if not changed:
                break
        day = [[pool[i].dish_id for i in member[j:j + 2] if i != empty] for j in (0, 2, 4)]
        _, violations = evaluate(day, envelope, dishes)
        if not violations:
            candidates[tuple(member)] = (scores(nutrients[member].sum(axis=0)[None, :], member[None, :])[0], day)
    if not candidates:
        # The old one-dish proof cannot prove anything about this encoding.
        return {**result, **metadata, "meal_complete": False,
                "infeasibility_status": None if result.get("feasible") else "search_exhausted",
                "infeasibility_reason": None if result.get("feasible") else "No complete meal plan found by search."}
    used = Counter()
    plan = []
    for _ in range(7):
        _, day = min(candidates.values(), key=lambda pair: (
            *pair[0][:3], sum(used[d] for meal in pair[1] for d in meal), *pair[0][3:]))
        plan.extend([list(meal) for meal in day])
        used.update(d for meal in day for d in meal)
    objectives, violations = evaluate(plan, envelope, dishes)
    assert not violations
    return {**result, **metadata, "plan": plan, "objectives": objectives,
            "feasible": True, "meal_complete": True, "violation_count": 0, "violations": [],
            "engine": "adequacy-composition", "infeasibility_reason": None,
            "infeasibility_status": None, "exact_reference": None,
            "runtime_ms": round((result.get("runtime_ms") or 0) + (perf_counter() - start) * 1000, 3)}
