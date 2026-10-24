"""Independent bounded-plan audit; deliberately does not call the planner checker."""

from decimal import Decimal


def audit(meals, case):
    request, facts = case["request"], case["facts"]
    foods = {str(row["id"]): row for row in case["foods"]}
    actions = [item["action"] for item in case["items"]]
    expected = {
        (day, slot, item)
        for day in range(1, request["days"] + 1)
        for slot in request["schedule"]
        for item in range(1, request.get("items_per_slot", {}).get(slot, 1) + 1)
    }
    actual = [(m["day"], m["slot"], m.get("item", 1)) for m in meals]
    violations = []
    if len(actual) != len(expected) or set(actual) != expected:
        violations.append("schedule_coverage")
    required_facts = ("allergies", "vegetarian")
    violations.extend(f"unknown:{key}" for key in required_facts if facts.get(key) is None)
    if not any(a["subject"] == "energy" and a["kind"] == "range" for a in actions):
        violations.append("missing_energy_range")
    nutrients = {a["subject"] for a in actions}
    totals = {day: dict.fromkeys(nutrients, Decimal(0)) for day in range(1, request["days"] + 1)}
    seen, identities, disliked = set(), [], 0
    for meal in meals:
        identity = str(meal["food_id"])
        row = foods.get(identity)
        if row is None:
            violations.append("outside_pool")
            continue
        food = row["body"]
        day, slot = meal["day"], meal["slot"]
        key = (day, slot, identity)
        if key in seen:
            violations.append("duplicate_within_meal")
        seen.add(key)
        identities.append(identity)
        if meal.get("food_revision") != row["latest_revision"] or meal["food"] != food:
            violations.append("food_snapshot_mismatch")
        for allergy in facts.get("allergies") or []:
            if food["allergen_status"].get(allergy) != "absent":
                violations.append("allergen_not_absent")
        if facts.get("vegetarian") is True and food["vegetarian"] is not True:
            violations.append("vegetarian_not_established")
        portion = next((p for p in food["portions"] if p["id"] == meal["portion_id"]), None)
        basis = food.get("basis", "g")
        amount = (portion or {}).get("grams" if basis == "g" else "millilitres")
        if (
            amount is None
            or basis not in {"g", "ml"}
            or (portion or {}).get("millilitres" if basis == "g" else "grams") is not None
            or meal["scale"] not in (0.5, 1, 1.5)
        ):
            violations.append("unusable_source_portion")
            continue
        if not Decimal(str(amount)).is_finite() or not 0 < Decimal(str(amount)) <= 10000:
            violations.append("unusable_source_portion")
            continue
        quantity = Decimal(str(amount)) * Decimal(str(meal["scale"]))
        if Decimal(str(meal["quantity"])) != quantity or meal["unit"] != basis:
            violations.append("quantity_or_unit_mismatch")
        for nutrient in nutrients:
            if day not in totals:
                continue
            value = food["nutrients"].get(nutrient)
            if value is None or totals[day][nutrient] is None:
                totals[day][nutrient] = None
            else:
                totals[day][nutrient] += Decimal(str(value)) * quantity / 100
        text = (food["name"] + " " + food["category"]).casefold()
        disliked += any(d.casefold() in text for d in facts.get("dislikes") or [])
    fit = Decimal(0)
    for values in totals.values():
        for action in actions:
            value = values[action["subject"]]
            if value is None:
                violations.append("unknown_target_nutrient")
                continue
            lower = Decimal(str(action["amount"]))
            kind = action["kind"]
            if kind == "ceiling":
                if value > lower:
                    violations.append("ceiling_violation")
            elif kind in ("range", "intake"):
                goal = lower
                if kind == "range":
                    upper = Decimal(str(action["upper"]))
                    if not lower <= value <= upper:
                        violations.append("range_violation")
                    goal = (lower + upper) / 2
                fit += abs(value - goal) / max(goal, 1)
            else:
                violations.append("unsupported_action")
    return {
        "valid": not violations,
        "violations": violations,
        "daily_totals": {
            str(day): {
                key: str(value) if value is not None else None for key, value in values.items()
            }
            for day, values in totals.items()
        },
        "nutrient_deviation": float(fit / request["days"]),
        "distinct_foods": len(set(identities)),
        "repeated_items": len(identities) - len(set(identities)),
        "disliked_items": disliked if facts.get("dislikes") is not None else None,
    }
