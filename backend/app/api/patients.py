"""Patient endpoints.

Week 1 uses ``data/patients.json`` as a **read-only** store (Lane C owns that
file). New synthetic patients created via ``POST /patients`` live in a
process-local overlay until Week 2 wires a persistent store.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from backend.app.models.patient import Patient

router = APIRouter(prefix="/patients", tags=["patients"])

_REPO_ROOT = Path(__file__).resolve().parents[3]
PATIENTS_FILE = _REPO_ROOT / "data" / "patients.json"

# Process-local overlay: seeded from the read-only JSON file, plus created rows.
_OVERLAY: dict[str, dict[str, Any]] = {}
_LOADED = False


def _normalise(raw: Any) -> dict[str, dict[str, Any]]:
    """Accept either a list of patients or {"patients": [...]}."""
    if isinstance(raw, dict):
        raw = raw.get("patients", raw)
    if isinstance(raw, list):
        out: dict[str, dict[str, Any]] = {}
        for item in raw:
            if isinstance(item, dict) and item.get("patient_id"):
                out[str(item["patient_id"])] = item
        return out
    if isinstance(raw, dict):
        return {str(k): v for k, v in raw.items() if isinstance(v, dict)}
    return {}


def _ensure_loaded() -> None:
    global _LOADED
    if _LOADED:
        return
    if PATIENTS_FILE.exists():
        try:
            _OVERLAY.update(_normalise(json.loads(PATIENTS_FILE.read_text())))
        except (json.JSONDecodeError, OSError):
            # A malformed/absent file must not take down the API in Week 1.
            pass
    _LOADED = True


def get_patient(patient_id: str) -> dict[str, Any] | None:
    """Return a patient record from the overlay/read-only store."""
    _ensure_loaded()
    return _OVERLAY.get(patient_id)


@router.get("", summary="List patients")
def list_patients() -> dict[str, Any]:
    _ensure_loaded()
    return {"count": len(_OVERLAY), "patients": list(_OVERLAY.values())}


@router.get("/{patient_id}", summary="Get a patient by id")
def read_patient(patient_id: str) -> dict[str, Any]:
    record = get_patient(patient_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "patient_not_found", "patient_id": patient_id},
        )
    return record


@router.post("", status_code=201, summary="Create a synthetic patient")
def create_patient(patient: Patient) -> dict[str, Any]:
    _ensure_loaded()
    record = patient.model_dump(by_alias=True, exclude_none=True)
    _OVERLAY[patient.patient_id] = record
    return record
