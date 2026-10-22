from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from backend.knowledge.runtime import selected_release

_REPO_ROOT = Path(__file__).resolve().parents[2]
from backend.datasets.paths import dataset_path

DATA_PATH = dataset_path("dishes.json")

CORE_NUTRIENTS = (
    "energy_kcal",
    "protein_g",
    "sodium_mg",
    "potassium_mg",
    "phosphorus_mg",
    "carbs_g",
)

_MINERALS = ("sodium_mg", "potassium_mg", "phosphorus_mg")

# Sodium and potassium and phosphorus count double.
RENAL_WEIGHTS: tuple[float, ...] = (1.0, 1.0, 2.0, 2.0, 2.0, 1.0)

_MINERAL_LOAD_WEIGHT = 0.20
_NEAR_TOLERANCE = 0.25
_CATEGORY_BONUS = 0.10
_CUISINE_BONUS = 0.03
_HPB_BONUS = 0.01
_VERIFIED_BONUS = 0.01

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


def load_dishes(path: str | None = None) -> list[dict]:
    """Cached catalogue records are shared and must not be mutated."""
    release = selected_release() if path is None else None
    return _load_catalogue(str(path or DATA_PATH), release.dishes_json if release else None)


@lru_cache(maxsize=1)
def _load_catalogue(path: str, release_json: str | None) -> list[dict]:
    if release_json is not None:
        return json.loads(release_json)
    with open(path, encoding="utf-8") as f:
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
    """External values are not clamped to catalogue bounds."""
    vec = []
    for n in CORE_NUTRIENTS:
        lo, hi = _nutrient_bounds()[n]
        value = float(dish.get(n, 0.0))
        vec.append(0.0 if hi == lo else (value - lo) / (hi - lo))
    return tuple(vec)


def nutrient_distance(dish_a: dict, dish_b: dict) -> float:
    va, vb = _normalised_vector(dish_a), _normalised_vector(dish_b)
    return float(sum((a - b) ** 2 for a, b in zip(va, vb)) ** 0.5)


def renal_nutrient_distance(dish_a: dict, dish_b: dict) -> float:
    va, vb = _normalised_vector(dish_a), _normalised_vector(dish_b)
    return float(
        sum(w * (a - b) ** 2 for w, a, b in zip(RENAL_WEIGHTS, va, vb)) ** 0.5
    )


def _mineral_load(dish: dict) -> float:
    """Generic mineral load is not a patient specific health measure."""
    vals = [_normalised_vector(dish)[i] for i, n in enumerate(CORE_NUTRIENTS) if n in _MINERALS]
    return sum(vals) / len(vals)


def _candidates(dish: dict, dishes: list[dict]) -> list[dict]:
    compatible = _COMPATIBLE_CATEGORIES.get(dish["category"], frozenset({dish["category"]}))
    return [d for d in dishes if d["dish_id"] != dish["dish_id"] and d["category"] in compatible]


def _verification_bonus(dish: dict) -> float:
    return (_HPB_BONUS if dish.get("hpb_id") else 0.0) + (
        _VERIFIED_BONUS if dish.get("verified") else 0.0
    )


def _reason(query: dict, cand: dict, distance: float, category_match: bool) -> str:
    parts = ["same category" if category_match else f"related category ({cand['category']})"]
    if query.get("cuisine") and query["cuisine"] == cand.get("cuisine"):
        parts.append(f"same cuisine ({cand['cuisine']})")
    if _mineral_load(cand) < _mineral_load(query):
        parts.append("lower combined normalised mineral load")
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
    """Legacy distance aliases the ranking score which may be negative. Supplied dishes retain cached normalization bounds."""
    dishes = dishes if dishes is not None else load_dishes()
    by_id = {d["dish_id"]: d for d in dishes}
    if dish_id not in by_id:
        raise KeyError(f"unknown dish_id: {dish_id}")
    if k <= 0:
        return []

    query = by_id[dish_id]
    scored = []
    for cand in _candidates(query, dishes):
        if version == 1:
            nd = nutrient_distance(query, cand)
        elif version == 2:
            nd = renal_nutrient_distance(query, cand)
        else:
            raise ValueError(f"unsupported version: {version}")
        category_match = cand["category"] == query["category"]
        distance = nd
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
                adj += _MINERAL_LOAD_WEIGHT * _mineral_load(cand)
            adj -= _verification_bonus(cand)
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
                "ranking_score": round(float(distance), 4),
                "nutrient_distance": round(nd, 4),
                "category_match": category_match,
                "reason": _reason(query, cand, nd, category_match),
            }
        )
        if len(results) == k:
            break
    return results
