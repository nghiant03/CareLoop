from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from backend.app.core import envelope_lifecycle
from backend.app.core.approval_gate import get_envelope_or_404
from backend.app.core.trace_store import trace_or_none
from backend.app.explain.views import clinician_explanation
from backend.app.models.envelope import (
    CitationSource,
    ExclusionFlag,
    NutrientConstraint,
    NutrientEnvelope,
    RuleFire,
)

router = APIRouter(prefix="/envelopes", tags=["envelopes"])


class ApproveRequest(BaseModel):
    """Accept legacy approval aliases. Explicit clinician and note fields take precedence."""

    model_config = ConfigDict(extra="forbid")

    approved_by: str = "clinician"
    notes: str | None = None
    clinician_id: str | None = None
    note: str | None = None
    expected_revision: int | None = Field(default=None, ge=0)

    @property
    def approver(self) -> str:
        return self.clinician_id or self.approved_by

    @property
    def approval_note(self) -> str | None:
        return self.note if self.note is not None else self.notes


class EditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    targets: list[NutrientConstraint] | None = None
    exclusions: list[ExclusionFlag] | None = None
    notes: str | None = None
    edited_by: str = "clinician"
    expected_revision: int | None = Field(default=None, ge=0)


class RejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rejected_by: str = "clinician"
    reason: str | None = None
    expected_revision: int | None = Field(default=None, ge=0)


@router.get("/latest", summary="Latest envelope for a patient")
def read_latest_envelope_for_patient(
    patient_id: str = Query(..., description="Patient id"),
) -> NutrientEnvelope:
    """The latest proposal need not be approved."""
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
    trace = trace_or_none(envelope) or []
    return clinician_explanation(envelope.model_dump(by_alias=True), trace)


@router.post("/{envelope_id}/approve", summary="Approve an envelope")
def approve_envelope(
    body: ApproveRequest | None = None,
    envelope: NutrientEnvelope = Depends(get_envelope_or_404),
) -> NutrientEnvelope:
    """Approve an eligible envelope. Stale revisions require a fresh review."""
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
    """Every edit clears approval and requires renewed review."""
    return envelope_lifecycle.edit(
        envelope, edited_by=body.edited_by, targets=body.targets,
        exclusions=body.exclusions, notes=body.notes, expected_revision=body.expected_revision,
    )


@router.post("/{envelope_id}/reject", summary="Reject an envelope")
def reject_envelope(
    body: RejectRequest | None = None,
    envelope: NutrientEnvelope = Depends(get_envelope_or_404),
) -> NutrientEnvelope:
    """Reject without changing the content version."""
    body = body or RejectRequest()
    snapshot = envelope.model_copy(deep=True)
    # Retain rejection attribution in the trace because the schema has no field for it.
    snapshot.fired_rules.append(RuleFire(
        rule_id="CLINICIAN-REJECT",
        fired_at=datetime.now(UTC),
        patient_summary=f"rejected by {body.rejected_by}",
        action_summary=(
            f"clinician rejection: {body.reason}" if body.reason
            else "clinician rejection"
        ),
        priority=0,
        citation=CitationSource(
            guideline="clinician decision",
            section="clinician reject",
            rule_id="CLINICIAN-REJECT",
        ),
    ))
    return envelope_lifecycle.reject(
        snapshot, reason=body.reason, expected_revision=body.expected_revision,
    )
