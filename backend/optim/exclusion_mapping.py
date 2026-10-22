"""Map rule exclusions to catalogue heuristics."""

from __future__ import annotations

from typing import Any

__all__ = ["SEMANTIC_EXCLUSIONS", "semantic_exclusion_hit"]


def _nutrient_gt(dish: Any, key: str, threshold: float) -> bool:
    try:
        return float(dish.nutrient(key)) > threshold
    except (KeyError, ValueError, TypeError):
        return False


SEMANTIC_EXCLUSIONS: dict[tuple[str, str], dict[str, Any]] = {
    ("dish_category", "high_potassium_foods"): {
        "predicate": ("nutrient_gt", "potassium_mg", 500.0),
        "rationale": (
            "high-potassium foods: > 500 mg potassium per serving "
            "(dataset p75 = 480 mg; standard patient-education cutoff for a "
            "high-K serving)"
        ),
    },
    ("dish_category", "phosphate_additive_processed"): {
        "predicate": ("nutrient_gt", "phosphorus_mg", 300.0),
        "rationale": (
            "phosphate-additive/processed foods: > 300 mg phosphorus per "
            "serving (dataset p75 = 260 mg); per-serving phosphorus density "
            "is the available proxy for additive-heavy processed food"
        ),
    },
    ("dish_category", "sugar_sweetened_beverage"): {
        "predicate": ("drink_with_sugar_gt", "sugar_g", 5.0),
        "rationale": (
            "sugar-sweetened beverages: drink-category items with more than "
            "5 g sugar per serving (ADA: avoid SSBs; unsweetened drinks and "
            "Kosong-style coffee/tea stay allowed)"
        ),
    },
    ("diet_pattern", "high_glycaemic_load"): {
        "predicate": ("nutrient_gt", "carbs_g", 75.0),
        "rationale": (
            "high-glycaemic-load pattern: > 75 g carbohydrate per serving "
            "(dataset p75 = 65 g), i.e. very large refined-carb portions"
        ),
    },
}


def semantic_exclusion_hit(flag_kind: str, flag_value: str, dish: Any) -> bool:
    """Unknown exclusions receive literal matching only."""
    spec = SEMANTIC_EXCLUSIONS.get((flag_kind, flag_value))
    if spec is None:
        return False
    predicate = spec["predicate"]
    if predicate[0] == "nutrient_gt":
        _, key, threshold = predicate
        return _nutrient_gt(dish, key, threshold)
    if predicate[0] == "drink_with_sugar_gt":
        _, key, threshold = predicate
        return dish.category.strip().lower() == "drink" and _nutrient_gt(dish, key, threshold)
    return False  # pragma: no cover - defensive
