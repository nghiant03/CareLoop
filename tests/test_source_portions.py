from decimal import Decimal

import pytest

from careloop.foods.portions import source_portions
from careloop.planning.checker import portion_quantity
from careloop.planning.search import candidates


def test_recorded_quantities_are_used_without_density_or_label_inference():
    food = {
        "basis": "ml",
        "portions": [
            {"id": "cup", "label": "Cup", "millilitres": 240},
            {"id": "unknown", "label": "Bowl"},
            {"id": "mass", "label": "Mass", "grams": 200},
            {"id": "both", "grams": 100, "millilitres": 100},
            {"id": "zero", "millilitres": 0},
            {"id": "nan", "millilitres": float("nan")},
        ],
    }
    assert [p["id"] for p in source_portions(food)] == ["cup"]
    assert portion_quantity(food, "cup", 0.5) == Decimal(120)
    with pytest.raises(ValueError, match="No usable source quantity"):
        portion_quantity(food, "mass", 1)
    with pytest.raises(ValueError, match="No usable source quantity"):
        portion_quantity(food, "unknown", 1)


def test_legacy_slot_and_portion_annotations_do_not_restrict_source_candidates():
    body = {
        "basis": "g",
        "portions": [{"id": "source", "grams": 322.991}],
        "meal_slots": ["lunch"],
        "planning_portions": [],
        "allergen_status": {},
        "nutrients": {"energy": 151},
    }
    rows = [{"id": "source-food", "latest_revision": 1, "body": body}]
    items = [{"action": {"subject": "energy"}}]
    options, excluded = candidates(rows, ["breakfast", "dinner"], {}, items)
    assert not excluded
    assert all(len(choices) == 3 for choices in options.values())
    assert options["breakfast"][1]["quantity"] == "322.9910"
