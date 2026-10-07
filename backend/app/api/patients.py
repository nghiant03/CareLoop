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


def _ui_view(record: dict[str, Any]) -> dict[str, Any]:
    """Add the flat, UI-facing fields to a raw patient record (superset).

    Keeps every raw field (``serum_K_meq_L`` etc.) and adds the snake_case
    ``id``/``name``/``serum_k``/``serum_po4`` names the React UI consumes.
    """
    view = dict(record)
    patient_id = str(record.get("patient_id", ""))
    view.setdefault("id", patient_id)
    view.setdefault("name", record.get("name") or f"Patient {patient_id}")
    view.setdefault("serum_k", record.get("serum_K_meq_L"))
    view.setdefault("serum_po4", record.get("serum_PO4_mg_dL"))
    view.setdefault("diagnoses", record.get("diagnoses", []))
    return view


def get_patient(patient_id: str) -> dict[str, Any] | None:
    """Return a patient record from the overlay/read-only store."""
    _ensure_loaded()
    return _OVERLAY.get(patient_id)


@router.get("", summary="List patients")
def list_patients() -> dict[str, Any]:
    _ensure_loaded()
    patients = [_ui_view(record) for record in _OVERLAY.values()]
    return {"count": len(patients), "patients": patients}


@router.get("/{patient_id}", summary="Get a patient by id")
def read_patient(patient_id: str) -> dict[str, Any]:
    record = get_patient(patient_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "patient_not_found", "patient_id": patient_id},
        )
    return _ui_view(record)


@router.post("", status_code=201, summary="Create a synthetic patient")
def create_patient(patient: Patient) -> dict[str, Any]:
    _ensure_loaded()
    record = patient.model_dump(by_alias=True, exclude_none=True)
    _OVERLAY[patient.patient_id] = record
    return record
