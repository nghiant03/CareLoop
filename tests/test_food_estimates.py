from copy import deepcopy

from careloop.adapters.sgfoodid import NAMESPACE
from careloop.foods.estimates import estimate_details, prepare
from careloop.foods.models import FoodBody
from careloop.planning.checker import check_plan


def row(identity, *, basis="g", category="Fruit / Fresh fruit", **nutrients):
    body = FoodBody.model_validate(
        {
            "name": identity,
            "category": category,
            "basis": basis,
            "nutrients": {
                "energy": 100,
                "fat": 2,
                "saturated_fat": 0.2,
                "fibre": 3,
                "sodium": 20,
                "trans_fat": 0.1,
                "total_sugars": 10,
                **nutrients,
            },
            "portions": [
                {"id": "p", "label": "100 units", "grams" if basis == "g" else "millilitres": 100}
            ],
            "provenance": {"kind": "manual", "source": "test://fixture", "notes": "Test only"},
        }
    ).model_dump(mode="json")
    return {"id": identity, "namespace": NAMESPACE, "latest_revision": 1, "body": body}


def test_missing_values_use_measured_cohort_and_keep_originals():
    rows = [
        row("a", sodium=10),
        row("b", sodium=30),
        row("c", sodium=80),
        row("missing", sodium=None, fibre=None, trans_fat=None),
    ]
    before = deepcopy(rows)
    plan = prepare(rows)
    body = next(p["body"] for p in plan if p["food_id"] == "missing")
    assert rows == before
    assert body["nutrients"]["sodium"] == 30
    assert estimate_details(body)["sodium"]["donor_count"] == 3
    assert body["nutrients"]["free_sugars"] == 10  # conservative proxy, not measured free sugar
    assert body["food_groups"]["fruit_and_vegetables"] == 100
    assert body["contains_egg"] is None and body["allergen_status"] == {}
    assert "not measured" in body["review_note"]
    applied = [
        {**r, "body": next(p["body"] for p in plan if p["food_id"] == r["id"])} for r in rows
    ]
    assert prepare(applied) == []


def test_source_trans_fat_restored_but_impossible_source_value_is_not_used():
    rows = [
        row("a"),
        row("b"),
        row("c"),
        row("restore", trans_fat=None),
        row("bad-source", trans_fat=None),
    ]
    rows[3]["body"]["source_details"] = {"Trans Fat (g) - Per 100": "0.25"}
    rows[4]["body"]["source_details"] = {"Trans Fat (g) - Per 100": "38.5"}
    plan = {r["food_id"]: r["body"] for r in prepare(rows)}
    assert plan["restore"]["nutrients"]["trans_fat"] == 0.25
    assert "trans_fat" not in estimate_details(plan["restore"])
    assert plan["bad-source"]["nutrients"]["trans_fat"] == 0.1
    assert estimate_details(plan["bad-source"])["trans_fat"]["method"] == "cohort_median"
    assert plan["bad-source"]["source_details"]["Trans Fat (g) - Per 100"] == "38.5"


def test_no_g_to_ml_donor_conversion_and_no_mixed_dish_vegetable_fraction_invented():
    rows = [
        row("a"),
        row("b"),
        row("c"),
        row("drink", basis="ml", category="Beverages / 100% Juices", sodium=None),
        row("mixed", category="Mixed / Set meals"),
    ]
    plan = {r["food_id"]: r["body"] for r in prepare(rows)}
    assert plan["drink"]["nutrients"]["sodium"] is None
    assert plan["drink"]["food_groups"]["fruit_and_vegetables"] == 0
    assert plan["mixed"]["food_groups"]["fruit_and_vegetables"] == 0
    assert (
        estimate_details(plan["mixed"])["fruit_and_vegetables"]["method"]
        == "unverified_recipe_zero_credit"
    )


def test_existing_values_and_other_namespaces_are_not_replaced():
    original = row("known", free_sugars=2)
    original["body"]["food_groups"]["fruit_and_vegetables"] = 75
    original["body"]["review_note"] = "Existing review"
    assert prepare([original]) == []
    other = row("other")
    other["namespace"] = "another-source"
    assert prepare([other]) == []


def test_checker_discloses_estimates_used_in_approved_bounds():
    food = prepare([row("apple")])[0]["body"]
    meal = {
        "food_id": "apple",
        "food_revision": 2,
        "food": food,
        "day": 1,
        "slot": "lunch",
        "item": 1,
        "portion_id": "p",
        "scale": 1,
        "quantity": "100",
        "unit": "g",
    }
    items = [
        {
            "action": {
                "kind": "range",
                "subject": "energy",
                "amount": 90,
                "upper": 110,
                "unit": "kcal/day",
            }
        },
        {"action": {"kind": "ceiling", "subject": "free_sugars", "amount": 20, "unit": "g/day"}},
    ]
    result = check_plan([meal], 1, ["lunch"], {"allergies": [], "vegetarian": False}, items)
    assert result["valid"]
    assert result["uses_estimates"]
    assert result["composition_basis"] == "includes_estimates"
    assert list(result["estimated_inputs"][0]["fields"]) == ["free_sugars"]
