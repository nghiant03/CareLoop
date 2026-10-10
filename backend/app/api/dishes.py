"""Dish catalogue endpoints (deterministic, read-only).

* ``GET /dishes?category=&search=`` — list/filter the dish database
  (``data/dishes.json``) with the nutrient fields the UI pickers need.
* ``GET /dishes/{dish_id}`` — one full dish record.

A missing or malformed catalogue answers 503 ``dish_database_unavailable``
instead of a healthy-looking empty list; only successful loads are cached, so
restoring the file recovers without a restart. Consumed by the frontend
meal-logging (adherence) screen.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

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


class DishCatalogueUnavailable(RuntimeError):
    """The dish catalogue could not be loaded (missing or malformed file)."""


# Cache successful loads only: caching a failure as an empty catalogue would
# keep answering empty 200s after the file is restored.
_DISH_CACHE: Optional[tuple[dict, ...]] = None


def _load_dishes() -> tuple[dict, ...]:
    global _DISH_CACHE
    if _DISH_CACHE is not None:
        return _DISH_CACHE
    if not DISHES_FILE.exists():
        raise DishCatalogueUnavailable(f"{DISHES_FILE} is missing")
    try:
        raw = json.loads(DISHES_FILE.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        raise DishCatalogueUnavailable(f"{DISHES_FILE} is unreadable: {exc}") from exc
    if isinstance(raw, dict):
        raw = raw.get("dishes")
    if not isinstance(raw, list) or any(
        not isinstance(dish, dict) or not isinstance(dish.get("dish_id"), str)
        or not dish["dish_id"].strip() for dish in raw
    ):
        raise DishCatalogueUnavailable(f"{DISHES_FILE} has an invalid catalogue shape")
    _DISH_CACHE = tuple(raw)
    return _DISH_CACHE


def _dishes_or_503() -> tuple[dict, ...]:
    try:
        return _load_dishes()
    except DishCatalogueUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": "dish_database_unavailable"},
        ) from exc


@router.get("", summary="List dishes with optional category/search filters")
def list_dishes(
    category: str | None = Query(None, description="Exact category match (e.g. hawker)"),
    search: str | None = Query(None, description="Case-insensitive substring on dish name"),
) -> dict:
    """List the catalogue. Returns ``{"count", "dishes"}`` with picker fields."""
    dishes = _dishes_or_503()
    if category:
        dishes = tuple(d for d in dishes if d.get("category") == category)
    if search:
        needle = search.strip().lower()
        dishes = tuple(d for d in dishes if needle in str(d.get("name", "")).lower())
    light = [{k: d.get(k) for k in _LIST_FIELDS} for d in dishes]
    return {"count": len(light), "dishes": light}


@router.get("/{dish_id}", summary="One full dish record")
def get_dish(dish_id: str) -> dict:
    for dish in _dishes_or_503():
        if dish.get("dish_id") == dish_id:
            return dish
    raise HTTPException(
        status_code=404,
        detail={"error": "dish_not_found", "dish_id": dish_id},
    )
