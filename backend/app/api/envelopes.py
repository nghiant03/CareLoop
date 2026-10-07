"""Envelope lifecycle endpoints: approve / edit / reject.

Only ``POST /envelopes/{envelope_id}/approve`` moves an envelope into the
APPROVED state that satisfies the downstream approval gate. ``edit`` moves it to
EDITED (awaiting re-confirmation) and ``reject`` to REJECTED — both remain
blocked downstream.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from backend.app.core.approval_gate import get_envelope_or_404, put_envelope
from backend.app.models.envelope import (
    EnvelopeStatus,
    ExclusionFlag,
    NutrientConstraint,
    NutrientEnvelope,
)

router = APIRouter(prefix="/envelopes", tags=["envelopes"])


class ApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved_by: str = "clinician"
    notes: Optional[str] = None


class EditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    targets: Optional[list[NutrientConstraint]] = None
    exclusions: Optional[list[ExclusionFlag]] = None
    notes: Optional[str] = None
    edited_by: str = "clinician"


class RejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rejected_by: str = "clinician"
    reason: Optional[str] = None


@router.get("/{envelope_id}", summary="Get an envelope")
def read_envelope(
    envelope: NutrientEnvelope = Depends(get_envelope_or_404),
) -> NutrientEnvelope:
    return envelope


@router.post("/{envelope_id}/approve", summary="Approve an envelope")
def approve_envelope(
    body: ApproveRequest | None = None,
    envelope: NutrientEnvelope = Depends(get_envelope_or_404),
) -> NutrientEnvelope:
    body = body or ApproveRequest()
    envelope.status = EnvelopeStatus.APPROVED
    envelope.approved_by = body.approved_by
    envelope.approved_at = datetime.now(timezone.utc)
    if body.notes is not None:
        envelope.notes = body.notes
    return put_envelope(envelope)


@router.post("/{envelope_id}/edit", summary="Edit an envelope (awaiting re-approval)")
def edit_envelope(
    body: EditRequest,
    envelope: NutrientEnvelope = Depends(get_envelope_or_404),
) -> NutrientEnvelope:
    if body.targets is not None:
        envelope.targets = body.targets
    if body.exclusions is not None:
        envelope.exclusions = body.exclusions
    if body.notes is not None:
        envelope.notes = body.notes
    # An edit invalidates any prior approval: clinician must re-confirm.
    envelope.status = EnvelopeStatus.EDITED
    envelope.approved_by = None
    envelope.approved_at = None
    envelope.version += 1
    return put_envelope(envelope)


@router.post("/{envelope_id}/reject", summary="Reject an envelope")
def reject_envelope(
    body: RejectRequest | None = None,
    envelope: NutrientEnvelope = Depends(get_envelope_or_404),
) -> NutrientEnvelope:
    body = body or RejectRequest()
    envelope.status = EnvelopeStatus.REJECTED
    envelope.approved_by = None
    envelope.approved_at = None
    if body.reason:
        envelope.notes = body.reason
    return put_envelope(envelope)
