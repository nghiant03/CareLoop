"""Expose envelope snapshots, explanations, and clinician lifecycle transitions.

Send the reviewed envelope's ``lifecycle_revision`` as ``expected_revision`` to detect
changes since review. Revision conflicts return HTTP 409 ``envelope_conflict``
and require reloading and review before retrying. Omitting the token does not
disable write-conflict checks, but cannot detect a stale client review.
"""

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
    """Accept both approval field pairs for client compatibility.

    A nonempty ``clinician_id`` takes precedence over ``approved_by``.
    A non-null ``note`` takes precedence over ``notes``, including an empty string.
    """

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
    """Return the patient's latest envelope regardless of lifecycle status.

    Return HTTP 404 ``envelope_not_found`` when none exists. A latest proposal
    is not necessarily approved and does not by itself authorize live planning.
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
    """Return the requested snapshot in any lifecycle status, or HTTP 404 if absent."""
    return envelope


@router.get("/{envelope_id}/explanation", summary="Clinician explanation of an envelope")
def explain_envelope(
    envelope: NutrientEnvelope = Depends(get_envelope_or_404),
) -> dict:
    """Explain the envelope's fired rules, conflicts, and citations."""
    trace = trace_or_none(envelope) or []
    return clinician_explanation(envelope.model_dump(by_alias=True), trace)


@router.post("/{envelope_id}/approve", summary="Approve an envelope")
def approve_envelope(
    body: ApproveRequest | None = None,
    envelope: NutrientEnvelope = Depends(get_envelope_or_404),
) -> NutrientEnvelope:
    """Approve the envelope and return it with reviewer and approval time.

    Reject rejected, scope-ineligible, or targetless envelopes with HTTP 422
    ``out_of_scope_envelope``. Omitted bodies use the default reviewer. Null
    approval notes preserve existing notes. Content version is unchanged.
    Stale revisions return HTTP 409 ``envelope_conflict``.
    """
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
    """Edit the envelope, clear approval, and increment its content version.

    Null or omitted fields preserve targets, exclusions, and notes. Supplied
    target/exclusion lists replace the whole list, and empty lists clear it.
    Every edit invalidates approval, including notes-only edits or empty JSON objects.
    Live planning and personal target guidance require renewed approval.

    Reject rejected or scope-ineligible envelopes with HTTP 422
    ``out_of_scope_envelope``. Stale revisions return HTTP 409 ``envelope_conflict``.
    """
    return envelope_lifecycle.edit(
        envelope, edited_by=body.edited_by, targets=body.targets,
        exclusions=body.exclusions, notes=body.notes, expected_revision=body.expected_revision,
    )


@router.post("/{envelope_id}/reject", summary="Reject an envelope")
def reject_envelope(
    body: RejectRequest | None = None,
    envelope: NutrientEnvelope = Depends(get_envelope_or_404),
) -> NutrientEnvelope:
    """Reject the envelope and clear approval without changing its content version.

    Accept any current status or scope eligibility. Omitted bodies use the default
    reviewer. A nonempty reason replaces notes. Rejection blocks live planning
    and personal target guidance. Reviewer attribution is retained.
    Stale revisions return HTTP 409 ``envelope_conflict``.
    """
    body = body or RejectRequest()
    snapshot = envelope.model_copy(deep=True)
    # The schema has no rejection-attribution field, so retain the reviewer in the trace.
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
