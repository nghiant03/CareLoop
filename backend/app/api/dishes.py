"""Dish catalogue endpoints (deterministic, read-only).

* ``GET /dishes?category=&search=`` — list/filter the dish database
  (``data/dishes.json``) with the nutrient fields the UI pickers need.
* ``GET /dishes/{dish_id}`` — one full dish record.

Consumed by the frontend meal-logging (adherence) screen.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/dishes", tags=["dishes"])

_REPO_ROOT = Path(__file__).resolve().parents[3]
DISHES_FILE = _REPO_ROOT / "data" / "dishes.json"

_LIST_FIELDS = (
    "dish_id",
    "name",
    "category",
    "cuisine",
    "portion_g",
    "energy_kcal",
    "protein_g",
    "sodium_mg",
    "potassium_mg",
    "phosphorus_mg",
    "carbs_g",
    "tags",
)


@lru_cache(maxsize=1)
def _load_dishes() -> tuple[dict, ...]:
    if not DISHES_FILE.exists():
        return ()
    try:
        raw = json.loads(DISHES_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return ()
    if isinstance(raw, dict):
        raw = raw.get("dishes", [])
    return tuple(d for d in raw if isinstance(d, dict))


@router.get("", summary="List dishes with optional category/search filters")
def list_dishes(
    category: str | None = Query(None, description="Exact category match (e.g. hawker)"),
    search: str | None = Query(None, description="Case-insensitive substring on dish name"),
) -> dict:
    """List the catalogue. Returns ``{"count", "dishes"}`` with picker fields."""
    dishes = _load_dishes()
    if category:
        dishes = tuple(d for d in dishes if d.get("category") == category)
    if search:
        needle = search.strip().lower()
        dishes = tuple(d for d in dishes if needle in str(d.get("name", "")).lower())
    light = [{k: d.get(k) for k in _LIST_FIELDS} for d in dishes]
    return {"count": len(light), "dishes": light}


@router.get("/{dish_id}", summary="One full dish record")
def get_dish(dish_id: str) -> dict:
    for dish in _load_dishes():
        if dish.get("dish_id") == dish_id:
            return dish
    raise HTTPException(
        status_code=404,
        detail={"error": "dish_not_found", "dish_id": dish_id},
    )
