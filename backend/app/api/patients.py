"""Patient endpoints.

Fixture patients are read-only seeds. Created profiles and timestamped
observations live in SQLite; every read overlays current observations.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from backend.app.models.patient import Patient
from backend.app.core import persistence

router = APIRouter(prefix="/patients", tags=["patients"])

_REPO_ROOT = Path(__file__).resolve().parents[3]
PATIENTS_FILE = _REPO_ROOT / "data" / "patients.json"

# Cache only fixture records; created profiles and observations are read from SQLite.
_SEED_PATIENTS: dict[str, dict[str, Any]] = {}
_SEEDS_LOADED = False


def _normalise(raw: Any) -> dict[str, dict[str, Any]]:
    """Index patient records from a list, wrapped list, or ID-keyed mapping."""
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


def _load_seeds_once() -> None:
    global _SEEDS_LOADED
    if _SEEDS_LOADED:
        return
    if PATIENTS_FILE.exists():
        try:
            _SEED_PATIENTS.update(_normalise(json.loads(PATIENTS_FILE.read_text())))
        except (json.JSONDecodeError, OSError):
            # Durable profiles remain available even if fixture loading fails.
            pass
    _SEEDS_LOADED = True


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
    """Read a durable profile or fixture, overlaid with its latest observations."""
    _load_seeds_once()
    record = persistence.saved_patients().get(patient_id) or _SEED_PATIENTS.get(patient_id)
    if record is None:
        return None
    record = dict(record)
    observations = [o for o in persistence.list_observations(patient_id)
                    if o["observed_at"] <= date.today().isoformat()]
    record["observations"] = observations
    for observation in observations:
        record[observation["metric"]] = observation["value"]
    return record


def list_patient_ids() -> list[str]:
    """All fixture and durable patient IDs, sorted."""
    _load_seeds_once()
    return sorted(set(_SEED_PATIENTS) | set(persistence.saved_patients()))


@router.get("", summary="List patients")
def list_patients() -> dict[str, Any]:
    _load_seeds_once()
    patients = [_ui_view(get_patient(pid)) for pid in list_patient_ids()]
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
    _load_seeds_once()
    record = patient.model_dump(by_alias=True, exclude_none=True)
    persistence.save_patient(record)
    return record
