"""Comparative search on explicitly supplied, provenance-bearing planning problems."""

import itertools
import math
import random
from time import perf_counter
from types import SimpleNamespace

from careloop.evaluation.oracle import audit
from careloop.planning.checker import preflight
from careloop.planning.search import OBJECTIVES, candidates, generate


def positions(case):
    request = case["request"]
    return [
        (day, slot, item)
        for day in range(1, request["days"] + 1)
        for slot in request["schedule"]
        for item in range(1, request.get("items_per_slot", {}).get(slot, 1) + 1)
    ]


def objective_score(result, objective):
    weights = OBJECTIVES[objective]
    return (
        weights[0] * result["nutrient_deviation"]
        + weights[1] * (result["disliked_items"] or 0)
        + weights[2] * result["repeated_items"]
    )


def signature(meals):
    return tuple(
        (m["day"], m["slot"], m.get("item", 1), m["food_id"], m["portion_id"], m["scale"])
        for m in meals
    )


def assess(alternatives, case):
    results = []
    for alternative in alternatives:
        result = audit(alternative["meals"], case)
        results.append(
            {
                **alternative,
                "independent_audit": result,
                "evaluation_score": objective_score(result, alternative["objective"]),
                "checker_agrees": alternative.get("check", {}).get("valid") == result["valid"]
                if "check" in alternative
                else None,
            }
        )
    return results


def sample_search(case, options, budget, seed=None, exact=False, seconds_limit=None):
    slots = positions(case)
    pools = [options[slot] for _, slot, _ in slots]
    size = math.prod(map(len, pools))
    if exact:
        choices = itertools.product(*pools)
    else:
        rng = random.Random(seed)
        choices = (tuple(rng.choice(pool) for pool in pools) for _ in range(budget))
    best, inspected = {}, 0
    started = perf_counter()
    for combination in choices:
        if not exact and seconds_limit is not None and perf_counter() - started >= seconds_limit:
            break
        inspected += 1
        meals = [
            {**choice, "day": day, "slot": slot, "item": item}
            for choice, (day, slot, item) in zip(combination, slots, strict=True)
        ]
        result = audit(meals, case)
        if not result["valid"]:
            continue
        for objective in OBJECTIVES:
            score = objective_score(result, objective)
            if objective not in best or score < best[objective][0]:
                best[objective] = (score, meals)
    return [{"objective": key, "meals": value[1]} for key, value in best.items()], {
        "complete_plans_checked": inspected,
        "search_space": size,
        "exhaustive": exact,
        "seconds_limit": seconds_limit,
    }


def benchmark(case, *, random_seeds=(17, 43, 91), random_budget=2000, exact_limit=100000):
    """No missing patient choices, target ranges or food annotations are synthesized."""
    if not case.get("provenance"):
        raise ValueError("Planning cases require source/annotation provenance")
    if not case.get("id") or not case.get("request", {}).get("days"):
        raise ValueError("Planning cases require an identity and a requested horizon")
    request = SimpleNamespace(**{"items_per_slot": {}, **case["request"]})
    issues = preflight(case["facts"], case["items"])
    options, excluded = candidates(case["foods"], request.schedule, case["facts"], case["items"])
    if issues or any(not values for values in options.values()):
        return {
            "id": case["id"],
            "state": "blocked",
            "blockers": issues,
            "empty_slots": [s for s, values in options.items() if not values],
            "excluded_foods": excluded,
            "methods": [],
        }
    methods = []
    for name, width in (("beam", 32), ("greedy", 1)):
        started = perf_counter()
        alternatives, metadata = generate(
            case["foods"], request, case["facts"], case["items"], beam_width=width
        )
        elapsed = perf_counter() - started
        methods.append(
            {
                "method": name,
                "seconds": elapsed,
                "metadata": metadata,
                "alternatives": assess(alternatives, case),
            }
        )
    # Compare random runs under the beam's observed wall-time ceiling, with a fixed work cap.
    # Record work units separately: complete-plan checks differ from partial-plan scoring.
    seconds_limit = methods[0]["seconds"]
    for seed in random_seeds:
        started = perf_counter()
        alternatives, metadata = sample_search(
            case, options, random_budget, seed, seconds_limit=seconds_limit
        )
        elapsed = perf_counter() - started
        methods.append(
            {
                "method": "random",
                "seed": seed,
                "seconds": elapsed,
                "metadata": metadata,
                "alternatives": assess(alternatives, case),
            }
        )
    size = math.prod(len(options[slot]) for _, slot, _ in positions(case))
    exact = {
        "state": "skipped",
        "reason": "Search space exceeds declared exact limit",
        "search_space": size,
        "limit": exact_limit,
    }
    if size <= exact_limit:
        started = perf_counter()
        alternatives, metadata = sample_search(case, options, exact_limit, exact=True)
        exact = {
            "state": "completed",
            "method": "exact",
            "seconds": perf_counter() - started,
            "metadata": metadata,
            "alternatives": assess(alternatives, case),
        }
        methods.append(exact)
    for method in methods:
        method["distinct_alternatives"] = len(
            {signature(a["meals"]) for a in method["alternatives"]}
        )
        for alternative in method["alternatives"]:
            reference = next(
                (
                    a
                    for a in exact.get("alternatives", [])
                    if a["objective"] == alternative["objective"]
                ),
                None,
            )
            alternative["absolute_optimality_gap"] = (
                alternative["evaluation_score"] - reference["evaluation_score"]
                if reference and alternative["independent_audit"]["valid"]
                else None
            )
    return {
        "id": case["id"],
        "state": "completed",
        "methods": methods,
        "exact": exact,
        "preferences_measured": case["facts"].get("dislikes") is not None,
        "budgets": {
            "beam_width": 32,
            "greedy_width": 1,
            "random_complete_plans": random_budget,
            "exact_limit": exact_limit,
        },
        "budget_note": "Random has the beam wall-time ceiling plus a fixed check cap; "
        "greedy uses width one. Work units differ; exact search is a separate reference.",
    }
