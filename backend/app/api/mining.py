"""Mining endpoints (deterministic, read-only).

* ``GET /mining/trends`` — longitudinal K+/PO4 trend flags over
  ``data/patients.json`` (``backend.mining.trends.detect_trends``).
* ``GET /mining/substitutions?dish_id=...&k=3`` — v2 substitution suggestions
  from the dish database (``backend.mining.substitutions.suggest_substitutions``).
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from backend.mining.substitutions import suggest_substitutions
from backend.mining.trends import detect_trends

router = APIRouter(prefix="/mining", tags=["mining"])

_REPO_ROOT = Path(__file__).resolve().parents[3]
PATIENTS_FILE = _REPO_ROOT / "data" / "patients.json"


def _load_patients() -> list[dict]:
    if not PATIENTS_FILE.exists():
        return []
    try:
        raw = json.loads(PATIENTS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    if isinstance(raw, dict):
        raw = raw.get("patients", [])
    return [p for p in raw if isinstance(p, dict)]


@router.get("/trends", summary="Rising K+/PO4 trend flags across the cohort")
def trends() -> dict:
    flags = detect_trends(_load_patients())
    return {"count": len(flags), "flags": flags}


@router.get("/substitutions", summary="Healthier substitute dishes for a dish")
def substitutions(
    dish_id: str = Query(..., description="Dish id from data/dishes.json"),
    k: int = Query(3, ge=1, le=10, description="Max suggestions"),
) -> dict:
    try:
        results = suggest_substitutions(dish_id, k=k, version=2)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={"error": "dish_not_found", "dish_id": dish_id},
        )
    return {"dish_id": dish_id, "k": k, "substitutions": results}