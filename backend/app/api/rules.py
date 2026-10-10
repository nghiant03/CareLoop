"""Create a fresh PROPOSED or scope-rejected envelope with its embedded trace.

Accept a patient ID for lookup or an inline patient record. Validate the engine
output against the shared model and persist a fresh proposal identity. Scope
rejection returns HTTP 200 with empty targets so the UI can explain the refusal;
eligible proposals still need clinician approval before live planning.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException

from rules.engine import run_rules as engine_run_rules

from backend.app.core.approval_gate import put_envelope
from backend.app.api.patients import get_patient
from backend.app.models.envelope import NutrientEnvelope

router = APIRouter(prefix="/rules", tags=["rules"])


_INLINE_FIELDS = {
    "age", "sex", "weight_kg", "diagnoses", "egfr", "serum_K_meq_L",
    "serum_k_meq_l", "serum_PO4_mg_dL", "serum_po4_mg_dl", "meds", "bmi",
    "pregnant", "hba1c_pct", "name", "height_cm",
}


def _resolve_patient(body: dict[str, Any]) -> dict[str, Any]:
    if any(field in body for field in _INLINE_FIELDS):
        patient = dict(body)
        if not patient.get("patient_id"):
            raise HTTPException(
                status_code=422,
                detail={"error": "validation_error", "detail": "patient_id is required"},
            )
        return patient
    patient_id = body.get("patient_id")
    if not patient_id:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "validation_error",
                "detail": "body must be {patient_id} or a full patient record",
            },
        )
    record = get_patient(str(patient_id))
    if record is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "patient_not_found", "patient_id": str(patient_id)},
        )
    return dict(record)


def run_rules_service(patient: dict[str, Any]) -> dict[str, Any]:
    """Run rules and persist a fresh proposal with its embedded decision trace.

    Returns ``{"envelope": NutrientEnvelope, "trace": [...]}``. The review
    queue uses the same service; neither call path grants live approval.
    """
    result = engine_run_rules(patient)

    envelope = NutrientEnvelope.model_validate(result["envelope"])
    trace = [row for row in result["trace"]]

    put_envelope(envelope, new_proposal=True)
    return {"envelope": envelope, "trace": trace}


@router.post("/run", summary="Run the rule engine -> PROPOSED envelope + trace")
def run_rules(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    patient = _resolve_patient(body)
    result = run_rules_service(patient)

    return {
        "envelope": result["envelope"].model_dump(by_alias=True),
        "trace": result["trace"],
    }
