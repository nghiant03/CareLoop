"""Record dated clinical observations for patient profiles, rules, and lab trends.

``observed_at`` is the measurement date; ``recorded_at`` is the UTC receipt
time. Recording an observation does not approve or edit an envelope.
"""

from __future__ import annotations

from datetime import date as date_type
import math
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from backend.app.api.patients import get_patient
from backend.app.core import persistence

router = APIRouter(prefix="/observations", tags=["observations"])

Metric = Literal["serum_K_meq_L", "serum_PO4_mg_dL", "egfr", "hba1c_pct"]


class ObservationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: str
    metric: Metric
    value: float
    unit: str
    source: Optional[str] = None
    observed_at: Optional[str] = None


def _require_patient(patient_id: str) -> None:
    if get_patient(patient_id) is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "patient_not_found", "patient_id": patient_id},
        )


@router.post("", status_code=201, summary="Record a clinical observation")
def create_observation(req: ObservationRequest) -> dict[str, Any]:
    """Record one observation, normalizing unit spelling only.

    ``mL/min`` for eGFR is accepted as shorthand for a value that is already
    body-surface-area indexed (stored as ``mL/min/1.73m2``). No unit
    conversion is performed, so an absolute un-indexed measurement must not
    be submitted under that shorthand.
    """
    _require_patient(req.patient_id)
    units = {
        "serum_K_meq_L": {"meq/l": "mEq/L", "mmol/l": "mEq/L"},
        "serum_PO4_mg_dL": {"mg/dl": "mg/dL"},
        # Both eGFR spellings denote the same indexed unit; see docstring.
        "egfr": {"ml/min": "mL/min/1.73m2", "ml/min/1.73m2": "mL/min/1.73m2"},
        "hba1c_pct": {"%": "%"},
    }
    unit = units[req.metric].get(req.unit.strip().lower().replace("²", "2"))
    if unit is None or not math.isfinite(req.value) or req.value < 0:
        raise HTTPException(status_code=422, detail={"error": "invalid_observation_value_or_unit"})
    if req.observed_at is not None:
        try:
            observed = date_type.fromisoformat(req.observed_at)
            if observed > date_type.today():
                raise ValueError("future observation")
            req.observed_at = observed.isoformat()
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "invalid_observed_date",
                    "observed_at": req.observed_at,
                },
            )
    return persistence.add_observation(
        req.patient_id,
        req.metric,
        req.value,
        unit=unit,
        source=req.source,
        observed_at=req.observed_at,
    )


@router.get("", summary="List a patient's observations (chronological)")
def list_observations_endpoint(
    patient_id: str = Query(...),
) -> dict[str, Any]:
    _require_patient(patient_id)
    observations = persistence.list_observations(patient_id)
    return {
        "patient_id": patient_id,
        "count": len(observations),
        "observations": observations,
    }
