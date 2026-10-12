"""Expose clinical observation recording and patient observation history."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime
from typing import Any, Literal

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
    source: str | None = None
    observed_at: str | None = None


def _require_patient(patient_id: str) -> None:
    if get_patient(patient_id) is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "patient_not_found", "patient_id": patient_id},
        )


@router.post("", status_code=201, summary="Record a clinical observation")
def create_observation(req: ObservationRequest) -> dict[str, Any]:
    """Record and return one observation without editing or approving an envelope.

    ``observed_at`` is the measurement date and defaults to today. ``recorded_at``
    is the UTC receipt time. Values must be finite and nonnegative. Unknown
    patients return HTTP 404. Invalid values or unsupported units return HTTP 422.

    Normalize unit spelling without converting values. eGFR ``mL/min`` means
    an already body-surface-area-indexed value, recorded as ``mL/min/1.73m2``.
    Do not submit absolute, unindexed measurements under that shorthand.
    """
    _require_patient(req.patient_id)
    units = {
        "serum_K_meq_L": {"meq/l": "mEq/L", "mmol/l": "mEq/L"},
        "serum_PO4_mg_dL": {"mg/dl": "mg/dL"},
        "egfr": {"ml/min": "mL/min/1.73m2", "ml/min/1.73m2": "mL/min/1.73m2"},
        "hba1c_pct": {"%": "%"},
    }
    unit = units[req.metric].get(req.unit.strip().lower().replace("²", "2"))
    if unit is None or not math.isfinite(req.value) or req.value < 0:
        raise HTTPException(status_code=422, detail={"error": "invalid_observation_value_or_unit"})
    if req.observed_at is not None:
        try:
            observed = date.fromisoformat(req.observed_at)
            if observed > datetime.now(UTC).date():
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
    """Return ``patient_id``, ``count``, and observations ordered oldest first.

    Order by measurement date, then receipt time. Patients without observations
    receive an empty list. Unknown patients return HTTP 404.
    """
    _require_patient(patient_id)
    observations = persistence.list_observations(patient_id)
    return {
        "patient_id": patient_id,
        "count": len(observations),
        "observations": observations,
    }
