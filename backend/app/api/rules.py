"""Rule-engine endpoint.

``POST /rules/run`` turns a patient into a **PROPOSED** nutrient envelope via
the real CLIPS rule engine (``rules.engine.run_rules``) and returns the
frontend contract ``{envelope, trace}``. The envelope is validated against the
canonical ``shared.envelope_schema.NutrientEnvelope`` and registered in the
approval-gate store (still PROPOSED — the gate keeps blocking downstream until
a clinician approves). The trace is pinned in ``core.trace_store`` so the
explanation endpoint can replay the decision.

Request body (both accepted):
* ``{"patient_id": "P0001"}`` — the patient is looked up in the patient store;
* a full patient record (``data/patients.json`` shape) — used inline.

Out-of-scope patients (pregnancy, dialysis, ketoacidosis) yield a REJECTED
envelope with empty targets and a clear ``notes`` reason — returned with HTTP
200 so the UI can render the explanation.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException

from rules.engine import run_rules as engine_run_rules

from backend.app.core.approval_gate import put_envelope
from backend.app.core.trace_store import put_trace
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
    """Shared service behind ``POST /rules/run`` (reused by the review queue).

    Runs the CLIPS rule engine for a patient record, validates the envelope,
    registers it with the approval gate (still PROPOSED/REJECTED — downstream
    consumption stays blocked until a clinician approves) and pins the trace.

    Returns ``{"envelope": NutrientEnvelope, "trace": [...]}``.
    """
    result = engine_run_rules(patient)

    envelope = NutrientEnvelope.model_validate(result["envelope"])
    trace = [row for row in result["trace"]]

    put_envelope(envelope, new_proposal=True)
    put_trace(envelope.envelope_id, trace)
    return {"envelope": envelope, "trace": trace}


@router.post("/run", summary="Run the rule engine -> PROPOSED envelope + trace")
def run_rules(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    patient = _resolve_patient(body)
    result = run_rules_service(patient)

    return {
        "envelope": result["envelope"].model_dump(by_alias=True),
        "trace": result["trace"],
    }
