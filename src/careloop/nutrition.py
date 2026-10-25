"""Shared target semantics; percent energy is measured against actual daily energy."""

from decimal import Decimal

UNITS = {
    "energy": "kcal/day",
    "protein": "g/day",
    "carbohydrate": "g/day",
    "fat": "g/day",
    "saturated_fat": "g/day",
    "trans_fat": "g/day",
    "fibre": "g/day",
    "free_sugars": "g/day",
    "sodium": "mg/day",
    "potassium": "mg/day",
    "phosphorus": "mg/day",
    "fruit_and_vegetables": "g/day",
}
ENERGY_FACTORS = {
    "protein": 4,
    "carbohydrate": 4,
    "free_sugars": 4,
    "fat": 9,
    "saturated_fat": 9,
    "trans_fat": 9,
}
NUMERIC_KINDS = {"intake", "minimum", "ceiling", "range"}


def energy_target_issue(items):
    for item in items:
        action = item["action"]
        if (
            action["subject"] == "energy"
            and action["kind"] == "range"
            and action.get("unit") == "kcal/day"
            and action.get("amount") is not None
            and action.get("upper") is not None
            and 0 < action["amount"] <= action["upper"]
        ):
            return None
    return (
        "Enter a daily energy range in kcal/day (lower and upper values) in the energy "
        "target fields, then save and approve. An assessment note is not an energy target."
    )


def supported_unit(subject, unit):
    return (subject in UNITS and UNITS[subject] == unit) or (
        unit == "%energy" and subject in ENERGY_FACTORS
    )


def required_nutrients(action):
    return {action["subject"]} | ({"energy"} if action.get("unit") == "%energy" else set())


def food_values(food):
    return {
        **food["nutrients"],
        "fruit_and_vegetables": food.get("food_groups", {}).get("fruit_and_vegetables"),
    }


def target_value(action, totals):
    value = totals.get(action["subject"])
    if value is None:
        return None
    value = Decimal(str(value))
    if action.get("unit") == "%energy":
        energy = totals.get("energy")
        if energy is None or Decimal(str(energy)) <= 0:
            return None
        value = value * ENERGY_FACTORS[action["subject"]] * 100 / Decimal(str(energy))
    return value


def outside_bound(action, value):
    low = Decimal(str(action["amount"]))
    if action["kind"] == "minimum":
        return value < low
    if action["kind"] == "ceiling":
        return value >= low if action.get("upper_exclusive", False) else value > low
    if action["kind"] == "range":
        return not low <= value <= Decimal(str(action["upper"]))
    return False  # Historical intake actions remain soft goals.


def bounds(action):
    if action["kind"] == "minimum":
        return action["amount"], float("inf")
    if action["kind"] == "ceiling":
        return 0, action["amount"]
    if action["kind"] == "range":
        return action["amount"], action["upper"]
    return None


def incompatible(left, right):
    a, b = bounds(left), bounds(right)
    if not a or not b or left["unit"] != right["unit"]:
        return False
    low, high = max(a[0], b[0]), min(a[1], b[1])
    return low > high or (
        low == high
        and any(x.get("upper_exclusive", False) and x["amount"] == high for x in (left, right))
    )
