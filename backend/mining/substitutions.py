"""Food substitution engine.

v1 — pure nutrient distance between two dishes over the 6 core nutrients
     (min-max normalised across the dish database).
v2 — ranked substitution suggestions: nutrient distance, category/cuisine
     similarity bonuses, a healthier-choice prior (prefer lower
     sodium/potassium/phosphorus among near-distance candidates), and
     hpb_id/verified as final tiebreaks.

Category compatibility keeps suggestions sensible: a drink never gets a soup.
``hpb_id``/``verified`` are honoured even though the current synthetic dataset
has ``hpb_id=None`` and ``verified=False`` for all 190 dishes (tiebreaks are
no-ops there).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_PATH = _REPO_ROOT / "data" / "dishes.json"

CORE_NUTRIENTS = (
    "energy_kcal",
    "protein_g",
    "sodium_mg",
    "potassium_mg",
    "phosphorus_mg",
    "carbs_g",
)

# Minerals whose intake CKD patients must limit — the "healthier choice" prior.
_MINERALS = ("sodium_mg", "potassium_mg", "phosphorus_mg")

# Weight of the healthier-choice prior, applied only to near-distance
# candidates (within NEAR_TOLERANCE of the best distance) so it acts as a
# tie-breaker among similar dishes rather than re-ranking everything.
_HEALTH_WEIGHT = 0.20
_NEAR_TOLERANCE = 0.25
_CATEGORY_BONUS = 0.10
_CUISINE_BONUS = 0.03
_HPB_BONUS = 0.01
_VERIFIED_BONUS = 0.01

# Which categories may substitute for which. Meals pair with rice-mixed-plate
# style meals; kopitiam drinks/desserts stay within their beverage-and-snack
# family. This is what stops "suggest a soup for a drink".
_COMPATIBLE_CATEGORIES: dict[str, frozenset[str]] = {
    "hawker": frozenset({"hawker", "cai_png"}),
    "cai_png": frozenset({"cai_png", "hawker"}),
    "zi_char": frozenset({"zi_char", "soup"}),
    "soup": frozenset({"soup", "zi_char"}),
    "kopitiam": frozenset({"kopitiam", "drink", "dessert"}),
    "drink": frozenset({"drink", "dessert"}),
    "dessert": frozenset({"dessert", "drink"}),
    "healthy": frozenset({"healthy"}),
}


@lru_cache(maxsize=1)
def load_dishes(path: str | None = None) -> list[dict]:
    """Load the dish database (cached)."""
    with open(path or DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _nutrient_bounds() -> dict[str, tuple[float, float]]:
    dishes = load_dishes()
    return {
        n: (
            min(float(d.get(n, 0.0)) for d in dishes),
            max(float(d.get(n, 0.0)) for d in dishes),
        )
        for n in CORE_NUTRIENTS
    }


def _normalised_vector(dish: dict) -> tuple[float, ...]:
    """Min-max normalise the 6 core nutrients across the dish DB -> [0, 1]."""
    vec = []
    for n in CORE_NUTRIENTS:
        lo, hi = _nutrient_bounds()[n]
        value = float(dish.get(n, 0.0))
        vec.append(0.0 if hi == lo else (value - lo) / (hi - lo))
    return tuple(vec)


def nutrient_distance(dish_a: dict, dish_b: dict) -> float:
    """Euclidean distance between two dishes over min-max normalised
    core nutrients (range [0, sqrt(len(CORE_NUTRIENTS))])."""
    va, vb = _normalised_vector(dish_a), _normalised_vector(dish_b)
    return float(sum((a - b) ** 2 for a, b in zip(va, vb)) ** 0.5)


def _health_term(dish: dict) -> float:
    """Mean normalised mineral load — lower is 'healthier'."""
    vals = [_normalised_vector(dish)[i] for i, n in enumerate(CORE_NUTRIENTS) if n in _MINERALS]
    return sum(vals) / len(vals)


def _candidates(dish: dict, dishes: list[dict]) -> list[dict]:
    compatible = _COMPATIBLE_CATEGORIES.get(dish["category"], frozenset({dish["category"]}))
    return [d for d in dishes if d["dish_id"] != dish["dish_id"] and d["category"] in compatible]


def _tiebreak(dish: dict) -> float:
    return (_HPB_BONUS if dish.get("hpb_id") else 0.0) + (
        _VERIFIED_BONUS if dish.get("verified") else 0.0
    )


def _reason(query: dict, cand: dict, distance: float, category_match: bool) -> str:
    parts = ["same category" if category_match else f"related category ({cand['category']})"]
    if query.get("cuisine") and query["cuisine"] == cand.get("cuisine"):
        parts.append(f"same cuisine ({cand['cuisine']})")
    if _health_term(cand) < _health_term(query):
        parts.append("lower sodium/potassium/phosphorus")
    parts.append("similar nutrients" if distance < 0.5 else "closest available match")
    if cand.get("hpb_id"):
        parts.append("HPB-verified")
    return ", ".join(parts)


def suggest_substitutions(
    dish_id: str,
    k: int = 3,
    version: int = 2,
    dishes: list[dict] | None = None,
) -> list[dict]:
    """Suggest up to ``k`` substitute dishes for ``dish_id``.

    version=1: rank purely by nutrient distance.
    version=2: nutrient distance + category/cuisine bonus + healthier-choice
    prior (lower sodium/potassium/phosphorus among near-distance candidates),
    hpb_id/verified tiebreaks.

    Candidates are restricted to compatible categories (never e.g. a soup for
    a drink) and the query dish itself is always excluded. Results are sorted
    by the returned ``distance`` (ascending) and deduplicated by dish_id.
    """
    dishes = dishes if dishes is not None else load_dishes()
    by_id = {d["dish_id"]: d for d in dishes}
    if dish_id not in by_id:
        raise KeyError(f"unknown dish_id: {dish_id}")
    if k <= 0:
        return []

    query = by_id[dish_id]
    scored = []
    for cand in _candidates(query, dishes):
        nd = nutrient_distance(query, cand)
        category_match = cand["category"] == query["category"]
        if version == 1:
            distance = nd
        elif version == 2:
            distance = nd
        else:
            raise ValueError(f"unsupported version: {version}")
        scored.append((cand, nd, distance, category_match))

    if version == 2 and scored:
        best = min(s[2] for s in scored)
        adjusted = []
        for cand, nd, distance, category_match in scored:
            adj = distance
            adj -= _CATEGORY_BONUS if category_match else _CATEGORY_BONUS / 2
            if query.get("cuisine") and query["cuisine"] == cand.get("cuisine"):
                adj -= _CUISINE_BONUS
            if distance <= best + _NEAR_TOLERANCE:
                adj += _HEALTH_WEIGHT * _health_term(cand)
            adj -= _tiebreak(cand)
            adjusted.append((cand, nd, adj, category_match))
        scored = adjusted

    scored.sort(key=lambda s: (s[2], s[0]["dish_id"]))

    results, seen = [], set()
    for cand, nd, distance, category_match in scored:
        if cand["dish_id"] in seen:
            continue
        seen.add(cand["dish_id"])
        results.append(
            {
                "dish_id": cand["dish_id"],
                "name": cand["name"],
                "distance": round(float(distance), 4),
                "nutrient_distance": round(nd, 4),
                "category_match": category_match,
                "reason": _reason(query, cand, nd, category_match),
            }
        )
        if len(results) == k:
            break
    return results