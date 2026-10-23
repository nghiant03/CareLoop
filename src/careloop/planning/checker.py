"""Independent Decimal arithmetic and mandatory checks, reused at approval.

Search scores are not evidence of validity. Every returned plan is recomputed here.
"""

from decimal import Decimal
from typing import get_args

from careloop.foods.models import Allergen, Nutrients
from careloop.patients.engine import UNITS


def preflight(facts, items):
    issues = []
    for fact in ("allergies", "vegetarian", "include_eggs", "include_dairy"):
        if facts.get(fact) is None:
            issues.append(f"Clarify patient {fact}")
    for allergy in facts.get("allergies") or []:
        if allergy not in get_args(Allergen):
            issues.append(f"Unsupported allergy label: {allergy}; record a supported exact label")
    actions = [item["action"] for item in items]
    if not any(a["subject"] == "energy" and a["kind"] == "range" for a in actions):
        issues.append("A clinician-approved daily energy range is required for planning")
    for action in actions:
        if action["kind"] not in {"range", "ceiling", "intake"}:
            issues.append(
                f"Planner cannot enforce target action: {action['kind']} / {action['subject']}"
            )
        elif UNITS.get(action["subject"]) != action["unit"]:
            issues.append(
                f"Unsupported target nutrient/unit: {action['subject']} / {action['unit']}"
            )
    return issues


def food_restrictions(food, facts):
    issues = []
    for allergy in facts.get("allergies") or []:
        status = food["allergen_status"].get(allergy, "unknown")
        if status != "absent":
            issues.append(f"{allergy}: {status}")
    if facts.get("vegetarian") is True and food["vegetarian"] is not True:
        issues.append("Vegetarian suitability not established")
    if facts.get("include_eggs") is False and food["contains_egg"] is not False:
        issues.append("Egg exclusion not established")
    if facts.get("include_dairy") is False and food["contains_dairy"] is not False:
        issues.append("Dairy exclusion not established")
    return issues


def portion_quantity(food, portion_id, scale):
    if scale not in (0.5, 1.0, 1.5) or portion_id not in food["planning_portions"]:
        raise ValueError("Unreviewed portion or unsupported scale")
    portion = next((p for p in food["portions"] if p["id"] == portion_id), None)
    if portion is None:
        raise ValueError("Portion not found")
    field = "grams" if food.get("basis", "g") == "g" else "millilitres"
    if portion.get(field) is None:
        raise ValueError("Portion unit does not match nutrient basis")
    return Decimal(str(portion[field])) * Decimal(str(scale))


def check_plan(meals, days, schedule, facts, items, items_per_slot=None):
    violations = [{"issue": message} for message in preflight(facts, items)]
    counts = items_per_slot or {}
    expected = {
        (day, slot, item)
        for day in range(1, days + 1)
        for slot in schedule
        for item in range(1, counts.get(slot, 1) + 1)
    }
    actual = [(m["day"], m["slot"], m.get("item", 1)) for m in meals]
    if len(actual) != len(expected) or set(actual) != expected:
        violations.append({"issue": "Meal coverage does not match requested days/schedule"})
    seen_foods = set()
    for meal in meals:
        key = (meal["day"], meal["slot"], meal.get("food_id"))
        if meal.get("food_id") and key in seen_foods:
            violations.append(
                {
                    "day": meal["day"],
                    "slot": meal["slot"],
                    "issue": "Repeated food within a meal; adjust its portion instead",
                }
            )
        seen_foods.add(key)
    totals = {
        day: {key: Decimal(0) for key in Nutrients.model_fields} for day in range(1, days + 1)
    }
    meal_totals = {
        day: {slot: {key: Decimal(0) for key in Nutrients.model_fields} for slot in schedule}
        for day in totals
    }
    for meal in meals:
        day, slot, food = meal["day"], meal["slot"], meal["food"]
        if day not in totals:
            continue
        for issue in food_restrictions(food, facts):
            violations.append({"day": day, "slot": slot, "issue": issue})
        if slot not in food["meal_slots"]:
            violations.append(
                {"day": day, "slot": slot, "issue": "Food not reviewed for this slot"}
            )
        try:
            quantity = portion_quantity(food, meal["portion_id"], meal["scale"])
        except ValueError as exc:
            violations.append({"day": day, "slot": slot, "issue": str(exc)})
            continue
        # Older stored g-based snapshots used the grams key; preserve their meaning.
        recorded = meal.get("quantity", meal.get("grams"))
        if Decimal(str(recorded)) != quantity or meal.get("unit", "g") != food.get("basis", "g"):
            violations.append({"day": day, "slot": slot, "issue": "Portion quantity/unit mismatch"})
        for nutrient in Nutrients.model_fields:
            value = food["nutrients"].get(nutrient)
            if value is None or totals[day][nutrient] is None:
                totals[day][nutrient] = None
            else:
                totals[day][nutrient] += Decimal(str(value)) * quantity / Decimal(100)
            if slot in meal_totals[day]:
                slot_totals = meal_totals[day][slot]
                if value is None or slot_totals[nutrient] is None:
                    slot_totals[nutrient] = None
                else:
                    slot_totals[nutrient] += Decimal(str(value)) * quantity / Decimal(100)
    for day, nutrients in totals.items():
        for item in items:
            action = item["action"]
            if action["kind"] not in {"range", "ceiling", "intake"}:
                continue
            value = nutrients.get(action["subject"])
            if value is None:
                violations.append(
                    {"day": day, "nutrient": action["subject"], "issue": "Unknown total"}
                )
                continue
            lower = Decimal(str(action["amount"]))
            violated = (action["kind"] == "ceiling" and value > lower) or (
                action["kind"] == "range" and not lower <= value <= Decimal(str(action["upper"]))
            )
            if violated:
                violations.append(
                    {
                        "day": day,
                        "nutrient": action["subject"],
                        "issue": "Outside approved bound",
                        "actual": str(value),
                        "kind": action["kind"],
                        "amount": action["amount"],
                        "upper": action.get("upper"),
                    }
                )
    return {
        "valid": not violations,
        "violations": violations,
        "meal_totals": {
            str(day): {
                slot: {
                    key: str(value) if value is not None else None for key, value in values.items()
                }
                for slot, values in slots.items()
            }
            for day, slots in meal_totals.items()
        },
        "daily_totals": {
            str(day): {
                key: str(value) if value is not None else None for key, value in nutrients.items()
            }
            for day, nutrients in totals.items()
        },
    }
