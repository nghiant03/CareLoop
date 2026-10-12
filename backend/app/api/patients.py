"""Expose patient creation and profile reads with current observations."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from backend.app.core import persistence
from backend.app.models.patient import Patient

router = APIRouter(prefix="/patients", tags=["patients"])

_REPO_ROOT = Path(__file__).resolve().parents[3]
PATIENTS_FILE = _REPO_ROOT / "data" / "patients.json"

# Cache fixtures only so saved profiles and observations stay current.
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
    """Return a copy with UI defaults and current lab aliases.

    Default missing ``id``, ``name``, and ``diagnoses`` fields. Canonical lab
    values override ``serum_k`` and ``serum_po4`` so stale aliases cannot mask
    newer observations. Preserve other existing fields and leave the input unchanged.
    """
    view = dict(record)
    patient_id = str(record.get("patient_id", ""))
    view.setdefault("id", patient_id)
    view.setdefault("name", record.get("name") or f"Patient {patient_id}")
    for alias, canonical in (
        ("serum_k", "serum_K_meq_L"),
        ("serum_po4", "serum_PO4_mg_dL"),
    ):
        if canonical in record:
            view[alias] = record[canonical]
        else:
            view.setdefault(alias, record.get(canonical))
    view.setdefault("diagnoses", record.get("diagnoses", []))
    return view


def get_patient(patient_id: str) -> dict[str, Any] | None:
    """Return a profile with its latest observed values, or ``None`` if unknown.

    Prefer a saved profile over a fixture. Include nonfuture observations in
    chronological order. The latest measurement wins for each metric, with
    receipt time breaking date ties. Leave the stored profile unchanged.
    """
    _load_seeds_once()
    record = persistence.saved_patients().get(patient_id) or _SEED_PATIENTS.get(patient_id)
    if record is None:
        return None
    record = dict(record)
    observations = [o for o in persistence.list_observations(patient_id)
                    if o["observed_at"] <= datetime.now(UTC).isoformat()]
    record["observations"] = observations
    for observation in observations:
        record[observation["metric"]] = observation["value"]
    return record


def list_patient_ids() -> list[str]:
    """Return sorted, distinct IDs from fixture and saved profiles."""
    _load_seeds_once()
    return sorted(set(_SEED_PATIENTS) | set(persistence.saved_patients()))


@router.get("", summary="List patients")
def list_patients() -> dict[str, Any]:
    """Return ``count`` and patient profiles sorted by ID, with current values and UI fields."""
    _load_seeds_once()
    patients = [
        _ui_view(patient)
        for pid in list_patient_ids()
        if (patient := get_patient(pid)) is not None
    ]
    return {"count": len(patients), "patients": patients}


@router.get("/{patient_id}", summary="Get a patient by id")
def read_patient(patient_id: str) -> dict[str, Any]:
    """Return a profile with current observed values and UI fields.

    Unknown patients return HTTP 404 ``patient_not_found``.
    """
    record = get_patient(patient_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "patient_not_found", "patient_id": patient_id},
        )
    return _ui_view(record)


@router.post("", status_code=201, summary="Create a synthetic patient")
def create_patient(patient: Patient) -> dict[str, Any]:
    """Create and return a new patient profile.

    Existing fixture or saved IDs return HTTP 409 ``patient_exists`` without
    replacing the profile. Repeated requests also return a conflict, not success.
    """
    _load_seeds_once()
    record = patient.model_dump(by_alias=True, exclude_none=True)
    patient_id = record["patient_id"]
    if patient_id in _SEED_PATIENTS or not persistence.insert_patient(record):
        raise HTTPException(
            status_code=409,
            detail={"error": "patient_exists", "patient_id": patient_id},
        )
    return record
