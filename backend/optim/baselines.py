"""Baseline search strategies for the CareLoop meal optimiser.

Search methods share ``_result``'s plan, objective, violation, front, and runtime
fields. ``feasible`` requires both hard compliance and actual meal delivery.
The pure-Python NSGA-II approximation uses constraint dominance.

Bounded exhaustive search is a baseline, not the exact reference. Use
``exact_reference.one_day_exact`` for exhaustive single-dish verdicts.
"""

from __future__ import annotations

import itertools
import random
import time

from .problem import (
    DAYS,
    MEALS_PER_DAY,
    NUTRIENT_KEYS,
    OBJECTIVE_NAMES,
    SLOTS,
    TAG_PREFERENCE,
    ConstraintKind,
    allowed_dishes,
    dish_lookup,
    evaluate,
    scalar_score,
    violation_magnitude,
)


def _make_result(
    method: str,
    plan: list[list[str]],
    envelope,
    dishes,
    evaluations: int,
    runtime_ms: float,
    front: list[dict] | None = None,
    front_size: int = 0,
) -> dict:
    """Assemble the standard result dict, gating ``feasible`` on delivery.

    The canonical evaluator intentionally accepts empty meal geometry (zero
    dishes violate nothing), so an empty plan must be reported here as an
    explicit search failure rather than a feasible result: delivery success
    requires meals in addition to hard-constraint satisfaction.
    """
    objectives, violations = evaluate(plan, envelope, dishes)
    if not any(meal for meal in plan):
        violations.append(
            {
                "type": "search_failure",
                "amount": float("inf"),
                "detail": (
                    f"{method} search delivered no meals (empty allowed pool "
                    "or failed construction); this is a search failure, not "
                    "a feasible empty plan"
                ),
            }
        )
    return {
        "method": method,
        "plan": plan,
        "objectives": objectives,
        "violations": violations,
        "violation_count": len(violations),
        "feasible": len(violations) == 0,
        "evaluations": evaluations,
        "runtime_ms": round(runtime_ms, 3),
        "front": front or [],
        "front_size": front_size,
    }


def _rank_key(objectives: dict, violations: list[dict]) -> tuple:
    return (len(violations), scalar_score(objectives))


def _decode(indices, pool: list[str]) -> list[list[str]]:
    return [[pool[i]] for i in indices]


def _repair_plan(envelope, dishes, plan, pool, max_passes: int = 8) -> list[list[str]]:
    """Local-search repair: single-slot swaps that lexicographically reduce
    ``(violation_count, violation_magnitude, scalar_score)``.

    Search stops after ``max_passes`` or when no improving swap exists. This
    heuristic can stop infeasible; it is not a complete feasibility constructor.
    """
    objectives, violations = evaluate(plan, envelope, dishes)
    current = (len(violations), violation_magnitude(violations), scalar_score(objectives))
    for _ in range(max_passes):
        improved = False
        for slot in range(len(plan)):
            for did in pool:
                if plan[slot] == [did]:
                    continue
                trial = [meal[:] for meal in plan]
                trial[slot] = [did]
                o, v = evaluate(trial, envelope, dishes)
                key = (len(v), violation_magnitude(v), scalar_score(o))
                if key < current:
                    plan = trial
                    current = key
                    improved = True
        if not improved:
            break
    return plan


def random_search(
    envelope, dishes, n_iter: int = 500, seed: int = 0, slots: int = SLOTS
) -> dict:
    t0 = time.perf_counter()
    pool = [d.dish_id for d in allowed_dishes(envelope, dishes)]
    if not pool:
        return _make_result("random", [], envelope, dishes, 0, 0.0)
    rng = random.Random(seed)
    best_plan: list[list[str]] = []
    best_key = None
    for _ in range(n_iter):
        indices = [rng.randrange(len(pool)) for _ in range(slots)]
        plan = _decode(indices, pool)
        objectives, violations = evaluate(plan, envelope, dishes)
        key = _rank_key(objectives, violations)
        if best_key is None or key < best_key:
            best_key = key
            best_plan = plan
    runtime = (time.perf_counter() - t0) * 1000.0
    return _make_result("random", best_plan, envelope, dishes, n_iter, runtime)


def _greedy_score(totals, meals_done, envelope, dish, pool_max) -> float:
    """Lower is better. Penalises MAX overruns, optimistic MIN shortfalls."""
    penalty = 0.0
    for c in envelope.targets:
        key = c.nutrient.value
        if c.kind == ConstraintKind.MAX:
            over = totals[key] - c.value
            if over > 0:
                penalty += over * 10.0
            else:
                # Gently prefer headroom rather than eating the whole ceiling.
                penalty += 0.02 * totals[key] / max(c.value, 1.0)
        elif c.kind == ConstraintKind.MIN:
            remaining = MEALS_PER_DAY - meals_done
            best_possible = totals[key] + remaining * pool_max[key]
            if best_possible < c.value:
                penalty += (c.value - best_possible) * 5.0
    penalty += 0.05 * dish.price_sgd
    penalty += 0.2 * (-sum(TAG_PREFERENCE.get(t, 0.0) for t in dish.tags))
    return penalty


def greedy_search(
    envelope, dishes, seed: int = 0, slots: int = SLOTS, max_passes: int = 4
) -> dict:
    t0 = time.perf_counter()
    lookup = dish_lookup(dishes)
    pool = [d.dish_id for d in allowed_dishes(envelope, dishes)]
    if not pool:
        return _make_result("greedy", [], envelope, dishes, 0, 0.0)
    n_days = slots // MEALS_PER_DAY
    pool_max = {k: max(lookup[d].nutrient(k) for d in pool) for k in NUTRIENT_KEYS}
    evaluations = 0

    plan: list[list[str]] = []
    for _day in range(n_days):
        running = {k: 0.0 for k in NUTRIENT_KEYS}
        for meal_index in range(MEALS_PER_DAY):
            best_score = None
            best_dish = None
            for did in pool:
                dish = lookup[did]
                trial = {k: running[k] + dish.nutrient(k) for k in NUTRIENT_KEYS}
                score = _greedy_score(trial, meal_index + 1, envelope, dish, pool_max)
                evaluations += 1
                if best_score is None or score < best_score:
                    best_score = score
                    best_dish = did
            assert best_dish is not None  # The allowed pool is nonempty.
            plan.append([best_dish])
            for k in NUTRIENT_KEYS:
                running[k] += lookup[best_dish].nutrient(k)

    # Local search: try every single-slot swap, keep lexicographic improvements.
    objectives, violations = evaluate(plan, envelope, dishes)
    evaluations += 1
    current = _rank_key(objectives, violations)
    for _ in range(max_passes):
        improved = False
        for slot in range(len(plan)):
            for did in pool:
                if plan[slot] == [did]:
                    continue
                trial = [meal[:] for meal in plan]
                trial[slot] = [did]
                o, v = evaluate(trial, envelope, dishes)
                evaluations += 1
                key = _rank_key(o, v)
                if key < current:
                    plan = trial
                    current = key
                    improved = True
        if not improved:
            break

    runtime = (time.perf_counter() - t0) * 1000.0
    return _make_result("greedy", plan, envelope, dishes, evaluations, runtime)


def exhaustive_search(
    envelope, dishes, max_combos: int = 100_000, seed: int = 0
) -> dict:
    """Score at most ``max_combos`` one-day combinations and repeat the best day.

    ``search_complete`` is False when the cap truncates enumeration. This
    baseline does not optimize horizon variety or prove truncated-search failure.
    """
    t0 = time.perf_counter()
    pool = [d.dish_id for d in allowed_dishes(envelope, dishes)]
    if not pool:
        result = _make_result("exhaustive", [], envelope, dishes, 0, 0.0)
        result["search_complete"] = True
        return result
    evaluations = 0
    best_key = None
    best_day = None
    combos = itertools.islice(
        itertools.product(range(len(pool)), repeat=MEALS_PER_DAY), max_combos
    )
    for combo in combos:
        day_plan = [[pool[i]] for i in combo]
        objectives, violations = evaluate(day_plan, envelope, dishes)
        evaluations += 1
        key = _rank_key(objectives, violations)
        if best_key is None or key < best_key:
            best_key = key
            best_day = day_plan
    full_plan = [meal[:] for _ in range(DAYS) for meal in (best_day or [])]
    runtime = (time.perf_counter() - t0) * 1000.0
    result = _make_result("exhaustive", full_plan, envelope, dishes, evaluations, runtime)
    # Nothing to enumerate is vacuously complete; otherwise the enumeration is
    # complete only when the cap did not stop it early.
    result["search_complete"] = evaluations >= len(pool) ** MEALS_PER_DAY
    return result


def _dominates(a: tuple, b: tuple) -> bool:
    return all(x <= y + 1e-12 for x, y in zip(a, b)) and any(
        x < y - 1e-12 for x, y in zip(a, b)
    )


def _cdominates(a: tuple, b: tuple) -> bool:
    """Constraint-dominance on vectors ``(violation_count, magnitude, *objectives)``.

    Feasible beats infeasible. Rank two infeasible plans by violation count,
    then magnitude. Apply objective Pareto dominance only when both are feasible
    or their violation count and magnitude tie.
    """
    a_feasible = a[0] <= 0.0
    b_feasible = b[0] <= 0.0
    if a_feasible and not b_feasible:
        return True
    if b_feasible and not a_feasible:
        return False
    if not a_feasible and not b_feasible:
        a_viol = (a[0], a[1])
        b_viol = (b[0], b[1])
        if a_viol < b_viol:
            return True
        if b_viol < a_viol:
            return False
    return _dominates(a[2:], b[2:])


def _fast_nondominated_sort(vectors: list[tuple]) -> list[list[int]]:
    n = len(vectors)
    dominated: list[list[int]] = [[] for _ in range(n)]
    counts = [0] * n
    fronts: list[list[int]] = [[]]
    for p in range(n):
        for q in range(n):
            if p == q:
                continue
            if _cdominates(vectors[p], vectors[q]):
                dominated[p].append(q)
            elif _cdominates(vectors[q], vectors[p]):
                counts[p] += 1
        if counts[p] == 0:
            fronts[0].append(p)
    i = 0
    while fronts[i]:
        nxt: list[int] = []
        for p in fronts[i]:
            for q in dominated[p]:
                counts[q] -= 1
                if counts[q] == 0:
                    nxt.append(q)
        i += 1
        fronts.append(nxt)
    return fronts[:-1]


def _crowding(front: list[int], vectors: list[tuple]) -> dict[int, float]:
    dist = {i: 0.0 for i in front}
    if not front:
        return dist
    m = len(vectors[0])
    for k in range(m):
        order = sorted(front, key=lambda i: vectors[i][k])
        dist[order[0]] = float("inf")
        dist[order[-1]] = float("inf")
        lo, hi = vectors[order[0]][k], vectors[order[-1]][k]
        if hi - lo < 1e-12:
            continue
        for j in range(1, len(order) - 1):
            dist[order[j]] += (vectors[order[j + 1]][k] - vectors[order[j - 1]][k]) / (
                hi - lo
            )
    return dist


def nsga2_fallback(
    envelope,
    dishes,
    pop_size: int = 40,
    n_gen: int = 80,
    seed: int = 42,
    slots: int = SLOTS,
) -> dict:
    t0 = time.perf_counter()
    pool = [d.dish_id for d in allowed_dishes(envelope, dishes)]
    n = len(pool)
    if n == 0:
        return _make_result("nsga2_fallback", [], envelope, dishes, 0, 0.0)

    rng = random.Random(seed)
    cache: dict[tuple, tuple] = {}

    def info(ind: list[int]):
        key = tuple(ind)
        got = cache.get(key)
        if got is None:
            got = evaluate(_decode(ind, pool), envelope, dishes)
            cache[key] = got
        return got

    def vector(ind: list[int]) -> tuple:
        objectives, violations = info(ind)
        return (
            float(len(violations)),
            violation_magnitude(violations),
        ) + tuple(objectives[k] for k in OBJECTIVE_NAMES)

    pop = [[rng.randrange(n) for _ in range(slots)] for _ in range(pop_size)]
    for ind in pop:
        info(ind)

    for _gen in range(n_gen):
        vectors = [vector(i) for i in pop]
        fronts = _fast_nondominated_sort(vectors)
        rank: dict[int, int] = {}
        crowd: dict[int, float] = {}
        for r, front in enumerate(fronts):
            for i in front:
                rank[i] = r
            crowd.update(_crowding(front, vectors))

        def select(rank: dict[int, int] = rank, crowd: dict[int, float] = crowd) -> int:
            a, b = rng.randrange(pop_size), rng.randrange(pop_size)
            if rank[a] != rank[b]:
                return a if rank[a] < rank[b] else b
            return a if crowd.get(a, 0.0) >= crowd.get(b, 0.0) else b

        offspring: list[list[int]] = []
        while len(offspring) < pop_size:
            p1 = pop[select()]
            p2 = pop[select()]
            child = [p1[j] if rng.random() < 0.5 else p2[j] for j in range(slots)]
            for j in range(slots):
                if rng.random() < 1.0 / slots:
                    child[j] = rng.randrange(n)
            offspring.append(child)
        for ind in offspring:
            info(ind)

        combined = pop + offspring
        cvectors = [vector(i) for i in combined]
        cfronts = _fast_nondominated_sort(cvectors)
        newpop: list[list[int]] = []
        for front in cfronts:
            cd = _crowding(front, cvectors)
            if len(newpop) + len(front) <= pop_size:
                for i in front:
                    newpop.append(combined[i])
            else:
                order = sorted(front, key=lambda i: cd[i], reverse=True)
                for i in order[: pop_size - len(newpop)]:
                    newpop.append(combined[i])
                break
        pop = newpop

    vectors = [vector(i) for i in pop]
    fronts = _fast_nondominated_sort(vectors)
    front0 = fronts[0] if fronts else []

    # Pick the most promising individual (fewest violations, then smallest
    # magnitude, then best scalar), repair it, and use it as the returned plan.
    ranked = sorted(
        range(len(pop)),
        key=lambda i: (
            len(info(pop[i])[1]),
            violation_magnitude(info(pop[i])[1]),
            scalar_score(info(pop[i])[0]),
        ),
    )
    best_ind = pop[ranked[0]] if ranked else None
    repaired_plan = (
        _repair_plan(envelope, dishes, _decode(best_ind, pool), pool)
        if best_ind is not None
        else []
    )

    front_entries: list[dict] = []
    seen: set[tuple] = set()
    for i in front0:
        objectives, violations = info(pop[i])
        key = tuple(pop[i])
        seen.add(key)
        front_entries.append(
            {
                "plan": _decode(pop[i], pool),
                "objectives": objectives,
                "violation_count": len(violations),
                "feasible": len(violations) == 0,
            }
        )
    # Ensure the repaired plan is represented in the front record.
    repaired_objectives, repaired_violations = evaluate(repaired_plan, envelope, dishes)
    if best_ind is None or tuple(best_ind) not in seen or repaired_violations != info(best_ind)[1]:
        front_entries.append(
            {
                "plan": repaired_plan,
                "objectives": repaired_objectives,
                "violation_count": len(repaired_violations),
                "feasible": len(repaired_violations) == 0,
            }
        )

    feasible = [e for e in front_entries if e["feasible"]]
    if feasible:
        best = min(feasible, key=lambda e: scalar_score(e["objectives"]))
    elif front_entries:
        best = min(
            front_entries, key=lambda e: (e["violation_count"], scalar_score(e["objectives"]))
        )
    else:
        best = None

    runtime = (time.perf_counter() - t0) * 1000.0
    if best is None:
        return _make_result("nsga2_fallback", [], envelope, dishes, len(cache), runtime)
    return _make_result(
        "nsga2_fallback",
        best["plan"],
        envelope,
        dishes,
        len(cache),
        runtime,
        front=front_entries,
        front_size=len(front_entries),
    )


__all__ = [
    "exhaustive_search",
    "greedy_search",
    "nsga2_fallback",
    "random_search",
]
