"""Expose read-only dish catalogue lookups for meal selection."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from backend.knowledge.runtime import selected_release

router = APIRouter(prefix="/dishes", tags=["dishes"])

_REPO_ROOT = Path(__file__).resolve().parents[3]
from backend.datasets.paths import dataset_path

DISHES_FILE = dataset_path("dishes.json")

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
    """Catalogue loading failed due to a missing file, read/JSON error, or invalid shape."""


# Leave failed loads uncached so later requests can retry after file repair.
_DISH_CACHE: tuple[dict, ...] | None = None


def _load_dishes() -> tuple[dict, ...]:
    """Load the pinned release or ``DISHES_FILE`` once, then return cached records.

    Accept a list or an object containing a ``dishes`` list. Each entry must be
    an object with a nonblank string ``dish_id``. Other fields are not validated.
    Raise ``DishCatalogueUnavailable`` for missing files, caught read/JSON errors,
    or invalid catalogue shape. Successful loads do not refresh on file changes.

    Records are shared with the cache. Callers must not mutate them.
    """
    global _DISH_CACHE
    release = selected_release()
    if _DISH_CACHE is not None:
        return _DISH_CACHE
    if release is not None:
        _DISH_CACHE = tuple(release.dishes())
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
    """Translate ``DishCatalogueUnavailable`` into HTTP 503 ``dish_database_unavailable``."""
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
    """Return ``count`` and ``dishes`` with the fields used by meal pickers.

    Combine an exact category filter with a case-insensitive name substring.
    Strip surrounding whitespace from search text. Empty filters are ignored.
    Preserve catalogue order and return an empty list when nothing matches.
    Missing picker fields have null values.

    Catalogue loading failures reported by the loader produce HTTP 503 with
    ``dish_database_unavailable`` rather than an empty success response.
    """
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
    """Return the first full catalogue record whose ID exactly matches ``dish_id``.

    Return HTTP 404 ``dish_not_found`` when no record matches. Catalogue loading
    failures reported by the loader produce HTTP 503 ``dish_database_unavailable``.
    """
    for dish in _dishes_or_503():
        if dish.get("dish_id") == dish_id:
            return dish
    raise HTTPException(
        status_code=404,
        detail={"error": "dish_not_found", "dish_id": dish_id},
    )
