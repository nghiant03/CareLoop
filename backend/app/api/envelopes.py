"""Envelope lifecycle endpoints: approve / edit / reject.

Only ``POST /envelopes/{envelope_id}/approve`` moves an envelope into the
APPROVED state that satisfies the downstream approval gate. ``edit`` moves it to
EDITED (awaiting re-confirmation) and ``reject`` to REJECTED — both remain
blocked downstream.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from backend.app.core.approval_gate import get_envelope_or_404
from backend.app.core import envelope_lifecycle
from backend.app.core.trace_store import trace_or_none
from backend.app.explain.views import clinician_explanation
from backend.app.models.envelope import (
    ExclusionFlag,
    NutrientConstraint,
    NutrientEnvelope,
)

router = APIRouter(prefix="/envelopes", tags=["envelopes"])


class ApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # ``approved_by``/``notes`` are the original fields; ``clinician_id``/``note``
    # are the frontend-contract aliases (either form is accepted).
    approved_by: str = "clinician"
    notes: Optional[str] = None
    clinician_id: Optional[str] = None
    note: Optional[str] = None
    expected_revision: Optional[int] = Field(default=None, ge=0)

    @property
    def approver(self) -> str:
        return self.clinician_id or self.approved_by

    @property
    def approval_note(self) -> Optional[str]:
        return self.note if self.note is not None else self.notes


class EditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    targets: Optional[list[NutrientConstraint]] = None
    exclusions: Optional[list[ExclusionFlag]] = None
    notes: Optional[str] = None
    edited_by: str = "clinician"
    expected_revision: Optional[int] = Field(default=None, ge=0)


class RejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rejected_by: str = "clinician"
    reason: Optional[str] = None
    expected_revision: Optional[int] = Field(default=None, ge=0)


@router.get("/latest", summary="Latest envelope for a patient")
def read_latest_envelope_for_patient(
    patient_id: str = Query(..., description="Patient id"),
) -> NutrientEnvelope:
    """The patient's most recent envelope, any status.

    Lets the what-if screen prefill its target editor from the current
    envelope (the proposal baseline) instead of retyping every constraint.
    """
    from backend.app.core.approval_gate import find_latest_envelope_for_patient

    envelope = find_latest_envelope_for_patient(patient_id)
    if envelope is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "envelope_not_found", "patient_id": patient_id},
        )
    return envelope


@router.get("/{envelope_id}", summary="Get an envelope")
def read_envelope(
    envelope: NutrientEnvelope = Depends(get_envelope_or_404),
) -> NutrientEnvelope:
    return envelope


@router.get("/{envelope_id}/explanation", summary="Clinician explanation of an envelope")
def explain_envelope(
    envelope: NutrientEnvelope = Depends(get_envelope_or_404),
) -> dict:
    """Explain the durable snapshot's fired rules, conflicts, and citations."""
    trace = trace_or_none(envelope) or []
    return clinician_explanation(envelope.model_dump(by_alias=True), trace)


@router.post("/{envelope_id}/approve", summary="Approve an envelope")
def approve_envelope(
    body: ApproveRequest | None = None,
    envelope: NutrientEnvelope = Depends(get_envelope_or_404),
) -> NutrientEnvelope:
    body = body or ApproveRequest()
    return envelope_lifecycle.approve(
        envelope, approved_by=body.approver, notes=body.approval_note,
        expected_revision=body.expected_revision,
    )


@router.post("/{envelope_id}/edit", summary="Edit an envelope (awaiting re-approval)")
def edit_envelope(
    body: EditRequest,
    envelope: NutrientEnvelope = Depends(get_envelope_or_404),
) -> NutrientEnvelope:
    return envelope_lifecycle.edit(
        envelope, edited_by=body.edited_by, targets=body.targets,
        exclusions=body.exclusions, notes=body.notes, expected_revision=body.expected_revision,
    )


@router.post("/{envelope_id}/reject", summary="Reject an envelope")
def reject_envelope(
    body: RejectRequest | None = None,
    envelope: NutrientEnvelope = Depends(get_envelope_or_404),
) -> NutrientEnvelope:
    body = body or RejectRequest()
    return envelope_lifecycle.reject(envelope, reason=body.reason, expected_revision=body.expected_revision)
