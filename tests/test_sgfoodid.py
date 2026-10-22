from decimal import Decimal

import pytest
from pydantic import ValidationError

from careloop.adapters.sgfoodid import MAPPING, normalize
from careloop.foods.models import FoodBody, Portion
from careloop.planning.checker import check_plan, portion_quantity


def source_row(name="Steamed chicken rice", basis="Per 100g", serving="1 plate(s) = 346g"):
    row = {
        column + suffix: "-"
        for column in MAPPING.values()
        for suffix in (" - Per 100", " - Per Serving")
    }
    row.update(
        {
            "Food Name": name,
            "Food Group": "Test group",
            "Food Subgroup": "Test subgroup",
            "Per 100 Unit": basis,
            "Default Serving Size": serving,
            "Alternative Serving Size(s)": "-",
            "Edible Portion": "93.35%",
            "Energy (kcal) - Per 100": "151",
            "Energy (kcal) - Per Serving": "488",
        }
    )
    return row


def test_edible_yield_matches_real_source_reference_without_changing_per100_value():
    records, counts = normalize([source_row()], "a" * 64, 0)
    body = records[0][1]
    assert body.nutrients.energy == 151
    assert body.portions[0].grams == 322.991
    actual = Decimal(str(body.nutrients.energy)) * Decimal(str(body.portions[0].grams)) / 100
    assert actual == Decimal("487.71641")
    assert counts["serving_discrepancies"] == 0  # source rounds the serving to 488 kcal
    assert body.source_details["Edible Portion"] == "93.35%"
    assert body.vegetarian is None and body.allergen_status == {}


def test_ml_basis_trace_added_sugar_and_independent_serving_check():
    row = source_row("Test beverage", "Per 100ml", "1 can = 330ml")
    row.update(
        {
            "Edible Portion": "100%",
            "Energy (kcal) - Per 100": "16",
            "Energy (kcal) - Per Serving": "53",
            "Protein (g) - Per 100": "Trace",
            "Added Sugar (g) - Per 100": "1",
            "Added Sugar (g) - Per Serving": "3.3",
        }
    )
    records, counts = normalize([row], "a" * 64, 0)
    body = records[0][1]
    assert body.basis == "ml"
    assert body.portions[0].millilitres == 330 and body.portions[0].grams is None
    assert body.nutrients.protein is None and body.nutrients.free_sugars is None
    assert body.nutrients.added_sugars == 1
    assert counts["unknown_qualifier_counts"]["Trace"] == 1
    food = body.model_dump(mode="json")
    food.update(
        planning_portions=["serving_0"], meal_slots=["lunch"], review_note="Test annotation"
    )
    food = FoodBody.model_validate(food).model_dump(mode="json")
    quantity = portion_quantity(food, "serving_0", 1)
    meals = [
        {
            "day": 1,
            "slot": "lunch",
            "food": food,
            "portion_id": "serving_0",
            "scale": 1,
            "quantity": str(quantity),
            "unit": "ml",
        }
    ]
    facts = {"allergies": [], "vegetarian": False, "include_eggs": True, "include_dairy": True}
    items = [
        {
            "action": {
                "kind": "range",
                "subject": "energy",
                "amount": 50,
                "upper": 60,
                "unit": "kcal/day",
            }
        }
    ]
    check = check_plan(meals, 1, ["lunch"], facts, items)
    assert check["valid"]
    assert Decimal(check["daily_totals"]["1"]["energy"]) == Decimal("52.8")
    meals[0]["unit"] = "g"
    assert not check_plan(meals, 1, ["lunch"], facts, items)["valid"]


def test_source_discrepancy_is_retained_for_review():
    row = source_row()
    row["Energy (kcal) - Per Serving"] = "900"
    records, counts = normalize([row], "a" * 64, 0)
    assert counts["serving_discrepancies"] == 1
    assert records[0][1].import_warnings
    assert records[0][1].source_details["Energy (kcal) - Per Serving"] == "900"


def test_no_density_assumptions_or_zero_for_unrecognized_values():
    with pytest.raises(ValidationError):
        Portion(id="x", label="x", grams=100, millilitres=100)
    row = source_row(basis="Per 100ml")
    with pytest.raises(ValueError, match="mismatched serving"):
        normalize([row], "a" * 64, 0)
    row = source_row()
    row["Energy (kcal) - Per 100"] = "<1"
    with pytest.raises(ValueError, match="Unsupported"):
        normalize([row], "a" * 64, 0)
