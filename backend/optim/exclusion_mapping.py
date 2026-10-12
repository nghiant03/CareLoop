"""Semantic exclusion mapping: rulebook exclusion values -> dish predicates.

The clinical rulebook (``rules/rules.json``) emits *semantic* exclusion values
(``high_potassium_foods``, ``phosphate_additive_processed``,
``sugar_sweetened_beverage``, ``high_glycaemic_load``, ...) that do not
literally match the dish dataset's tag/category vocabulary (``data/dishes.json``
tags use e.g. ``high_potassium`` and have no ``sugar_sweetened_beverage``
category). Literal matching alone would miss these semantic categories.

This module is the documented bridge: each rulebook value maps to a
deterministic predicate over the dish's per-serving nutrients / category.
These are catalogue heuristics, not verified ingredient or recipe annotations.
Thresholds are set from the dataset's own distribution
so that "high-X" dishes (the top of the distribution) are excluded while the
bulk of the pool stays usable:

===============================  =============================================
Rulebook exclusion               Dish predicate (per serving)
===============================  =============================================
``dish_category=                 ``potassium_mg > 500`` (dataset p75 = 480 mg;
high_potassium_foods``           patient-education "high-K per serving" cutoff)
``dish_category=                 ``phosphorus_mg > 300`` (dataset p75 = 260 mg;
phosphate_additive_processed``   per-serving phosphorus density is the available
                                 proxy for additive-heavy processed food)
``dish_category=                 ``category == "drink"`` AND ``sugar_g > 5``
sugar_sweetened_beverage``
``diet_pattern=high_glycaemic_   ``carbs_g > 75`` (dataset p75 = 60 g; very large
load``                           refined-carb portions)
``ingredient=potassium_chloride`` literal ingredient match (unchanged; no dish in
                                 the dataset carries it, correctly a no-op)
``diet_pattern=pregnancy``       no dish predicate (a scope flag about the
                                 person, not a food property) — no-op
===============================  =============================================

Values not listed here have only literal tag/category/ingredient matching.
An unknown semantic value may therefore match no dishes; adding a rulebook
exclusion requires checking its catalogue coverage.
"""

from __future__ import annotations

from typing import Any

__all__ = ["SEMANTIC_EXCLUSIONS", "semantic_exclusion_hit"]


def _nutrient_gt(dish: Any, key: str, threshold: float) -> bool:
    try:
        return float(dish.nutrient(key)) > threshold
    except (KeyError, ValueError, TypeError):
        return False


# (kind, value) -> predicate spec.  Predicates are small tuples interpreted by
# :func:`semantic_exclusion_hit` so the table stays data, not code.
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
    """Does the semantic mapping exclude ``dish`` for this rulebook exclusion?

    Literal tag/category/ingredient matching is tried first by the caller
    (:func:`backend.optim.problem._matches_exclusion`); this function covers
    only the rulebook values listed in :data:`SEMANTIC_EXCLUSIONS`.  Unknown
    values return ``False`` (literal-only behaviour, unchanged).
    """
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
