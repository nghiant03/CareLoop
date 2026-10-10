"""Dish data contract and self-contained toy pool for optimiser tests and demos.

Eight plausible Singapore hawker/local dishes with per-serving nutrient values.
Nutrient keys mirror :class:`shared.envelope_schema.NutrientKind` values exactly,
so objective/constraint code can index them by ``constraint.nutrient.value``.

Production catalogue loading uses ``real_data.load_dishes``. This module's
``load_dishes`` returns the toy pool by default (or when the given file is
missing) and only reads the nested nutrient JSON schema; flat catalogue rows
are rejected with ``ValueError`` rather than read as zero nutrients.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

# Canonical nutrient keys (mirror NutrientKind).
NUTRIENT_KEYS: tuple[str, ...] = (
    "energy_kcal",
    "protein_g",
    "sodium_mg",
    "potassium_mg",
    "phosphorus_mg",
    "carbs_g",
    "fat_g",
    "sat_fat_g",
    "fiber_g",
    "sugar_g",
)


@dataclass(frozen=True)
class Dish:
    """Per-serving nutrients and matchable metadata for one dish.

    Attributes are frozen, but the nested nutrients mapping is mutable; callers
    sharing records must not mutate it. price_sgd is the price of one serving.
    """

    dish_id: str
    name: str
    category: str
    nutrients: dict[str, float]
    ingredients: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    price_sgd: float = 0.0
    price_is_estimated: bool = False
    verified: bool = False

    def nutrient(self, key: str) -> float:
        """Return a nutrient value, defaulting to 0.0 when absent."""
        return float(self.nutrients.get(key, 0.0))


def _nut(
    energy_kcal: float,
    protein_g: float,
    sodium_mg: float,
    potassium_mg: float,
    phosphorus_mg: float,
    carbs_g: float,
    fat_g: float,
    sat_fat_g: float,
    fiber_g: float,
    sugar_g: float,
) -> dict[str, float]:
    return {
        "energy_kcal": energy_kcal,
        "protein_g": protein_g,
        "sodium_mg": sodium_mg,
        "potassium_mg": potassium_mg,
        "phosphorus_mg": phosphorus_mg,
        "carbs_g": carbs_g,
        "fat_g": fat_g,
        "sat_fat_g": sat_fat_g,
        "fiber_g": fiber_g,
        "sugar_g": sugar_g,
    }


# ---------------------------------------------------------------------------
# Toy dish pool
# ---------------------------------------------------------------------------
# Note: "char_kway_teow" contains ingredient "lard" and "fried_chicken_wing_set"
# carries category "deep_fried" — both are hit by the sample envelope exclusions
# in spike_pymoo.py, exercising the exclusion path.

TOY_DISHES: list[Dish] = [
    Dish(
        dish_id="chicken_rice",
        name="Hainanese Chicken Rice",
        category="rice",
        nutrients=_nut(600, 30, 1200, 500, 350, 75, 18, 5, 3, 4),
        ingredients=("chicken", "rice", "garlic", "ginger", "sesame_oil"),
        tags=("high_protein", "moderate_sodium"),
        price_sgd=5.00,
    ),
    Dish(
        dish_id="nasi_lemak",
        name="Nasi Lemak",
        category="rice",
        nutrients=_nut(750, 22, 1400, 550, 300, 85, 35, 16, 5, 8),
        ingredients=("rice", "coconut_milk", "sambal", "egg", "ikan_bilis", "peanuts"),
        tags=("high_sodium", "high_sat_fat", "high_energy"),
        price_sgd=4.50,
    ),
    Dish(
        dish_id="char_kway_teow",
        name="Char Kway Teow",
        category="noodle",
        nutrients=_nut(800, 25, 1600, 450, 320, 90, 32, 14, 4, 6),
        ingredients=("flat_noodles", "egg", "cockles", "lard", "dark_soy_sauce", "chinese_sausage"),
        tags=("high_sodium", "high_sat_fat", "high_energy"),
        price_sgd=5.00,
    ),
    Dish(
        dish_id="fish_soup_bee_hoon",
        name="Fish Soup Bee Hoon",
        category="soup",
        nutrients=_nut(400, 28, 700, 700, 380, 45, 8, 2, 3, 3),
        ingredients=("batang_fish", "bee_hoon", "tomato", "ginger", "evaporated_milk"),
        tags=("lean_protein", "low_sodium"),
        price_sgd=6.00,
    ),
    Dish(
        dish_id="yong_tau_foo_soup",
        name="Yong Tau Foo (Clear Soup)",
        category="soup",
        nutrients=_nut(350, 20, 650, 800, 300, 30, 12, 3, 6, 4),
        ingredients=("tofu", "fish_paste", "leafy_vegetables", "clear_broth"),
        tags=("lean_protein", "vegetable", "low_sodium", "high_fiber"),
        price_sgd=5.50,
    ),
    Dish(
        dish_id="grilled_salmon_brown_rice",
        name="Grilled Salmon with Brown Rice",
        category="rice",
        nutrients=_nut(550, 38, 400, 900, 450, 55, 20, 3, 7, 3),
        ingredients=("salmon", "brown_rice", "broccoli", "olive_oil"),
        tags=("lean_protein", "high_protein", "high_fiber", "low_sodium"),
        price_sgd=9.00,
    ),
    Dish(
        dish_id="vegetable_bee_hoon",
        name="Vegetable Bee Hoon",
        category="noodle",
        nutrients=_nut(380, 12, 600, 600, 180, 65, 8, 2, 6, 5),
        ingredients=("bee_hoon", "cabbage", "carrot", "light_soy_sauce"),
        tags=("vegetable", "high_fiber", "low_sodium"),
        price_sgd=4.00,
    ),
    Dish(
        dish_id="fried_chicken_wing_set",
        name="Fried Chicken Wing Set",
        category="deep_fried",
        nutrients=_nut(700, 26, 1100, 480, 340, 60, 40, 18, 3, 3),
        ingredients=("chicken_wing", "batter", "frying_oil", "fries"),
        tags=("high_sodium", "high_sat_fat", "deep_fried", "high_energy"),
        price_sgd=6.50,
    ),
]


def load_dishes(path: str | None = None) -> list[Dish]:
    """Return the toy pool by default, or read nested nutrient JSON.

    Missing files also return a shallow copy of the toy pool. Existing files
    require a list of rows with ``dish_id``, ``name``, ``category``, and a
    ``nutrients`` mapping. Ingredients, tags, and price_sgd are optional.
    Missing nutrient keys default to zero. Rows without a nutrient mapping
    raise ValueError; use ``real_data.load_dishes`` for the flat catalogue.
    """
    if path is None:
        return list(TOY_DISHES)
    if not os.path.exists(path):
        return list(TOY_DISHES)
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    dishes: list[Dish] = []
    for row in raw:
        nested = row.get("nutrients")
        if not isinstance(nested, dict):
            raise ValueError(
                f"{path}: dish {row.get('dish_id')!r} has no 'nutrients' "
                "mapping — this loader reads the nested schema only; use "
                "backend.optim.real_data.load_dishes for the flat catalogue"
            )
        nutrients = {k: float(nested.get(k, 0.0)) for k in NUTRIENT_KEYS}
        dishes.append(
            Dish(
                dish_id=row["dish_id"],
                name=row.get("name", row["dish_id"]),
                category=row.get("category", "unknown"),
                nutrients=nutrients,
                ingredients=tuple(row.get("ingredients", ())),
                tags=tuple(row.get("tags", ())),
                price_sgd=float(row.get("price_sgd", 0.0)),
            )
        )
    return dishes
