"""Evaluate the production recommendation core against independent exhaustive checks."""

from time import perf_counter
from types import SimpleNamespace

from careloop.evaluation.oracle import audit
from careloop.planning.recommendations import recommend_records


def replacement_options(case, original):
    for row in case["foods"]:
        if str(row["id"]) == original["food_id"]:
            continue
        food = row["body"]
        for portion in food["portions"]:
            amount = portion.get("grams" if food.get("basis", "g") == "g" else "millilitres")
            if amount is None:
                continue
            for scale in (0.5, 1, 1.5):
                from decimal import Decimal

                yield {
                    "day": original["day"],
                    "slot": original["slot"],
                    "item": original.get("item", 1),
                    "food_id": str(row["id"]),
                    "food_revision": row["latest_revision"],
                    "food": food,
                    "portion_id": portion["id"],
                    "scale": scale,
                    "quantity": str(Decimal(str(amount)) * Decimal(str(scale))),
                    "unit": food.get("basis", "g"),
                }


def benchmark(case, meals, *, limit=5, clusters=4):
    if not audit(meals, case)["valid"]:
        return {"state": "blocked", "reason": "No independently valid parent plan", "tasks": []}
    tasks = []
    plan = {"body": {"meals": meals}, "request": case["request"]}
    for index, original in enumerate(meals):
        feasible, choices = set(), {}
        for choice in replacement_options(case, original):
            candidate = [*meals]
            candidate[index] = choice
            key = (choice["food_id"], choice["portion_id"], choice["scale"])
            choices[key] = choice
            if audit(candidate, case)["valid"]:
                feasible.add(choice["food_id"])
        for method in ("nearest", "cluster", "same_category"):
            data = SimpleNamespace(
                day=original["day"],
                slot=original["slot"],
                item=original.get("item", 1),
                limit=limit,
                clusters=clusters,
                method=method,
            )
            started = perf_counter()
            result = recommend_records(
                plan, case["facts"], case["items"], case["foods"], data, index
            )
            elapsed = perf_counter() - started
            returned = set()
            audited = []
            for item in result["recommendations"]:
                key = (item["food_id"], item["portion_id"], item["scale"])
                candidate = [*meals]
                candidate[index] = choices[key]
                checked = audit(candidate, case)
                audited.append(
                    {"food_id": item["food_id"], "audit": checked, "target_fit": item["target_fit"]}
                )
                returned.add(item["food_id"])
            tasks.append(
                {
                    "index": index,
                    "method": method,
                    "seconds": elapsed,
                    "feasible_foods": len(feasible),
                    "returned_foods": len(returned),
                    "coverage_at_limit": len(returned & feasible) / len(feasible)
                    if feasible
                    else None,
                    "found_when_available": bool(returned & feasible) if feasible else None,
                    "invalid_suggestions": sum(not a["audit"]["valid"] for a in audited),
                    "audited": audited,
                    "result": result,
                }
            )
    return {
        "state": "completed",
        "case_id": case["id"],
        "tasks": tasks,
        "limitation": "Compatibility is limited to documented meal annotations; no taste labels.",
    }
