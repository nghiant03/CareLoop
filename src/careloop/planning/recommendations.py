from decimal import Decimal

from careloop.foods.clustering import fit, retrieve
from careloop.foods.models import Nutrients
from careloop.foods.service import planning_pool
from careloop.nutrition import target_value
from careloop.planning.checker import check_plan
from careloop.planning.search import MAX_SLOT_CANDIDATES, candidates, shortlist
from careloop.planning.service import begin, current_context, get_plan
from careloop.workflow import WorkflowError


def nutrient_delta(original, replacement):
    before_quantity = Decimal(str(original.get("quantity", original.get("grams"))))
    after_quantity = Decimal(replacement["quantity"])
    result = {}
    for key in Nutrients.model_fields:
        before = original["food"]["nutrients"].get(key)
        after = replacement["food"]["nutrients"].get(key)
        result[key] = (
            None
            if before is None or after is None
            else str(
                (Decimal(str(after)) * after_quantity - Decimal(str(before)) * before_quantity)
                / 100
            )
        )
    return result


def target_fit(totals, items):
    result = 0.0
    for item in items:
        action = item["action"]
        if action["kind"] == "ceiling":
            continue  # Scoring distance to a ceiling would reward higher intake.
        goal = action["amount"]
        if action["kind"] == "range":
            goal = (goal + action["upper"]) / 2
        actual = target_value(action, totals)
        if actual is None:
            return float("inf")
        distance = (
            max(goal - float(actual), 0)
            if action["kind"] == "minimum"
            else abs(float(actual) - goal)
        )
        result += distance / max(goal, 1)
    return result


def recommend(conn, plan_id, data):
    begin(conn, data)
    plan = get_plan(conn, plan_id)
    target, facts = current_context(conn, plan["target_id"], plan["target_revision"])
    if plan["needs_review"] or not plan["approved_at"]:
        raise WorkflowError(409, "Recommendations require a current approved plan")
    index = next(
        (
            i
            for i, meal in enumerate(plan["body"]["meals"])
            if meal["day"] == data.day
            and meal["slot"] == data.slot
            and meal.get("item", 1) == data.item
        ),
        None,
    )
    if index is None:
        raise WorkflowError(422, "Requested meal does not exist")
    original = plan["body"]["meals"][index]
    foods = [
        row
        for row in planning_pool(conn, data.food_ids, data.excluded_food_ids)
        if str(row["id"]) != original["food_id"]
    ]
    return recommend_records(
        plan,
        facts,
        target["body"]["items"],
        foods,
        data,
        index,
        automatic_pool=data.food_ids is None,
    )


def recommend_records(plan, facts, items, foods, data, index, *, automatic_pool=False):
    """Pure retrieval/checking shared by the approved workflow and frozen experiments."""
    original = plan["body"]["meals"][index]
    source = {
        "id": original["food_id"],
        "latest_revision": original["food_revision"],
        "body": original["food"],
    }
    foods = [row for row in foods if str(row["id"]) != original["food_id"]]
    model = fit([source, *foods], data.clusters)
    retrieved = retrieve(foods, source, model, data.method)
    options, excluded = candidates([row for row, _ in retrieved], [data.slot], facts, items)
    choices = options[data.slot]
    eligible_portions = len(choices)
    if automatic_pool and len(choices) > MAX_SLOT_CANDIDATES:
        meal_count = sum(m["day"] == data.day for m in plan["body"]["meals"])
        choices = shortlist(choices, [item["action"] for item in items], 1 / meal_count, facts)
    if len(choices) > MAX_SLOT_CANDIDATES:
        raise WorkflowError(422, f"Narrow the pool: at most {MAX_SLOT_CANDIDATES} portion choices")
    distances = {str(row["id"]): distance for row, distance in retrieved}
    accepted, rejected = [], []
    for choice in choices:
        meal = {**choice, "day": data.day, "item": data.item}
        meals = list(plan["body"]["meals"])
        meals[index] = meal
        check = check_plan(
            meals,
            plan["request"]["days"],
            plan["request"]["schedule"],
            facts,
            items,
            plan["request"].get("items_per_slot"),
        )
        selection = {
            "food_id": meal["food_id"],
            "food_revision": meal["food_revision"],
            "portion_id": meal["portion_id"],
            "scale": meal["scale"],
        }
        if not check["valid"]:
            rejected.append({**selection, "violations": check["violations"]})
            continue
        text = (meal["food"]["name"] + " " + meal["food"]["category"]).casefold()
        disliked = any(d.casefold() in text for d in facts.get("dislikes") or [])
        fit_score = target_fit(check["daily_totals"][str(data.day)], items)
        similarity = distances[meal["food_id"]]
        score = fit_score + 0.25 * disliked
        if data.method != "same_category":
            score += similarity
        accepted.append(
            {
                **selection,
                "name": meal["food"]["name"],
                "quantity": meal["quantity"],
                "unit": meal["unit"],
                "score": score,
                "target_fit": fit_score,
                "disliked": disliked,
                "nutrient_distance": similarity,
                "nutrient_delta": nutrient_delta(original, meal),
                "check": check,
                "substitution": {
                    "item": data.item,
                    "day": data.day,
                    "slot": data.slot,
                    "food_id": meal["food_id"],
                    "portion_id": meal["portion_id"],
                    "scale": meal["scale"],
                },
            }
        )
    accepted.sort(key=lambda r: (r["score"], r["food_id"], r["portion_id"], r["scale"]))
    best = {}
    for item in accepted:
        best.setdefault(item["food_id"], item)
    return {
        "method": data.method,
        "model": model,
        "pool_revisions": [
            {"food_id": str(row["id"]), "revision": row["latest_revision"]}
            for row in [source, *foods]
        ],
        "retrieved_foods": len(retrieved),
        "checked_portions": len(choices),
        "eligible_portions": eligible_portions,
        "shortlisted": eligible_portions > len(choices),
        "eligible_foods": len(best),
        "recommendations": list(best.values())[: data.limit],
        "excluded_foods": excluded,
        "rejected_portions": rejected,
        "approval_required": True,
        "infeasibility_proven": False,
    }
