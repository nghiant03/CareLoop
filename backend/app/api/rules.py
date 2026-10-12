"""Expose rule-based nutrient envelope proposals."""

from __future__ import annotations

import math
from typing import Any, Literal

from fastapi import APIRouter, Body, HTTPException
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    ValidationError,
    field_validator,
)

from backend.app.api.patients import get_patient
from backend.app.core.approval_gate import put_envelope
from backend.app.models.envelope import NutrientEnvelope
from rules.engine import normalize_patient_labs
from rules.engine import run_rules as engine_run_rules

router = APIRouter(prefix="/rules", tags=["rules"])


_INLINE_FIELDS = {
    "age", "sex", "weight_kg", "diagnoses", "egfr", "serum_K_meq_L",
    "serum_k_meq_l", "serum_PO4_mg_dL", "serum_po4_mg_dl", "meds", "bmi",
    "pregnant", "hba1c_pct", "name", "height_cm",
}


class _RulePatientInput(BaseModel):
    """Validate live rule inputs while preserving extra profile fields.

    Missing or null optional labs remain unknown. Clinical numbers must be finite
    and nonnegative. Weight must be positive, as must height when supplied. Numeric
    strings are accepted, but booleans are rejected. Callers normalize lab aliases before
    validation. This model is not a stored profile or historical snapshot.
    """

    model_config = ConfigDict(extra="allow")

    patient_id: str = Field(min_length=1)
    age: int = Field(ge=0, le=130)
    sex: Literal["F", "M", "X"]
    weight_kg: float = Field(gt=0)
    diagnoses: list[str] = Field(default_factory=list)
    meds: list[str] = Field(default_factory=list)
    egfr: float | None = Field(default=None, ge=0)
    serum_K_meq_L: float | None = Field(default=None, ge=0)
    serum_PO4_mg_dL: float | None = Field(default=None, ge=0)
    bmi: float | None = Field(default=None, ge=0)
    pregnant: StrictBool | None = None
    hba1c_pct: float | None = Field(default=None, ge=0)
    height_cm: float | None = Field(default=None, gt=0)

    @field_validator("patient_id")
    @classmethod
    def _nonblank_patient_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("patient_id must not be blank")
        return value

    @field_validator("age", "weight_kg", "egfr", "serum_K_meq_L",
                     "serum_PO4_mg_dL", "bmi", "hba1c_pct", "height_cm", mode="before")
    @classmethod
    def _reject_boolean_number(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("clinical numbers must not be booleans")
        return value

    @field_validator("weight_kg", "egfr", "serum_K_meq_L", "serum_PO4_mg_dL",
                     "bmi", "hba1c_pct", "height_cm")
    @classmethod
    def _finite_number(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("must be a finite number")
        return value


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
    """Validate rule inputs and save a fresh envelope with its decision trace.

    Return ``envelope`` as a ``NutrientEnvelope`` and ``trace`` as a list. Saving
    does not grant approval. Model validation errors return JSON-safe HTTP 422.
    Other exceptions propagate rather than being classified as client errors.
    """
    try:
        validated = _RulePatientInput.model_validate(normalize_patient_labs(patient))
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error": "validation_error", "detail": exc.errors(
                include_url=False, include_input=False, include_context=False,
            )},
        ) from exc

    result = engine_run_rules(validated.model_dump())
    envelope = NutrientEnvelope.model_validate(result["envelope"])
    trace = [row for row in result["trace"]]

    put_envelope(envelope, new_proposal=True)
    return {"envelope": envelope, "trace": trace}


@router.post("/run", summary="Run the rule engine -> PROPOSED envelope + trace")
def run_rules(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Create a fresh envelope and return it with the rule trace.

    Submit a patient ID for lookup or a complete inline record. Inline fields
    select inline validation, not a partial update to a saved profile. Unknown
    lookup IDs return HTTP 404 ``patient_not_found``.

    Scope-rejected results return HTTP 200 with empty targets. Eligible results
    are PROPOSED and require clinician approval before live planning.
    """
    patient = _resolve_patient(body)
    result = run_rules_service(patient)

    return {
        "envelope": result["envelope"].model_dump(by_alias=True),
        "trace": result["trace"],
    }
