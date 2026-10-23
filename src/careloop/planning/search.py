from careloop.foods.portions import source_portions
from careloop.planning.checker import check_plan, food_restrictions, portion_quantity, preflight

OBJECTIVES = {
    "nutrient_fit": (1.0, 0.05, 0.02),
    "preference_match": (0.3, 1.0, 0.05),
    "variety": (0.3, 0.05, 1.0),
}
BEAM_WIDTH = 32
MAX_SLOT_CANDIDATES = 500


def candidates(foods, schedule, facts, items):
    options = {slot: [] for slot in schedule}
    excluded = []
    required = {item["action"]["subject"] for item in items}
    for row in foods:
        food = row["body"]
        reasons = food_restrictions(food, facts)
        missing = sorted(key for key in required if food["nutrients"].get(key) is None)
        if missing:
            reasons.append("Unknown nutrients: " + ", ".join(missing))
        portions = source_portions(food)
        if not portions:
            reasons.append("No source portion with a usable quantity matching the nutrient basis")
        if reasons:
            excluded.append({"food_id": str(row["id"]), "reasons": reasons})
            continue
        for slot in schedule:
            for portion_id in sorted(p["id"] for p in portions):
                for scale in (0.5, 1.0, 1.5):
                    options[slot].append(
                        {
                            "slot": slot,
                            "food_id": str(row["id"]),
                            "food_revision": row["latest_revision"],
                            "food": food,
                            "portion_id": portion_id,
                            "scale": scale,
                            "quantity": str(portion_quantity(food, portion_id, scale)),
                            "unit": food.get("basis", "g"),
                        }
                    )
    return options, excluded


def rank(meals, actions, fraction, facts, previous, objective):
    fit = violation = 0.0
    for action in actions:
        total = sum(
            float(m["quantity"]) * m["food"]["nutrients"][action["subject"]] / 100 for m in meals
        )
        low = action["amount"] * fraction
        if action["kind"] == "range":
            high = action["upper"] * fraction
            middle = (low + high) / 2
            fit += abs(total - middle) / max(middle, 1)
            violation += max(low - total, total - high, 0) / max(high, 1)
        elif action["kind"] == "ceiling":
            violation += max(total - low, 0) / max(low, 1)
        else:
            fit += abs(total - low) / max(low, 1)
    dislikes = [d.casefold() for d in facts.get("dislikes") or []]
    disliked = sum(
        any(d in (m["food"]["name"] + " " + m["food"]["category"]).casefold() for d in dislikes)
        for m in meals
    )
    ids = [m["food_id"] for m in meals]
    repeated = len(ids) - len(set(ids)) + sum(food_id in previous for food_id in ids)
    weights = OBJECTIVES[objective]
    return 1000 * violation + weights[0] * fit + weights[1] * disliked + weights[2] * repeated


def generate(foods, request, facts, items, *, beam_width=BEAM_WIDTH):
    if not isinstance(beam_width, int) or not 1 <= beam_width <= BEAM_WIDTH:
        raise ValueError(f"Beam width must be between 1 and {BEAM_WIDTH}")
    issues = preflight(facts, items)
    if issues:
        return [], {"status": "blocked", "blockers": issues}
    options, excluded = candidates(foods, request.schedule, facts, items)
    for slot, choices in options.items():
        if not choices:
            issues.append(f"No eligible candidate in the selected food pool for {slot}")
        elif len(choices) > MAX_SLOT_CANDIDATES:
            issues.append(
                f"Narrow the food pool for {slot}: candidate limit is {MAX_SLOT_CANDIDATES}"
            )
        elif len({choice["food_id"] for choice in choices}) < request.items_per_slot.get(slot, 1):
            issues.append(f"Not enough distinct eligible foods for {slot}'s requested item count")
    if issues:
        return [], {"status": "blocked", "blockers": issues, "excluded_foods": excluded}
    alternatives = []
    evaluations = 0
    positions = [
        (slot, item)
        for slot in request.schedule
        for item in range(1, request.items_per_slot.get(slot, 1) + 1)
    ]
    actions = [item["action"] for item in items]
    for objective in OBJECTIVES:
        plan, used = [], set()
        for day in range(1, request.days + 1):
            beam = [[]]
            for position, (slot, item) in enumerate(positions, 1):
                expanded = [
                    partial + [{**choice, "day": day, "item": item}]
                    for partial in beam
                    for choice in options[slot]
                    if not any(
                        m["slot"] == slot and m["food_id"] == choice["food_id"] for m in partial
                    )
                ]
                expanded.sort(
                    key=lambda meals: rank(
                        meals, actions, position / len(positions), facts, used, objective
                    )
                )
                evaluations += len(expanded)
                beam = expanded[:beam_width]
            valid = [
                meals
                for meals in beam
                if check_plan(
                    [{**m, "day": 1} for m in meals],
                    1,
                    request.schedule,
                    facts,
                    items,
                    request.items_per_slot,
                )["valid"]
            ]
            chosen = (valid or beam)[0]
            plan.extend(chosen)
            used.update(m["food_id"] for m in chosen)
        check = check_plan(
            plan, request.days, request.schedule, facts, items, request.items_per_slot
        )
        alternatives.append({"objective": objective, "meals": plan, "check": check})
    return alternatives, {
        "status": "drafts_available"
        if any(a["check"]["valid"] for a in alternatives)
        else "search_failed",
        "excluded_foods": excluded,
        "algorithm": "beam-source-portions-v3",
        "beam_width": beam_width,
        "scored_partial_plans": evaluations,
        "infeasibility_proven": False,
    }
